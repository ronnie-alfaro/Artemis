from __future__ import annotations

from app.domain.karakeep import KarakeepClient
from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult


class KarakeepBookmarkTool:
    definition = Tool(
        name="karakeep.create_bookmark",
        description="Save an approved link as a Karakeep bookmark.",
        risk_level=RiskLevel.WRITE,
    )

    def __init__(self, client: KarakeepClient) -> None:
        self._client = client

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        url = invocation.input.get("url")
        title = invocation.input.get("title")
        if not isinstance(url, str):
            raise ValueError("Karakeep bookmark URL is required")
        if title is not None and not isinstance(title, str):
            raise ValueError("Karakeep bookmark title must be text")
        bookmark = await self._client.create_link(url, title)
        return ToolResult(
            invocation_id=invocation.id,
            output={
                "bookmark_id": bookmark.id,
                "url": bookmark.url or url,
                "title": bookmark.title or "",
            },
        )
