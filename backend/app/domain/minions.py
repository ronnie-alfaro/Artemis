"""Ephemeral worker contracts shared by local and remote transports."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.domain.models import utcnow
from app.domain.tool_calling import CallContext, FunctionCall


class MinionJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    mythology: str
    state: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    task: str = Field(max_length=240)
    target: str
    call: FunctionCall = Field(exclude=True)
    context: CallContext = Field(exclude=True)
    approval_id: UUID | None = Field(default=None, exclude=True)
    result: dict[str, Any] | None = Field(default=None, exclude=True)


class MinionEvent(BaseModel):
    sequence: int
    timestamp: str = Field(default_factory=lambda: utcnow().isoformat())
    minion: dict[str, Any]
