from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from uuid import UUID

import httpx
from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]

from app.application.curiosity import analyze_specification, parse_document
from app.domain.curiosity import (
    COMMAND_NAME,
    ExplorationInput,
    ExplorationStatus,
    MountedAPI,
    MountedRead,
)
from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.infrastructure.curiosity import PostgresExplorationStore

_PATH = re.compile(r"/(?:[A-Za-z0-9_.~-]+(?:/[A-Za-z0-9_.~-]+)*/?)?")
_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "additionalProperties",
    "enum",
    "const",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
}
_ANNOTATIONS = {"title", "description", "example", "examples", "default", "deprecated"}


class CuriosityError(ValueError):
    pass


def _checked_schema(value: object, components: dict[str, object]) -> dict[str, object]:
    remaining = 256

    def resolve(node: object, depth: int, ancestors: frozenset[str]) -> dict[str, object]:
        nonlocal remaining
        remaining -= 1
        if not isinstance(node, dict) or depth > 8 or remaining < 0:
            raise ValueError("Unsupported schema")
        if "$ref" in node:
            reference = node["$ref"]
            match = (
                re.fullmatch(r"#/components/schemas/([A-Za-z0-9_.-]+)", reference)
                if isinstance(reference, str)
                else None
            )
            if not match or match[1] in ancestors or set(node) - _ANNOTATIONS != {"$ref"}:
                raise ValueError("Unsupported schema reference")
            return resolve(components.get(match[1]), depth + 1, ancestors | {match[1]})

        schema: dict[str, object] = {}
        for key, item in node.items():
            if key in _ANNOTATIONS:
                continue
            if key not in _SCHEMA_KEYS:
                raise ValueError("Unsupported schema keyword")
            if key == "properties" and isinstance(item, dict):
                schema[key] = {
                    name: resolve(child, depth + 1, ancestors) for name, child in item.items()
                }
            elif key == "items" or (key == "additionalProperties" and isinstance(item, dict)):
                schema[key] = resolve(item, depth + 1, ancestors)
            else:
                schema[key] = item
        return schema

    return resolve(value, 0, frozenset())


