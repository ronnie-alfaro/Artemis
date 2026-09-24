from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult


class FakeEchoTool:
    definition = Tool(
        name="fake.echo_tool",
        description="Returns deterministic sanitized echo text.",
        risk_level=RiskLevel.READ,
    )

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            invocation_id=invocation.id,
            output={"content": f"FakeAgent response: {invocation.input['content']}"},
        )
