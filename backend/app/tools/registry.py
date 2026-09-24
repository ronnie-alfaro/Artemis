from __future__ import annotations

from typing import Protocol

from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult


class ToolRunner(Protocol):
    definition: Tool

    async def invoke(self, invocation: ToolInvocation) -> ToolResult: ...


class ApprovalRequired(PermissionError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolRunner] = {}

    def register(self, tool: ToolRunner) -> None:
        self._tools[tool.definition.name] = tool

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        tool = self._tools[invocation.tool_name]
        if tool.definition.risk_level is not RiskLevel.READ:
            raise ApprovalRequired(f"{tool.definition.name} requires approval")
        return await tool.invoke(invocation)
