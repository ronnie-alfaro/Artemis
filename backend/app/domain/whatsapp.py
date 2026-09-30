from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class WhatsAppMessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    REACTION = "reaction"


class WhatsAppSettings(BaseModel):
    """Secret-backed configuration for one manually created WhatsApp agent."""

    model_config = ConfigDict(frozen=True)

    agent_name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    token: SecretStr
    base_url: str = "https://api.whatsapp.com/agent/v1"
    poll_timeout_seconds: int = Field(default=25, ge=0, le=25)

    @field_validator("base_url")
    @classmethod
    def https_only(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("WhatsApp base_url must use HTTPS")
        return value.rstrip("/")


class WhatsAppAttachment(BaseModel):
    id: str
    mime_type: str | None = None
    sha256_base64: str | None = None
    caption: str | None = None
    filename: str | None = None
    voice: bool | None = None


class WhatsAppInbound(BaseModel):
    id: str
    sender_id: str
    timestamp: str
    type: WhatsAppMessageType
    text: str | None = None
    attachments: list[WhatsAppAttachment] = Field(default_factory=list)

    @property
    def content(self) -> str:
        if self.text:
            return self.text
        if self.type is WhatsAppMessageType.REACTION:
            return "[WhatsApp reaction]"
        description = self.attachments[0].caption if self.attachments else None
        return description or f"[WhatsApp {self.type.value} message]"


class WhatsAppUpdateBatch(BaseModel):
    messages: list[WhatsAppInbound] = Field(default_factory=list)
    next_offset: int


class WhatsAppChannelStatus(BaseModel):
    configured: bool
    agent_name: str | None = None
    running: bool = False
    last_error: str | None = None


class WhatsAppSkillBinding(BaseModel):
    agent_name: str
    capabilities: list[str] = Field(default_factory=list)
    available_capabilities: list[str] = Field(default_factory=list)


class WhatsAppSkillSelection(BaseModel):
    capabilities: list[str] = Field(default_factory=list)


DEFAULT_WHATSAPP_GREETING = "Hola, soy tu asistente de WhatsApp."


class WhatsAppAgentProfile(BaseModel):
    agent_name: str
    greeting: str = Field(default=DEFAULT_WHATSAPP_GREETING, min_length=1, max_length=1024)


class WhatsAppAgentProfileUpdate(BaseModel):
    greeting: str = Field(min_length=1, max_length=1024)
