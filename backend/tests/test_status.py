from __future__ import annotations

import asyncio
from uuid import uuid4

from app.agents.status import StatusAgent
from app.domain.models import AgentRequest, Channel, IncomingMessage


def test_status_agent_uses_custom_greeting_and_only_bound_skills() -> None:
    message = IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(
            name="whatsapp",
            allowed_capabilities=["assistant.status", "seerr.media"],
            assistant_greeting="Bienvenido a Cine Club.",
        ),
        content="hola",
    )
    response = asyncio.run(
        StatusAgent(
            {
                "seerr.media": (
                    "• Películas y series: escribe ‘quiero pedir <título>’. "
                    "Responde con el número y luego ‘confirmo’."
                )
            }
        ).run(AgentRequest(execution_id=uuid4(), node_id="status", message=message))
    )
    assert "Bienvenido a Cine Club." in response.result.content
    assert "Seerr: Busca y solicita películas y series." in response.result.content


def test_status_agent_does_not_advertise_unbound_skills() -> None:
    message = IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="whatsapp", allowed_capabilities=["assistant.status"]),
        content="hola",
    )
    response = asyncio.run(
        StatusAgent().run(AgentRequest(execution_id=uuid4(), node_id="status", message=message))
    )
    assert "no tengo habilidades opcionales" in response.result.content
    assert "películas o series" not in response.result.content


def test_status_agent_advertises_assigned_karakeep_skill() -> None:
    message = IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="whatsapp", allowed_capabilities=["karakeep.bookmarks"]),
        content="hola",
    )
    response = asyncio.run(
        StatusAgent(
            {"karakeep.bookmarks": "• Guardar enlaces: escribe ‘guarda https://ejemplo.com’."}
        ).run(AgentRequest(execution_id=uuid4(), node_id="status", message=message))
    )
    assert "Karakeep: Busca y guarda enlaces." in response.result.content


def test_help_summary_and_details_follow_custom_name_and_bindings() -> None:
    from app.api.main import build_orchestrator
    from app.domain.skills import SkillPresentation

    orchestrator = build_orchestrator()
    status = orchestrator.registry.get("status")
    status.presentations["usenet"] = SkillPresentation(
        name="Mis descargas", description="Busca y descarga títulos."
    )

    def ask(content: str, allowed: list[str] | None = None) -> str:
        message = IncomingMessage(
            conversation_id=uuid4(),
            channel=Channel(name="whatsapp", allowed_capabilities=allowed or ["usenet.downloads"]),
            content=content,
        )
        result = asyncio.run(orchestrator.handle(message))
        assert result.plan.nodes[0].agent_name == "status"
        return result.message.content

    summary = ask("ayuda")
    assert "Mis descargas: Busca y descarga títulos." in summary
    assert "pausa las descargas" not in summary
    assert "Karakeep:" not in summary
    for command in ("ayuda Usenet", "AYUDA Mis descargas", "/help usenet.downloads"):
        detail = ask(command)
        assert detail.startswith("Mis descargas\n")
        assert "•" in detail
        assert "Descargas:\n" not in detail
    assert "No encuentro" in ask("ayuda desconocido")
    assert "No encuentro" in ask("ayuda Usenet", ["assistant.status"])


def test_skill_presentation_api_saves_and_validates() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.main import build_orchestrator
    from app.api.skills import install_skill_routes

    class Store:
        def __init__(self) -> None:
            self.saved = {}

        async def save(self, skill_id, value):
            self.saved[skill_id] = value

    app = FastAPI()
    orchestrator = build_orchestrator()
    install_skill_routes(app, orchestrator)
    store = Store()
    app.state.skill_presentations = store
    client = TestClient(app)
    payload = {"name": "  Mis descargas  ", "description": "  Busca títulos. "}
    response = client.put("/api/v1/skills/usenet/presentation", json=payload)
    assert response.status_code == 200
    assert store.saved["usenet"].name == "Mis descargas"
    assert client.get("/api/v1/skills/presentations").json()["usenet"] == {
        "name": "Mis descargas", "description": "Busca títulos."
    }
    for invalid in ({"name": " ", "description": "válida"},
                    {"name": "Seerr", "description": "válida"},
                    {"name": "x" * 81, "description": "válida"},
                    {"name": 123, "description": "válida"}):
        assert client.put("/api/v1/skills/usenet/presentation", json=invalid).status_code == 422
    assert client.put("/api/v1/skills/unknown/presentation", json=payload).status_code == 404
    app.state.skill_presentations = None
    assert client.put("/api/v1/skills/usenet/presentation", json=payload).status_code == 503
