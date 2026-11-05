import asyncio
from uuid import uuid4

from app.api.main import build_orchestrator
from app.application.codex import CodexDeliveryWorker, CodexQueue
from app.domain.models import Channel, IncomingMessage


def test_queue_deduplicates_messages_and_rejects_offline_workers(tmp_path):
    queue = CodexQueue(str(tmp_path))
    message_id, conversation_id = uuid4(), uuid4()
    try:
        queue.submit(message_id, conversation_id, "rest", "Hola", "chat")
        raise AssertionError("An offline worker must not accept new jobs")
    except ValueError:
        pass
    (tmp_path / "heartbeat").touch()
    first = queue.submit(message_id, conversation_id, "rest", "Hola", "chat")
    duplicate = queue.submit(message_id, conversation_id, "rest", "Hola", "chat")
    assert first.id == duplicate.id
    assert len(queue.recent()) == 1
    (tmp_path / "heartbeat").unlink()
    assert queue.submit(message_id, conversation_id, "rest", "Hola", "chat").id == first.id


def test_skill_routes_questions_tool_requests_and_conversation_scoped_results(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ARTEMIS_CODEX_QUEUE_DIR", str(tmp_path))
    (tmp_path / "heartbeat").touch()

    async def scenario():
        runtime = build_orchestrator()
        conversation = uuid4()

        async def send(text, identifier=conversation):
            return await runtime.handle(
                IncomingMessage(
                    conversation_id=identifier, channel=Channel(name="rest"), content=text
                )
            )

        assert "Codex activo" in (await send("utiliza codex")).message.content
        assert "crear herramienta" in (await send("ayuda")).message.content
        response = await send("¿Qué herramientas tiene Artemis?")
        assert "Petición" in response.message.content
        queue = runtime.codex_queue
        question = queue.recent()[0]
        assert question.mode == "chat"
        await send("crear herramienta para consultar un servidor")
        tool = queue.recent()[0]
        assert tool.mode == "tool"
        assert str(tool.id)[:8] in (await send("estado")).message.content
        question.status, question.answer = "completed", "Respuesta privada"
        queue.save(question)
        assert "Respuesta privada" in (await send(f"resultado {question.id}")).message.content
        other = uuid4()
        await send("utiliza codex", other)
        assert "No encuentro" in (await send(f"resultado {question.id}", other)).message.content
        await send("salir")
        assert (await send("ayuda")).executions[0].agent_name == "status"

    asyncio.run(scenario())


def test_delivery_targets_origin_and_does_not_repeat_chunks_after_partial_failure(tmp_path):
    queue = CodexQueue(str(tmp_path))
    (tmp_path / "heartbeat").touch()
    conversation = uuid4()
    job = queue.submit(uuid4(), conversation, "whatsapp", "Hola", "chat")
    job.status, job.answer = "completed", "a" * 5000
    queue.save(job)
    other = queue.submit(uuid4(), uuid4(), "rest", "Hola desde la web", "chat")
    other.status, other.answer = "completed", "No enviar a WhatsApp"
    queue.save(other)

    class Channel:
        def __init__(self):
            self.sent = []
            self.fail = True

        async def recipient_for_conversation(self, identifier):
            assert identifier == conversation
            return "origin"

        async def send_notification(self, recipient, text):
            assert recipient == "origin"
            if len(self.sent) == 1 and self.fail:
                raise RuntimeError("temporary")
            self.sent.append(text)

    async def scenario():
        channel = Channel()
        worker = CodexDeliveryWorker(queue, channel)
        try:
            await worker.run_once()
        except RuntimeError:
            pass
        assert len(channel.sent) == 1
        assert not queue.load(job.id).delivered
        channel.fail = False
        await worker.run_once()
        assert len(channel.sent) == 2
        assert queue.load(job.id).delivered
        assert not queue.load(other.id).delivered
        await worker.run_once()
        assert len(channel.sent) == 2

    asyncio.run(scenario())


def test_codex_api_protects_artifacts_and_returns_job_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    monkeypatch.setenv("ARTEMIS_CODEX_QUEUE_DIR", str(tmp_path))
    monkeypatch.setenv("ARTEMIS_ADMIN_TOKEN", "test-secret")
    (tmp_path / "heartbeat").touch()
    queue = CodexQueue(str(tmp_path))
    job = queue.submit(uuid4(), uuid4(), "rest", "crear herramienta", "tool")
    job.status, job.has_patch = "completed", True
    queue.save(job)
    queue.path(job.id, ".patch").write_text("test patch")
    with TestClient(create_app()) as client:
        endpoint = f"/api/v1/skills/codex/jobs/{job.id}/patch"
        assert client.get(endpoint).status_code == 401
        auth = {"Authorization": "Bearer test-secret"}
        assert client.get(endpoint, headers=auth).text == "test patch"
        items = client.get("/api/v1/skills/codex/jobs", headers=auth).json()
        assert "conversation_id" not in items[0]
        assert client.get("/api/v1/skills/codex/configuration", headers=auth).json()["connected"]
        assert (
            client.get(f"/api/v1/skills/codex/jobs/{uuid4()}/patch", headers=auth).status_code
            == 404
        )
