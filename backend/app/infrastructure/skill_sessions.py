from __future__ import annotations

from uuid import UUID

import asyncpg


class PostgresSkillSessionStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: asyncpg.Pool | None = None

    @property
    def _connection_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Skill session store is not started")
        return self._pool

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS conversation_skill_sessions (
                channel TEXT NOT NULL,
                conversation_id UUID NOT NULL,
                skill TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (channel, conversation_id)
            )
        """)

    async def get(self, channel: str, conversation_id: UUID) -> str | None:
        value = await self._connection_pool.fetchval(
            "SELECT skill FROM conversation_skill_sessions WHERE channel=$1 AND conversation_id=$2",
            channel, conversation_id,
        )
        return str(value) if value is not None else None

    async def set(self, channel: str, conversation_id: UUID, skill: str | None) -> None:
        if skill is None:
            await self._connection_pool.execute(
                "DELETE FROM conversation_skill_sessions WHERE channel=$1 AND conversation_id=$2",
                channel, conversation_id,
            )
        else:
            await self._connection_pool.execute("""
                INSERT INTO conversation_skill_sessions(channel, conversation_id, skill)
                VALUES ($1, $2, $3)
                ON CONFLICT (channel, conversation_id) DO UPDATE SET
                    skill=EXCLUDED.skill, updated_at=now()
            """, channel, conversation_id, skill)

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
