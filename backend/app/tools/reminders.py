from __future__ import annotations

from app.application.reminders import ReminderService
from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.domain.reminders import ReminderCreate


class CreateReminderTool:
    definition = Tool(
        name="reminders.create",
        description=(
            "Crea un recordatorio por fecha o por el resultado de una herramienta de consulta."
        ),
        risk_level=RiskLevel.WRITE,
        requires_approval=False,
    )

    def __init__(self, service: ReminderService) -> None:
        self._service = service

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        reminder = await self._service.create(ReminderCreate.model_validate(invocation.input))
        return ToolResult(
            invocation_id=invocation.id,
            output={"id": str(reminder.id), "status": reminder.status},
        )
