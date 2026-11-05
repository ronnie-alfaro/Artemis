from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, JsonValue, field_validator


class ResultCondition(BaseModel):
    path: str = Field(min_length=1, max_length=256)
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "gt",
        "gte",
        "lt",
        "lte",
        "exists",
        "not_exists",
        "is_empty",
        "changed",
    ] = "equals"
    value: JsonValue = None


class TimeTrigger(BaseModel):
    kind: Literal["time"] = "time"
    at: AwareDatetime


class ToolTrigger(BaseModel):
    kind: Literal["tool"] = "tool"
    tool_name: str = Field(min_length=1, max_length=128)
    input: dict[str, JsonValue] = Field(default_factory=dict)
    condition: ResultCondition
    interval_seconds: int = Field(default=60, ge=10, le=604800)


ReminderTrigger = Annotated[TimeTrigger | ToolTrigger, Field(discriminator="kind")]


class ReminderCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4096)
    trigger: ReminderTrigger
    request_id: UUID | None = None

    @field_validator("message", mode="before")
    @classmethod
    def trim_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class Reminder(BaseModel):
    id: UUID
    message: str
    trigger: ReminderTrigger
    status: Literal["active", "paused", "firing", "completed", "cancelled"]
    next_check_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None = None
    last_value: str | None = None
    last_error: str | None = None
    notification_id: UUID | None = None
    last_hash: str | None = Field(default=None, exclude=True)


class ReminderStateUpdate(BaseModel):
    status: Literal["active", "paused"]


class ReminderPreview(BaseModel):
    matched: bool
    values: list[JsonValue]
    output: dict[str, JsonValue]
