from __future__ import annotations

import asyncpg

from app.domain.seerr import SeerrConfigurationInput, SeerrSettings
from app.infrastructure.config_cipher import ConfigurationCipher, configuration_cipher


class PostgresSeerrConfigurationStore:
    """Stores only an encrypted local copy of the Seerr API key."""

    def __init__(self, database_url: str, encryption_key: str | ConfigurationCipher) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._cipher = configuration_cipher(encryption_key)
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS seerr_configuration (
                singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
                base_url TEXT NOT NULL,
                encrypted_api_key BYTEA NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    @property
    def _connection_pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("Seerr configuration store is not started")
        return self._pool

    async def load(self) -> SeerrSettings | None:
        row = await self._connection_pool.fetchrow(
            "SELECT base_url, encrypted_api_key FROM seerr_configuration WHERE singleton=TRUE"
        )
        if not row:
            return None
        api_key = (await self._cipher.decrypt(bytes(row["encrypted_api_key"]), "seerr")).decode()
        return SeerrSettings.model_validate({"base_url": row["base_url"], "api_key": api_key})

    async def save(self, configuration: SeerrConfigurationInput) -> SeerrSettings:
        settings = SeerrSettings.model_validate(configuration.model_dump())
        encrypted = await self._cipher.encrypt(settings.api_key.encode(), "seerr")
        await self._connection_pool.execute(
            """
            INSERT INTO seerr_configuration(singleton, base_url, encrypted_api_key)
            VALUES (TRUE, $1, $2)
            ON CONFLICT (singleton) DO UPDATE SET
                base_url=EXCLUDED.base_url,
                encrypted_api_key=EXCLUDED.encrypted_api_key,
                updated_at=now()
            """,
            str(settings.base_url).rstrip("/"),
            encrypted,
        )
        return settings

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
