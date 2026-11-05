import asyncio

import pytest

from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.tools.registry import ApprovalRequired, ToolRegistry


class WriteTool:
    definition = Tool(name="write", description="test", risk_level=RiskLevel.WRITE)

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult(invocation_id=invocation.id, output={})


def test_write_tool_requires_approval() -> None:
    registry = ToolRegistry()
    registry.register(WriteTool())
    with pytest.raises(ApprovalRequired):
        invocation = ToolInvocation(
            tool_name="write", agent_name="test", input={}, risk_level=RiskLevel.WRITE
        )
        asyncio.run(registry.invoke(invocation))


@pytest.mark.parametrize("risk", [RiskLevel.DESTRUCTIVE, RiskLevel.ADMIN])
def test_approval_flag_cannot_bypass_high_risk_tools(risk):
    class HighRiskTool(WriteTool):
        definition = Tool(
            name="high-risk", description="test", risk_level=risk, requires_approval=False,
        )

    registry = ToolRegistry()
    registry.register(HighRiskTool())
    with pytest.raises(ApprovalRequired):
        asyncio.run(registry.invoke(ToolInvocation(
            tool_name="high-risk", agent_name="test", input={}, risk_level=risk,
        )))


def test_read_only_invocation_cannot_use_a_preapproved_write_tool():
    class PreapprovedWrite(WriteTool):
        definition = Tool(
            name="write", description="test", risk_level=RiskLevel.WRITE, requires_approval=False,
        )

    registry = ToolRegistry()
    registry.register(PreapprovedWrite())
    with pytest.raises(PermissionError):
        asyncio.run(registry.invoke(ToolInvocation(
            tool_name="write", agent_name="reminders", input={}, risk_level=RiskLevel.READ,
        )))
