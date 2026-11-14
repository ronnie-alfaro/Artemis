import asyncio
import logging
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from test_whatsapp import FakeState

from app.application.whatsapp import WhatsAppAgentRuntime
from app.domain.models import ChatResponse, ExecutionPlan, OutgoingMessage
from app.domain.whatsapp import WhatsAppSettings
from app.infrastructure.telegram_http import HttpTelegramClient


def settings():
    return WhatsAppSettings(agent_name="123", token=SecretStr("123:secret-test-token"))


def test_private_authorized_chat_reuses_orchestrator_and_durable_inbox(caplog):
    async def run():
        calls = []
        requests = []

        def transport(request):
            requests.append(request)
            if request.url.path.endswith("getUpdates"):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": [
                            {
                                "update_id": i,
                                "message": {
                                    "chat": {"id": uid, "type": kind},
                                    "from": {"id": uid},
                                    "text": "/start",
                                },
                            }
                            for i, uid, kind in [
                                (1, 42, "private"),
                                (2, 99, "private"),
                                (3, 42, "group"),
                            ]
                        ],
                    },
                )
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 10}})

        async def handle(incoming):
            calls.append(incoming)
            return ChatResponse(
                message=OutgoingMessage(
                    conversation_id=incoming.conversation_id,
                    execution_id=uuid4(),
                    content="Listo",
                ),
                plan=ExecutionPlan(conversation_id=incoming.conversation_id, nodes=[]),
                executions=[],
            )

        state = FakeState()
        client = HttpTelegramClient(settings(), {42}, httpx.MockTransport(transport))
        runtime = WhatsAppAgentRuntime(settings(), client, state, handle, channel_name="telegram")
        await runtime.run_once()
        await runtime.run_once()
        assert len(calls) == 1
        assert calls[0].channel.name == "telegram"
        assert calls[0].channel.allowed_capabilities == ["assistant.status"]
        assert calls[0].content == "hola"
        assert state.offset == 4
        assert runtime._agent_key == "telegram:123"
        assert len([r for r in requests if r.url.path.endswith("sendMessage")]) == 1
        assert "123:secret-test-token" not in caplog.text
        await client.aclose()

    with caplog.at_level(logging.INFO, logger="httpx"):
        asyncio.run(run())


def test_bot_api_errors_are_safe_and_cursor_is_not_advanced():
    async def run():
        client = HttpTelegramClient(
            settings(),
            {42},
            httpx.MockTransport(lambda request: httpx.Response(401, json={"ok": False})),
        )
        state = FakeState()
        runtime = WhatsAppAgentRuntime(settings(), client, state, None, channel_name="telegram")
        with pytest.raises(RuntimeError, match="Telegram Bot API request failed") as error:
            await runtime.run_once()
        assert "secret-test-token" not in str(error.value)
        assert error.value.__context__ is None
        assert state.offset is None
        await client.aclose()

    asyncio.run(run())


def test_empty_allowlist_is_rejected():
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_IDS"):
        HttpTelegramClient(settings(), set())


@pytest.mark.parametrize("provider", ["codex", "antigravity"])
def test_async_results_return_to_telegram_conversation(tmp_path, provider):
    from importlib import import_module

    module = import_module(f"app.application.{provider}")
    prefix = "Codex" if provider == "codex" else "Antigravity"
    queue = getattr(module, f"{prefix}Queue")(str(tmp_path))
    (tmp_path / "heartbeat").touch()
    conversation = uuid4()
    job = queue.submit(uuid4(), conversation, "telegram", "Hola", "chat")
    job.status, job.answer = "completed", "Resultado para Telegram"
    queue.save(job)

    class Channel:
        def __init__(self):
            self.sent = []

        async def recipient_for_conversation(self, identifier):
            return "42" if identifier == conversation else None

        async def send_notification(self, recipient, content):
            self.sent.append((recipient, content))

    channel = Channel()
    worker = getattr(module, f"{prefix}DeliveryWorker")(queue, channel)
    asyncio.run(worker.run_once())
    asyncio.run(worker.run_once())
    assert len(channel.sent) == 1
    assert channel.sent[0][0] == "42"
    assert "Resultado para Telegram" in channel.sent[0][1]


def test_revoked_user_cannot_execute_messages_already_queued():
    async def run():
        from test_whatsapp import FakeClient

        from app.domain.whatsapp import WhatsAppInbound, WhatsAppMessageType, WhatsAppUpdateBatch

        async def handle(incoming):
            raise AssertionError("Revoked user must not reach tools")

        state = FakeState()
        inbound = WhatsAppInbound(
            id="old", sender_id="99", timestamp="0", type=WhatsAppMessageType.TEXT, text="run tool"
        )
        await state.enqueue("telegram:123", inbound)
        runtime = WhatsAppAgentRuntime(
            settings(),
            FakeClient(WhatsAppUpdateBatch(next_offset=1)),
            state,
            handle,
            channel_name="telegram",
            allowed_recipient_ids=frozenset({"42"}),
        )
        await runtime.run_once()
        assert "old" in state.complete

    asyncio.run(run())
