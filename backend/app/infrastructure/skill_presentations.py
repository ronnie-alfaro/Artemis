from __future__ import annotations

import asyncpg

from app.domain.skills import SkillPresentation


class PostgresSkillPresentationStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute("""
            CREATE TABLE IF NOT EXISTS skill_presentations (
                skill_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL
            )
        """)

    async def load(self) -> dict[str, SkillPresentation]:
        if self._pool is None:
            raise RuntimeError("Skill presentation store is not started")
        rows = await self._pool.fetch("SELECT skill_id, name, description FROM skill_presentations")
        return {row["skill_id"]: SkillPresentation(
            name=row["name"], description=row["description"]
        ) for row in rows}

    async def save(self, skill_id: str, value: SkillPresentation) -> None:
        if self._pool is None:
            raise RuntimeError("Skill presentation store is not started")
        await self._pool.execute("""
            INSERT INTO skill_presentations(skill_id, name, description) VALUES ($1, $2, $3)
            ON CONFLICT (skill_id) DO UPDATE SET name=EXCLUDED.name,
                description=EXCLUDED.description
        """, skill_id, value.name, value.description)

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
