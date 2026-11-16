import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_usenet import FakeDownloads

from app.api.main import build_orchestrator
from app.application.antigravity import AntigravityDeliveryWorker
from app.application.conversation import ConversationSkillWorker
from app.domain.models import Channel, IncomingMessage


class Bot:
    def __init__(self, conversation, allowed):
        self.conversation, self.allowed, self.sent = conversation, allowed, []

    def status(self):
        return SimpleNamespace(agent_name="primary")

    async def capabilities(self):
        return self.allowed

    async def recipient_for_conversation(self, identifier):
        return "42" if identifier == self.conversation else None

    async def send_notification(self, recipient, text):
        self.sent.append((recipient, text))


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANTIGRAVITY_QUEUE_DIR", str(tmp_path))
    (tmp_path / "heartbeat").touch()
    (tmp_path / "conversation-v1").touch()
    downloads = FakeDownloads()
    orchestrator = build_orchestrator(usenet_client=downloads)
    conversation = uuid4()
    bot = Bot(conversation, ["assistant.status", "usenet.downloads"])
    channel = Channel(
        name="telegram",
        natural_conversation=True,
        agent_name="primary",
        assistant_persona="Hablas como un pirata amable.",
        allowed_capabilities=bot.allowed,
    )
    bridge = ConversationSkillWorker(
        orchestrator.antigravity_queue,
        lambda name: SimpleNamespace(runtime=bot),
        orchestrator.handle,
        orchestrator.approvals,
    )
    return orchestrator, bot, channel, bridge, downloads


def test_uses_agy_by_default_with_persona_and_only_assigned_skills(tmp_path, monkeypatch):
    async def run():
        orchestrator, bot, channel, bridge, downloads = setup(tmp_path, monkeypatch)
        response = await orchestrator.handle(
            IncomingMessage(
                conversation_id=bot.conversation,
                channel=channel,
                content="¿Me buscas Matrix para bajar?",
            )
        )
        assert response.message.deferred
        assert response.plan.nodes[0].capability == "assistant.conversation"
        job = orchestrator.antigravity_queue.recent()[0]
        assert job.mode == "assistant" and "pirata" in job.persona
        assert [skill["capability"] for skill in job.skills] == ["usenet.downloads"]
        assert not downloads.searches
        job.status, job.decision = (
            "waiting_skill",
            {
                "reply": "",
                "capability": "usenet.downloads",
                "command": "busca Matrix",
            },
        )
        orchestrator.antigravity_queue.save(job)
        await bridge.run_once()
        updated = orchestrator.antigravity_queue.load(job.id)
        assert downloads.searches == [("Matrix", "")]
        assert updated.status == "queued"
        assert "result" in updated.observations[0]
        updated.status, updated.answer = "completed", "¡Arrr! Encontré Matrix. ¿Cuál prefieres?"
        orchestrator.antigravity_queue.save(updated)
        delivery = AntigravityDeliveryWorker(orchestrator.antigravity_queue, bot)
        await delivery.run_once()
        await delivery.run_once()
        assert bot.sent == [("42", updated.answer)]

    asyncio.run(run())


def test_help_and_former_menus_also_go_to_conversation(tmp_path, monkeypatch):
    async def run():
        orchestrator, bot, channel, _, _ = setup(tmp_path, monkeypatch)
        for content in ["hola", "ayuda", "¿Qué puedes hacer?", "busca algo", "utiliza usenet"]:
            response = await orchestrator.handle(
                IncomingMessage(
                    conversation_id=bot.conversation,
                    channel=channel,
                    content=content,
                )
            )
            assert response.message.deferred
            assert response.executions[0].agent_name == "conversation"

    asyncio.run(run())


def test_old_worker_does_not_receive_conversational_jobs(tmp_path, monkeypatch):
    async def run():
        orchestrator, bot, channel, _, _ = setup(tmp_path, monkeypatch)
        (tmp_path / "conversation-v1").unlink()
        response = await orchestrator.handle(
            IncomingMessage(
                conversation_id=bot.conversation,
                channel=channel,
                content="Hola",
            )
        )
        assert not response.message.deferred
        assert "AGY" in response.message.content
        assert orchestrator.antigravity_queue.recent() == []

    asyncio.run(run())


