from __future__ import annotations

from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    Permission,
    RiskLevel,
    ToolInvocation,
)
from app.tools.registry import ToolRegistry


class FakeAgent:
    definition = Agent(
        name="fake",
        version="0.1.0",
        purpose="Deterministic reference agent for the first Artemis vertical slice.",
        capabilities=[
            AgentCapability(
                name="fake.echo", description="Echo a request through a registered tool"
            )
        ],
        permissions=[
            Permission(name="fake.echo.read", description="Use the deterministic echo tool")
        ],
        risk_level=RiskLevel.READ,
    )

    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools

    async def run(self, request: AgentRequest) -> AgentResponse:
        invocation = ToolInvocation(
            tool_name="fake.echo_tool",
            agent_name="fake",
            input={"content": request.message.content},
            risk_level=RiskLevel.READ,
        )
        result = await self._tools.invoke(invocation)
        return AgentResponse(
            result=AgentResult(
                agent_name="fake",
                content=result.output["content"],
                metadata={"execution_id": str(request.execution_id)},
            )
        )
