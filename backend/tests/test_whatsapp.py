from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from app.application.whatsapp import WhatsAppAgentRuntime
from app.domain.models import ChatResponse, ExecutionPlan, OutgoingMessage
from app.domain.whatsapp import (
    WhatsAppInbound,
    WhatsAppMessageType,
    WhatsAppSettings,
    WhatsAppUpdateBatch,
)


class FakeState:
    def __init__(self) -> None:
        self.offset: int | None = None
        self.complete: set[str] = set()
        self.conversations: dict[str, UUID] = {}
        self.inbox: dict[str, WhatsAppInbound] = {}

    async def start(self) -> None:
        pass

    async def get_offset(self, agent_name: str) -> int | None:
        return self.offset

    async def set_offset(self, agent_name: str, offset: int) -> None:
        self.offset = offset

    async def enqueue(self, agent_name: str, message: WhatsAppInbound) -> None:
        self.inbox.setdefault(message.id, message)

    async def pending(self, agent_name: str) -> list[WhatsAppInbound]:
        return [
            message for message_id, message in self.inbox.items() if message_id not in self.complete
        ]

    async def completed(self, agent_name: str, message_id: str) -> bool:
        return message_id in self.complete

    async def conversation_for(self, agent_name: str, participant_id: str) -> UUID:
        return self.conversations.setdefault(participant_id, uuid4())

    async def mark_completed(self, agent_name: str, message: WhatsAppInbound) -> None:
        self.complete.add(message.id)

    async def capabilities_for(self, agent_name: str) -> list[str]:
        return ["assistant.status"]

    async def set_capabilities(self, agent_name: str, capabilities: list[str]) -> None:
        pass

    async def greeting_for(self, agent_name: str) -> str:
        return "Hola, soy Artemis."

    async def set_greeting(self, agent_name: str, greeting: str) -> None:
        pass

    async def aclose(self) -> None:
        pass


class FakeClient:
    def __init__(self, batch: WhatsAppUpdateBatch) -> None:
        self.batch = batch
        self.received_offsets: list[int | None] = []
        self.read: list[str] = []
        self.sent: list[tuple[str, str, str]] = []

    async def updates(self, offset: int | None, timeout: int) -> WhatsAppUpdateBatch | None:
        self.received_offsets.append(offset)
        return self.batch

    async def mark_read(self, message_id: str, typing: bool = False) -> None:
        assert typing
        self.read.append(message_id)

    async def send_text(self, recipient_id: str, message: OutgoingMessage, reply_to: str) -> str:
        self.sent.append((recipient_id, message.content, reply_to))
        return "wamid.outbound"

    async def aclose(self) -> None:
        pass


def test_whatsapp_runtime_bridges_once_and_persists_cursor() -> None:
    inbound = WhatsAppInbound(
        id="wamid.inbound",
        sender_id="user:123",
        timestamp="1736844652",
        type=WhatsAppMessageType.TEXT,
        text="hello",
    )
    state = FakeState()
    client = FakeClient(WhatsAppUpdateBatch(messages=[inbound], next_offset=42))
    handled: list[str] = []

    async def handle(message):
        handled.append(message.content)
        return ChatResponse(
            message=OutgoingMessage(
                conversation_id=message.conversation_id, content="reply", execution_id=uuid4()
            ),
            plan=ExecutionPlan(conversation_id=message.conversation_id, nodes=[]),
            executions=[],
        )

    runtime = WhatsAppAgentRuntime(
        WhatsAppSettings(agent_name="primary", token="secret"), client, state, handle
    )
    asyncio.run(runtime.run_once())
    asyncio.run(runtime.run_once())

    assert handled == ["hello"]
    assert client.read == ["wamid.inbound"]
    assert client.sent == [("user:123", "reply", "wamid.inbound")]
    assert client.received_offsets == [None, 42]
    assert state.offset == 42


def test_whatsapp_runtime_does_not_reply_to_reactions() -> None:
    inbound = WhatsAppInbound(
        id="wamid.reaction",
        sender_id="user:123",
        timestamp="1736844652",
        type=WhatsAppMessageType.REACTION,
    )
    state = FakeState()
    client = FakeClient(WhatsAppUpdateBatch(messages=[inbound], next_offset=9))

    async def handle(message):
        raise AssertionError("reaction must not enter the orchestrator")

    runtime = WhatsAppAgentRuntime(
        WhatsAppSettings(agent_name="primary", token="secret"), client, state, handle
    )
    asyncio.run(runtime.run_once())
    assert client.sent == []
    assert state.offset == 9
