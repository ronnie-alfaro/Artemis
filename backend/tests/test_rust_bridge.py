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


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["whatsapp", "telegram"])
async def test_context_runtime_matches_preview_and_persists_metrics(channel):
    assert DSN and BRIDGE
    if not os.getenv("ARTEMIS_CONTEXT_TOKEN"):
        pytest.skip("requires an authenticated test bridge")
    from app.application.rust_bridge import INSTRUCTIONS

    store = BridgeStore(DSN)
    await store.start()
    conversation = uuid4()
    turn = uuid4()
    bot = f"test-{conversation}"
    scope = f"agent:{channel}:{bot}"
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
        store, BRIDGE, {channel: SimpleNamespace(runtime=runtime)}, handler, lambda *_: [],
    )
    payload = {
        "text": "Busca Matrix",
        "image_context": "",
        "persona": "Soy Artemis. Respondo en español.",
        "greeting": "",
        "approval_ids": [],
        "skills": [{"capability": "seerr.media", "description": "Busca", "help": "Busca"}],
    }
    try:
        await store.context.save(scope, {"enabled": True, "semantic_memory": False})
        await store.save_providers(channel, bot, ["primary", "backup"])
        await store.enqueue(turn, channel, bot, conversation, payload)
        row = await store.context.turn(channel, bot, conversation)
        settings = await store.context.effective(scope, ["primary"])
        context = {
            **payload, "message": payload["text"], "observations": [], "actions_remaining": 4,
        }
        prepared, _, _ = await bridge.context_source.prepare(
            row, context, INSTRUCTIONS, settings, persist=False,
        )
        response = await bridge.request(
            "POST", "/v1/context/preview", timeout=5, context_auth=True,
            payload={"provider": "primary", "context": prepared},
        )
        preview = response.json()
        assert preview["capabilities"] == ["seerr.media"]
        assert "Soy Artemis" in preview["prompt"]
        context_request = {
            "providers": ["primary"], "prompt": "",
            "actions_remaining": 4, "capabilities": ["seerr.media"],
            "contexts": {"primary": prepared}, "scope": f"{channel}:{bot}:{conversation}",
        }
        unauthenticated = await bridge.client.post(BRIDGE + "/v1/context/decide",
                                                   json=context_request)
        assert unauthenticated.status_code == 401
        for expected in (False, True):
            outcome = await bridge._decide(context_request, context_auth=True)
            assert outcome.attempts[0].cache_hit is expected
        changed = {**prepared, "skills": [*prepared["skills"], {
            "capability": "other.read", "description": "irrelevante", "help": "",
        }]}
        next_request = {**context_request, "contexts": {"primary": changed}}
        outcome = await bridge._decide(next_request, context_auth=True)
        assert not outcome.attempts[0].cache_hit
        assert await bridge.process_turn()
        assert await bridge.process_turn()
        assert await bridge.process_turn()
        handler.assert_awaited_once()
        assert await bridge.deliver()
        assert await store.last_provider(channel, bot) == "backup"
        samples = [item for item in await store.context.metrics() if item["conversation"]
                   == conversation]
        initial = next(item for item in reversed(samples) if item["provider"] == "primary")
        assert initial["values"]["estimated_tokens"] == preview["estimated_tokens"]
        assert initial["values"]["usage"] is None
        assert any(item["provider"] == "backup" and item["values"]["status"] == "ok"
                   for item in samples)
        assert (await store.context.revisions(scope))[0]["config"]["enabled"]
    finally:
        await store.pool.execute("DELETE FROM bridge_turns WHERE bot=$1", bot)
        await store.pool.execute("DELETE FROM bridge_bot_providers WHERE bot=$1", bot)
        await store.pool.execute("DELETE FROM bridge_context_metrics WHERE bot=$1", bot)
        await store.pool.execute("DELETE FROM bridge_context_config WHERE scope=$1", scope)
        await bridge.close()


@pytest.mark.asyncio
async def test_summary_is_incremental_and_scoped():
    assert DSN
    from app.domain.context_builder import merge_settings

    store = BridgeStore(DSN)
    await store.start()
    bot, conversation, other = str(uuid4()), uuid4(), uuid4()
    try:
        for group, prefix in [(conversation, "ref-"), (other, "private-")]:
            for index in range(5):
                await store.pool.execute("""
                    INSERT INTO bridge_turns(id,channel,bot,conversation,payload,phase,reply)
                    VALUES($1,'telegram',$2,$3,$4::jsonb,'done',$5)
                """, uuid4(), bot, group, '{"text":"Objetivo: confirmar la opción"}',
                    f"¿Confirmas {prefix}{index}?")
        row = await store.context.turn("telegram", bot, conversation)
        row = {**dict(row), "ordinal": row["ordinal"] + 1}
        config = merge_settings({"recent_turns": 2, "summarize_after": 2})
        recent, summary, generated = await store.context.history(row, config, persist=True)
        assert generated and len(recent) == 2
        assert summary["references"] == [f"¿Confirmas ref-{index}?" for index in range(3)]
        again = await store.context.history(row, config, persist=True)
        assert again == (recent, summary, False)
        assert "private" not in str(again)
    finally:
        await store.pool.execute("DELETE FROM bridge_context_summary WHERE bot=$1", bot)
        await store.pool.execute("DELETE FROM bridge_turns WHERE bot=$1", bot)
        await store.close()
