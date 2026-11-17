from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.rust_bridge import BASIC, UNCERTAIN, RustBridge
from app.infrastructure.conversation_bridge import BridgeStore

DSN = os.getenv("ARTEMIS_BRIDGE_TEST_DSN")
BRIDGE = os.getenv("ARTEMIS_BRIDGE_TEST_URL")

pytestmark = pytest.mark.skipif(not DSN or not BRIDGE, reason="requires bridge and test PostgreSQL")


@pytest.mark.asyncio
async def test_durable_turn_fallback_and_recovery() -> None:
    assert DSN and BRIDGE
    store = BridgeStore(DSN)
    await store.start()
    conversation = uuid4()
    first, interrupted, basic = uuid4(), uuid4(), uuid4()
    bot = f"test-{conversation}"
    runtime = SimpleNamespace(
        status=lambda: SimpleNamespace(agent_name=bot),
        capabilities=AsyncMock(return_value=["seerr.media"]),
        recipient_for_conversation=AsyncMock(return_value="recipient"),
        send_notification=AsyncMock(),
    )
    handler = AsyncMock(return_value=SimpleNamespace(
        message=SimpleNamespace(content="Matrix encontrado"),
    ))
    bridge = RustBridge(
        store, BRIDGE, {"telegram": SimpleNamespace(runtime=runtime)}, handler, lambda *_: [],
    )
    payload = {
        "text": "Busca Matrix",
        "image_context": "",
        "persona": "Prueba",
        "greeting": "",
        "approval_ids": [],
        "skills": [{"capability": "seerr.media", "description": "buscar", "help": "busca"}],
    }
    try:
        await store.save_providers("telegram", bot, ["primary", "backup"])
        await store.enqueue(first, "telegram", bot, conversation, payload)
        await store.enqueue(first, "telegram", bot, conversation, payload)
        await store.enqueue(interrupted, "telegram", bot, conversation, payload)
        assert await bridge.process_turn()
        assert await bridge.process_turn()
        handler.assert_awaited_once()
        # A fresh orchestrator must be able to resume from the committed skill result.
        await bridge.client.aclose()
        bridge = RustBridge(
            store, BRIDGE, {"telegram": SimpleNamespace(runtime=runtime)}, handler, lambda *_: [],
        )
        assert await bridge.process_turn()
        handler.assert_awaited_once()
        assert await bridge.deliver()
        runtime.send_notification.assert_awaited_once_with("recipient", "Encontré Matrix.")
        assert await store.last_provider("telegram", bot) == "backup"

        # An expired in-progress action has an unknown outcome. Recovery must not replay it.
        lease = await store.claim()
        assert lease and lease["id"] == interrupted
        assert await store.checkpoint(lease, "executing", decision={
            "capability": "seerr.media", "command": "busca Matrix", "reply": "",
        })
        await store.pool.execute(
            "UPDATE bridge_turns SET lease_until=now() WHERE id=$1", interrupted,
        )
        assert await bridge.process_turn()
        assert await bridge.deliver()
        runtime.send_notification.assert_awaited_with("recipient", UNCERTAIN)
        handler.assert_awaited_once()

        await store.save_providers("telegram", bot, ["always-fails"])
        await store.enqueue(basic, "telegram", bot, conversation, payload)
        assert await bridge.process_turn()
        assert await bridge.deliver()
        runtime.send_notification.assert_awaited_with("recipient", BASIC)
    finally:
        await store.pool.execute("DELETE FROM bridge_turns WHERE bot=$1", bot)
        await store.pool.execute("DELETE FROM bridge_bot_providers WHERE bot=$1", bot)
        await bridge.close()
