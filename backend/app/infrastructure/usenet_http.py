from __future__ import annotations

import base64
import re

# XML-RPC parsing is hardened by defusedxml monkey_patch() below.
import xmlrpc.client  # nosec B411
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

# Only the result type and exception come from stdlib; parsing uses defusedxml.
from xml.etree.ElementTree import Element, ParseError  # nosec B405
from xml.parsers.expat import ExpatError

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from defusedxml.xmlrpc import monkey_patch

from app.domain.usenet import (
    DownloadItem,
    DownloadStatus,
    SearchItem,
    UsenetClientError,
    UsenetSettings,
)

monkey_patch()
MAX_RESPONSE = 12 * 1024 * 1024
_ID = re.compile(r"^[\w.-]{1,256}$", re.ASCII)


def _xml(content: bytes) -> Element:
    try:
        return ElementTree.fromstring(content)
    except (ParseError, DefusedXmlException, ValueError) as error:
        raise UsenetClientError(
            "invalid_response", "El servicio devolvió un archivo inválido."
        ) from error


def _identifier(value: str) -> str:
    parsed = urlsplit(value)
    candidate = (
        (parse_qs(parsed.query).get("id", [""])[0] or parsed.path.rstrip("/").rsplit("/", 1)[-1])
        if parsed.scheme
        else value
    )
    candidate = candidate.removesuffix(".nzb")
    if not _ID.fullmatch(candidate):
        raise UsenetClientError(
            "invalid_response", "El resultado no tiene un identificador válido."
        )
    return candidate


