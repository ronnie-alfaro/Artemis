"""Memory tools integrated with Artemis permissions and approvals."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.infrastructure.memory_manager import MemoryManager


class MemoryTool:
    def __init__(self, manager: MemoryManager,
                 action: Literal["search", "remember", "forget"]) -> None:
        self.manager = manager
        self.action = action
        self.definition = Tool(
            name=f"memory.{action}",
            description=f"Memoria semántica del agente: {action}.",
            risk_level=RiskLevel.READ if action == "search" else RiskLevel.WRITE,
            requires_approval=action != "search",
            timeout_seconds=120,
            input_example={"collection": "agent_memory", "text": "Preferencias del agente"},
        )

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        collection = invocation.input.get("collection", "agent_memory")
        text = invocation.input.get("id" if self.action == "forget" else "text")
        if not isinstance(collection, str) or not isinstance(text, str):
            raise ValueError("Indica colección y texto (o ID para borrar).")
        result: Any
        if self.action == "search":
            limit = invocation.input.get("limit", 5)
            if type(limit) is not int:
                raise ValueError("El límite debe ser entero.")
            result = await asyncio.to_thread(
                self.manager.search, collection, invocation.agent_name, text, limit,
            )
        elif self.action == "remember":
            result = await asyncio.to_thread(
                self.manager.remember, collection, invocation.agent_name, text,
            )
        else:
            result = await asyncio.to_thread(
                self.manager.forget, collection, invocation.agent_name, text,
            )
        return ToolResult(invocation_id=invocation.id,
                          output={"result": json.dumps(result, ensure_ascii=False)})
