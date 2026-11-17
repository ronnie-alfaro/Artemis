"""Read-only administrative access to persistent memory."""
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from app.infrastructure.memory_manager import MemoryManager


def install_memory_routes(app: FastAPI, memory: MemoryManager) -> None:
    @app.get("/api/v1/memory/{collection}")
    def browse_memory(
        collection: Literal["agent_persona", "agent_memory", "agent_relations"],
        agent: str | None = Query(default=None, min_length=1, max_length=200),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, object]:
        try:
            return memory.browse(collection, agent, offset, limit)
        except Exception as exc:
            raise HTTPException(503, "No se pudo consultar la memoria persistente.") from exc
