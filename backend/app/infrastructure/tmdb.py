from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import httpx

BASE = "https://api.themoviedb.org/3"


class TmdbError(Exception):
    """A TMDB failure safe to display in chat."""


class TmdbClient:
    def __init__(self, token: str = "", api_key: str = "") -> None:
        self._token = token.strip()
        self._api_key = api_key.strip()

    @property
    def configured(self) -> bool:
        return bool(self._token or self._api_key)

    async def get(self, path: str, **params: str | int | float) -> dict[str, Any]:
        if not self.configured:
            raise TmdbError("Configura TMDB_RAT o TMDB_API en Artemis.")
        try:
            if self._token:
                async with httpx.AsyncClient(timeout=6) as client:
                    response = await client.get(
                        f"{BASE}/{path}", params=params,
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                    if response.status_code not in (401, 403) or not self._api_key:
                        response.raise_for_status()
                        return self._object(response.json())
            # urllib avoids logging the query string that carries the v3 API key.
            return await asyncio.to_thread(self._get_with_key, path, params)
        except (httpx.HTTPStatusError, HTTPError) as error:
            status = (
                error.response.status_code if isinstance(error, httpx.HTTPStatusError)
                else error.code
            )
            message = {
                401: "TMDB rechazó las credenciales.",
                403: "TMDB rechazó las credenciales.",
                404: "TMDB no encontró ese título o episodio.",
                429: "TMDB alcanzó su límite de consultas. Inténtalo más tarde.",
            }.get(status, f"TMDB respondió con un error HTTP {status}.")
            raise TmdbError(message) from None
        except (httpx.RequestError, OSError, ValueError):
            raise TmdbError("No pude obtener una respuesta válida de TMDB.") from None

    def _get_with_key(self, path: str, params: dict[str, str | int | float]) -> dict[str, Any]:
        query = urlencode({**params, "api_key": self._api_key})
        with urlopen(f"{BASE}/{path}?{query}", timeout=6) as response:
            return self._object(json.load(response))

    @staticmethod
    def _object(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
