from uuid import uuid4

from test_memory import Encoder

from app.application.interaction_memory import InteractionMemory
from app.domain.models import Channel, IncomingMessage
from app.infrastructure.memory_manager import MemoryManager


def test_durable_retry_idempotency_and_scope(tmp_path):
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    recorder = InteractionMemory(memory)
    message = IncomingMessage(conversation_id=uuid4(), channel=Channel(name='whatsapp',
                              agent_name='alice'), content='cat real event')
    from types import SimpleNamespace
    response = SimpleNamespace(message=SimpleNamespace(deferred=False, content='recorded'))
    recorder.enqueue(message, response)
    reopened = InteractionMemory(memory)
    reopened.flush()
    recorder.enqueue(message, response)
    reopened.flush()
    page = memory.browse('agent_memory', agent='alice')
    assert page['total'] == 1
    assert 'cat real event' in page['items'][0]['text']
    assert page['items'][0]['metadata']['conversation_id'] == str(message.conversation_id)
    assert memory.browse('agent_memory', agent='bob')['total'] == 0
    assert not list(recorder.directory.glob('*.json'))


def test_failure_retains_pending_and_synthetic_is_excluded(tmp_path, monkeypatch):
    from types import SimpleNamespace
    memory = MemoryManager(str(tmp_path), encoder=Encoder())
    recorder = InteractionMemory(memory)
    message = IncomingMessage(conversation_id=uuid4(), channel=Channel(name='telegram'),
                              content='cat')
    response = SimpleNamespace(message=SimpleNamespace(deferred=True, content=''))
    recorder.enqueue(message, response)
    def unavailable(**kwargs):
        raise RuntimeError('offline')
    monkeypatch.setattr(memory, 'remember_event', unavailable)
    recorder.flush()
    assert len(list(recorder.directory.glob('*.json'))) == 1
    message.id = uuid4()
    message.required_capabilities = ['seerr.search']
    recorder.enqueue(message, response)
    assert len(list(recorder.directory.glob('*.json'))) == 1


def test_deferred_results_persist_and_skip_history(tmp_path):
    import time

    from app.application.antigravity import AntigravityQueue
    from app.application.codex import CodexJob, CodexQueue

    memory = MemoryManager(str(tmp_path / 'memory'), encoder=Encoder())
    directory = tmp_path / 'codex'
    directory.mkdir()
    queue = CodexQueue(str(directory))
    recorder = InteractionMemory(memory, (queue, AntigravityQueue()))
    recorder.flush_results()
    for created_at in (time.time() - 100, time.time() + 1):
        queue.save(CodexJob(id=uuid4(), conversation_id=uuid4(), channel='whatsapp',
                           prompt='cat', answer='real answer', status='completed',
                           created_at=created_at))
    recorder.flush_results()
    InteractionMemory(memory, (queue,)).flush_results()
    page = memory.browse('agent_memory', agent='primary')
    assert page['total'] == 1
    assert 'real answer' in page['items'][0]['text']
    assert len(list(directory.glob('*.memory'))) == 1
