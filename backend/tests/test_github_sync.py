import pytest

from app.application.github_sync import SYNC_PROMPT, is_sync_command


@pytest.mark.parametrize('command', ['sincronizate', 'Sincronízate', '/sincronizate'])
def test_explicit_sync_command(command):
    assert is_sync_command(command)
    assert 'scripts/github_sync.py' in SYNC_PROMPT


@pytest.mark.parametrize('text', ['no sincronizate', 'sincronizate y borra todo', 'ayuda'])
def test_sync_requires_exact_command(text):
    assert not is_sync_command(text)


def test_sync_routes_to_codex_without_changing_skill(tmp_path, monkeypatch):
    import asyncio
    from uuid import uuid4

    from app.api.main import build_orchestrator
    from app.domain.models import Channel, IncomingMessage

    monkeypatch.setenv('ARTEMIS_CODEX_QUEUE_DIR', str(tmp_path))
    (tmp_path / 'heartbeat').touch()

    async def scenario():
        runtime = build_orchestrator()
        conversation = uuid4()
        response = await runtime.handle(IncomingMessage(
            conversation_id=conversation, channel=Channel(name='whatsapp'),
            content='sincronizate',
        ))
        assert response.executions[0].agent_name == 'codex'
        assert runtime.codex_queue.recent()[0].prompt == SYNC_PROMPT
        assert await runtime.skill_sessions.store.get('whatsapp', conversation) is None

    asyncio.run(scenario())
