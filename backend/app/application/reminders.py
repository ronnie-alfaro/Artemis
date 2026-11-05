from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from uuid import UUID

from app.application.notifications import NotificationsDisabled
from app.application.reminder_conditions import (
    ConditionResult,
    evaluate_condition,
    normalize_output,
    validate_condition,
)
from app.domain.models import RiskLevel, Tool, ToolInvocation, utcnow
from app.domain.reminders import Reminder, ReminderCreate, ReminderPreview, TimeTrigger, ToolTrigger
from app.infrastructure.reminders import PostgresReminderStore
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class RemindersUnavailable(RuntimeError):
    pass


class ReminderService:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools
        self.store: PostgresReminderStore | None = None

    def storage(self) -> PostgresReminderStore:
        if self.store is None:
            raise RemindersUnavailable("El almacenamiento de recordatorios no está disponible.")
        return self.store

    def catalog(self) -> list[Tool]:
        return [
            tool
            for tool in self.tools.list_tools()
            if tool.risk_level is RiskLevel.READ and self.tools.can_invoke(tool.name, "reminders")
        ]

    def validate_tool(self, trigger: ToolTrigger) -> Tool:
        available = {tool.name: tool for tool in self.catalog()}
        if trigger.tool_name not in available:
            raise ValueError("Elige una herramienta de consulta disponible para recordatorios.")
        validate_condition(trigger.condition)
        return available[trigger.tool_name]

    async def create(self, payload: ReminderCreate) -> Reminder:
        if payload.request_id:
            existing = await self.storage().get(payload.request_id)
            if existing and (
                existing.message == payload.message and existing.trigger == payload.trigger
            ):
                return existing
        if isinstance(payload.trigger, TimeTrigger):
            if payload.trigger.at <= utcnow():
                raise ValueError("La fecha del recordatorio debe estar en el futuro.")
        else:
            self.validate_tool(payload.trigger)
        return await self.storage().create(payload)

    async def evaluate(
        self,
        trigger: ToolTrigger,
        previous_hash: str | None = None,
    ) -> tuple[ReminderPreview, ConditionResult]:
        definition = self.validate_tool(trigger)
        result = await asyncio.wait_for(
            self.tools.invoke(
                ToolInvocation(
                    tool_name=trigger.tool_name,
                    agent_name="reminders",
                    risk_level=RiskLevel.READ,
                    input=dict(trigger.input),
                )
            ),
            timeout=definition.timeout_seconds,
        )
        output = normalize_output(result.output)
        condition = evaluate_condition(output, trigger.condition, previous_hash)
        return ReminderPreview(
            matched=condition.matched,
            values=condition.values,
            output=output,
        ), condition


class ReminderWorker:
    def __init__(self, service: ReminderService) -> None:
        self.service = service
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="reminders-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _deliver(self, reminder: Reminder, claim: UUID) -> None:
        try:
            result = await self.service.tools.invoke(
                ToolInvocation(
                    tool_name="notifications.send",
                    agent_name="reminders",
                    risk_level=RiskLevel.WRITE,
                    input={
                        "title": "Recordatorio",
                        "message": reminder.message,
                        "event": "reminder.triggered",
                        "event_id": str(reminder.id),
                    },
                )
            )
        except Exception as error:
            message = (
                "Notificaciones está desactivado; se reintentará."
                if isinstance(error, NotificationsDisabled)
                else "No se pudo encolar el aviso; revisa Notificaciones. Se reintentará."
            )
            await self.service.storage().checked(
                reminder.id,
                claim,
                utcnow() + timedelta(seconds=60),
                None,
                None,
                message,
            )
        else:
            await self.service.storage().completed(reminder.id, claim, UUID(result.output["id"]))

    async def run_once(self) -> bool:
        work = await self.service.storage().claim_due()
        if work is None:
            return False
        reminder, claim = work
        if reminder.status == "firing":
            await self._deliver(reminder, claim)
            return True
        try:
            if isinstance(reminder.trigger, ToolTrigger):
                _, result = await self.service.evaluate(reminder.trigger, reminder.last_hash)
                matched, preview, fingerprint = result.matched, result.preview, result.fingerprint
            else:
                matched, preview, fingerprint = True, "Fecha y hora alcanzadas.", None
        except Exception:
            interval = (
                reminder.trigger.interval_seconds
                if isinstance(reminder.trigger, ToolTrigger)
                else 60
            )
            await self.service.storage().checked(
                reminder.id,
                claim,
                utcnow() + timedelta(seconds=interval),
                None,
                None,
                (
                    "No se pudo comprobar la herramienta. "
                    "Revisa sus parámetros y conexión; se reintentará."
                ),
            )
            return True
        if matched:
            if await self.service.storage().begin_fire(reminder.id, claim, preview, fingerprint):
                await self._deliver(reminder, claim)
        else:
            interval = (
                reminder.trigger.interval_seconds
                if isinstance(reminder.trigger, ToolTrigger)
                else 60
            )
            await self.service.storage().checked(
                reminder.id,
                claim,
                utcnow() + timedelta(seconds=interval),
                preview,
                fingerprint,
            )
        return True

    async def _run(self) -> None:
        while True:
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Reminder scheduling failed; retrying")
                worked = False
            await asyncio.sleep(0.1 if worked else 1)