@pytest.mark.parametrize("revoked", [False, True])
def test_bridge_blocks_unassigned_skills_and_rechecks_live_permissions(
    tmp_path, monkeypatch, revoked
):
    async def run():
        orchestrator, bot, channel, bridge, downloads = setup(tmp_path, monkeypatch)
        await orchestrator.handle(
            IncomingMessage(
                conversation_id=bot.conversation, channel=channel, content="Busca Matrix"
            )
        )
        job = orchestrator.antigravity_queue.recent()[0]
        job.status = "waiting_skill"
        job.decision = {
            "capability": "usenet.downloads" if revoked else "seerr.media",
            "command": "busca Matrix",
        }
        orchestrator.antigravity_queue.save(job)
        if revoked:
            bot.allowed = ["assistant.status"]
        await bridge.run_once()
        assert downloads.searches == []
        assert (
            "no está asignada"
            in orchestrator.antigravity_queue.load(job.id).observations[0]["result"]
        )

    asyncio.run(run())


@pytest.mark.parametrize("user_confirmed", [False, True])
def test_model_cannot_grant_itself_approval(tmp_path, monkeypatch, user_confirmed):
    async def run():
        orchestrator, bot, channel, bridge, _ = setup(tmp_path, monkeypatch)
        approval = orchestrator.approvals.create(
            conversation_id=bot.conversation,
            agent_name="usenet",
            tool_name="usenet.enqueue",
            parameters={},
            reason="Download selected item",
            idempotency_key="pending",
        )
        await orchestrator.handle(
            IncomingMessage(
                conversation_id=bot.conversation,
                channel=channel,
                content="sí, dale" if user_confirmed else "¿qué está pendiente?",
            )
        )
        job = orchestrator.antigravity_queue.recent()[0]
        assert str(approval.id) in job.approval_ids
        job.status, job.decision = (
            "waiting_skill",
            {"capability": "usenet.downloads", "command": "confirmo"},
        )
        orchestrator.antigravity_queue.save(job)
        called = []

        async def handle(message):
            called.append(message)
            return SimpleNamespace(message=SimpleNamespace(content="Done"))

        bridge.handle = handle
        await bridge.run_once()
        assert bool(called) == user_confirmed

    asyncio.run(run())


@pytest.mark.parametrize("skill", ["codex", "antigravity"])
def test_bridge_dispatches_explicit_capability_before_session_commands(
    tmp_path, monkeypatch, skill
):
    async def run():
        codex_directory = tmp_path / "codex"
        codex_directory.mkdir()
        (codex_directory / "heartbeat").touch()
        monkeypatch.setenv("ARTEMIS_CODEX_QUEUE_DIR", str(codex_directory))
        orchestrator, bot, channel, bridge, _ = setup(tmp_path, monkeypatch)
        capability = f"{skill}.assistant"
        bot.allowed.append(capability)
        channel.allowed_capabilities.append(capability)
        await orchestrator.handle(
            IncomingMessage(
                conversation_id=bot.conversation, channel=channel, content="Revisa Artemis"
            )
        )
        job = orchestrator.antigravity_queue.recent()[0]
        command = f"utiliza {skill} revisa los logs del servicio"
        job.status = "waiting_skill"
        job.decision = {"capability": capability, "command": command}
        orchestrator.antigravity_queue.save(job)
        await bridge.run_once()
        updated = orchestrator.antigravity_queue.load(job.id)
        assert "no está disponible" not in updated.observations[0]["result"]
        queue = getattr(orchestrator, f"{skill}_queue")
        dispatched = [item for item in queue.recent() if item.mode == "chat"]
        assert len(dispatched) == 1
        assert dispatched[0].prompt == command
        assert dispatched[0].channel == channel.name
        assert dispatched[0].conversation_id == bot.conversation
        assert await orchestrator.skill_sessions.store.get(channel.name, bot.conversation) is None

    asyncio.run(run())
