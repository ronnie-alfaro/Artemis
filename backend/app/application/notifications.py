from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.application.webhook_notifications import WebhookNotificationWorker
from app.domain.notifications import (
    NotificationConfiguration,
    NotificationEvent,
    NotificationPayload,
    NotificationReceipt,
    NotificationSettings,
)


class NotificationStore(Protocol):
    async def receive(
        self, source: str, payload: NotificationPayload, notify: bool = False
    ) -> tuple[NotificationEvent, bool]: ...

    async def recent(self, source: str | None, limit: int) -> list[NotificationEvent]: ...

    async def save_notification_settings(self, settings: NotificationSettings) -> None: ...


class NotificationsUnavailable(RuntimeError):
    pass


class NotificationsDisabled(ValueError):
    pass


class NotificationService:
    """Shared delivery entry point for skills, manual sends and webhook adapters."""

    def __init__(self) -> None:
        self.store: NotificationStore | None = None
        self.notifier: WebhookNotificationWorker | None = None
        self.settings = NotificationSettings()
        self.recipients: Callable[[], Awaitable[list[str]]] | None = None

    async def configuration(self) -> NotificationConfiguration:
        return NotificationConfiguration(
            settings=self.settings,
            storage_available=self.store is not None,
            whatsapp_configured=self.notifier is not None,
            recipient_available=(
                await self.notifier.recipient_available() if self.notifier else False
            ),
            available_recipients=await self.recipients() if self.recipients else [],
        )

    async def configure(self, settings: NotificationSettings) -> NotificationConfiguration:
        if self.store is None:
            raise NotificationsUnavailable(
                "El almacenamiento de notificaciones no está disponible."
            )
        if settings.recipient_id:
            recipients = await self.recipients() if self.recipients else []
            if settings.recipient_id not in recipients:
                raise ValueError("Elige una conversación de WhatsApp registrada.")
        await self.store.save_notification_settings(settings)
        self.settings = settings
        if self.notifier:
            self.notifier.configure(settings)
        return await self.configuration()

    async def publish(
        self, source: str, payload: NotificationPayload, require_delivery: bool = False,
    ) -> NotificationReceipt:
        if self.store is None:
            raise NotificationsUnavailable(
                "El almacenamiento de notificaciones no está disponible."
            )
        if require_delivery:
            if not self.settings.enabled:
                raise NotificationsDisabled("La herramienta de notificaciones está desactivada.")
            if self.notifier is None:
                raise NotificationsUnavailable("Configura el canal WhatsApp para enviar avisos.")
        deliver = self.settings.enabled and self.notifier is not None
        event, duplicate = await self.store.receive(source, payload, notify=deliver)
        if deliver and self.notifier:
            self.notifier.wake()
        return NotificationReceipt(
            id=event.id, duplicate=duplicate, whatsapp_status=event.whatsapp_status,
        )

    async def history(self, source: str | None = None, limit: int = 50) -> list[NotificationEvent]:
        if self.store is None:
            raise NotificationsUnavailable("El historial de notificaciones no está disponible.")
        return await self.store.recent(source, limit)
