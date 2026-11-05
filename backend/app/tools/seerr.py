from __future__ import annotations

from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.domain.seerr import SeerrClient, SeerrRequestInput


class SeerrRequestTool:
    definition = Tool(
        name="seerr.create_request",
        description="Create an approved Seerr media request.",
        risk_level=RiskLevel.WRITE,
    )

    def __init__(self, client: SeerrClient) -> None:
        self._client = client

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        request = SeerrRequestInput.model_validate(invocation.input)
        result = await self._client.create_request(request)
        return ToolResult(
            invocation_id=invocation.id,
            output={
                "request_id": str(result.request_id),
                "status": result.status,
                "duplicate": str(result.duplicate).lower(),
            },
        )
