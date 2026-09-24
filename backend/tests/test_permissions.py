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
