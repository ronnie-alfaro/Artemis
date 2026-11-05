from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from app.application.notifications import (
    NotificationsDisabled,
    NotificationService,
    NotificationsUnavailable,
)
from app.domain.models import RiskLevel, ToolInvocation
from app.domain.notifications import (
    NotificationConfiguration,
    NotificationEvent,
    NotificationPayload,
    NotificationReceipt,
    NotificationSettings,
)
from app.tools.registry import ToolRegistry


def install_notification_routes(
    app: FastAPI, service: NotificationService, tools: ToolRegistry,
) -> None:
    @app.get("/api/v1/tools/notifications/configuration", response_model=NotificationConfiguration)
    async def configuration() -> NotificationConfiguration:
        return await service.configuration()

    @app.put("/api/v1/tools/notifications/configuration", response_model=NotificationConfiguration)
    async def configure(payload: NotificationSettings) -> NotificationConfiguration:
        try:
            return await service.configure(payload)
        except NotificationsUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.post(
        "/api/v1/tools/notifications/send", response_model=NotificationReceipt, status_code=202
    )
    async def send(payload: NotificationPayload) -> NotificationReceipt:
        try:
            result = await tools.invoke(ToolInvocation(
                tool_name="notifications.send", agent_name="control-plane",
                input=payload.model_dump(), risk_level=RiskLevel.WRITE,
            ))
        except NotificationsUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except NotificationsDisabled as error:
            raise HTTPException(409, str(error)) from error
        return NotificationReceipt.model_validate(result.output)

    @app.get("/api/v1/tools/notifications/history", response_model=list[NotificationEvent])
    async def history(
        source: Annotated[str | None, Query(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[NotificationEvent]:
        try:
            return await service.history(source, limit)
        except NotificationsUnavailable as error:
            raise HTTPException(503, str(error)) from error
