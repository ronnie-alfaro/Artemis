from __future__ import annotations

from app.domain.karakeep import KarakeepBookmark, KarakeepClientError


class UnconfiguredKarakeepClient:
    """Explicitly refuses writes until an operator configures the Karakeep skill."""

    @staticmethod
    def _error() -> KarakeepClientError:
        return KarakeepClientError(
            "configuration",
            "Karakeep is not configured. An operator must configure the Karakeep skill first.",
        )

    async def list_lists(self) -> None:
        raise self._error()

    async def create_link(self, url: str, title: str | None = None) -> KarakeepBookmark:
        raise self._error()
