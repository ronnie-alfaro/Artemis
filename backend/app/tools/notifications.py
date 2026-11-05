from __future__ import annotations

from app.application.notifications import NotificationService
from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.domain.notifications import NotificationPayload


class SendNotificationTool:
    definition = Tool(
        name="notifications.send",
        description="Envía un aviso mediante el canal y destinatario configurados.",
        risk_level=RiskLevel.WRITE,
        requires_approval=False,
    )

    def __init__(self, service: NotificationService) -> None:
        self._service = service

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        # Skills cannot supply arbitrary recipients or change the configured destination.
        payload = NotificationPayload.model_validate(invocation.input)
        source = "manual" if invocation.agent_name == "control-plane" else invocation.agent_name
        receipt = await self._service.publish(source, payload, require_delivery=True)
        return ToolResult(
            invocation_id=invocation.id,
            output={
                "id": str(receipt.id), "status": receipt.status,
                "duplicate": str(receipt.duplicate).lower(),
                "whatsapp_status": receipt.whatsapp_status,
            },
        )
