from __future__ import annotations

# ruff: noqa: E501
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.domain.seerr import (
    MediaType,
    SeerrClientError,
    SeerrClientErrorCode,
    SeerrMedia,
    SeerrPendingRequest,
    SeerrPendingRequests,
    SeerrRequestInput,
    SeerrRequestResult,
    SeerrRequestStatus,
    SeerrSearchResult,
    SeerrSettings,
)


class HttpSeerrClient:
    """Typed Seerr adapter. It intentionally never includes response bodies in errors."""

    def __init__(self, settings: SeerrSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.timeout_seconds)

    async def test_connection(self) -> None:
        payload = await self._request("GET", "/api/v1/auth/me")
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr returned an unexpected user response."
            )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_pending_requests(self, page: int = 1) -> SeerrPendingRequests:
        if page < 1:
            raise ValueError("page must be positive")
        payload = await self._request(
            "GET", f"/api/v1/request?filter=unavailable&take=10&skip={(page - 1) * 10}&sort=added"
        )
        try:
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ValueError("Invalid request list")
            results = []
            for item in payload["results"]:
                media_type = MediaType(item["type"])
                media = await self.get_media_details(media_type, item["media"]["tmdbId"])
                results.append(SeerrPendingRequest(
                    request_id=item["id"], media=media,
                    status={1: "pendiente de aprobación", 2: "aprobada; pendiente de disponibilidad"}.get(
                        item["status"], "pendiente"
                    ),
                ))
            return SeerrPendingRequests(
                results=results, total=payload["pageInfo"]["results"], page=page
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr devolvió una lista de pendientes no válida."
            ) from error

    async def search_media(self, query: str) -> SeerrSearchResult:
        # Seerr rejects form-style '+' spaces; encode the query using RFC 3986.
        encoded = urlencode({"query": query}, quote_via=quote)
        payload = await self._request("GET", f"/api/v1/search?{encoded}")
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr returned an unexpected search response."
            )
        return SeerrSearchResult(
            results=[self._media(item) for item in results if self._is_media(item)]
        )

    async def get_media_details(self, media_type: MediaType, tmdb_id: int) -> SeerrMedia:
        path = f"/api/v1/{'movie' if media_type is MediaType.MOVIE else 'tv'}/{tmdb_id}"
        payload = await self._request("GET", path)
        return self._media(payload, media_type)

    async def create_request(self, request: SeerrRequestInput) -> SeerrRequestResult:
        payload: dict[str, object] = {
            "mediaType": request.media_type.value,
            "mediaId": request.tmdb_id,
        }
        if request.seasons:
            payload["seasons"] = request.seasons
        if request.quality_profile_id:
            payload["profileId"] = request.quality_profile_id
        response = await self._request("POST", "/api/v1/request", json=payload)
        if not isinstance(response, dict) or not isinstance(response.get("id"), int):
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr returned an unexpected request response."
            )
        return SeerrRequestResult(
            request_id=response["id"], status=str(response.get("status", "pending"))
        )

    async def get_request_status(self, request_id: int) -> SeerrRequestStatus:
        payload = await self._request("GET", f"/api/v1/request/{request_id}")
        if not isinstance(payload, dict):
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr returned an unexpected status response."
            )
        return SeerrRequestStatus(
            request_id=request_id, status=str(payload.get("status", "unknown"))
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> object:
        try:
            response = await self._client.request(
                method,
                f"{str(self._settings.base_url).rstrip('/')}{path}",
                headers={"X-Api-Key": self._settings.api_key},
                **kwargs,
            )
        except httpx.TimeoutException as error:
            raise SeerrClientError(
                SeerrClientErrorCode.TIMEOUT, "Seerr no respondió a tiempo."
            ) from error
        except httpx.RequestError as error:
            raise SeerrClientError(
                SeerrClientErrorCode.NETWORK, "Artemis no pudo conectar con Seerr."
            ) from error
        mapping = {
            401: SeerrClientErrorCode.UNAUTHORIZED,
            403: SeerrClientErrorCode.FORBIDDEN,
            404: SeerrClientErrorCode.NOT_FOUND,
            409: SeerrClientErrorCode.DUPLICATE,
        }
        if response.status_code in mapping:
            request_id = None
            if response.status_code == 409:
                try:
                    duplicate = response.json()
                    if isinstance(duplicate, dict) and isinstance(duplicate.get("id"), int):
                        request_id = duplicate["id"]
                except ValueError:
                    pass
            message = (
                "La solicitud ya existe en Seerr."
                if request_id
                else "Seerr no pudo completar la solicitud."
            )
            raise SeerrClientError(mapping[response.status_code], message, request_id)
        if response.is_error:
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr devolvió un error inesperado."
            )
        try:
            return response.json()
        except ValueError as error:
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr devolvió una respuesta JSON no válida."
            ) from error

    @staticmethod
    def _is_media(item: object) -> bool:
        return (
            isinstance(item, dict)
            and item.get("mediaType") in {"movie", "tv"}
            and isinstance(item.get("id"), int)
        )

    @staticmethod
    def _media(item: object, fallback: MediaType | None = None) -> SeerrMedia:
        if not isinstance(item, dict):
            raise SeerrClientError(
                SeerrClientErrorCode.UNEXPECTED, "Seerr returned invalid media data."
            )
        media_type = fallback or MediaType(str(item.get("mediaType")))
        title = item.get("title") if media_type is MediaType.MOVIE else item.get("name")
        release_date = (
            item.get("releaseDate") if media_type is MediaType.MOVIE else item.get("firstAirDate")
        )
        year = (
            int(str(release_date)[:4])
            if isinstance(release_date, str) and len(release_date) >= 4
            else None
        )
        return SeerrMedia(
            media_type=media_type,
            tmdb_id=item["id"],
            title=str(title or "Unknown"),
            year=year,
            overview=item.get("overview") if isinstance(item.get("overview"), str) else None,
            request_status=str(item["mediaInfo"].get("status"))
            if isinstance(item.get("mediaInfo"), dict)
            and item["mediaInfo"].get("status") is not None
            else None,
        )
