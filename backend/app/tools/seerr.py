from __future__ import annotations

import json

from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.domain.seerr import SeerrApiInput, SeerrClient, SeerrRequestInput


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


def safe_api_output(value: object) -> str:
    def redact(item: object) -> object:
        if isinstance(item, dict):
            return {
                key: "[oculto]" if any(word in str(key).lower().replace("_", "")
                    for word in ("apikey", "token", "password", "secret",
                                 "cookie", "authorization"))
                else redact(val) for key, val in item.items()
            }
        if isinstance(item, list):
            return [redact(val) for val in item]
        return item
    return json.dumps(redact(value), ensure_ascii=False)


class SeerrApiTool:
    definition = Tool(
        name="seerr.api_write",
        description="Execute a confirmed Seerr API mutation.",
        risk_level=RiskLevel.ADMIN,
    )

    def __init__(self, client: SeerrClient) -> None:
        self._client = client

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        request = SeerrApiInput.model_validate(invocation.input)
        if request.method == "GET":
            raise ValueError("Use the read API for GET")
        result = await self._client.api_request(request)
        return ToolResult(invocation_id=invocation.id, output={"response": safe_api_output(result)})
