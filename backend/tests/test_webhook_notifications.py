from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
from test_whatsapp import FakeClient, FakeState

from app.application.webhook_notifications import WebhookNotificationWorker, notification_text
from app.application.whatsapp import WhatsAppAgentRuntime
from app.domain.models import OutgoingMessage, utcnow
from app.domain.webhooks import WebhookEvent
from app.domain.whatsapp import WhatsAppSettings, WhatsAppUpdateBatch
from app.infrastructure.whatsapp_http import HttpWhatsAppClient


def event():
    return WebhookEvent(
        id=uuid4(), source="seerr", event="MEDIA_AVAILABLE", event_id="delivery-1",
        title="Dune", message="Ya disponible", received_at=utcnow(), whatsapp_status="pending",
    )


class Queue:
    def __init__(self):
        self.item = event()
        self.claims = 0

    async def claim_notification(self):
        self.claims += 1
        if self.item.whatsapp_status not in {"pending", "retry"}:
            return None
        self.item.whatsapp_status = "sending"
        return self.item

    async def finish_notification(self, event_id, error=None):
        assert event_id == self.item.id
        self.item.whatsapp_status = "retry" if error else "sent"
        self.item.whatsapp_error = error


class Channel:
    def __init__(self):
        self.recipient = "user:creator"
        self.sent = []
        self.fail = False

    async def notification_recipient(self, preferred=None):
        return self.recipient

    async def send_notification(self, recipient, content):
        if self.fail:
            raise RuntimeError("sensitive provider detail")
        self.sent.append((recipient, content))


def test_notification_is_sent_once_and_marked_sent():
    async def scenario():
        queue, channel = Queue(), Channel()
        worker = WebhookNotificationWorker(queue, channel)
        assert await worker.run_once()
        assert queue.item.whatsapp_status == "sent"
        assert len(channel.sent) == 1
        assert channel.sent[0][0] == "user:creator"
        assert "Dune" in channel.sent[0][1] and "MEDIA_AVAILABLE" in channel.sent[0][1]
        assert not await worker.run_once()
        assert len(channel.sent) == 1

    asyncio.run(scenario())


def test_failed_send_remains_retryable_without_exposing_provider_detail():
    async def scenario():
        queue, channel = Queue(), Channel()
        worker = WebhookNotificationWorker(queue, channel)
        channel.fail = True
        await worker.run_once()
        assert queue.item.whatsapp_status == "retry"
        assert "sensitive" not in queue.item.whatsapp_error
        channel.fail = False
        await worker.run_once()
        assert queue.item.whatsapp_status == "sent"
        assert queue.item.whatsapp_error is None
        assert len(channel.sent) == 1

    asyncio.run(scenario())


def test_no_recipient_keeps_event_pending_and_text_fits_whatsapp():
    async def scenario():
        queue, channel = Queue(), Channel()
        channel.recipient = None
        worker = WebhookNotificationWorker(queue, channel)
        assert not await worker.run_once()
        assert queue.claims == 0
        assert queue.item.whatsapp_status == "pending"
        queue.item.message = "x" * 4096
        from app.application.whatsapp_formatting import whatsapp_chunks
        chunks = whatsapp_chunks(notification_text(queue.item))
        assert all(len(chunk) <= 4096 for chunk in chunks)
        assert "".join(chunks).count("x") == 4096

    asyncio.run(scenario())


def test_recipient_is_only_known_conversation_and_notification_has_no_reply_context():
    async def scenario():
        state = FakeState()
        client = FakeClient(WhatsAppUpdateBatch(next_offset=1))

        async def handle(message):
            raise AssertionError("notification must not enter the orchestrator")

        runtime = WhatsAppAgentRuntime(
            WhatsAppSettings(agent_name="primary", token="secret"), client, state, handle,
        )
        assert await runtime.notification_recipient() is None
        state.conversations["user:creator"] = uuid4()
        assert await runtime.notification_recipient() == "user:creator"
        assert await runtime.notification_recipient("user:unknown") is None
        state.conversations["user:other"] = uuid4()
        assert await runtime.notification_recipient() is None
        assert await runtime.notification_recipient("user:creator") == "user:creator"
        await runtime.send_notification("user:creator", "Aviso de Seerr")
        assert client.sent == [("user:creator", "Aviso de Seerr", None)]

    asyncio.run(scenario())


def test_http_notification_omits_context_but_regular_reply_preserves_it():
    async def scenario():
        payloads = []

        def handler(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"messages": [{"id": "outbound-id"}]})

        client = HttpWhatsAppClient(
            WhatsAppSettings(agent_name="primary", token="secret"),
            httpx.AsyncClient(
                base_url="https://example.test", transport=httpx.MockTransport(handler)
            ),
        )
        message = OutgoingMessage(conversation_id=uuid4(), execution_id=uuid4(), content="Aviso")
        await client.send_text("user:creator", message)
        await client.send_text("user:creator", message, "original-message")
        assert "context" not in payloads[0]
        assert payloads[0]["to"] == "user:creator"
        assert payloads[1]["context"] == {"message_id": "original-message"}
        await client.aclose()

    asyncio.run(scenario())


def test_operator_can_pause_and_resume_notification_delivery():
    from app.domain.notifications import NotificationSettings

    async def scenario():
        queue, channel = Queue(), Channel()
        worker = WebhookNotificationWorker(queue, channel)
        worker.configure(NotificationSettings(enabled=False))
        assert not await worker.run_once()
        assert queue.claims == 0 and channel.sent == []
        worker.configure(NotificationSettings(enabled=True))
        assert await worker.run_once()
        assert queue.item.whatsapp_status == "sent"
        assert len(channel.sent) == 1

    asyncio.run(scenario())
