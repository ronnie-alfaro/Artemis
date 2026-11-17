"""Versioned configuration encryption; AWS credentials use the standard SDK chain."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ConfigurationEncryptionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "No se pudo cifrar o descifrar la configuración. Revisa la clave y sus permisos."
        )


class ConfigurationCipher(Protocol):
    async def encrypt(self, plaintext: bytes, purpose: str) -> bytes: ...
    async def decrypt(self, ciphertext: bytes, purpose: str) -> bytes: ...


class FernetConfigurationCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    async def encrypt(self, plaintext: bytes, purpose: str) -> bytes:
        return self._fernet.encrypt(plaintext)

    async def decrypt(self, ciphertext: bytes, purpose: str) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken:
            raise ConfigurationEncryptionError() from None


class KmsConfigurationCipher:
    """One fresh AES-256 data key per write; only wrapped keys reach PostgreSQL."""

    prefix = b"artemis-kms-v1:"

    def __init__(self, client: Any, key_id: str, legacy_key: str | None = None) -> None:
        self._client, self._key_id = client, key_id
        self._legacy = FernetConfigurationCipher(legacy_key) if legacy_key else None

    @staticmethod
    def _context(purpose: str) -> dict[str, str]:
        return {"application": "artemis", "purpose": purpose}

    async def encrypt(self, plaintext: bytes, purpose: str) -> bytes:
        try:
            data = await asyncio.to_thread(
                self._client.generate_data_key,
                KeyId=self._key_id,
                KeySpec="AES_256",
                EncryptionContext=self._context(purpose),
            )
            nonce = os.urandom(12)
            encrypted = AESGCM(data["Plaintext"]).encrypt(nonce, plaintext, purpose.encode())
            envelope = {
                "key": base64.b64encode(data["CiphertextBlob"]).decode(),
                "nonce": base64.b64encode(nonce).decode(),
                "data": base64.b64encode(encrypted).decode(),
            }
            return self.prefix + json.dumps(envelope, separators=(",", ":")).encode()
        except Exception:
            raise ConfigurationEncryptionError() from None

    async def decrypt(self, ciphertext: bytes, purpose: str) -> bytes:
        if not ciphertext.startswith(self.prefix):
            if self._legacy:
                return await self._legacy.decrypt(ciphertext, purpose)
            raise ConfigurationEncryptionError()
        try:
            envelope = json.loads(ciphertext[len(self.prefix) :])
            data = await asyncio.to_thread(
                self._client.decrypt,
                KeyId=self._key_id,
                CiphertextBlob=base64.b64decode(envelope["key"], validate=True),
                EncryptionContext=self._context(purpose),
            )
            return AESGCM(data["Plaintext"]).decrypt(
                base64.b64decode(envelope["nonce"], validate=True),
                base64.b64decode(envelope["data"], validate=True),
                purpose.encode(),
            )
        except Exception:
            raise ConfigurationEncryptionError() from None


def configuration_cipher(value: str | ConfigurationCipher) -> ConfigurationCipher:
    return FernetConfigurationCipher(value) if isinstance(value, str) else value


def configured_cipher() -> ConfigurationCipher | None:
    key_id = os.getenv("ARTEMIS_KMS_KEY_ID")
    legacy_key = os.getenv("ARTEMIS_CONFIG_ENCRYPTION_KEY")
    if key_id:
        # Import lazily: deployments still using Fernet do not initialize the AWS SDK.
        import boto3
        from botocore.config import Config

        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if not region:
            raise RuntimeError("AWS_REGION is required when ARTEMIS_KMS_KEY_ID is configured")
        client = boto3.client(
            "kms",
            region_name=region,
            config=Config(
                connect_timeout=3,
                read_timeout=5,
                retries={"mode": "standard", "total_max_attempts": 2},
            ),
        )
        return KmsConfigurationCipher(client, key_id, legacy_key)
    return FernetConfigurationCipher(legacy_key) if legacy_key else None
