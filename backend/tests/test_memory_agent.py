import json
from uuid import uuid4

import numpy as np
import pytest

from app.agents.memory import MemoryAgent
from app.application.approvals import ApprovalStore
from app.domain.models import AgentRequest, Channel, IncomingMessage
from app.domain.skills import MEMORY_CAPABILITY
from app.infrastructure.memory_manager import MemoryManager
from app.tools.registry import ToolRegistry
from app.tools.tools_memory import MemoryTool


class Encoder:
    def encode(self, texts, **kwargs):
        return np.array([[1.0, 0.0] if "gato" in text else [0.0, 1.0] for text in texts])


@pytest.mark.asyncio
async def test_chat_memory_writes_need_confirmation_and_keep_chat_scope(tmp_path):
    manager = MemoryManager(str(tmp_path), encoder=Encoder())
    approvals = ApprovalStore()
    tools = ToolRegistry(approvals)
    for action in ("search", "remember", "update"):
        tools.register(MemoryTool(manager, action))
    agent = MemoryAgent(tools, approvals)
    channel = Channel(name="whatsapp", agent_name="artemis",
                      allowed_capabilities=[MEMORY_CAPABILITY])
    chat, other_chat = uuid4(), uuid4()

    async def command(content, conversation=chat, sender_channel=channel):
        response = await agent.run(AgentRequest(
            execution_id=uuid4(), node_id="memory",
            message=IncomingMessage(
                channel=sender_channel, conversation_id=conversation, content=content,
            ),
        ))
        return response.result.content

    assert "no está asignada" in await command(
        "buscar gato", sender_channel=channel.model_copy(update={"allowed_capabilities": []}),
    )
    assert "confirmo" in await command("guardar Tengo un gato")
    assert json.loads(await command("buscar gato")) == []
    assert "No hay" in await command("confirmo", other_chat)
    assert "Guardé" in await command("confirmo")
    record, = json.loads(await command("buscar gato"))
    memory_id = record["id"]

    assert json.loads(await command("buscar gato", other_chat)) == []
    assert "confirmo" in await command(f"actualizar {memory_id} Tengo un perro", other_chat)
    assert "No encontré" in await command("confirmo", other_chat)
    assert "confirmo" in await command(f"actualizar {memory_id} Tengo un perro")
    assert json.loads(await command("buscar gato"))[0]["text"] == "Tengo un gato"
    assert "Actualicé" in await command("confirmo")
    record, = json.loads(await command("buscar perro"))
    assert (record["id"], record["text"]) == (memory_id, "Tengo un perro")
    assert "No hay" in await command("confirmo")
