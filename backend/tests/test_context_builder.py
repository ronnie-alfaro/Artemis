from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_memory import Encoder

from app.application.context_builder import ContextSource, propose_core, redact
from app.domain.context_builder import merge_settings
from app.infrastructure.memory_manager import MemoryManager


def test_overrides_cannot_remove_protected_sections():
    effective = merge_settings({"budget": 8000}, {"max_tools": 2}, {"budget": 7000})
    assert effective.budget == 7000
    assert effective.max_tools == 2
    with pytest.raises(ValidationError):
        merge_settings({"components": {"operations": {"enabled": False}}})
    with pytest.raises(ValidationError):
        merge_settings({"budget": 1024})


@pytest.mark.asyncio
async def test_migration_preserves_original_and_is_scoped(tmp_path):
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    source = ContextSource(None, memory)
    original = "Soy Artemis. Respondo en español. " + ("Ejemplos narrativos. " * 80)
    core = propose_core(original)
    revision = await source.save_persona("whatsapp:primary", original, original, core)
    assert await source.persona("whatsapp:primary", original, 150) == (core, original, revision)
    versions = await source.versions("whatsapp:primary")
    assert any(item["text"] == original and item["source"] == "original" for item in versions)
    assert await source.versions("telegram:primary") == []
    assert memory.browse("agent_persona")["total"] == 3
    assert "Soy Artemis" in core and "español" in core


@pytest.mark.asyncio
async def test_chroma_failure_falls_back_to_this_channels_persona(tmp_path, monkeypatch):
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    source = ContextSource(None, memory)

    def unavailable(_):
        raise OSError("offline")

    monkeypatch.setattr(memory, "persona_versions", unavailable)
    core, extended, origin = await source.persona("telegram:primary", "Soy Artemisa.", 150)
    assert core == extended == "Soy Artemisa."
    assert origin == "channel-fallback"


@pytest.mark.asyncio
async def test_semantic_memory_requires_channel_agent_and_conversation(tmp_path):
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    source = ContextSource(None, memory)
    conversation = uuid4()
    metadata = {"conversation_id": str(conversation), "channel": "telegram", "kind": "requested"}
    memory.remember_event("alice", "one", "cat preference", metadata)
    memory.remember_event("bob", "two", "cat preference hidden", metadata)
    memory.remember_event("alice", "three", "cat secret", {**metadata, "channel": "whatsapp"})
    settings = merge_settings({"memory_threshold": 0})
    row = {"bot": "alice", "channel": "telegram", "conversation": conversation}
    assert await source.memories(row, "cat preference", settings) == ["cat preference"]
    assert await source.memories(row, "cat preference", merge_settings({
        "semantic_memory": False,
    })) == []


def test_redacts_known_secret_patterns_in_nested_data():
    result = redact({"observations": ["password=example1234", "BearEr some-long-test-token"]})
    assert result == {"observations": ["[credencial omitida]", "[credencial omitida]"]}
