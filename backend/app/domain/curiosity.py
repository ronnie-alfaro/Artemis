import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class ExplorationStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ExplorationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: str = Field(min_length=1, max_length=500)
    specification: str = Field(min_length=2, max_length=131_072)

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("El objetivo contiene caracteres inválidos.")
        return value


class DeclaredOperation(BaseModel):
    method: str
    path: str
    operation_id: str | None = None
    parameters: list[str] = Field(default_factory=list)
    responses: list[str] = Field(default_factory=list)
    authentication_declared: bool
    references_present: bool


class ExplorationSummary(BaseModel):
    id: UUID
    objective: str
    fingerprint: str
    created_at: datetime
    status: ExplorationStatus


class Exploration(ExplorationSummary):
    specification_version: str | None = None
    operations: list[DeclaredOperation] = Field(default_factory=list)
    reason: str | None = None
    history: list[ExplorationStatus]


class MountedRead(BaseModel):
    operation: str
    url: str
    response_schema: dict[str, JsonValue]


class MountedAPI(BaseModel):
    name: str
    operations: list[MountedRead]


CAPABILITY = "curiosity.api"
CHAT_CONTEXT_KEY = "curiosity_direct_command"
COMMAND_NAME = r"[A-Za-z0-9_-]{1,64}"


def chat_command(content: str) -> str | None:
    text = content.strip()
    prefix = re.match(r"^/?curiosidad\s+", text, re.I)
    return text[prefix.end() :] if prefix else None
