import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_config_cipher import Kms

from app.api.main import create_app
from app.application.channels import ChannelController
from app.domain.channels import ChannelConfigurationInput, ChannelConnection
from app.infrastructure.channel_config import PostgresChannelConfigurationStore
from app.infrastructure.config_cipher import ConfigurationEncryptionError, KmsConfigurationCipher


class Pool:
    def __init__(self):
        self.rows = {}

    async def execute(self, query, *values):
        if query.startswith("DELETE"):
            self.rows.pop(values[0], None)
        else:
            self.rows[values[0]] = values[1]

    async def fetchval(self, query, provider):
        return self.rows.get(provider)


class Runtime:
    def __init__(self, connection):
        self.connection = connection
        self.started = False
        self.sent = []

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def recipient_for_conversation(self, identifier):
        return "42"

    async def send_notification(self, recipient, content):
        self.sent.append((recipient, content))


def controller():
    kms = Kms()
    store = PostgresChannelConfigurationStore(
        "postgresql://test", KmsConfigurationCipher(kms, "key")
    )
    store._pool = Pool()
    environment = ChannelConnection(
        token=SecretStr("123:original"), agent_name="123", allowed_user_ids=[42]
    )
    return ChannelController("telegram", store, environment, Runtime), kms


def test_encrypted_save_live_reload_blank_token_and_disable_survive_restart():
    async def run():
        channel, kms = controller()
        await channel.start()
        original = channel.runtime
        await channel.configure(
            ChannelConfigurationInput(token=SecretStr("123:replacement"), allowed_user_ids=[42, 99])
        )
        assert not original.started
        assert channel.runtime.started
        assert channel.connection.token.get_secret_value() == "123:replacement"
        assert b"replacement" not in channel.store._pool.rows["telegram"]
        # Delivery worker holds the controller, so results follow the replacement connection.
        await channel.send_notification("42", "result")
        assert channel.runtime.sent == [("42", "result")]
        assert await channel.recipient_for_conversation(uuid4()) == "42"
        await channel.configure(ChannelConfigurationInput(enabled=False, allowed_user_ids=[42]))
        assert channel.runtime is None
        restarted = ChannelController("telegram", channel.store, channel.environment, Runtime)
        await restarted.start()
        assert restarted.runtime is None  # The environment must not re-enable a disabled channel.
        assert restarted.connection.token.get_secret_value() == "123:replacement"
        assert restarted.configuration().credential_source == "control plane"
        assert "replacement" not in restarted.configuration().model_dump_json()
        assert len(kms.calls) > 0

    asyncio.run(run())


def test_kms_failure_keeps_working_channel_and_existing_record():
    async def run():
        channel, kms = controller()
        await channel.start()
        working = channel.runtime
        kms.fail = True
        with pytest.raises(ConfigurationEncryptionError):
            await channel.configure(ChannelConfigurationInput(allowed_user_ids=[42]))
        assert channel.runtime is working
        assert working.started
        assert channel.store._pool.rows == {}

    asyncio.run(run())


def test_api_authentication_secret_masking_and_token_preservation(monkeypatch):
    monkeypatch.setenv("ARTEMIS_ADMIN_TOKEN", "admin")
    app = create_app()
    with TestClient(app) as client:
        channel, _ = controller()
        app.state.telegram = channel
        assert client.get("/api/v1/channels/telegram/configuration").status_code == 401
        headers = {"Authorization": "Bearer admin"}
        payload = {"token": "123:private-token", "allowed_user_ids": [42]}
        result = client.put(
            "/api/v1/channels/telegram/configuration", json=payload, headers=headers
        )
        assert result.status_code == 200
        assert "private-token" not in result.text
        assert result.json()["agent_name"] == "123"
        bad = client.put(
            "/api/v1/channels/telegram/configuration",
            json={"token": "123:private-token", "allowed_user_ids": "bad"},
            headers=headers,
        )
        assert bad.status_code == 422
        assert "private-token" not in bad.text
        result = client.put(
            "/api/v1/channels/telegram/configuration",
            json={"allowed_user_ids": [99]},
            headers=headers,
        )
        assert result.status_code == 200
        assert channel.connection.token.get_secret_value() == "123:private-token"
        assert client.get("/api/v1/channels/telegram/configuration", headers=headers).json()[
            "allowed_user_ids"
        ] == [99]


def test_failed_start_rolls_back_saved_settings_and_restores_previous_runtime():
    async def run():
        channel, _ = controller()
        await channel.start()
        calls = []

        class FailingRuntime(Runtime):
            async def start(self):
                calls.append(self.connection.token.get_secret_value())
                if self.connection.token.get_secret_value() == "123:broken":
                    raise RuntimeError("startup failed")
                await super().start()

        channel.factory = FailingRuntime
        with pytest.raises(RuntimeError, match="No se pudo aplicar"):
            await channel.configure(
                ChannelConfigurationInput(
                    token=SecretStr("123:broken"),
                    allowed_user_ids=[42],
                )
            )
        assert calls == ["123:broken", "123:original"]
        assert channel.connection.token.get_secret_value() == "123:original"
        assert channel.runtime.started
        assert channel.store._pool.rows == {}

    asyncio.run(run())


def test_remote_validation_fails_before_storing_or_stopping_current_channel():
    async def run():
        channel, _ = controller()
        await channel.start()
        working = channel.runtime

        async def reject(candidate):
            raise ValueError("invalid credentials")

        channel.validate = reject
        with pytest.raises(ValueError):
            await channel.configure(ChannelConfigurationInput(allowed_user_ids=[42]))
        assert channel.runtime is working and working.started
        assert channel.store._pool.rows == {}

    asyncio.run(run())
