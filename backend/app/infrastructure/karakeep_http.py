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

    async def create_link(self, url: str, title: str | None = None) -> KarakeepBookmark:
        payload: dict[str, str] = {"type": "link", "url": url}
        if title:
            payload["title"] = title
        response = await self._request("POST", "/api/v1/bookmarks", json=payload)
        if not isinstance(response, dict) or not isinstance(response.get("id"), str):
            raise KarakeepClientError(
                "unexpected", "Karakeep returned an unexpected bookmark response."
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
            raise KarakeepClientError("timeout", "Karakeep did not respond in time.") from error
        except httpx.RequestError as error:
            raise KarakeepClientError("network", "Artemis could not reach Karakeep.") from error
        if response.status_code in {401, 403}:
            raise KarakeepClientError("unauthorized", "Karakeep rejected the API key.")
        if response.is_error:
            raise KarakeepClientError("unexpected", "Karakeep returned an unexpected error.")
        try:
            return response.json()
        except ValueError as error:
            raise KarakeepClientError("unexpected", "Karakeep returned invalid JSON.") from error
