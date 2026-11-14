"""Verify the configured KMS identity without reading or writing application data."""
from __future__ import annotations

import asyncio
import os

from app.infrastructure.config_cipher import KmsConfigurationCipher, configured_cipher


async def check() -> None:
    cipher = configured_cipher()
    if not isinstance(cipher, KmsConfigurationCipher):
        raise RuntimeError("KMS is not configured")
    probe = os.urandom(32)
    envelope = await cipher.encrypt(probe, "configuration-check")
    result = await cipher.decrypt(envelope, "configuration-check")
    if result != probe:
        raise RuntimeError("KMS round trip failed")


def main() -> None:
    try:
        asyncio.run(check())
    except Exception:
        raise SystemExit(
            "No se pudo verificar KMS. Revisa región, ARN y credenciales/permisos del servidor."
        ) from None
    print("KMS verificado: cifrado y descifrado correctos; no se modificaron datos.")


if __name__ == "__main__":
    main()
