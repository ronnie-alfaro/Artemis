from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


class NotificationSettings(BaseModel):
    enabled: bool = True
    channel: Literal["whatsapp"] = "whatsapp"
    recipient_id: str | None = Field(default=None, min_length=1, max_length=200)


class NotificationConfiguration(BaseModel):
    settings: NotificationSettings
    storage_available: bool
    whatsapp_configured: bool
    recipient_available: bool
    available_recipients: list[str]


class NotificationPayload(BaseModel):
    event: str = Field(
        default="notification", min_length=1, max_length=128,
        validation_alias=AliasChoices("notification_type", "event"),
    )
    event_id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(
        default="", max_length=512, validation_alias=AliasChoices("title", "subject")
    )
    message: str = Field(default="", max_length=4096)

    @field_validator("event", "event_id", "title", "message", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if not self.title and not self.message:
            raise ValueError("El evento debe incluir un título o un mensaje.")
        return self


class NotificationEvent(BaseModel):
    id: UUID
    source: str
    event: str
    event_id: str | None
    title: str
    message: str
    received_at: datetime
    whatsapp_status: str = "not_requested"
    whatsapp_error: str | None = None


class NotificationReceipt(BaseModel):
    id: UUID
    status: str = "received"
    duplicate: bool
    whatsapp_status: str = "not_requested"
