from uuid import uuid4

import numpy as np
import pytest

from app.application.approvals import ApprovalStore
from app.domain.models import RiskLevel, ToolInvocation
from app.infrastructure.memory_manager import COLLECTIONS, MemoryManager
from app.tools.registry import ApprovalRequired, ToolRegistry
from app.tools.tools_memory import MemoryTool


class Encoder:
    def encode(self, texts, **kwargs):
        return np.array([[1.0, 0.0] if "cat" in text else [0.0, 1.0] for text in texts])


@pytest.mark.parametrize("collection", COLLECTIONS)
def test_persistence_search_and_scope(tmp_path, collection):
    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    cat = manager.remember(collection, "alice", "cat preference")
    manager.remember(collection, "alice", "dog preference")
    manager.remember(collection, "bob", "cat secret")
    reopened = MemoryManager(str(tmp_path), encoder=Encoder())
    results = reopened.search(collection, "alice", "cat", 2)
    assert results[0]["id"] == cat
    assert len(results) == 2
    assert not reopened.forget(collection, "bob", cat)
    assert reopened.forget(collection, "alice", cat)
    assert not reopened.forget(collection, "alice", cat)
    assert reopened.search(collection, "nobody", "cat") == []


def test_validation_and_empty(tmp_path):
    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    assert manager.search("agent_memory", "alice", "cat") == []
    with pytest.raises(ValueError):
        manager.remember("invalid", "alice", "cat")
    with pytest.raises(ValueError):
        manager.remember("agent_memory", "alice", " ")
    for limit in (0, 51, True):
        with pytest.raises(ValueError):
            manager.search("agent_memory", "alice", "cat", limit)


@pytest.mark.asyncio
async def test_tools_approval_and_scope(tmp_path):
    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    registry = ToolRegistry(ApprovalStore())
    for action in ("search", "remember", "forget"):
        registry.register(MemoryTool(manager, action))
    with pytest.raises(ApprovalRequired):
        await registry.invoke(ToolInvocation(
            tool_name="memory.remember", agent_name="alice", risk_level=RiskLevel.WRITE,
            input={"text": "cat"},
        ))
    manager.remember("agent_memory", "bob", "cat secret")
    result = await registry.invoke(ToolInvocation(
        id=uuid4(), tool_name="memory.search", agent_name="alice", risk_level=RiskLevel.READ,
        input={"text": "cat", "agent": "bob"},
    ))
    assert result.output["result"] == "[]"


def test_admin_browse_vectors_pagination_and_scope(tmp_path):
    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    manager.remember("agent_memory", "alice", "cat")
    manager.remember("agent_memory", "bob", "dog")
    page = manager.browse("agent_memory", limit=1)
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert len(page["items"][0]["embedding"]) == 2
    scoped = manager.browse("agent_memory", agent="bob")
    assert scoped["total"] == 1
    assert scoped["items"][0]["text"] == "dog"
    assert manager.browse("agent_memory", offset=2)["items"] == []
    assert manager.browse("agent_persona")["total"] == 0


def test_memory_routes_validation_and_unavailable(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.memory import install_memory_routes

    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    app = FastAPI()
    install_memory_routes(app, manager)
    with TestClient(app) as client:
        assert client.get("/api/v1/memory/agent_memory").json()["total"] == 0
        for path in ("invalid", "agent_memory?offset=-1", "agent_memory?limit=51"):
            assert client.get(f"/api/v1/memory/{path}").status_code == 422
        def unavailable(*args, **kwargs):
            raise RuntimeError("private path")
        monkeypatch.setattr(manager, "browse", unavailable)
        response = client.get("/api/v1/memory/agent_memory")
        assert response.status_code == 503
        assert "private path" not in response.text


def test_image_memories_expire_and_semantic_search_is_conversation_scoped(tmp_path):
    import time

    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    metadata = {"kind": "image", "scope": "chat-a", "image_id": "img-a",
                "expires_at": str(time.time() + 100)}
    manager.remember_event("alice", "image-a", "cat picture", metadata)
    manager.remember_event("alice", "image-b", "cat secret",
                           {**metadata, "scope": "chat-b", "image_id": "img-b"})
    expired = manager.remember_event("alice", "image-old", "cat old",
                                    {**metadata, "expires_at": "1"})
    assert manager.search_images("alice", "chat-a", "cat")[0]["image_id"] == "img-a"
    assert manager.browse("agent_memory")["total"] == 0
    assert all(item["id"] != expired for item in manager.search("agent_memory", "alice", "cat"))


def test_memory_map_and_explore_routes(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.memory import install_memory_routes

    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    cat = manager.remember("agent_memory", "alice", "cat")
    dog = manager.remember("agent_memory", "alice", "dog")
    other = manager.remember("agent_memory", "bob", "cat preference")
    app = FastAPI()
    install_memory_routes(app, manager)
    base = "/api/v1/memory/agent_memory"
    with TestClient(app) as client:
        snapshot = client.get(f"{base}/map", params={"agent": "alice"}).json()
        assert snapshot["total"] == 2
        assert {item["id"] for item in snapshot["items"]} == {cat, dog}
        assert all(item["metadata"]["created_at"] > 0 for item in snapshot["items"])
        results = client.post(f"{base}/explore", json={"text": "cat", "agent": "alice"})
        assert [item["id"] for item in results.json()] == [cat, dog]
        neighbors = client.post(f"{base}/explore", json={"memory_id": cat, "ids": [cat, other]})
        assert [item["id"] for item in neighbors.json()] == [other]
        assert client.post(f"{base}/explore", json={"text": "cat", "ids": []}).json() == []
        assert client.post(f"{base}/explore", json={"text": "  "}).status_code == 422
        assert client.post(
            f"{base}/explore", json={"text": "cat", "memory_id": cat},
        ).status_code == 422
