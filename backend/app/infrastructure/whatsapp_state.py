from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg

from app.domain.whatsapp import DEFAULT_WHATSAPP_GREETING, WhatsAppInbound


class PostgresWhatsAppStateStore:
    """Durable cursor, idempotency, and opaque participant-to-conversation mapping."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=4)
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS whatsapp_poll_state (
                    agent_name TEXT PRIMARY KEY,
                    next_offset BIGINT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS whatsapp_conversations (
                    agent_name TEXT NOT NULL,
                    participant_id TEXT NOT NULL,
                    conversation_id UUID NOT NULL,
                    PRIMARY KEY (agent_name, participant_id)
                );
                CREATE TABLE IF NOT EXISTS whatsapp_completed_messages (
                    agent_name TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (agent_name, message_id)
                );
                CREATE TABLE IF NOT EXISTS whatsapp_skill_bindings (
                    agent_name TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    PRIMARY KEY (agent_name, capability)
                );
                CREATE TABLE IF NOT EXISTS whatsapp_inbox (
                    agent_name TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    completed_at TIMESTAMPTZ,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (agent_name, message_id)
                );
                CREATE TABLE IF NOT EXISTS whatsapp_agent_profiles (
                    agent_name TEXT PRIMARY KEY,
                    greeting TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )

    @property
    def _connection_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("WhatsApp state store is not started")
        return self._pool

    async def get_offset(self, agent_name: str) -> int | None:
        value = await self._connection_pool.fetchval(
            "SELECT next_offset FROM whatsapp_poll_state WHERE agent_name = $1", agent_name
        )
        return int(value) if value is not None else None

    async def set_offset(self, agent_name: str, offset: int) -> None:
        await self._connection_pool.execute(
            """
            INSERT INTO whatsapp_poll_state(agent_name, next_offset) VALUES ($1, $2)
            ON CONFLICT (agent_name) DO UPDATE SET
                next_offset = EXCLUDED.next_offset, updated_at = now()
            """,
            agent_name,
            offset,
        )

    async def enqueue(self, agent_name: str, message: WhatsAppInbound) -> None:
        await self._connection_pool.execute(
            """
            INSERT INTO whatsapp_inbox(agent_name, message_id, payload) VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (agent_name, message_id) DO NOTHING
            """,
            agent_name,
            message.id,
            json.dumps(message.model_dump(mode="json")),
        )

    async def pending(self, agent_name: str) -> list[WhatsAppInbound]:
        rows = await self._connection_pool.fetch(
            """
            SELECT payload FROM whatsapp_inbox
            WHERE agent_name=$1 AND completed_at IS NULL
            ORDER BY received_at, message_id
            """,
            agent_name,
        )
        return [
            WhatsAppInbound.model_validate(
                json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            )
            for row in rows
        ]

    async def completed(self, agent_name: str, message_id: str) -> bool:
        return bool(
            await self._connection_pool.fetchval(
                "SELECT EXISTS(SELECT 1 FROM whatsapp_completed_messages "
                "WHERE agent_name=$1 AND message_id=$2)",
                agent_name,
                message_id,
            )
        )

    async def conversation_for(self, agent_name: str, participant_id: str) -> UUID:
        conversation_id = uuid4()
        value = await self._connection_pool.fetchval(
            """
            INSERT INTO whatsapp_conversations(agent_name, participant_id, conversation_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (agent_name, participant_id) DO UPDATE SET
                participant_id = EXCLUDED.participant_id
            RETURNING conversation_id
            """,
            agent_name,
            participant_id,
            conversation_id,
        )
        return UUID(str(value))

    async def mark_completed(self, agent_name: str, message: WhatsAppInbound) -> None:
        await self._connection_pool.execute(
            "INSERT INTO whatsapp_completed_messages(agent_name, message_id) "
            "VALUES ($1, $2) ON CONFLICT DO NOTHING",
            agent_name,
            message.id,
        )
        await self._connection_pool.execute(
            "UPDATE whatsapp_inbox SET completed_at=now() WHERE agent_name=$1 AND message_id=$2",
            agent_name,
            message.id,
        )

    async def capabilities_for(self, agent_name: str) -> list[str]:
        rows = await self._connection_pool.fetch(
            "SELECT capability FROM whatsapp_skill_bindings "
            "WHERE agent_name=$1 ORDER BY capability",
            agent_name,
        )
        # Status is a mandatory safe fallback. Optional skills narrow what the
        # planner can choose, but ordinary chat must never fail for lack of one.
        return sorted({"assistant.status", *(str(row["capability"]) for row in rows)})

    async def set_capabilities(self, agent_name: str, capabilities: list[str]) -> None:
        unique = sorted({"assistant.status", *capabilities})
        async with self._connection_pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM whatsapp_skill_bindings WHERE agent_name=$1", agent_name
            )
            if unique:
                await connection.executemany(
                    "INSERT INTO whatsapp_skill_bindings(agent_name, capability) VALUES ($1, $2)",
                    [(agent_name, capability) for capability in unique],
                )

    async def greeting_for(self, agent_name: str) -> str:
        greeting = await self._connection_pool.fetchval(
            "SELECT greeting FROM whatsapp_agent_profiles WHERE agent_name=$1", agent_name
        )
        return str(greeting) if greeting else DEFAULT_WHATSAPP_GREETING

    async def set_greeting(self, agent_name: str, greeting: str) -> None:
        await self._connection_pool.execute(
            """
            INSERT INTO whatsapp_agent_profiles(agent_name, greeting) VALUES ($1, $2)
            ON CONFLICT (agent_name) DO UPDATE SET greeting=EXCLUDED.greeting, updated_at=now()
            """,
            agent_name,
            greeting,
        )

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