class HttpUsenetClient:
    def __init__(self, settings: UsenetSettings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        url = str(settings.provider_url).rstrip("/")
        self._provider_url = url + "/api" if not urlsplit(url).path else url

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, service: str, **kwargs: Any) -> bytes:
        try:
            async with self._client.stream(method, url, **kwargs) as response:
                if response.status_code in {401, 403}:
                    raise UsenetClientError("unauthorized", f"{service} rechazó las credenciales.")
                if response.status_code == 429:
                    raise UsenetClientError(
                        "rate_limit", f"{service} alcanzó su límite de consultas."
                    )
                if response.status_code != 200:
                    raise UsenetClientError(
                        "http_error", f"{service} respondió con HTTP {response.status_code}."
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE:
                        raise UsenetClientError(
                            "too_large", "La respuesta supera el tamaño permitido."
                        )
                return bytes(content)
        except httpx.TimeoutException as error:
            # An append timeout can have an unknown outcome: never retry it automatically.
            raise UsenetClientError(
                "timeout", f"{service} no respondió a tiempo. Consulta el estado antes de repetir."
            ) from error
        except httpx.RequestError as error:
            raise UsenetClientError("network", f"No pude conectar con {service}.") from error

    async def _provider(self, function: str, **params: str) -> bytes:
        query = urlencode(
            {"t": function, "apikey": self.settings.provider_api_key.get_secret_value(), **params},
            quote_via=quote,
        )
        content = await self._request("GET", f"{self._provider_url}?{query}", "el buscador")
        # Newznab may report API errors as XML with HTTP 200 (also for t=get).
        root = _xml(content)
        if root.tag.rsplit("}", 1)[-1] == "error":
            code = root.get("code", "")
            reason = "El buscador rechazó las credenciales o el acceso a la API."
            if code in {"500", "501"}:
                reason = "El buscador alcanzó su límite de consultas."
            raise UsenetClientError("provider_error", reason)
        return content

    @staticmethod
    def _items(content: bytes) -> list[SearchItem]:
        root = _xml(content)
        if root.tag != "rss" or root.find("channel") is None:
            raise UsenetClientError(
                "invalid_response", "El buscador devolvió una respuesta inválida."
            )
        items = []
        for element in root.findall("./channel/item")[:10]:
            attrs = {
                child.get("name", ""): child.get("value", "")
                for child in element
                if child.tag.rsplit("}", 1)[-1] == "attr"
            }
            guid = attrs.get("guid") or element.findtext("guid", "")
            title = element.findtext("title", "").strip()
            enclosure = element.find("enclosure")
            size = attrs.get("size") or (
                (enclosure.get("length") or "0") if enclosure is not None else "0"
            )
            if not guid or not title:
                continue
            items.append(
                SearchItem(
                    id=_identifier(guid),
                    title=title[:240],
                    size_bytes=int(size) if size.isdigit() else 0,
                    category=attrs.get("category") or element.findtext("category", "")[:100],
                    published=element.findtext("pubDate", "")[:100],
                )
            )
        return items

    async def search(self, query: str, category: str = "") -> list[SearchItem]:
        params = {"q": query, "limit": "10", "o": "xml", "extended": "1"}
        if category:
            params["cat"] = category
        return self._items(await self._provider("search", **params))

    async def details(self, item_id: str) -> SearchItem:
        items = self._items(await self._provider("details", id=_identifier(item_id)))
        if not items:
            raise UsenetClientError("not_found", "Ese resultado ya no está disponible.")
        return items[0]

    async def _rpc(self, method: str, *params: Any) -> Any:
        body = xmlrpc.client.dumps(params, methodname=method, allow_none=False).encode()
        content = await self._request(
            "POST",
            str(self.settings.nzbget_url),
            "el gestor de descargas",
            content=body,
            headers={"Content-Type": "text/xml"},
            auth=httpx.BasicAuth(
                self.settings.nzbget_username, self.settings.nzbget_password.get_secret_value()
            ),
        )
        try:
            values, _ = xmlrpc.client.loads(content)
            return values[0]
        except (
            xmlrpc.client.Error,
            ParseError,
            ExpatError,
            DefusedXmlException,
            ValueError,
            IndexError,
        ) as error:
            raise UsenetClientError(
                "rpc_error",
                "El gestor de descargas rechazó la operación o devolvió una respuesta inválida.",
            ) from error

    async def test_provider(self) -> None:
        await self.search("linux")

    async def test_downloader(self) -> None:
        await self.status()

    @staticmethod
    def _downloads(value: Any) -> list[DownloadItem]:
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise UsenetClientError("invalid_response", "No pude leer la lista de descargas.")
        try:
            return [
                DownloadItem(
                    id=item["NZBID"],
                    title=str(item.get("NZBName") or item.get("Name") or "Sin título")[:240],
                    status=str(item.get("Status", "UNKNOWN")),
                    size_mb=item.get("FileSizeMB", 0),
                    remaining_mb=item.get("RemainingSizeMB", 0),
                    history_time=item.get("HistoryTime", 0),
                )
                for item in value
            ]
        except (KeyError, ValueError, TypeError) as error:
            raise UsenetClientError(
                "invalid_response", "No pude leer la lista de descargas."
            ) from error

    async def queue(self) -> list[DownloadItem]:
        return self._downloads(await self._rpc("listgroups", 0))

    async def history(self) -> list[DownloadItem]:
        return sorted(
            self._downloads(await self._rpc("history", False)),
            key=lambda item: item.history_time,
            reverse=True,
        )[:10]

    async def status(self) -> DownloadStatus:
        value = await self._rpc("status")
        try:
            return DownloadStatus(
                paused=value["DownloadPaused"],
                speed_bytes=(int(value.get("DownloadRateHi", 0)) << 32)
                + int(value.get("DownloadRateLo", value.get("DownloadRate", 0))),
                remaining_mb=value["RemainingSizeMB"],
                free_disk_mb=value["FreeDiskSpaceMB"],
            )
        except (KeyError, ValueError, TypeError) as error:
            raise UsenetClientError(
                "invalid_response", "No pude leer el estado de descargas."
            ) from error

    async def download(self, item_id: str, title: str) -> int:
        item_id = _identifier(item_id)
        content = await self._provider("get", id=item_id)
        root = _xml(content)
        if root.tag.rsplit("}", 1)[-1] != "nzb" or not list(root):
            raise UsenetClientError(
                "invalid_file", "El buscador no devolvió un archivo de descarga válido."
            )
        filename = re.sub(r"[^\w .-]", "_", title, flags=re.ASCII)[:160].strip(" .") or item_id
        # Transfer bytes in memory; never pass a provider URL containing its key to NZBGet.
        result = await self._rpc(
            "append",
            filename + ".nzb",
            base64.b64encode(content).decode("ascii"),
            "",
            0,
            False,
            False,
            "artemis:" + item_id,
            0,
            "SCORE",
            [],
        )
        if type(result) is not int or result <= 0:
            raise UsenetClientError(
                "rejected", "El gestor no aceptó la descarga. Revisa la cola y el historial."
            )
        return result

    async def pause(self) -> None:
        if await self._rpc("pausedownload") is not True:
            raise UsenetClientError("rejected", "No se pudo pausar las descargas.")

    async def resume(self) -> None:
        if await self._rpc("resumedownload") is not True:
            raise UsenetClientError("rejected", "No se pudo reanudar las descargas.")
