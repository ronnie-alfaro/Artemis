"""Typed contracts for the first migrated tools; legacy text agents remain compatible."""

from typing import Literal

from pydantic import Field

from app.application.native_tools import Arguments, NativeTools


class MemoryText(Arguments):
    collection: Literal["agent_persona", "agent_memory", "agent_relations"] = "agent_memory"
    text: str = Field(min_length=1, max_length=20000)


class MemorySearch(MemoryText):
    limit: int = Field(default=5, ge=1, le=100)


class MemoryForget(Arguments):
    collection: Literal["agent_persona", "agent_memory", "agent_relations"] = "agent_memory"
    id: str = Field(min_length=1, max_length=200)


def register_memory_contracts(tools: NativeTools) -> None:
    tools.register("memory.search", "memory", MemorySearch)
    tools.register("memory.remember", "memory", MemoryText)
    tools.register("memory.forget", "memory", MemoryForget)
