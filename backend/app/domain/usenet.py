from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator

DEFAULT_NZBGET_URL = "https://ronnie.nunavut.usbx.me/nzbget/xmlrpc"


class UsenetConfigurationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_url: HttpUrl
    provider_api_key: SecretStr | None = Field(default=None, max_length=1024)
    nzbget_url: HttpUrl = Field(default=HttpUrl(DEFAULT_NZBGET_URL))
    nzbget_username: str = Field(min_length=1, max_length=200)
    nzbget_password: SecretStr | None = Field(default=None, max_length=1024)

    @field_validator("provider_url", "nzbget_url")
    @classmethod
    def clean_endpoint(cls, value: HttpUrl) -> HttpUrl:
        parsed = urlsplit(str(value))
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use an endpoint without credentials, query or fragment")
        return value


class UsenetSettings(UsenetConfigurationInput):
    provider_api_key: SecretStr = Field(min_length=1, max_length=1024)
    nzbget_password: SecretStr = Field(min_length=1, max_length=1024)


class UsenetConfigurationStatus(BaseModel):
    configured: bool
    provider_url: str | None = None
    nzbget_url: str = DEFAULT_NZBGET_URL
    nzbget_username: str | None = None
    credential_source: str | None = None
    provider_test: str | None = None
    downloader_test: str | None = None
    last_test: str | None = None


class SearchItem(BaseModel):
    id: str
    title: str
    size_bytes: int = 0
    category: str = ""
    published: str = ""


class DownloadItem(BaseModel):
    id: int
    title: str
    status: str
    size_mb: int = 0
    remaining_mb: int = 0
    history_time: int = 0


class DownloadStatus(BaseModel):
    paused: bool
    speed_bytes: int
    remaining_mb: int
    free_disk_mb: int


class UsenetClientError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code, self.safe_message = code, safe_message
        super().__init__(safe_message)


class UsenetClient(Protocol):
    async def search(self, query: str, category: str = "") -> list[SearchItem]: ...

    async def details(self, item_id: str) -> SearchItem: ...

    async def queue(self) -> list[DownloadItem]: ...

    async def history(self) -> list[DownloadItem]: ...

    async def status(self) -> DownloadStatus: ...

    async def download(self, item_id: str, title: str) -> int: ...

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...
