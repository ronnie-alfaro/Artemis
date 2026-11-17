from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class KarakeepSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: HttpUrl
    api_key: str = Field(min_length=1)
    timeout_seconds: float = Field(default=10, gt=0, le=30)


class KarakeepConfigurationInput(BaseModel):
    base_url: HttpUrl
    api_key: str = Field(min_length=1, max_length=1024)


class KarakeepConfigurationStatus(BaseModel):
    configured: bool
    base_url: str | None = None
    credential_source: str | None = None
    last_test: str | None = None


class KarakeepBookmark(BaseModel):
    id: str
    url: str | None = None
    title: str | None = None
    description: str | None = None


class KarakeepClientError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code, self.safe_message = code, safe_message
        super().__init__(safe_message)


class KarakeepClient(Protocol):
    async def list_lists(self) -> None: ...

    async def search_bookmarks(self, query: str) -> list[KarakeepBookmark]: ...

    async def create_link(self, url: str, title: str | None = None) -> KarakeepBookmark: ...
