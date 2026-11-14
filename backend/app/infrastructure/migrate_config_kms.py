"""Run with python -m app.infrastructure.migrate_config_kms [--apply]."""

from __future__ import annotations

import argparse
import asyncio
import os

import asyncpg

from app.infrastructure.config_cipher import KmsConfigurationCipher, configured_cipher

# SQL identifiers are fixed. Never accept arbitrary tables/columns from the command line.
TABLES = (
    (
        "seerr_configuration",
        "seerr",
        "SELECT encrypted_api_key FROM seerr_configuration WHERE singleton=TRUE FOR UPDATE",
        "UPDATE seerr_configuration SET encrypted_api_key=$1 WHERE singleton=TRUE",
    ),
    (
        "karakeep_configuration",
        "karakeep",
        "SELECT encrypted_api_key FROM karakeep_configuration WHERE singleton=TRUE FOR UPDATE",
        "UPDATE karakeep_configuration SET encrypted_api_key=$1 WHERE singleton=TRUE",
    ),
    (
        "usenet_configuration",
        "usenet",
        "SELECT encrypted_settings FROM usenet_configuration WHERE singleton=TRUE FOR UPDATE",
        "UPDATE usenet_configuration SET encrypted_settings=$1 WHERE singleton=TRUE",
    ),
)


async def migrate(apply: bool) -> None:
    cipher = configured_cipher()
    if not isinstance(cipher, KmsConfigurationCipher):
        raise RuntimeError("Configura ARTEMIS_KMS_KEY_ID y AWS_REGION antes de migrar.")
    database_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(database_url)
    count = 0
    try:
        async with connection.transaction():
            for table, purpose, select, update in TABLES:
                if not await connection.fetchval("SELECT to_regclass($1)", table):
                    continue
                value = await connection.fetchval(select)
                if value is None or bytes(value).startswith(cipher.prefix):
                    continue
                count += 1
                if apply:
                    encrypted = await cipher.encrypt(
                        await cipher.decrypt(bytes(value), purpose), purpose
                    )
                    # Verify the new envelope before replacing the existing ciphertext.
                    await cipher.decrypt(encrypted, purpose)
                    await connection.execute(update, encrypted)
            if await connection.fetchval("SELECT to_regclass('channel_configuration')"):
                rows = await connection.fetch(
                    "SELECT provider, encrypted_settings FROM channel_configuration FOR UPDATE"
                )
                for row in rows:
                    value = bytes(row["encrypted_settings"])
                    if value.startswith(cipher.prefix):
                        continue
                    count += 1
                    if apply:
                        purpose = f"channel:{row['provider']}"
                        encrypted = await cipher.encrypt(
                            await cipher.decrypt(value, purpose), purpose
                        )
                        await cipher.decrypt(encrypted, purpose)
                        await connection.execute(
                            "UPDATE channel_configuration SET encrypted_settings=$1 "
                            "WHERE provider=$2",
                            encrypted,
                            row["provider"],
                        )
        print(f"Configuraciones {'migradas' if apply else 'pendientes'}: {count}")
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrar configuraciones Fernet a AWS KMS")
    parser.add_argument(
        "--apply", action="store_true", help="Aplicar; por defecto solo cuenta registros"
    )
    args = parser.parse_args()
    try:
        asyncio.run(migrate(args.apply))
    except Exception:
        raise SystemExit(
            "La migración no se completó. Revisa PostgreSQL, KMS y la clave Fernet anterior. "
            "La transacción no se confirmó."
        ) from None


if __name__ == "__main__":
    main()
