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
        StatusAgent().run(AgentRequest(execution_id=uuid4(), node_id="status", message=message))
    )
    assert "Bienvenido a Cine Club." in response.result.content
    assert "películas o series" in response.result.content


def test_status_agent_does_not_advertise_unbound_skills() -> None:
    message = IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="whatsapp", allowed_capabilities=["assistant.status"]),
        content="hola",
    )
    response = asyncio.run(
        StatusAgent().run(AgentRequest(execution_id=uuid4(), node_id="status", message=message))
    )
    assert "no tengo skills opcionales" in response.result.content
    assert "películas o series" not in response.result.content
