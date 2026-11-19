"""Read-only administrative access to persistent memory."""
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.memory_manager import MEMORY_MAP_LIMIT, MemoryManager

MemoryCollection = Literal["agent_persona", "agent_memory", "agent_relations"]


class MemoryExploreRequest(BaseModel):
    agent: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=1000)
    memory_id: str | None = Field(default=None, min_length=1, max_length=200)
    ids: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=MEMORY_MAP_LIMIT,
    )


def install_memory_routes(app: FastAPI, memory: MemoryManager) -> None:
    @app.get("/api/v1/activity/memories")
    def recent_memories() -> list[dict[str, object]]:
        try:
            return memory.recent_memories()
        except Exception as exc:
            raise HTTPException(503, "No se pudo consultar la actividad de memoria.") from exc

    @app.get("/api/v1/memory/{collection}")
    def browse_memory(
        collection: MemoryCollection,
        agent: str | None = Query(default=None, min_length=1, max_length=200),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, object]:
        try:
            return memory.browse(collection, agent, offset, limit)
        except Exception as exc:
            raise HTTPException(503, "No se pudo consultar la memoria persistente.") from exc

    @app.get("/api/v1/memory/{collection}/map")
    def map_memory(
        collection: MemoryCollection,
        agent: str | None = Query(default=None, min_length=1, max_length=200),
    ) -> dict[str, object]:
        try:
            return memory.browse(collection, agent, limit=MEMORY_MAP_LIMIT)
        except Exception as exc:
            raise HTTPException(503, "No se pudo cargar el mapa de memoria.") from exc

    @app.post("/api/v1/memory/{collection}/explore")
    def explore_memory(
        collection: MemoryCollection, body: MemoryExploreRequest,
    ) -> list[dict[str, object]]:
        text = body.text.strip() if body.text else None
        if bool(text) == bool(body.memory_id):
            raise HTTPException(422, "Escribe una frase o selecciona un recuerdo.")
        try:
            return memory.explore(
                collection, agent=body.agent, text=text, memory_id=body.memory_id, ids=body.ids,
            )
        except Exception as exc:
            raise HTTPException(503, "No se pudo buscar en la memoria persistente.") from exc
