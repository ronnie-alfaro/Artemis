import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.application.antigravity import AntigravityQueue


def test_antigravity_routes_and_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANTIGRAVITY_QUEUE_DIR", str(tmp_path))
    (tmp_path / "heartbeat").touch()
    queue = AntigravityQueue(str(tmp_path))
    message, conversation = uuid4(), uuid4()
    job = queue.submit(message, conversation, "rest", "Revisa el proyecto", "chat")
    assert queue.submit(message, conversation, "rest", "otra", "chat").id == job.id
    client = TestClient(create_app())
    assert client.get("/api/v1/skills/antigravity/configuration").json()["connected"]
    jobs = client.get("/api/v1/skills/antigravity/jobs").json()
    assert jobs[0]["id"] == str(job.id)
    assert "conversation_id" not in jobs[0]
    assert "antigravity.assistant" in {
        capability.name
        for agent in client.app.state.orchestrator.registry.list_agents()
        for capability in agent.capabilities
    }


@pytest.mark.asyncio
async def test_worker_writes_source_and_returns_answer(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    # Load a private copy: the worker configures its queue module on import.
    spec = importlib.util.spec_from_file_location(
        "antigravity_test_worker", scripts / "antigravity_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.pop("codex_worker", None)
    try:
        spec.loader.exec_module(module)
        source = tmp_path / "source"
        source.mkdir()
        cli = tmp_path / "agy"
        cli.write_text(
            "#!/usr/bin/env python3\nimport pathlib, sys\nsys.stdin.read()\n"
            'pathlib.Path("changed.txt").write_text("done")\n'
            'print("Tarea terminada")\n'
        )
        cli.chmod(0o755)
        monkeypatch.setattr(module, "CLI", str(cli))
        monkeypatch.setattr(module, "STATE", tmp_path)
        monkeypatch.setattr(module, "SOURCE", source)
        monkeypatch.setattr(module.worker, "QUEUE", tmp_path)
        path = tmp_path / "job.json"
        job = {
            "id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "channel": "rest",
            "created_at": 1,
            "prompt": "Edita",
            "status": "queued",
        }
        path.write_text(json.dumps(job))
        await module.execute(path, job)
        assert (source / "changed.txt").read_text() == "done"
        assert json.loads(path.read_text())["status"] == "completed"
        assert job["answer"] == "Tarea terminada"
        assert "--dangerously-skip-permissions" in module.command()
        assert "--continue" not in module.command()
    finally:
        sys.modules.pop("codex_worker", None)
        if previous is not None:
            sys.modules["codex_worker"] = previous


@pytest.mark.asyncio
async def test_conversation_worker_uses_persona_and_returns_structured_answer_without_host_tools(
    tmp_path,
    monkeypatch,
):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "agy_natural_test", scripts / "antigravity_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.pop("codex_worker", None)
    try:
        spec.loader.exec_module(module)
        source = tmp_path / "source"
        source.mkdir()
        cli = tmp_path / "agy"
        cli.write_text(
            "#!/usr/bin/env python3\nimport json, pathlib, sys\n"
            "args=sys.argv[1:]\n"
            'assert "--dangerously-skip-permissions" not in args\n'
            'assert "--sandbox" in args\n'
            'settings=json.loads(args[args.index("--settings")+1])\n'
            'assert settings["permissions"] == {"allow":[],"deny":["*"]}\n'
            'prompt=next(v for v in args if v.startswith("--print="))\n'
            'assert "pirata" in prompt and "habilidades_asignadas" in prompt\n'
            'print(json.dumps({"status":"SUCCESS", "structured_output":'
            '{"reply":"¡Arrr, hola!", "capability":"", "command":""}}))\n'
        )
        cli.chmod(0o755)
        monkeypatch.setattr(module, "CLI", str(cli))
        monkeypatch.setattr(module, "STATE", tmp_path)
        monkeypatch.setattr(module, "SOURCE", source)
        monkeypatch.setattr(module.worker, "QUEUE", tmp_path)
        path = tmp_path / "job.json"
        job = {
            "id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "channel": "telegram",
            "created_at": 1,
            "prompt": "Hola",
            "status": "queued",
            "mode": "assistant",
            "persona": "Habla como pirata",
            "skills": [],
            "observations": [],
        }
        path.write_text(json.dumps(job))
        await module.execute(path, job)
        assert job["status"] == "completed"
        assert job["answer"] == "¡Arrr, hola!"
        assert list(source.iterdir()) == []
    finally:
        sys.modules.pop("codex_worker", None)
        if previous is not None:
            sys.modules["codex_worker"] = previous
