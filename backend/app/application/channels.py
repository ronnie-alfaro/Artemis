from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.application.whatsapp import WhatsAppAgentRuntime
from app.domain.channels import (
    ChannelConfigurationInput,
    ChannelConfigurationStatus,
    ChannelConnection,
    Provider,
)
from app.domain.whatsapp import WhatsAppChannelStatus
from app.infrastructure.channel_config import PostgresChannelConfigurationStore


class ChannelController:
    """Stable delivery target while replacing a channel's poller and credentials."""

    def __init__(
        self,
        provider: Provider,
        store: PostgresChannelConfigurationStore | None,
        environment: ChannelConnection | Callable[[], ChannelConnection | None] | None,
        factory: Callable[[ChannelConnection], WhatsAppAgentRuntime],
        validate: Callable[[ChannelConnection], Awaitable[None]] | None = None,
    ) -> None:
        self.provider, self.store, self.environment, self.factory = (
            provider,
            store,
            environment,
            factory,
        )
        self.validate = validate
        self.runtime: WhatsAppAgentRuntime | None = None
        self.connection: ChannelConnection | None = None
        self.source: str | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        saved = await self.store.load(self.provider) if self.store else None
        self.connection = saved or (
            self.environment() if callable(self.environment) else self.environment
        )
        self.source = "control plane" if saved else "environment" if self.connection else None
        if self.connection:
            self.connection.validate_for(self.provider)
        if self.connection and self.connection.enabled:
            self.runtime = self.factory(self.connection)
            await self.runtime.start()

    async def stop(self) -> None:
        if self.runtime:
            await self.runtime.stop()

    def configuration(self) -> ChannelConfigurationStatus:
        connection = self.connection
        return ChannelConfigurationStatus(
            configured=connection is not None,
            enabled=bool(connection and connection.enabled),
            editable=self.store is not None,
            credential_source=self.source,
            agent_name=connection.agent_name if connection else None,
            allowed_user_ids=connection.allowed_user_ids if connection else [],
        )

    def status(self) -> WhatsAppChannelStatus:
        return self.runtime.status() if self.runtime else WhatsAppChannelStatus(configured=False)

    async def configure(self, payload: ChannelConfigurationInput) -> ChannelConfigurationStatus:
        async with self._lock:
            if not self.store:
                raise RuntimeError("La configuración cifrada no está disponible.")
            token = payload.token
            if token is None or not token.get_secret_value():
                token = self.connection.token if self.connection else None
            if token is None:
                raise ValueError("Introduce el token para la primera configuración.")
            candidate = ChannelConnection(
                **{**payload.model_dump(exclude={"token"}), "token": token}
            )
            candidate.validate_for(self.provider)
            if candidate.enabled and self.validate:
                await self.validate(candidate)
            previous, previous_source = self.connection, self.source
            # Encryption must succeed before the working connection is interrupted.
            await self.store.save(self.provider, candidate)
            try:
                await self.stop()
                self.runtime = None
                if candidate.enabled:
                    runtime = self.factory(candidate)
                    try:
                        await runtime.start()
                    except Exception:
                        await runtime.stop()
                        raise
                    self.runtime = runtime
                self.connection, self.source = candidate, "control plane"
            except Exception:
                if previous_source == "control plane" and previous:
                    await self.store.save(self.provider, previous)
                else:
                    await self.store.delete(self.provider)
                if previous and previous.enabled:
                    self.runtime = self.factory(previous)
                    await self.runtime.start()
                raise RuntimeError("No se pudo aplicar la configuración del canal.") from None
            return self.configuration()

    async def notification_recipients(self) -> list[str]:
        return await self.runtime.notification_recipients() if self.runtime else []

    async def notification_recipient(self, preferred: str | None = None) -> str | None:
        return await self.runtime.notification_recipient(preferred) if self.runtime else None

    async def recipient_for_conversation(self, conversation_id: UUID) -> str | None:
        return (
            await self.runtime.recipient_for_conversation(conversation_id) if self.runtime else None
        )

    async def send_notification(self, recipient_id: str, content: str) -> None:
        # Keep delivery in flight from being cancelled by a configuration replacement.
        async with self._lock:
            if not self.runtime:
                raise RuntimeError("El canal está desactivado.")
            await self.runtime.send_notification(recipient_id, content)
