import asyncio
import copy

import pytest
from cryptography.fernet import Fernet
from test_config_cipher import Kms

from app.infrastructure import migrate_config_kms
from app.infrastructure.config_cipher import ConfigurationEncryptionError, KmsConfigurationCipher


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.before = copy.deepcopy(self.connection.rows)

    async def __aexit__(self, kind, value, tb):
        if kind:
            self.connection.rows = self.before


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def transaction(self):
        return Transaction(self)

    async def fetchval(self, query, *args):
        if query.startswith("SELECT to_regclass"):
            if args:
                return args[0] if args[0] in self.rows else None
            return "channel_configuration" if "channel_configuration" in self.rows else None
        return self.rows[query.split(" FROM ")[1].split()[0]]

    async def fetch(self, query):
        return [
            {"provider": provider, "encrypted_settings": encrypted}
            for provider, encrypted in self.rows["channel_configuration"].items()
        ]

    async def execute(self, query, *values):
        table = query.split()[1]
        if table == "channel_configuration":
            self.rows[table][values[1]] = values[0]
        else:
            self.rows[table] = values[0]

    async def close(self):
        self.closed = True


def prepare(monkeypatch):
    legacy = Fernet.generate_key()
    cipher = KmsConfigurationCipher(Kms(), "key", legacy.decode())
    connection = Connection(
        {
            "seerr_configuration": Fernet(legacy).encrypt(b"seerr-secret"),
            "usenet_configuration": Fernet(legacy).encrypt(b'{"password":"private"}'),
            "channel_configuration": {
                "telegram": Fernet(legacy).encrypt(b'{"token":"bot-secret"}')
            },
        }
    )

    async def connect(url):
        return connection

    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setattr(migrate_config_kms, "configured_cipher", lambda: cipher)
    monkeypatch.setattr(migrate_config_kms.asyncpg, "connect", connect)
    return connection, cipher


def test_preview_does_not_call_kms_and_apply_is_idempotent(monkeypatch, capsys):
    connection, cipher = prepare(monkeypatch)
    before = copy.deepcopy(connection.rows)
    asyncio.run(migrate_config_kms.migrate(False))
    assert connection.rows == before
    assert cipher._client.calls == []
    asyncio.run(migrate_config_kms.migrate(True))
    after = copy.deepcopy(connection.rows)
    assert after["seerr_configuration"].startswith(cipher.prefix)
    assert after["channel_configuration"]["telegram"].startswith(cipher.prefix)
    assert b"bot-secret" not in after["channel_configuration"]["telegram"]
    assert asyncio.run(cipher.decrypt(after["seerr_configuration"], "seerr")) == b"seerr-secret"
    asyncio.run(migrate_config_kms.migrate(True))
    assert connection.rows == after
    assert "migradas: 0" in capsys.readouterr().out


def test_failed_migration_rolls_back_all_rows(monkeypatch):
    connection, cipher = prepare(monkeypatch)
    connection.rows["usenet_configuration"] = b"invalid-old-ciphertext"
    before = copy.deepcopy(connection.rows)
    with pytest.raises(ConfigurationEncryptionError):
        asyncio.run(migrate_config_kms.migrate(True))
    assert connection.rows == before
    assert connection.closed
    assert cipher._client.calls  # First row was processed before the second one failed.
