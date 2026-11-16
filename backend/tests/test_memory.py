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
