from __future__ import annotations

import json
from typing import TypedDict
from uuid import UUID, uuid4

import asyncpg

DEFAULT_PROVIDERS = ["codex", "agy"]


class TurnPayload(TypedDict):
    text: str
    image_context: str
    persona: str
    greeting: str
    skills: list[dict[str, str]]
    approval_ids: list[str]


class BridgeStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def start(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS bridge_bot_providers (
                channel text NOT NULL, bot text NOT NULL, providers text[] NOT NULL,
                PRIMARY KEY (channel, bot)
            );
            CREATE TABLE IF NOT EXISTS bridge_cli_providers (
                id text PRIMARY KEY, label text NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bridge_turns (
                id uuid PRIMARY KEY, channel text NOT NULL, bot text NOT NULL,
                conversation uuid NOT NULL, ordinal bigint GENERATED ALWAYS AS IDENTITY,
                payload jsonb NOT NULL, observations jsonb NOT NULL DEFAULT '[]',
                decision jsonb, provider text, reply text,
                phase text NOT NULL DEFAULT 'model'
                    CHECK (phase IN ('model','skill','executing','done')),
                lease uuid, lease_until timestamptz,
                created_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS bridge_turns_pending
                ON bridge_turns (channel, bot, conversation, ordinal) WHERE phase <> 'done';
            CREATE INDEX IF NOT EXISTS bridge_turns_history
                ON bridge_turns (channel, bot, conversation, ordinal DESC) WHERE phase = 'done';
            CREATE TABLE IF NOT EXISTS bridge_outbox (
                turn_id uuid PRIMARY KEY REFERENCES bridge_turns(id) ON DELETE CASCADE,
                next_chunk integer NOT NULL DEFAULT 0,
                due_at timestamptz NOT NULL DEFAULT now(),
                lease uuid, delivered_at timestamptz
            );
        """)

    async def enqueue(
        self, id: UUID, channel: str, bot: str, conversation: UUID, payload: TurnPayload,
    ) -> None:
        await self.pool.execute("""
            INSERT INTO bridge_turns (id, channel, bot, conversation, payload)
            VALUES ($1, $2, $3, $4, $5::jsonb) ON CONFLICT (id) DO NOTHING
        """, id, channel, bot, conversation, json.dumps(payload))

    async def claim(self) -> asyncpg.Record | None:
        return await self.pool.fetchrow("""
            UPDATE bridge_turns AS t SET lease=$1, lease_until=now()+interval '9 minutes'
            WHERE t.id = (
                SELECT q.id FROM bridge_turns AS q
                WHERE q.phase <> 'done' AND (q.lease_until IS NULL OR q.lease_until <= now())
                  AND NOT EXISTS (
                    SELECT 1 FROM bridge_turns AS p
                    WHERE (p.channel,p.bot,p.conversation)=(q.channel,q.bot,q.conversation)
                      AND p.ordinal < q.ordinal AND p.phase <> 'done'
                  )
                ORDER BY q.ordinal LIMIT 1 FOR UPDATE OF q SKIP LOCKED
            ) RETURNING t.*
        """, uuid4())

    async def release_unstarted(self, row: asyncpg.Record) -> None:
        await self.pool.execute("""
            UPDATE bridge_turns SET lease=NULL, lease_until=NULL
            WHERE id=$1 AND lease=$2 AND phase IN ('model','skill')
        """, row["id"], row["lease"])

    async def checkpoint(
        self, row: asyncpg.Record, phase: str, *, decision: dict[str, str] | None = None,
        provider: str | None = None, observations: list[dict[str, str]] | None = None,
    ) -> bool:
        result: str = await self.pool.execute("""
            UPDATE bridge_turns SET phase=$3, decision=$4::jsonb,
                provider=COALESCE($5,provider), observations=COALESCE($6::jsonb,observations),
                lease=CASE WHEN $3='executing' THEN lease END,
                lease_until=CASE WHEN $3='executing' THEN now()+interval '2 minutes' END
            WHERE id=$1 AND lease=$2 AND lease_until > now()
        """, row["id"], row["lease"], phase, json.dumps(decision) if decision else None,
            provider, json.dumps(observations) if observations is not None else None)
        return result == "UPDATE 1"

    async def finish(self, row: asyncpg.Record, reply: str, provider: str | None) -> None:
        await self.pool.execute("""
            WITH completed AS (
                UPDATE bridge_turns SET phase='done', reply=$3, provider=$4,
                    payload=payload - 'image_context' - 'approval_ids' - 'skills' - 'persona',
                    observations='[]'::jsonb,
                    decision=NULL, lease=NULL, lease_until=NULL
                WHERE id=$1 AND lease=$2 AND lease_until > now() RETURNING id
            )
            INSERT INTO bridge_outbox (turn_id) SELECT id FROM completed
        """, row["id"], row["lease"], reply, provider)

    async def history(self, row: asyncpg.Record) -> list[dict[str, str]]:
        previous = await self.pool.fetch("""
            SELECT left(payload->>'text',4000) AS message, left(reply,4000) AS reply
            FROM bridge_turns
            WHERE (channel,bot,conversation)=($1,$2,$3) AND ordinal < $4 AND phase='done'
            ORDER BY ordinal DESC LIMIT 8
        """, row["channel"], row["bot"], row["conversation"], row["ordinal"])
        return [dict(item) for item in reversed(previous)]

    async def providers(self, channel: str, bot: str) -> list[str]:
        value = await self.pool.fetchval("""
            SELECT providers FROM bridge_bot_providers WHERE channel=$1 AND bot=$2
        """, channel, bot)
        return list(DEFAULT_PROVIDERS) if value is None else value

    async def save_providers(self, channel: str, bot: str, providers: list[str]) -> None:
        await self.pool.execute("""
            INSERT INTO bridge_bot_providers VALUES ($1,$2,$3)
            ON CONFLICT (channel,bot) DO UPDATE SET providers=excluded.providers
        """, channel, bot, providers)

    async def catalog(self) -> dict[str, str]:
        rows = await self.pool.fetch("SELECT id,label FROM bridge_cli_providers ORDER BY id")
        return {"codex": "Codex", "agy": "Antigravity", **{r["id"]: r["label"] for r in rows}}

    async def register(self, id: str, label: str) -> None:
        await self.pool.execute("""
            INSERT INTO bridge_cli_providers VALUES ($1,$2)
            ON CONFLICT (id) DO UPDATE SET label=excluded.label
        """, id, label)

    async def last_provider(self, channel: str, bot: str) -> str | None:
        provider: str | None = await self.pool.fetchval("""
            SELECT provider FROM bridge_turns WHERE channel=$1 AND bot=$2 AND phase='done'
            ORDER BY ordinal DESC LIMIT 1
        """, channel, bot)
        return provider

    async def claim_delivery(self) -> asyncpg.Record | None:
        return await self.pool.fetchrow("""
            WITH pending AS (
                UPDATE bridge_outbox AS o SET lease=$1,due_at=now()+interval '45 seconds'
                WHERE o.turn_id=(
                    SELECT x.turn_id FROM bridge_outbox AS x
                    JOIN bridge_turns AS t ON t.id=x.turn_id
                    WHERE x.delivered_at IS NULL AND x.due_at <= now() AND NOT EXISTS (
                        SELECT 1 FROM bridge_outbox AS p JOIN bridge_turns AS u ON u.id=p.turn_id
                        WHERE (u.channel,u.bot,u.conversation)=(t.channel,t.bot,t.conversation)
                          AND u.ordinal < t.ordinal AND p.delivered_at IS NULL
                    )
                    ORDER BY t.ordinal LIMIT 1 FOR UPDATE OF x SKIP LOCKED
                ) RETURNING *
            )
            SELECT pending.*,t.channel,t.bot,t.conversation,t.reply FROM pending
            JOIN bridge_turns t ON t.id=pending.turn_id
        """, uuid4())

    async def delivery_progress(self, row: asyncpg.Record, count: int, done: bool) -> None:
        await self.pool.execute("""
            UPDATE bridge_outbox SET next_chunk=$3,
                delivered_at=CASE WHEN $4 THEN now() ELSE NULL END,
                due_at=now(), lease=NULL
            WHERE turn_id=$1 AND lease=$2
        """, row["turn_id"], row["lease"], count, done)

    async def postpone_delivery(self, row: asyncpg.Record) -> None:
        await self.pool.execute("""
            UPDATE bridge_outbox SET due_at=now()+interval '1 minute', lease=NULL
            WHERE turn_id=$1 AND lease=$2
        """, row["turn_id"], row["lease"])

    async def close(self) -> None:
        await self.pool.close()
