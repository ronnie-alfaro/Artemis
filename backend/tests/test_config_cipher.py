import asyncio
import base64
import json
import os
import traceback

import pytest
from cryptography.fernet import Fernet

from app.infrastructure.config_cipher import (
    ConfigurationEncryptionError,
    KmsConfigurationCipher,
    configured_cipher,
)


class Kms:
    def __init__(self):
        self.keys = {}
        self.calls = []
        self.fail = False

    def generate_data_key(self, **kwargs):
        self.calls.append(("generate", kwargs))
        if self.fail:
            raise RuntimeError("sensitive-provider-detail")
        key, blob = os.urandom(32), os.urandom(64)
        self.keys[blob] = (key, kwargs["EncryptionContext"])
        return {"Plaintext": key, "CiphertextBlob": blob}

    def decrypt(self, **kwargs):
        self.calls.append(("decrypt", kwargs))
        if self.fail:
            raise RuntimeError("sensitive-provider-detail")
        key, context = self.keys[kwargs["CiphertextBlob"]]
        if kwargs["EncryptionContext"] != context:
            raise RuntimeError("context mismatch")
        return {"Plaintext": key}


def test_kms_envelope_and_binding_to_integration():
    async def run():
        kms = Kms()
        cipher = KmsConfigurationCipher(kms, "key-id")
        secret = b"telegram-token-sensitive"
        encrypted = await cipher.encrypt(secret, "channel:telegram")
        assert secret not in encrypted
        assert encrypted.startswith(cipher.prefix)
        envelope = json.loads(encrypted[len(cipher.prefix) :])
        assert len(base64.b64decode(envelope["nonce"])) == 12
        assert await cipher.decrypt(encrypted, "channel:telegram") == secret
        assert kms.calls[0][1]["KeySpec"] == "AES_256"
        assert kms.calls[0][1]["KeyId"] == "key-id"
        with pytest.raises(ConfigurationEncryptionError):
            await cipher.decrypt(encrypted, "channel:whatsapp")
        # Even if a wrapped key is substituted, authenticated local ciphertext rejects it.
        other = await cipher.encrypt(secret, "channel:telegram")
        envelope["key"] = json.loads(other[len(cipher.prefix) :])["key"]
        with pytest.raises(ConfigurationEncryptionError):
            await cipher.decrypt(cipher.prefix + json.dumps(envelope).encode(), "channel:telegram")

    asyncio.run(run())


def test_legacy_read_but_all_new_writes_use_kms_and_errors_do_not_leak():
    async def run():
        legacy_key = Fernet.generate_key()
        legacy = Fernet(legacy_key).encrypt(b"old-secret")
        kms = Kms()
        cipher = KmsConfigurationCipher(kms, "key-id", legacy_key.decode())
        assert await cipher.decrypt(legacy, "seerr") == b"old-secret"
        assert kms.calls == []
        with pytest.raises(ConfigurationEncryptionError):
            await KmsConfigurationCipher(kms, "key-id").decrypt(legacy, "seerr")
        kms.fail = True
        with pytest.raises(ConfigurationEncryptionError) as error:
            await cipher.encrypt(b"old-secret", "seerr")
        rendered = "".join(traceback.format_exception(error.value))
        assert "sensitive-provider-detail" not in rendered
        assert "old-secret" not in str(error.value)

    asyncio.run(run())


def test_no_aws_initialization_without_kms_and_region_is_required(monkeypatch):
    monkeypatch.delenv("ARTEMIS_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("ARTEMIS_CONFIG_ENCRYPTION_KEY", raising=False)
    assert configured_cipher() is None
    monkeypatch.setenv("ARTEMIS_KMS_KEY_ID", "alias/artemis")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(RuntimeError, match="AWS_REGION"):
        configured_cipher()


def test_real_aws_sdk_contract_with_stubbed_responses():
    import boto3
    from botocore.stub import Stubber

    client = boto3.client(
        "kms", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing"
    )
    context = {"application": "artemis", "purpose": "seerr"}
    key, wrapped = os.urandom(32), b"stubbed-wrapped-key"
    with Stubber(client) as stub:
        stub.add_response(
            "generate_data_key",
            {"Plaintext": key, "CiphertextBlob": wrapped},
            {
                "KeyId": "alias/artemis",
                "KeySpec": "AES_256",
                "EncryptionContext": context,
            },
        )
        stub.add_response(
            "decrypt",
            {"Plaintext": key},
            {
                "KeyId": "alias/artemis",
                "CiphertextBlob": wrapped,
                "EncryptionContext": context,
            },
        )

        async def run():
            cipher = KmsConfigurationCipher(client, "alias/artemis")
            encrypted = await cipher.encrypt(b"private", "seerr")
            assert await cipher.decrypt(encrypted, "seerr") == b"private"

        asyncio.run(run())
        stub.assert_no_pending_responses()