def _url(value: str) -> httpx.URL:
    try:
        url = httpx.URL(value)
        if (
            url.scheme != "https"
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
            or not _PATH.fullmatch(url.path)
            or any(segment in {".", ".."} for segment in url.path.split("/"))
            or "%" in value
            or "\\" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError
    except (httpx.InvalidURL, ValueError):
        raise CuriosityError("Se requiere una URL HTTPS directa y sin credenciales.") from None
    return url


class CuriosityTool:
    definition = Tool(
        name="curiosity.read",
        description="Valida o ejecuta lecturas de APIs documentadas, con destinos autorizados.",
        risk_level=RiskLevel.READ,
        requires_approval=False,
        timeout_seconds=12,
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.store: PostgresExplorationStore | None = None
        self._transport = transport

    def allowed(self, url: httpx.URL) -> bool:
        raw = os.getenv("ARTEMIS_CURIOSITY_ALLOWED_URLS", "")
        return str(url) in {entry.strip() for entry in raw.split(",")}

    async def _get(self, url: httpx.URL) -> str:
        if not self.allowed(url):
            raise CuriosityError("El destino exacto no está autorizado en Curiosidad.")
        try:
            async with (
                asyncio.timeout(8),
                httpx.AsyncClient(
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                    timeout=6,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                ) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                if response.status_code != 200:
                    raise CuriosityError(f"Se esperaba HTTP 200 y llegó {response.status_code}.")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type != "application/json" and not content_type.endswith("+json"):
                    raise CuriosityError("El destino no devolvió JSON.")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise CuriosityError("El destino aplicó una codificación no admitida.")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > 131_072:
                        raise CuriosityError("El destino devolvió más de 128 KiB.")
                    body.extend(chunk)
                return body.decode()
        except httpx.HTTPStatusError as error:
            raise CuriosityError(
                f"El servicio respondió HTTP {error.response.status_code}."
            ) from None
        except (httpx.RequestError, TimeoutError, UnicodeError):
            raise CuriosityError("No pude leer una respuesta JSON UTF-8 del servicio.") from None

    async def mount(
        self, channel: str, conversation: UUID, name: str | None, source: str, inline: str | None
    ) -> MountedAPI:
        store = self._store()
        source_url = _url(source)
        if name is None:
            origin = re.sub(r"[^a-z0-9]+", "-", source_url.host.lower()).strip("-")[:40]
            digest = hashlib.sha256(str(source_url).encode()).hexdigest()[:12]
            name = f"{origin}-{digest}"
        specification = inline if inline is not None else await self._get(source_url)
        report = await asyncio.to_thread(
            analyze_specification, ExplorationInput(objective=name, specification=specification)
        )
        if report.status is not ExplorationStatus.ANALYZED:
            raise CuriosityError(report.reason or "El documento no es compatible.")
        document = parse_document(specification)
        if not str(document.get("openapi", "")).startswith(("3.0.", "3.1.")):
            raise CuriosityError("El montaje requiere OpenAPI 3.0 o 3.1.")
        base = source_url.copy_with(path="/")
        servers = document.get("servers", [])
        if servers:
            if (
                not isinstance(servers, list)
                or len(servers) != 1
                or not isinstance(servers[0], dict)
                or not isinstance(servers[0].get("url"), str)
                or servers[0].get("variables")
            ):
                raise CuriosityError("El documento debe declarar un único servidor fijo.")
            server = servers[0]["url"]
            if server.startswith("/") and not server.startswith("//"):
                server = str(base).rstrip("/") + server
            base = _url(server)
        components = document.get("components")
        schemas = components.get("schemas") if isinstance(components, dict) else None
        schema_components = schemas if isinstance(schemas, dict) else {}
        operations: dict[str, MountedRead] = {}
        for item in report.operations:
            if (
                item.method != "GET"
                or item.authentication_declared
                or item.parameters
                or not item.operation_id
                or not re.fullmatch(COMMAND_NAME, item.operation_id)
            ):
                continue
            operation = document["paths"][item.path]["get"]
            path_item = document["paths"][item.path]
            if (
                operation.get("parameters")
                or path_item.get("parameters")
                or operation.get("requestBody")
                or "servers" in operation
                or "servers" in path_item
                or not _PATH.fullmatch(item.path)
                or any(part in {".", ".."} for part in item.path.split("/"))
            ):
                continue
            responses = operation.get("responses")
            response = responses.get("200") if isinstance(responses, dict) else None
            content = response.get("content") if isinstance(response, dict) else None
            media = content.get("application/json") if isinstance(content, dict) else None
            schema = media.get("schema") if isinstance(media, dict) else None
            try:
                contract = _checked_schema(schema, schema_components)
                if contract.get("type") not in ("object", "array"):
                    continue
                Draft202012Validator.check_schema(contract)
            except (ValueError, SchemaError):
                continue
            url = _url(str(base).rstrip("/") + item.path)
            if not self.allowed(url):
                continue
            if item.operation_id in operations:
                raise CuriosityError("La documentación repite un identificador de operación.")
            operations[item.operation_id] = MountedRead.model_validate(
                {
                    "operation": item.operation_id,
                    "url": str(url),
                    "response_schema": contract,
                }
            )
            if len(operations) == 16:
                break
        if not operations:
            raise CuriosityError(
                "El documento no contiene GET autorizados sin parámetros ni autenticación "
                "con un contrato JSON admitido."
            )
        api = MountedAPI(name=name, operations=list(operations.values()))
        await store.mount(channel, conversation, api)
        return api

    async def learned_queries(self, channel: str, conversation: UUID) -> list[str]:
        if self.store is None:
            return []
        return [
            f"Curiosidad consultar {api.name} {read.operation}"
            for api in await self.store.mounted_apis(channel, conversation)
            for read in api.operations
            if self.allowed(_url(read.url))
        ][:50]

    def _store(self) -> PostgresExplorationStore:
        if self.store is None:
            raise CuriosityError("Curiosidad no dispone de PostgreSQL.")
        return self.store

    async def remove(self, channel: str, conversation: UUID, name: str) -> bool:
        return await self._store().unmount(channel, conversation, name)

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if invocation.agent_name != "curiosity":
            raise PermissionError("La ejecución está reservada al agente Curiosidad.")
        channel = str(invocation.input["channel"])
        conversation = UUID(str(invocation.input["conversation"]))
        name = str(invocation.input["name"])
        api = await self._store().mounted(channel, conversation, name)
        if api is None:
            raise CuriosityError("No hay una integración con ese nombre en esta conversación.")
        operation = next(
            (item for item in api.operations if item.operation == invocation.input["operation"]),
            None,
        )
        if operation is None:
            raise CuriosityError(
                "Operaciones disponibles: " + ", ".join(item.operation for item in api.operations)
            )
        body = await self._get(_url(operation.url))
        try:
            data = json.loads(body)
            if not Draft202012Validator(operation.response_schema).is_valid(data):
                raise ValueError
            display = json.dumps(data, ensure_ascii=True, allow_nan=False, indent=2)
        except (ValueError, RecursionError):
            raise CuriosityError(
                "La respuesta no cumple el contrato JSON de la operación."
            ) from None
        return ToolResult(
            invocation_id=invocation.id,
            output={
                "data": display[:3000] + ("\n… (respuesta truncada)" if len(display) > 3000 else "")
            },
        )
