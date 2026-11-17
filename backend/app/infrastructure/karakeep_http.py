from __future__ import annotations

from typing import Any

import httpx

from app.domain.karakeep import (
    KarakeepBookmark,
    KarakeepClientError,
    KarakeepSettings,
)


class HttpKarakeepClient:
    def __init__(self, settings: KarakeepSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)

    async def list_lists(self) -> None:
        await self._request("GET", "/api/v1/lists")

    async def search_bookmarks(self, query: str) -> list[KarakeepBookmark]:
        response = await self._request(
            "GET",
            "/api/v1/bookmarks/search",
            params={"q": query, "limit": 5, "sortOrder": "relevance", "includeContent": "false"},
        )
        if not isinstance(response, dict) or not isinstance(response.get("bookmarks"), list):
            raise KarakeepClientError("unexpected", "Karakeep devolvió resultados no válidos.")
        results = []
        for item in response["bookmarks"][:5]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise KarakeepClientError("unexpected", "Karakeep devolvió un bookmark no válido.")
            content = item.get("content")
            if not isinstance(content, dict):
                raise KarakeepClientError("unexpected", "Karakeep devolvió contenido no válido.")
            title = item.get("title") or content.get("title")
            description = item.get("summary") or content.get("description")
            url = content.get("url")
            results.append(
                KarakeepBookmark(
                    id=item["id"],
                    title=title if isinstance(title, str) else None,
                    url=(
                        url
                        if isinstance(url, str) and url.startswith(("https://", "http://"))
                        else None
                    ),
                    description=description if isinstance(description, str) else None,
                )
            )
        return results

    async def create_link(self, url: str, title: str | None = None) -> KarakeepBookmark:
        payload: dict[str, str] = {"type": "link", "url": url}
        if title:
            payload["title"] = title
        response = await self._request("POST", "/api/v1/bookmarks", json=payload)
        if not isinstance(response, dict) or not isinstance(response.get("id"), str):
            raise KarakeepClientError(
                "unexpected", "Karakeep devolvió una respuesta de marcador no válida."
            )
        return KarakeepBookmark(
            id=response["id"],
            url=response.get("url") if isinstance(response.get("url"), str) else url,
            title=response.get("title") if isinstance(response.get("title"), str) else title,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> object:
        try:
            response = await self._client.request(
                method,
                f"{str(self._settings.base_url).rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {self._settings.api_key}"},
                **kwargs,
            )
        except httpx.TimeoutException as error:
            raise KarakeepClientError("timeout", "Karakeep no respondió a tiempo.") from error
        except httpx.RequestError as error:
            raise KarakeepClientError(
                "network", "Artemis no pudo conectar con Karakeep."
            ) from error
        if response.status_code in {401, 403}:
            raise KarakeepClientError("unauthorized", "Karakeep rechazó la clave de API.")
        if response.is_error:
            raise KarakeepClientError("unexpected", "Karakeep devolvió un error inesperado.")
        try:
            return response.json()
        except ValueError as error:
            raise KarakeepClientError(
                "unexpected", "Karakeep devolvió una respuesta JSON no válida."
            ) from error
