import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

spec = importlib.util.spec_from_file_location(
    "codex_worker", Path(__file__).resolve().parents[2] / "scripts/codex_worker.py"
)
assert spec and spec.loader
codex_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codex_worker)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "tool"])
async def test_worker_executes_with_write_permissions_in_real_source(tmp_path, monkeypatch, mode):
    source = tmp_path / "source"
    source.mkdir()
    queue = tmp_path / "queue"
    queue.mkdir()
    cli = tmp_path / "codex"
    cli.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        'prompt = sys.stdin.read()\n'
        'assert "Eres Artemis." in prompt\n'
        'assert "irreverente, divertida e ingeniosa" in prompt\n'
        "args = sys.argv\n"
        'assert args[args.index("-s") + 1] == "danger-full-access"\n'
        'assert args[args.index("-c") + 1] == \'approval_policy="never"\'\n'
        'assert pathlib.Path(args[args.index("-C") + 1]) == pathlib.Path.cwd()\n'
        'pathlib.Path("changed.txt").write_text("done")\n'
        'pathlib.Path(args[args.index("--output-last-message") + 1]).write_text("Terminado")\n'
    )
    cli.chmod(0o755)
    monkeypatch.setattr(codex_worker, "STATE", tmp_path)
    monkeypatch.setattr(codex_worker, "QUEUE", queue)
    monkeypatch.setattr(codex_worker, "SOURCE", source)
    monkeypatch.setattr(codex_worker, "CLI", str(cli))
    job = {
        "id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "channel": "rest",
        "prompt": "Edita el proyecto",
        "mode": mode,
        "created_at": 1,
    }
    path = queue / f"{job['id']}.json"
    await codex_worker.execute(path, job)
    assert (source / "changed.txt").read_text() == "done"
    saved = json.loads(path.read_text())
    assert saved["status"] == "completed"
    assert saved["answer"] == "Terminado"
    assert saved["has_patch"] is False
    assert not list(queue.glob("*.patch"))


def test_visual_history_is_excluded_and_artifacts_expire(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr(codex_worker, "STATE", tmp_path)
    monkeypatch.setattr(codex_worker, "QUEUE", tmp_path / "queue")
    (tmp_path / "queue").mkdir()
    (tmp_path / "workspaces").mkdir()
    job_id = str(uuid4())
    prompt = "[Imagen temporal img-" + "a" * 24 + "; caduca 1.0] gato"
    job = {"id": job_id, "prompt": prompt, "status": "completed", "created_at": time.time() - 1,
           "channel": "telegram", "conversation_id": "chat", "answer": "gato"}
    (tmp_path / "queue" / (job_id + ".json")).write_text(json.dumps(job))
    (tmp_path / "workspaces" / (job_id + ".log")).write_text("visual data")
    codex_worker.register_image_expiry(job)
    assert codex_worker.history({**job, "created_at": time.time()}) == []
    codex_worker.purge_image_artifacts()
    assert not list((tmp_path / "queue").glob("*"))
    assert not list((tmp_path / "workspaces").glob("*"))
