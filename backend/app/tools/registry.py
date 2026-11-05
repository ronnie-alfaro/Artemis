from __future__ import annotations

# ruff: noqa: E501
from typing import Protocol

from app.application.approvals import ApprovalStore
from app.domain.models import ApprovalStatus, RiskLevel, Tool, ToolInvocation, ToolResult


class ToolRunner(Protocol):
    definition: Tool

    async def invoke(self, invocation: ToolInvocation) -> ToolResult: ...


class ApprovalRequired(PermissionError):
    pass


class ToolRegistry:
    def __init__(self, approvals: ApprovalStore | None = None) -> None:
        self._tools: dict[str, ToolRunner] = {}
        self._authorized_agents: dict[str, set[str]] = {}
        self._approvals = approvals

    def register(self, tool: ToolRunner, authorized_agents: set[str] | None = None) -> None:
        self._tools[tool.definition.name] = tool
        allowed = set(authorized_agents or set())
        if allowed and tool.definition.risk_level is RiskLevel.READ:
            allowed.add("reminders")
        self._authorized_agents[tool.definition.name] = allowed

    def replace(self, tool: ToolRunner, authorized_agents: set[str] | None = None) -> None:
        if tool.definition.name not in self._tools:
            raise KeyError(f"tool '{tool.definition.name}' is not registered")
        self.register(tool, authorized_agents)

    def can_invoke(self, name: str, agent_name: str) -> bool:
        if name not in self._tools:
            return False
        allowed = self._authorized_agents[name]
        return not allowed or agent_name in allowed

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        tool = self._tools[invocation.tool_name]
        if invocation.risk_level is RiskLevel.READ and tool.definition.risk_level is not RiskLevel.READ:
            raise PermissionError("A read-only invocation cannot execute a mutating tool")
        allowed_agents = self._authorized_agents[tool.definition.name]
        if allowed_agents and invocation.agent_name not in allowed_agents:
            raise PermissionError(
                f"agent '{invocation.agent_name}' is not authorized for {tool.definition.name}"
            )
        requires_approval = tool.definition.risk_level is not RiskLevel.READ and (
            tool.definition.requires_approval or tool.definition.risk_level is not RiskLevel.WRITE
        )
        if requires_approval:
            if not invocation.approval_id or not self._approvals:
                raise ApprovalRequired(f"{tool.definition.name} requires approval")
            approval = self._approvals.get(invocation.approval_id)
            if (
                approval.status is not ApprovalStatus.APPROVED
                or approval.tool_name != tool.definition.name
            ):
                raise ApprovalRequired(f"{tool.definition.name} requires a current approval")
        return await tool.invoke(invocation)

    def get(self, name: str) -> ToolRunner:
        return self._tools[name]

    def list_tools(self) -> list[Tool]:
        return [tool.definition for tool in self._tools.values()]
