from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from app.domain.curiosity import DeclaredOperation, Exploration, ExplorationInput, ExplorationStatus
from app.domain.models import utcnow

HTTP_METHODS = ("get", "head", "options", "post", "put", "patch", "delete", "trace")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise ValueError(f"Unsupported JSON constant {value}")


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_reference(value: Any) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if "$ref" in item or "$dynamicRef" in item:
                return True
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _collect_parameters(*levels: Any) -> list[str]:
    names: dict[str, None] = {}
    for level in levels:
        if not isinstance(level, list):
            continue
        for item in level:
            parameter = _object(item)
            name, location = parameter.get("name"), parameter.get("in")
            if isinstance(name, str) and location in ("query", "header", "path", "cookie", "body"):
                names[f"{location} {name[:128]}"] = None
    return list(names)[:64]


def analyze_specification(payload: ExplorationInput) -> Exploration:
    fingerprint = hashlib.sha256(payload.specification.encode()).hexdigest()
    result = Exploration(
        id=uuid4(),
        objective=payload.objective,
        fingerprint=fingerprint,
        created_at=utcnow(),
        status=ExplorationStatus.DISCOVERED,
        history=[ExplorationStatus.DISCOVERED],
    )
    try:
        document = json.loads(
            payload.specification, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant
        )
        if not isinstance(document, dict):
            raise ValueError("Expected an object")
        canonical = json.dumps(
            document, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        if "\\u0000" in canonical:
            raise ValueError("Unexpected null character")
        result.fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        version = document.get("openapi") or document.get("swagger")
        if not isinstance(version, str) or not (
            version == "2.0"
            and document.get("swagger") == version
            or version.startswith(("3.0.", "3.1."))
            and document.get("openapi") == version
        ):
            result.status = ExplorationStatus.BLOCKED
            result.reason = "Se requiere Swagger 2.0 u OpenAPI 3.0/3.1 en JSON."
        else:
            result.specification_version = version[:24]
            result.operations = _collect_operations(document)
            result.status = ExplorationStatus.ANALYZED
            if not result.operations:
                result.reason = "El documento no contiene operaciones HTTP directas."
    except (ValueError, RecursionError):
        result.status = ExplorationStatus.FAILED
        result.reason = "Documento JSON inválido o inventario fuera de los límites admitidos."
    result.history.append(result.status)
    return result


def _collect_operations(document: dict[str, Any]) -> list[DeclaredOperation]:
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("Expected paths object")
    operations: list[DeclaredOperation] = []
    for path, raw_item in paths.items():
        if not path.startswith("/") or path.startswith("//"):
            continue
        item = _object(raw_item)
        if "$ref" in item:
            continue
        for method in HTTP_METHODS:
            if method not in item:
                continue
            operation = item[method]
            if not isinstance(operation, dict) or len(path) > 512 or len(operations) >= 128:
                raise ValueError("Operation limit exceeded or malformed operation")
            operation_id = operation.get("operationId")
            operations.append(
                DeclaredOperation(
                    method=method.upper(),
                    path=path,
                    operation_id=operation_id[:128] if isinstance(operation_id, str) else None,
                    parameters=_collect_parameters(
                        item.get("parameters"), operation.get("parameters")
                    ),
                    responses=[
                        code
                        for code in _object(operation.get("responses"))
                        if code == "default" or (len(code) == 3 and code.isascii())
                    ][:32],
                    authentication_declared=bool(
                        operation.get("security", document.get("security"))
                    ),
                    references_present=_has_reference([item.get("parameters"), operation]),
                )
            )
    return operations
