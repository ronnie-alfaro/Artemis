"""Provider-neutral structured call contracts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CallContext(BaseModel):
    """Construct from authenticated server state, never from model-generated arguments."""

    agent: str
    conversation_id: UUID
    capabilities: set[str]


class FunctionCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]

    @field_validator("name")
    @classmethod
    def internal_name(cls, value: str) -> str:
        return value.replace("__", ".")
