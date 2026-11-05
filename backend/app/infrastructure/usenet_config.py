from __future__ import annotations

import json

import asyncpg
from cryptography.fernet import Fernet

from app.domain.usenet import UsenetConfigurationInput, UsenetSettings


class PostgresUsenetConfigurationStore:
    def __init__(self, database_url: str, encryption_key: str) -> None:
        self._database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._fernet = Fernet(encryption_key.encode())
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._database_url, min_size=1, max_size=2)
        await self._pool.execute(
            "CREATE TABLE IF NOT EXISTS usenet_configuration "
            "(singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton), "
            "encrypted_settings BYTEA NOT NULL)"
        )

    async def load(self) -> UsenetSettings | None:
        if not self._pool:
            raise RuntimeError("Usenet configuration store is not started")
        row = await self._pool.fetchrow(
            "SELECT encrypted_settings FROM usenet_configuration WHERE singleton=TRUE"
        )
        if not row:
            return None
        return UsenetSettings.model_validate_json(
            self._fernet.decrypt(bytes(row["encrypted_settings"]))
        )

    async def save(self, configuration: UsenetConfigurationInput) -> UsenetSettings:
        if not self._pool:
            raise RuntimeError("Usenet configuration store is not started")
        previous = await self.load()
        values = configuration.model_dump()
        for key in ("provider_api_key", "nzbget_password"):
            secret = values[key]
            if secret is None or not secret.get_secret_value():
                if previous is None:
                    raise ValueError(
                        "Introduce las dos credenciales para la primera configuración."
                    )
                values[key] = getattr(previous, key)
        settings = UsenetSettings.model_validate(values)
        # SecretStr masks JSON by default: serialize the two secrets explicitly inside encryption.
        payload = settings.model_dump(mode="json")
        payload["provider_api_key"] = settings.provider_api_key.get_secret_value()
        payload["nzbget_password"] = settings.nzbget_password.get_secret_value()
        encrypted = self._fernet.encrypt(json.dumps(payload).encode())
        await self._pool.execute(
            "INSERT INTO usenet_configuration(singleton, encrypted_settings) VALUES(TRUE, $1) "
            "ON CONFLICT(singleton) DO UPDATE SET encrypted_settings=EXCLUDED.encrypted_settings",
            encrypted,
        )
        return settings

    async def aclose(self) -> None:
        if self._pool:
            await self._pool.close()
