from __future__ import annotations

from app.domain.seerr import (
    MediaType,
    SeerrApiInput,
    SeerrClientError,
    SeerrClientErrorCode,
    SeerrMedia,
    SeerrPendingRequests,
    SeerrRequestInput,
    SeerrRequestResult,
    SeerrRequestStatus,
    SeerrSearchResult,
)


class UnconfiguredSeerrClient:
    """Explicitly refuses work until an operator configures the Seerr skill."""

    @staticmethod
    def _error() -> SeerrClientError:
        return SeerrClientError(
            SeerrClientErrorCode.CONFIGURATION,
            "Seerr no está configurado. Configura su conexión en Habilidades para empezar.",
        )

    async def api_request(self, request: SeerrApiInput) -> object:
        raise self._error()

    async def list_pending_requests(self, page: int = 1) -> SeerrPendingRequests:
        raise self._error()

    async def search_media(self, query: str) -> SeerrSearchResult:
        raise self._error()

    async def get_media_details(self, media_type: MediaType, tmdb_id: int) -> SeerrMedia:
        raise self._error()

    async def create_request(self, request: SeerrRequestInput) -> SeerrRequestResult:
        raise self._error()

    async def get_request_status(self, request_id: int) -> SeerrRequestStatus:
        raise self._error()
