from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
