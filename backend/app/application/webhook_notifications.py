from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from app.domain.notifications import NotificationSettings
from app.domain.webhooks import WebhookEvent

logger = logging.getLogger(__name__)


class NotificationStore(Protocol):
    async def claim_notification(self) -> WebhookEvent | None: ...

    async def finish_notification(self, event_id: UUID, error: str | None = None) -> None: ...


class NotificationChannel(Protocol):
    async def notification_recipient(self, preferred: str | None = None) -> str | None: ...

    async def send_notification(self, recipient_id: str, content: str) -> None: ...


def notification_text(event: WebhookEvent) -> str:
    source = {"reminders": "Recordatorios", "manual": "Artemis"}.get(event.source, event.source)
    parts = [
        f"*Aviso de {source}* · {event.event}",
        f"*{event.title}*" if event.title else "",
        event.message,
    ]
    return "\n\n".join(part for part in parts if part)


class WebhookNotificationWorker:
    def __init__(
        self,
        store: NotificationStore,
        channel: NotificationChannel,
        recipient: str | None = None,
    ) -> None:
        self._store, self._channel, self._recipient = store, channel, recipient
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._enabled = True

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="webhook-whatsapp-notifications")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    def configure(self, settings: NotificationSettings) -> None:
        self._enabled = settings.enabled
        self._recipient = settings.recipient_id
        self.wake()

    async def recipient_available(self) -> bool:
        return await self._channel.notification_recipient(self._recipient) is not None

    async def run_once(self) -> bool:
        if not self._enabled:
            return False
        recipient = await self._channel.notification_recipient(self._recipient)
        if recipient is None:
            return False
        event = await self._store.claim_notification()
        if event is None:
            return False
        try:
            await self._channel.send_notification(recipient, notification_text(event))
        except Exception:
            # Provider details and recipient identifiers never enter the event log.
            await self._store.finish_notification(
                event.id, "No se pudo enviar por WhatsApp; se reintentará."
            )
        else:
            await self._store.finish_notification(event.id)
        return True

    async def _run(self) -> None:
        while True:
            self._wake.clear()
            try:
                attempted = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Webhook notification processing failed; retrying")
                attempted = False
            if attempted:
                # Pace event delivery instead of sending a burst of queued notifications.
                await asyncio.sleep(5)
            else:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=5)
                except TimeoutError:
                    pass
