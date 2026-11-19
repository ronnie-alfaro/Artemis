from types import SimpleNamespace
from uuid import uuid4

from test_memory import Encoder

from app.application.interaction_memory import InteractionMemory
from app.domain.models import Channel, IncomingMessage
from app.infrastructure.memory_manager import MemoryManager


def message(content):
    return IncomingMessage(
        conversation_id=uuid4(), channel=Channel(name="whatsapp", agent_name="alice"),
        content=content,
    )


def test_explicit_memory_retries_idempotently_and_uses_first_person(tmp_path, monkeypatch):
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    recorder = InteractionMemory(memory)
    request = message("Artemis, recuerda que me gusta el café.")
    assert recorder.enqueue(request)
    original = memory.remember_event

    def unavailable(**kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(memory, "remember_event", unavailable)
    recorder.flush()
    assert len(list(recorder.directory.glob("*.json"))) == 1
    monkeypatch.setattr(memory, "remember_event", original)
    reopened = InteractionMemory(memory)
    reopened.flush()
    recorder.enqueue(request)
    reopened.flush()
    items = memory.recent_memories()
    assert len(items) == 1
    assert items[0]["text"] == "Quiero recordar lo que me dijo el usuario: «me gusta el café.»"
    assert items[0]["metadata"]["kind"] == "requested"
    assert memory.browse("agent_memory", agent="alice")["total"] == 1
    assert memory.browse("agent_memory", agent="bob")["total"] == 0
    assert not list(recorder.directory.glob("*.json"))


def test_only_milestones_and_feedback_become_memories(tmp_path):
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    recorder = InteractionMemory(memory)
    recorder.enqueue(message("¿Qué hora es?"))
    synthetic = message("Recuerda una prueba")
    synthetic.required_capabilities = ["seerr.search"]
    recorder.enqueue(synthetic)
    recorder.enqueue(message("Buen trabajo, Artemis"))
    recorder.enqueue(message("Ahora tienes un mapa de recuerdos."))
    outcome = SimpleNamespace(executions=[
        SimpleNamespace(result=SimpleNamespace(metadata={"learned_integration": "biblioteca"})),
    ])
    recorder.enqueue(message("Aprende esta API https://example.org/openapi.json"), outcome)
    recorder.flush()
    assert {item["text"] for item in memory.recent_memories()} == {
        "El usuario me felicitó por mi trabajo.",
        "Ahora cuento con un mapa de recuerdos.",
        "Aprendí a consultar la integración biblioteca con Curiosidad.",
    }


def test_legacy_memory_is_outside_the_active_collection(tmp_path):
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    assert memory.recent_memories() == []
    legacy = memory._client.get_or_create_collection("agent_memory", embedding_function=None)
    legacy.add(ids=["old"], documents=["Transcripción anterior"], embeddings=[[1.0, 0.0]])
    assert memory.browse("agent_memory")["total"] == 0
    assert legacy.count() == 1
