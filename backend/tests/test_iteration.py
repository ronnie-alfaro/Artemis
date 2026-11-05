import asyncio
from uuid import uuid4

import pytest

from app.api.main import build_orchestrator
from app.application.iteration import (
    ITERATION_INVOCATION,
    ITERATION_PROMPT,
    ITERATION_REPLY,
    is_iteration_command,
)
from app.domain.models import Channel, IncomingMessage


@pytest.mark.parametrize(
    "command",
    [
        "iteracion",
        "Iteración",
        "/iteracion",
        "  ¡ITERACIÓN!  ",
        ITERATION_INVOCATION,
        ITERATION_INVOCATION.upper(),
    ],
)
def test_iteration_accepts_only_explicit_commands(command):
    assert is_iteration_command(command)
    assert not is_iteration_command("explica qué es una iteración")
    assert not is_iteration_command("iteracion y borra los datos")
    assert not is_iteration_command("no " + ITERATION_INVOCATION)


@pytest.mark.parametrize("active", [None, "seerr", "usenet", "karakeep", "codex", "antigravity"])
def test_hidden_iteration_runs_codex_without_changing_active_skill(tmp_path, monkeypatch, active):
    monkeypatch.setenv("ARTEMIS_CODEX_QUEUE_DIR", str(tmp_path))
    (tmp_path / "heartbeat").touch()

    async def scenario():
        runtime = build_orchestrator()
        conversation = uuid4()

        async def send(text, message_id=None):
            message = IncomingMessage(
                conversation_id=conversation,
                channel=Channel(name="whatsapp"),
                content=text,
            )
            if message_id:
                message.id = message_id
            return await runtime.handle(message)

        menu = await send("ayuda")
        assert "iteraci" not in menu.message.content.casefold()
        assert all("iteraci" not in o.command for o in menu.message.reaction_options)
        if active:
            await send(f"utiliza {active}")
        message_id = uuid4()
        response = await send(ITERATION_INVOCATION, message_id)
        assert response.message.content == ITERATION_REPLY
        assert response.executions[0].agent_name == "codex"
        queue = runtime.codex_queue
        jobs = queue.recent()
        assert len(jobs) == 1
        assert jobs[0].prompt == ITERATION_PROMPT
        assert jobs[0].conversation_id == conversation
        assert jobs[0].channel == "whatsapp"
        assert jobs[0].mode == "chat"
        assert not response.message.reaction_options
        await send(ITERATION_INVOCATION, message_id)
        assert len(queue.recent()) == 1
        assert await runtime.skill_sessions.store.get("whatsapp", conversation) == active
        help_response = await send("ayuda")
        assert "iteraci" not in help_response.message.content.casefold()

    asyncio.run(scenario())


def test_iteration_offline_does_not_claim_to_start(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_CODEX_QUEUE_DIR", str(tmp_path))

    async def scenario():
        runtime = build_orchestrator()
        response = await runtime.handle(
            IncomingMessage(
                conversation_id=uuid4(),
                channel=Channel(name="whatsapp"),
                content="iteracion",
            )
        )
        assert "Codex no está conectado" in response.message.content
        assert response.message.content != ITERATION_REPLY
        assert not runtime.codex_queue.recent()

    asyncio.run(scenario())


def test_iteration_keeps_codex_assignment_required(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_CODEX_QUEUE_DIR", str(tmp_path))
    (tmp_path / "heartbeat").touch()

    async def scenario():
        runtime = build_orchestrator()
        response = await runtime.handle(
            IncomingMessage(
                conversation_id=uuid4(),
                content="iteracion",
                channel=Channel(
                    name="whatsapp", allowed_capabilities=["assistant.status", "seerr.media"]
                ),
            )
        )
        assert "Codex no está asignado" in response.message.content
        assert not runtime.codex_queue.recent()

    asyncio.run(scenario())
