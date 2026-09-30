from __future__ import annotations

import json

import asyncpg

from app.domain.models import ApprovalRequest


class PostgresApprovalStore:
    """Durable approval and audit records, scoped to this Artemis deployment."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_records (
                approval_id UUID PRIMARY KEY,
                status TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                payload JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    @property
    def _connection_pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("Approval store is not started")
        return self._pool

    async def load(self) -> list[ApprovalRequest]:
        rows = await self._connection_pool.fetch("SELECT payload FROM approval_records")
        return [
            ApprovalRequest.model_validate(
                json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            )
            for row in rows
        ]

    async def save(self, approval: ApprovalRequest) -> None:
        await self._connection_pool.execute(
            """
            INSERT INTO approval_records(approval_id, status, expires_at, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (approval_id) DO UPDATE SET
                status=EXCLUDED.status,
                expires_at=EXCLUDED.expires_at,
                payload=EXCLUDED.payload,
                updated_at=now()
            """,
            approval.id,
            approval.status.value,
            approval.expires_at,
            json.dumps(approval.model_dump(mode="json")),
        )

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
