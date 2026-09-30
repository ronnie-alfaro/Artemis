from __future__ import annotations

import asyncpg
from cryptography.fernet import Fernet

from app.domain.karakeep import KarakeepConfigurationInput, KarakeepSettings


class PostgresKarakeepConfigurationStore:
    def __init__(self, database_url: str, encryption_key: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._fernet = Fernet(encryption_key.encode())
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute(
            "CREATE TABLE IF NOT EXISTS karakeep_configuration "
            "(singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton), "
            "base_url TEXT NOT NULL, encrypted_api_key BYTEA NOT NULL)"
        )

    async def load(self) -> KarakeepSettings | None:
        if not self._pool:
            raise RuntimeError("Karakeep configuration store is not started")
        row = await self._pool.fetchrow(
            "SELECT base_url, encrypted_api_key FROM karakeep_configuration WHERE singleton=TRUE"
        )
        if not row:
            return None
        return KarakeepSettings.model_validate(
            {
                "base_url": row["base_url"],
                "api_key": self._fernet.decrypt(bytes(row["encrypted_api_key"])).decode(),
            }
        )

    async def save(self, configuration: KarakeepConfigurationInput) -> KarakeepSettings:
        if not self._pool:
            raise RuntimeError("Karakeep configuration store is not started")
        settings = KarakeepSettings.model_validate(configuration.model_dump())
        await self._pool.execute(
            "INSERT INTO karakeep_configuration(singleton, base_url, encrypted_api_key) "
            "VALUES(TRUE, $1, $2) ON CONFLICT(singleton) DO UPDATE SET "
            "base_url=EXCLUDED.base_url, encrypted_api_key=EXCLUDED.encrypted_api_key",
            str(settings.base_url).rstrip("/"),
            self._fernet.encrypt(settings.api_key.encode()),
        )
        return settings

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
