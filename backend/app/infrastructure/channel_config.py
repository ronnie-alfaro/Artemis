from __future__ import annotations

import json

import asyncpg

from app.domain.channels import ChannelConnection, Provider
from app.infrastructure.config_cipher import ConfigurationCipher


class PostgresChannelConfigurationStore:
    def __init__(self, database_url: str, cipher: ConfigurationCipher) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._cipher = cipher
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute(
            "CREATE TABLE IF NOT EXISTS channel_configuration "
            "(provider TEXT PRIMARY KEY, encrypted_settings BYTEA NOT NULL, "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )

    async def load(self, provider: Provider) -> ChannelConnection | None:
        if self._pool is None:
            raise RuntimeError("Channel configuration store is not started")
        value = await self._pool.fetchval(
            "SELECT encrypted_settings FROM channel_configuration WHERE provider=$1",
            provider,
        )
        if value is None:
            return None
        return ChannelConnection.model_validate_json(
            await self._cipher.decrypt(bytes(value), f"channel:{provider}"),
        )

    async def save(self, provider: Provider, connection: ChannelConnection) -> None:
        if self._pool is None:
            raise RuntimeError("Channel configuration store is not started")
        payload = connection.model_dump(mode="json")
        payload["token"] = connection.token.get_secret_value()
        encrypted = await self._cipher.encrypt(json.dumps(payload).encode(), f"channel:{provider}")
        await self._pool.execute(
            "INSERT INTO channel_configuration(provider, encrypted_settings) VALUES ($1,$2) "
            "ON CONFLICT(provider) DO UPDATE SET encrypted_settings=EXCLUDED.encrypted_settings, "
            "updated_at=now()",
            provider,
            encrypted,
        )

    async def delete(self, provider: Provider) -> None:
        if self._pool is None:
            raise RuntimeError("Channel configuration store is not started")
        await self._pool.execute("DELETE FROM channel_configuration WHERE provider=$1", provider)

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
