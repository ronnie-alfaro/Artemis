from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.application.orchestrator import Orchestrator
from app.domain.usenet import (
    UsenetClientError,
    UsenetConfigurationInput,
    UsenetConfigurationStatus,
    UsenetSettings,
)
from app.infrastructure.usenet_config import PostgresUsenetConfigurationStore
from app.infrastructure.usenet_http import HttpUsenetClient


def configuration_status(settings: UsenetSettings | None) -> UsenetConfigurationStatus:
    if settings is None:
        return UsenetConfigurationStatus(configured=False)
    return UsenetConfigurationStatus(
        configured=True,
        provider_url=str(settings.provider_url).rstrip("/"),
        nzbget_url=str(settings.nzbget_url),
        nzbget_username=settings.nzbget_username,
        credential_source="control plane",
    )


def install_usenet_routes(app: FastAPI, orchestrator: Orchestrator) -> None:
    def store() -> PostgresUsenetConfigurationStore:
        value: PostgresUsenetConfigurationStore | None = app.state.usenet_configuration
        if value is None:
            raise HTTPException(
                503, "La configuración cifrada no está disponible en este despliegue."
            )
        return value

    @app.get("/api/v1/skills/usenet/configuration", response_model=UsenetConfigurationStatus)
    async def get_configuration() -> UsenetConfigurationStatus:
        return configuration_status(await store().load())

    @app.put("/api/v1/skills/usenet/configuration", response_model=UsenetConfigurationStatus)
    async def put_configuration(payload: UsenetConfigurationInput) -> UsenetConfigurationStatus:
        try:
            settings = await store().save(payload)
        except ValueError as error:
            raise HTTPException(
                422, "Introduce la API key y la contraseña para configurar las conexiones."
            ) from error
        client = HttpUsenetClient(settings)
        orchestrator.usenet_agent.set_client(client)  # type: ignore[attr-defined]
        await orchestrator.approvals.flush()  # type: ignore[attr-defined]
        old_client: HttpUsenetClient | None = app.state.usenet_client
        app.state.usenet_client = client
        app.state.usenet_configured = True
        if old_client:
            await old_client.aclose()
        return configuration_status(settings)

    @app.post("/api/v1/skills/usenet/configuration/test", response_model=UsenetConfigurationStatus)
    async def test_configuration() -> UsenetConfigurationStatus:
        settings = await store().load()
        result = configuration_status(settings)
        if settings is None:
            result.last_test = "Configura las conexiones primero."
            return result
        client = HttpUsenetClient(settings)
        try:
            try:
                await client.test_provider()
                result.provider_test = "Conexión verificada"
            except UsenetClientError as error:
                result.provider_test = error.safe_message
            try:
                await client.test_downloader()
                result.downloader_test = "Conexión verificada"
            except UsenetClientError as error:
                result.downloader_test = error.safe_message
        finally:
            await client.aclose()
        result.last_test = (
            "Conexiones verificadas"
            if result.provider_test == result.downloader_test == "Conexión verificada"
            else "Revisa el resultado de cada conexión."
        )
        return result
