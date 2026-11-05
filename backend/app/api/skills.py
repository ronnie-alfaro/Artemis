from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.agents.status import StatusAgent
from app.application.orchestrator import Orchestrator
from app.domain.skills import DEFAULT_PRESENTATIONS, SkillPresentation


def install_skill_routes(app: FastAPI, orchestrator: Orchestrator) -> None:
    agent = orchestrator.registry.get("status")  # type: ignore[attr-defined]
    if not isinstance(agent, StatusAgent):
        raise RuntimeError("El agente de estado no está disponible")

    @app.get("/api/v1/skills/presentations")
    async def list_presentations() -> dict[str, SkillPresentation]:
        return agent.presentations

    @app.put("/api/v1/skills/{skill_id}/presentation")
    async def save_presentation(skill_id: str, payload: SkillPresentation) -> SkillPresentation:
        if skill_id not in DEFAULT_PRESENTATIONS:
            raise HTTPException(404, "Habilidad no encontrada.")
        if any(key != skill_id and value.name.casefold() == payload.name.casefold()
               for key, value in agent.presentations.items()):
            raise HTTPException(422, "Ese nombre ya pertenece a otra habilidad.")
        if payload.name.casefold() in {
            key.casefold() for key in DEFAULT_PRESENTATIONS if key != skill_id
        }:
            raise HTTPException(422, "Ese nombre identifica a otra habilidad.")
        store = getattr(app.state, "skill_presentations", None)
        if store is None:
            raise HTTPException(503, "La persistencia de configuración no está disponible.")
        await store.save(skill_id, payload)
        agent.presentations[skill_id] = payload
        return payload
