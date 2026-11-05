from __future__ import annotations

import asyncio
import time
from uuid import UUID, uuid4

from app.application.whatsapp import WhatsAppAgentRuntime
from app.domain.models import ChatResponse, ExecutionPlan, OutgoingMessage, ReactionOption
from app.domain.whatsapp import (
    WhatsAppInbound,
    WhatsAppMessageType,
    WhatsAppSettings,
    WhatsAppUpdateBatch,
)


class FakeState:
    def __init__(self) -> None:
        self.menus: dict[tuple[str, str], dict] = {}
        self.offset: int | None = None
        self.complete: set[str] = set()
        self.conversations: dict[str, UUID] = {}
        self.inbox: dict[str, WhatsAppInbound] = {}

    async def clear_reaction_menus(self, agent_name, recipient_id=None):
        self.menus = {
            key: value
            for key, value in self.menus.items()
            if key[0] != agent_name or (recipient_id is not None and key[1] != recipient_id)
        }

    async def save_reaction_menu(self, agent_name, recipient_id, message_id, options):
        self.menus[(agent_name, recipient_id)] = {
            "message_id": message_id,
            "options": options,
            "expires": time.time() + 900,
            "consumed": None,
        }

    async def claim_reaction(self, agent_name, inbound):
        menu = self.menus.get((agent_name, inbound.sender_id))
        if not menu or menu["message_id"] != inbound.reaction_message_id:
            return None
        if menu["expires"] <= time.time() or menu["consumed"] not in {None, inbound.id}:
            return None
        for option in menu["options"]:
            if option.emoji.replace("\ufe0f", "") == (inbound.reaction_emoji or "").replace(
                "\ufe0f", ""
            ):
                menu["consumed"] = inbound.id
                return option
        return None

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

    async def participants_for(self, agent_name: str) -> list[str]:
        return list(self.conversations)

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
        self.sent: list[tuple[str, str, str | None]] = []

    async def updates(self, offset: int | None, timeout: int) -> WhatsAppUpdateBatch | None:
        self.received_offsets.append(offset)
        return self.batch

    async def mark_read(self, message_id: str, typing: bool = False) -> None:
        assert typing
        self.read.append(message_id)

    async def send_text(
        self, recipient_id: str, message: OutgoingMessage, reply_to: str | None = None
    ) -> str:
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


def test_notifications_use_whatsapp_format_and_keep_long_content():
    state = FakeState()
    client = FakeClient(WhatsAppUpdateBatch(messages=[], next_offset=1))

    async def handle(message):
        raise AssertionError("notification must not enter the orchestrator")

    runtime = WhatsAppAgentRuntime(
        WhatsAppSettings(agent_name="primary", token="secret"), client, state, handle
    )
    content = "## Resultado\n\n**Listo**\n" + "texto " * 1500
    asyncio.run(runtime.send_notification("user:123", content))
    assert len(client.sent) > 1
    assert client.sent[0][1].startswith("*Resultado*\n\n*Listo*")
    assert all(len(message) <= 4096 for _, message, _ in client.sent)
    assert sum(message.count("texto") for _, message, _ in client.sent) == 1500


def test_reaction_menu_routes_only_current_offered_choice_once():
    async def scenario():
        state = FakeState()
        client = FakeClient(WhatsAppUpdateBatch(messages=[], next_offset=1))
        handled = []

        async def handle(message):
            handled.append(message.content)
            return ChatResponse(
                message=OutgoingMessage(
                    conversation_id=message.conversation_id,
                    content="Respuesta",
                    execution_id=uuid4(),
                    reaction_options=[
                        ReactionOption(emoji="1️⃣", label="Matrix", command="baja el 1")
                    ]
                    if message.content == "busca Matrix"
                    else [],
                ),
                plan=ExecutionPlan(conversation_id=message.conversation_id, nodes=[]),
                executions=[],
            )

        runtime = WhatsAppAgentRuntime(
            WhatsAppSettings(agent_name="primary", token="secret"),
            client,
            state,
            handle,
        )
        text = WhatsAppInbound(
            id="search",
            sender_id="user:123",
            timestamp="1",
            type=WhatsAppMessageType.TEXT,
            text="busca Matrix",
        )
        await runtime._process(text)
        assert "1️⃣ Matrix" in client.sent[0][1]
        reaction = WhatsAppInbound(
            id="reaction",
            sender_id="user:123",
            timestamp="2",
            type=WhatsAppMessageType.REACTION,
            reaction_emoji="1⃣",
            reaction_message_id="wamid.outbound",
        )
        for index, changes in enumerate(
            [
                {"reaction_emoji": "👍"},
                {"reaction_emoji": ""},
                {"reaction_message_id": "old"},
                {"sender_id": "user:other"},
            ]
        ):
            await runtime._process(reaction.model_copy(update={"id": f"ignored{index}", **changes}))
        assert handled == ["busca Matrix"]
        await runtime._process(reaction)
        await runtime._process(reaction)
        await runtime._process(reaction.model_copy(update={"id": "second-click"}))
        assert handled == ["busca Matrix", "baja el 1"]
        assert len(client.sent) == 2

    asyncio.run(scenario())


