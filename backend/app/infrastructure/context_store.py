"""Configuration revisions, extractive summaries and turn telemetry in PostgreSQL."""
import json
from uuid import UUID

from app.domain.context_builder import ContextSettings, merge_settings

SCHEMA = """
ALTER TABLE bridge_turns ADD COLUMN IF NOT EXISTS context_results jsonb NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS bridge_context_config (
    revision bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope text NOT NULL,
    config jsonb NOT NULL,
    restored_from bigint REFERENCES bridge_context_config(revision),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bridge_context_config_scope
    ON bridge_context_config(scope, revision DESC);
CREATE TABLE IF NOT EXISTS bridge_context_summary (
    channel text NOT NULL, bot text NOT NULL, conversation uuid NOT NULL,
    ordinal bigint NOT NULL, content jsonb NOT NULL,
    PRIMARY KEY(channel, bot, conversation)
);
CREATE TABLE IF NOT EXISTS bridge_context_metrics (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    turn_id uuid NOT NULL, channel text NOT NULL, bot text NOT NULL,
    conversation uuid NOT NULL, provider text NOT NULL,
    values jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bridge_context_metrics_scope_provider
    ON bridge_context_metrics(channel, bot, provider, created_at DESC);
CREATE INDEX IF NOT EXISTS bridge_context_metrics_created
    ON bridge_context_metrics(created_at DESC);
"""


