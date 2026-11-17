from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from app.domain.reminders import Reminder, ReminderCreate, TimeTrigger


class PostgresReminderStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Reminder store is not started")
        return self._pool

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id UUID PRIMARY KEY,
                message TEXT NOT NULL,
                trigger JSONB NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                next_check_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_checked_at TIMESTAMPTZ,
                last_value TEXT,
                last_hash TEXT,
                last_error TEXT,
                notification_id UUID,
                claim_id UUID,
                lease_until TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders(next_check_at)
                WHERE status IN ('active', 'firing');
        """)

    @staticmethod
    def _model(row: Mapping[str, object]) -> Reminder:
        data = dict(row)
        if isinstance(data["trigger"], str):
            data["trigger"] = json.loads(data["trigger"])
        return Reminder.model_validate(data)

    async def create(self, payload: ReminderCreate) -> Reminder:
        identifier = payload.request_id or uuid4()
        due = payload.trigger.at if isinstance(payload.trigger, TimeTrigger) else None
        row = await self.pool.fetchrow(
            """
            INSERT INTO reminders(id, message, trigger, next_check_at)
            VALUES ($1, $2, $3::jsonb, COALESCE($4, now()))
            ON CONFLICT (id) DO NOTHING RETURNING *
        """,
            identifier,
            payload.message,
            payload.trigger.model_dump_json(),
            due,
        )
        if row is None:
            existing = await self.get(identifier)
            if existing is None or (
                existing.message != payload.message or existing.trigger != payload.trigger
            ):
                raise ValueError("Ese identificador pertenece a otro recordatorio.")
            return existing
        return self._model(row)

    async def get(self, identifier: UUID) -> Reminder | None:
        row = await self.pool.fetchrow("SELECT * FROM reminders WHERE id=$1", identifier)
        return self._model(row) if row else None

    async def list(self) -> list[Reminder]:
        rows = await self.pool.fetch("""
            SELECT * FROM reminders WHERE status <> 'cancelled'
            ORDER BY created_at DESC LIMIT 100
        """)
        return [self._model(row) for row in rows]

    async def set_state(self, identifier: UUID, status: str) -> Reminder | None:
        row = await self.pool.fetchrow(
            """
            UPDATE reminders SET status=$2, updated_at=now(), claim_id=NULL, lease_until=NULL
            WHERE id=$1 AND status IN ('active', 'paused') RETURNING *
        """,
            identifier,
            status,
        )
        return self._model(row) if row else None

    async def claim_due(self) -> tuple[Reminder, UUID] | None:
        claim = uuid4()
        row = await self.pool.fetchrow(
            """
            UPDATE reminders SET claim_id=$1, lease_until=now() + interval '3 minutes'
            WHERE id=(
                SELECT id FROM reminders WHERE status IN ('active', 'firing')
                    AND next_check_at <= now() AND (lease_until IS NULL OR lease_until <= now())
                ORDER BY next_check_at, id FOR UPDATE SKIP LOCKED LIMIT 1
            ) RETURNING *
        """,
            claim,
        )
        return (self._model(row), claim) if row else None

    async def checked(
        self,
        identifier: UUID,
        claim: UUID,
        next_check: datetime,
        preview: str | None,
        fingerprint: str | None,
        error: str | None = None,
    ) -> None:
        await self.pool.execute(
            """
            UPDATE reminders SET next_check_at=$3, last_checked_at=now(),
                last_value=COALESCE($4,last_value), last_hash=COALESCE($5,last_hash),
                last_error=$6, claim_id=NULL, lease_until=NULL, updated_at=now()
            WHERE id=$1 AND claim_id=$2 AND status IN ('active', 'firing')
        """,
            identifier,
            claim,
            next_check,
            preview,
            fingerprint,
            error,
        )

    async def begin_fire(
        self,
        identifier: UUID,
        claim: UUID,
        preview: str,
        fingerprint: str | None,
    ) -> bool:
        value = await self.pool.fetchval(
            """
            UPDATE reminders SET status='firing', last_checked_at=now(), last_value=$3,
                last_hash=$4, last_error=NULL, updated_at=now()
            WHERE id=$1 AND claim_id=$2 AND status='active' RETURNING id
        """,
            identifier,
            claim,
            preview,
            fingerprint,
        )
        return value is not None

    async def completed(self, identifier: UUID, claim: UUID, notification_id: UUID) -> None:
        await self.pool.execute(
            """
            UPDATE reminders SET status='completed', notification_id=$3, next_check_at=NULL,
                claim_id=NULL, lease_until=NULL, last_error=NULL, updated_at=now()
            WHERE id=$1 AND claim_id=$2 AND status='firing'
        """,
            identifier,
            claim,
            notification_id,
        )

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