def test_reaction_menu_invalidated_by_text_and_expiry():
    async def scenario():
        state = FakeState()
        client = FakeClient(WhatsAppUpdateBatch(messages=[], next_offset=1))
        handled = []

        async def handle(message):
            handled.append(message.content)
            return ChatResponse(
                message=OutgoingMessage(
                    conversation_id=message.conversation_id, content="Listo", execution_id=uuid4()
                ),
                plan=ExecutionPlan(conversation_id=message.conversation_id, nodes=[]),
                executions=[],
            )

        runtime = WhatsAppAgentRuntime(
            WhatsAppSettings(agent_name="primary", token="secret"),
            client,
            state,
            handle,
        )
        option = ReactionOption(emoji="1️⃣", label="Matrix", command="1")
        await state.save_reaction_menu("primary", "user:123", "menu", [option])
        reaction = WhatsAppInbound(
            id="r1",
            sender_id="user:123",
            timestamp="1",
            type=WhatsAppMessageType.REACTION,
            reaction_emoji="1️⃣",
            reaction_message_id="menu",
        )
        state.menus[("primary", "user:123")]["expires"] = 0
        await runtime._process(reaction)
        assert handled == []
        await state.save_reaction_menu("primary", "user:123", "menu", [option])
        await runtime._process(
            WhatsAppInbound(
                id="exit",
                sender_id="user:123",
                timestamp="2",
                type=WhatsAppMessageType.TEXT,
                text="salir",
            )
        )
        await runtime._process(reaction.model_copy(update={"id": "r2"}))
        assert handled == ["salir"]

    asyncio.run(scenario())


def test_http_reaction_fields_survive_inbox_serialization():
    from app.infrastructure.whatsapp_http import HttpWhatsAppClient

    inbound = HttpWhatsAppClient._inbound(
        {
            "id": "reaction",
            "from": "user:123",
            "timestamp": "1",
            "type": "reaction",
            "reaction": {"emoji": "🍎", "message_id": "menu"},
        }
    )
    restored = WhatsAppInbound.model_validate_json(inbound.model_dump_json())
    assert restored.reaction_emoji == "🍎"
    assert restored.reaction_message_id == "menu"


def test_long_choice_response_keeps_menu_together_in_last_message():
    async def scenario():
        state = FakeState()
        client = FakeClient(WhatsAppUpdateBatch(messages=[], next_offset=1))
        option = ReactionOption(emoji="1️⃣", label="Matrix", command="1")

        async def handle(message):
            return ChatResponse(
                message=OutgoingMessage(
                    conversation_id=message.conversation_id,
                    content="Resultados\n" + "detalle " * 1400 + "\n1. Matrix",
                    execution_id=uuid4(),
                    reaction_options=[option],
                ),
                plan=ExecutionPlan(conversation_id=message.conversation_id, nodes=[]),
                executions=[],
            )

        runtime = WhatsAppAgentRuntime(
            WhatsAppSettings(agent_name="primary", token="secret"),
            client,
            state,
            handle,
        )
        await runtime._process(
            WhatsAppInbound(
                id="search",
                sender_id="user:123",
                timestamp="1",
                type=WhatsAppMessageType.TEXT,
                text="busca Matrix",
            )
        )
        assert len(client.sent) > 1
        assert all(len(content) <= 4096 for _, content, _ in client.sent)
        assert "1️⃣ Matrix" in client.sent[-1][1]
        assert "Reacciona aquí" in client.sent[-1][1]
        assert state.menus[("primary", "user:123")]["options"] == [option]

    asyncio.run(scenario())
