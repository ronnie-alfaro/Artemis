from uuid import UUID

import asyncpg

from app.domain.curiosity import Exploration, ExplorationSummary


class PostgresExplorationStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        try:
            await pool.execute("""
                CREATE TABLE IF NOT EXISTS curiosity_explorations (
                    id UUID PRIMARY KEY,
                    objective TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    report JSONB NOT NULL,
                    UNIQUE (objective, fingerprint)
                )
            """)
            await pool.execute("""
                CREATE INDEX IF NOT EXISTS curiosity_explorations_recent
                    ON curiosity_explorations (created_at DESC, id DESC)
            """)
        except BaseException:
            await pool.close()
            raise
        self._pool = pool

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Exploration store is not started")
        return self._pool

    async def save(self, report: Exploration) -> Exploration:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """
                INSERT INTO curiosity_explorations
                    (id, objective, fingerprint, created_at, report)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (objective, fingerprint) DO NOTHING
            """,
                report.id,
                report.objective,
                report.fingerprint,
                report.created_at,
                report.model_dump_json(),
            )
            saved = await connection.fetchval(
                """
                SELECT report FROM curiosity_explorations
                WHERE objective=$1 AND fingerprint=$2
            """,
                report.objective,
                report.fingerprint,
            )
        return Exploration.model_validate_json(saved)

    async def get(self, exploration_id: UUID) -> Exploration | None:
        report = await self.pool.fetchval(
            "SELECT report FROM curiosity_explorations WHERE id=$1",
            exploration_id,
        )
        return Exploration.model_validate_json(report) if report is not None else None

    async def recent(self) -> list[ExplorationSummary]:
        rows = await self.pool.fetch("""
            SELECT id, objective, fingerprint, created_at, report->>'status' AS status
            FROM curiosity_explorations ORDER BY created_at DESC, id DESC LIMIT 50
        """)
        return [ExplorationSummary.model_validate(dict(row)) for row in rows]

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
