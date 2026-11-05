from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg

from app.domain.notifications import NotificationSettings
from app.domain.webhooks import WebhookEvent, WebhookPayload


class PostgresWebhookEventStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: asyncpg.Pool | None = None

    @property
    def _connection_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Webhook event store is not started")
        return self._pool

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id UUID PRIMARY KEY,
                source TEXT NOT NULL,
                event TEXT NOT NULL,
                event_id TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(source, event_id)
            );
            ALTER TABLE webhook_events
                ADD COLUMN IF NOT EXISTS whatsapp_status TEXT NOT NULL DEFAULT 'not_requested',
                ADD COLUMN IF NOT EXISTS whatsapp_error TEXT,
                ADD COLUMN IF NOT EXISTS whatsapp_attempts INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS whatsapp_available_at TIMESTAMPTZ NOT NULL DEFAULT now();
            CREATE TABLE IF NOT EXISTS notification_configuration (
                singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
                enabled BOOLEAN NOT NULL,
                channel TEXT NOT NULL,
                recipient_id TEXT
            );
            CREATE INDEX IF NOT EXISTS webhook_events_notification_idx
                ON webhook_events(whatsapp_available_at)
                WHERE whatsapp_status IN ('pending', 'retry', 'sending');
            CREATE INDEX IF NOT EXISTS webhook_events_received_at_idx
                ON webhook_events(received_at DESC, id DESC);
        """)

    async def receive(
        self, source: str, payload: WebhookPayload, notify: bool = False
    ) -> tuple[WebhookEvent, bool]:
        row = await self._connection_pool.fetchrow("""
            INSERT INTO webhook_events(id, source, event, event_id, title, message, whatsapp_status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (source, event_id) DO NOTHING
            RETURNING *
        """, uuid4(), source, payload.event, payload.event_id, payload.title, payload.message,
            "pending" if notify else "not_requested")
        duplicate = row is None
        if row is None:
            row = await self._connection_pool.fetchrow(
                "SELECT * FROM webhook_events WHERE source=$1 AND event_id=$2",
                source, payload.event_id,
            )
        if row is None:
            raise RuntimeError("Webhook event could not be loaded")
        return WebhookEvent.model_validate(dict(row)), duplicate

    async def recent(self, source: str | None, limit: int) -> list[WebhookEvent]:
        rows = await self._connection_pool.fetch("""
            SELECT * FROM webhook_events WHERE ($1::text IS NULL OR source=$1)
            ORDER BY received_at DESC, id DESC LIMIT $2
        """, source, limit)
        return [WebhookEvent.model_validate(dict(row)) for row in rows]

    async def load_notification_settings(self) -> NotificationSettings | None:
        row = await self._connection_pool.fetchrow(
            "SELECT enabled, channel, recipient_id FROM notification_configuration WHERE singleton"
        )
        return NotificationSettings.model_validate(dict(row)) if row else None

    async def save_notification_settings(self, settings: NotificationSettings) -> None:
        await self._connection_pool.execute("""
            INSERT INTO notification_configuration(singleton, enabled, channel, recipient_id)
            VALUES (TRUE, $1, $2, $3)
            ON CONFLICT (singleton) DO UPDATE SET enabled=EXCLUDED.enabled,
                channel=EXCLUDED.channel, recipient_id=EXCLUDED.recipient_id
        """, settings.enabled, settings.channel, settings.recipient_id)

    async def claim_notification(self) -> WebhookEvent | None:
        row = await self._connection_pool.fetchrow("""
            UPDATE webhook_events SET whatsapp_status='sending',
                whatsapp_attempts=whatsapp_attempts+1,
                whatsapp_available_at=now() + interval '2 minutes'
            WHERE id=(
                SELECT id FROM webhook_events
                WHERE whatsapp_status IN ('pending', 'retry', 'sending')
                    AND whatsapp_available_at <= now()
                ORDER BY received_at, id FOR UPDATE SKIP LOCKED LIMIT 1
            ) RETURNING *
        """)
        return WebhookEvent.model_validate(dict(row)) if row else None

    async def finish_notification(self, event_id: UUID, error: str | None = None) -> None:
        await self._connection_pool.execute("""
            UPDATE webhook_events SET whatsapp_status=$2, whatsapp_error=$3,
                whatsapp_available_at=now() + make_interval(
                    secs => LEAST(300, 5 * power(2, LEAST(whatsapp_attempts, 6)))::int
                )
            WHERE id=$1
        """, event_id, "retry" if error else "sent", error)

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