class ContextStore:
    def __init__(self, pool):
        self.pool = pool

    async def scopes(self, scopes: list[str]) -> dict[str, dict]:
        rows = await self.pool.fetch("""
            SELECT DISTINCT ON (scope) scope, config FROM bridge_context_config
            WHERE scope = ANY($1::text[]) ORDER BY scope, revision DESC
        """, scopes)
        return {row["scope"]: json.loads(row["config"]) for row in rows}

    async def effective(self, agent: str, providers: list[str]) -> dict[str, ContextSettings]:
        layers = await self.scopes(["global", agent, *(f"provider:{p}" for p in providers)])
        return {
            provider: merge_settings(layers.get("global", {}), layers.get(agent, {}),
                                     layers.get(f"provider:{provider}", {}))
            for provider in providers
        }

    async def revisions(self, scope: str) -> list[dict]:
        rows = await self.pool.fetch("""
            SELECT revision, config, updated_at, restored_from FROM bridge_context_config
            WHERE scope=$1 ORDER BY revision DESC LIMIT 30
        """, scope)
        return [{**dict(row), "config": json.loads(row["config"])} for row in rows]

    async def save(self, scope: str, config: dict, restored_from: int | None = None) -> int:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(80310743)")
            rows = await connection.fetch("""
                SELECT DISTINCT ON (scope) scope, config FROM bridge_context_config
                ORDER BY scope, revision DESC
            """)
            layers = {row["scope"]: json.loads(row["config"]) for row in rows}
            layers[scope] = config
            global_config = layers.get("global", {})
            agents = [{}] + [v for k, v in layers.items() if k.startswith("agent:")]
            providers = [{}] + [v for k, v in layers.items() if k.startswith("provider:")]
            for agent in agents:
                for provider in providers:
                    merge_settings(global_config, agent, provider)
            return await connection.fetchval("""
                INSERT INTO bridge_context_config(scope, config, restored_from)
                VALUES($1,$2::jsonb,$3) RETURNING revision
            """, scope, json.dumps(config), restored_from)

    async def turn(self, channel: str, bot: str, conversation: UUID):
        return await self.pool.fetchrow("""
            SELECT channel,bot,conversation,ordinal,id,created_at FROM bridge_turns
            WHERE (channel,bot,conversation)=($1,$2,$3) ORDER BY ordinal DESC LIMIT 1
        """, channel, bot, conversation)

    async def history(self, row, settings: ContextSettings, *, persist: bool) -> tuple:
        scope = row["channel"], row["bot"], row["conversation"]
        cutoff = row["ordinal"]
        records = await self.pool.fetch("""
            SELECT ordinal,left(payload->>'text',2500) AS message,left(reply,2500) AS reply,
                   context_results
            FROM bridge_turns WHERE (channel,bot,conversation)=($1,$2,$3)
            AND ordinal < $4 AND phase='done' ORDER BY ordinal DESC LIMIT $5
        """, *scope, cutoff, settings.summarize_after + settings.recent_turns + 20)
        recent = [{**dict(item), "context_results": json.loads(item["context_results"])}
                  for item in reversed(records[:settings.recent_turns])]
        old = records[settings.recent_turns:]
        previous = await self.pool.fetchrow("""
            SELECT ordinal,content FROM bridge_context_summary
            WHERE (channel,bot,conversation)=($1,$2,$3) AND ordinal < $4
        """, *scope, cutoff)
        summary = json.loads(previous["content"]) if previous else None
        if len(records) <= settings.summarize_after and not previous:
            return recent, None, False
        if not old or (previous and old[0]["ordinal"] <= previous["ordinal"]):
            return recent, summary, False

        # Only verbatim excerpts enter extractive checkpoints. Approval IDs remain in the turn.
        entries = old if previous is None else [item for item in old
                                               if item["ordinal"] > previous["ordinal"]]
        summary = summary or {"user_context": [], "assistant_context": [], "references": []}
        summary.setdefault("tool_results", [])
        limit = settings.summary_size // len(summary)
        for item in reversed(entries):
            message, reply = item["message"] or "", item["reply"] or ""
            summary["user_context"].append(message[:min(400, limit)])
            summary["assistant_context"].append(reply[:min(400, limit)])
            for result in json.loads(item["context_results"]):
                summary["tool_results"].append(
                    f"{result['capability']}: {result['result']}"[:min(240, limit)],
                )
            if "?" in reply or any(char.isdigit() for char in reply):
                summary["references"].append(reply[-min(240, limit):])
        for key, values in summary.items():
            trimmed: list[str] = []
            for value in reversed(values):
                if value and value not in trimmed and sum(map(len, trimmed)) + len(value) <= limit:
                    trimmed.append(value)
            summary[key] = list(reversed(trimmed))
        if persist:
            await self.pool.execute("""
                INSERT INTO bridge_context_summary(channel,bot,conversation,ordinal,content)
                VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(channel,bot,conversation)
                DO UPDATE SET ordinal=excluded.ordinal,content=excluded.content
                WHERE bridge_context_summary.ordinal < excluded.ordinal
            """, *scope, old[0]["ordinal"], json.dumps(summary))
        return recent, summary, persist

    async def calibration(self, channel: str, bot: str, provider: str) -> int:
        row = await self.pool.fetchrow("""
            SELECT count(*) AS samples,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY extra) AS overhead
            FROM (
                SELECT (values->'usage'->>'input_tokens')::bigint
                       - (values->>'estimated_tokens')::bigint AS extra
                FROM bridge_context_metrics
                WHERE channel=$1 AND bot=$2 AND provider=$3
                AND values->>'status'='ok' AND values->'usage'->>'input_tokens' IS NOT NULL
                AND values->>'estimated_tokens' IS NOT NULL
                ORDER BY created_at DESC LIMIT 30
            ) measured
        """, channel, bot, provider)
        return max(0, int(row["overhead"])) if row["samples"] >= 5 else 0

    async def record(self, row, provider: str, values: dict) -> None:
        await self.pool.execute("""
            INSERT INTO bridge_context_metrics(turn_id,channel,bot,conversation,provider,values)
            VALUES($1,$2,$3,$4,$5,$6::jsonb)
        """, row["id"], row["channel"], row["bot"], row["conversation"], provider,
            json.dumps(values))

    async def metrics(self) -> list[dict]:
        rows = await self.pool.fetch("""
            SELECT created_at,channel,bot,conversation,provider,values FROM bridge_context_metrics
            WHERE created_at > now() - interval '30 days' ORDER BY created_at DESC LIMIT 1000
        """)
        return [{**dict(row), "values": json.loads(row["values"])} for row in rows]
