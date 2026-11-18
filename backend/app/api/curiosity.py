import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.application.curiosity import analyze_specification
from app.domain.curiosity import Exploration, ExplorationInput, ExplorationSummary
from app.infrastructure.curiosity import PostgresExplorationStore

router = APIRouter(prefix="/api/v1/curiosity/explorations")


def _store(request: Request) -> PostgresExplorationStore:
    store = getattr(request.app.state, "curiosity", None)
    if not isinstance(store, PostgresExplorationStore):
        raise HTTPException(503, "El almacenamiento de Curiosidad no está disponible.")
    return store


@router.get("")
async def list_explorations(request: Request) -> list[ExplorationSummary]:
    return await _store(request).recent()


@router.post("")
async def submit_exploration(request: Request, payload: ExplorationInput) -> Exploration:
    store = _store(request)
    report = await asyncio.to_thread(analyze_specification, payload)
    return await store.save(report)


@router.get("/{exploration_id}")
async def get_exploration(request: Request, exploration_id: UUID) -> Exploration:
    report = await _store(request).get(exploration_id)
    if report is None:
        raise HTTPException(404, "Exploración no encontrada.")
    return report
