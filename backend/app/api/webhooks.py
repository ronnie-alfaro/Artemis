from __future__ import annotations

import json
import os
import re
import secrets
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query, Request

from app.application.notifications import NotificationService
from app.application.webhook_notifications import WebhookNotificationWorker
from app.domain.webhooks import WebhookEvent, WebhookPayload, WebhookReceipt
from app.infrastructure.webhook_events import PostgresWebhookEventStore

SOURCE_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
MAX_BODY_BYTES = 65536


def is_webhook_ingest(method: str, path: str) -> bool:
    return method == "POST" and re.fullmatch(
        r"/api/v1/webhooks/[a-z0-9][a-z0-9_-]{0,63}", path
    ) is not None


def install_webhook_routes(app: FastAPI) -> None:
    def store() -> PostgresWebhookEventStore:
        value: PostgresWebhookEventStore | None = getattr(app.state, "webhook_events", None)
        if value is None:
            raise HTTPException(503, "El almacenamiento de eventos no está disponible.")
        return value

    @app.get("/api/v1/webhooks/configuration")
    async def configuration() -> dict[str, bool | str]:
        notifier: WebhookNotificationWorker | None = getattr(app.state, "webhook_notifier", None)
        service: NotificationService = app.state.notifications
        return {
            "whatsapp_enabled": notifier is not None and service.settings.enabled,
            "whatsapp_recipient_available": (
                await notifier.recipient_available() if notifier else False
            ),
            "configured": bool(os.getenv("ARTEMIS_WEBHOOK_TOKEN")),
            "storage_available": getattr(app.state, "webhook_events", None) is not None,
            "docker_url": "http://artemis-api:8000/api/v1/webhooks/{source}",
        }

    @app.get("/api/v1/webhooks/events", response_model=list[WebhookEvent])
    async def recent_events(
        source: Annotated[str | None, Query(pattern=SOURCE_PATTERN)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[WebhookEvent]:
        return await store().recent(source, limit)

    @app.post("/api/v1/webhooks/{source}", response_model=WebhookReceipt, status_code=202)
    async def receive_event(
        request: Request, source: Annotated[str, Path(pattern=SOURCE_PATTERN)],
    ) -> WebhookReceipt:
        token = os.getenv("ARTEMIS_WEBHOOK_TOKEN")
        if not token:
            raise HTTPException(503, "Los webhooks no están configurados.")
        expected = f"Bearer {token}".encode()
        supplied = request.headers.get("authorization", "").encode()
        if not (
            secrets.compare_digest(supplied, expected)
            or secrets.compare_digest(supplied, token.encode())
        ):
            raise HTTPException(401, "Token de webhook no válido.")
        store()
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            raise HTTPException(415, "Envía el evento como application/json.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "El evento supera el tamaño permitido.")
        try:
            payload = WebhookPayload.model_validate(json.loads(body))
        except (ValueError, RecursionError) as error:
            raise HTTPException(
                422, "JSON no válido: incluye un título o mensaje y campos válidos."
            ) from error
        service: NotificationService = app.state.notifications
        return await service.publish(source, payload)
