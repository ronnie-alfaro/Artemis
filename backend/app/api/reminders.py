from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.application.reminders import ReminderService, RemindersUnavailable
from app.domain.models import RiskLevel, Tool, ToolInvocation
from app.domain.reminders import (
    Reminder,
    ReminderCreate,
    ReminderPreview,
    ReminderStateUpdate,
    ToolTrigger,
)


def install_reminder_routes(app: FastAPI, service: ReminderService) -> None:
    @app.exception_handler(RemindersUnavailable)
    async def unavailable(request: Request, error: RemindersUnavailable) -> Response:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.get("/api/v1/tools/reminders/catalog", response_model=list[Tool])
    async def catalog() -> list[Tool]:
        return service.catalog()

    @app.get("/api/v1/tools/reminders", response_model=list[Reminder])
    async def list_reminders() -> list[Reminder]:
        return await service.storage().list()

    @app.post("/api/v1/tools/reminders", response_model=Reminder, status_code=201)
    async def create(payload: ReminderCreate) -> Reminder:
        try:
            result = await service.tools.invoke(
                ToolInvocation(
                    tool_name="reminders.create",
                    agent_name="control-plane",
                    risk_level=RiskLevel.WRITE,
                    input=payload.model_dump(mode="json"),
                )
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        reminder = await service.storage().get(UUID(result.output["id"]))
        if reminder is None:
            raise HTTPException(503, "No se pudo recuperar el recordatorio.")
        return reminder

    @app.post("/api/v1/tools/reminders/preview", response_model=ReminderPreview)
    async def preview(trigger: ToolTrigger) -> ReminderPreview:
        try:
            service.validate_tool(trigger)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        try:
            result, _ = await service.evaluate(trigger)
            return result
        except Exception as error:
            raise HTTPException(
                502, "No se pudo consultar la herramienta. Revisa parámetros y conexión."
            ) from error

    async def set_state(identifier: UUID, status: str) -> Reminder:
        value = await service.storage().set_state(identifier, status)
        if value is None:
            if await service.storage().get(identifier) is None:
                raise HTTPException(404, "Recordatorio no encontrado.")
            raise HTTPException(409, "El recordatorio ya se ha disparado o terminado.")
        return value

    @app.patch("/api/v1/tools/reminders/{identifier}", response_model=Reminder)
    async def update(identifier: UUID, payload: ReminderStateUpdate) -> Reminder:
        return await set_state(identifier, payload.status)

    @app.delete("/api/v1/tools/reminders/{identifier}", status_code=204)
    async def cancel(identifier: UUID) -> Response:
        await set_state(identifier, "cancelled")
        return Response(status_code=204)
