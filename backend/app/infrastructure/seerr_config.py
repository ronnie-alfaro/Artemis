from __future__ import annotations

import asyncpg
from cryptography.fernet import Fernet, InvalidToken

from app.domain.seerr import SeerrConfigurationInput, SeerrSettings


class PostgresSeerrConfigurationStore:
    """Stores only an encrypted local copy of the Seerr API key."""

    def __init__(self, database_url: str, encryption_key: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._fernet = Fernet(encryption_key.encode())
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
        try:
            api_key = self._fernet.decrypt(bytes(row["encrypted_api_key"])).decode()
        except InvalidToken as error:
            raise RuntimeError(
                "Seerr credentials cannot be decrypted with this deployment key"
            ) from error
        return SeerrSettings.model_validate({"base_url": row["base_url"], "api_key": api_key})

    async def save(self, configuration: SeerrConfigurationInput) -> SeerrSettings:
        settings = SeerrSettings.model_validate(configuration.model_dump())
        encrypted = self._fernet.encrypt(settings.api_key.encode())
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
