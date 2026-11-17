from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class MediaType(StrEnum):
    MOVIE = "movie"
    TV = "tv"


class SeerrMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: MediaType
    tmdb_id: int = Field(gt=0)
    title: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1888, le=2200)
    overview: str | None = None
    request_status: str | None = None


class SeerrSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[SeerrMedia]


class SeerrPendingRequest(BaseModel):
    request_id: int = Field(gt=0)
    media: SeerrMedia
    status: str


class SeerrPendingRequests(BaseModel):
    results: list[SeerrPendingRequest]
    total: int = Field(ge=0)
    page: int = Field(ge=1)


class SeerrRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: MediaType
    tmdb_id: int = Field(gt=0)
    requester: str = Field(min_length=1, max_length=200)
    seasons: list[int] | None = None
    quality_profile_id: int | None = Field(default=None, gt=0)


class SeerrRequestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: int = Field(gt=0)
    status: str
    duplicate: bool = False


class SeerrRequestStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: int = Field(gt=0)
    status: str


class SeerrClientErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    DUPLICATE = "duplicate"
    TIMEOUT = "timeout"
    NETWORK = "network"
    UNEXPECTED = "unexpected"
    CONFIGURATION = "configuration"


class SeerrClientError(Exception):
    def __init__(
        self, code: SeerrClientErrorCode, safe_message: str, request_id: int | None = None
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.request_id = request_id
        super().__init__(safe_message)


class SeerrSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: HttpUrl
    api_key: str = Field(min_length=1)
    timeout_seconds: float = Field(default=10, gt=0, le=30)


class SeerrConfigurationStatus(BaseModel):
    configured: bool
    base_url: str | None = None
    credential_source: str | None = None
    last_test: str | None = None


class SeerrConfigurationInput(BaseModel):
    base_url: HttpUrl
    api_key: str = Field(min_length=1, max_length=1024)


class SeerrApiInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str = Field(min_length=1, max_length=2000)
    body: dict[str, object] | list[object] | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        # Accept only literal API paths, never URLs, encoded traversal or fragments.
        path = value.split("?", 1)[0]
        if (
            not re.fullmatch(r"/api/v1/[A-Za-z0-9_/-]+", path)
            or any(part in {".", "..", ""} for part in path[1:].split("/"))
            or any(char in value for char in "\\\r\n#")
        ):
            raise ValueError("Usa una ruta /api/v1/ válida de Seerr")
        return value


class SeerrClient(Protocol):
    async def api_request(self, request: SeerrApiInput) -> object: ...

    async def list_pending_requests(self, page: int = 1) -> SeerrPendingRequests: ...

    async def search_media(self, query: str) -> SeerrSearchResult: ...

    async def get_media_details(self, media_type: MediaType, tmdb_id: int) -> SeerrMedia: ...

    async def create_request(self, request: SeerrRequestInput) -> SeerrRequestResult: ...

    async def get_request_status(self, request_id: int) -> SeerrRequestStatus: ...
