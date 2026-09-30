from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from app.domain.models import Channel, ChatResponse, IncomingMessage
from app.domain.whatsapp import WhatsAppChannelStatus, WhatsAppInbound, WhatsAppSettings
from app.domain.whatsapp_ports import WhatsAppClient, WhatsAppStateStore

logger = logging.getLogger(__name__)

HandleMessage = Callable[[IncomingMessage], Awaitable[ChatResponse]]


class WhatsAppAgentRuntime:
    """Owns a single long-poll lease and bridges provider traffic to Artemis."""

    def __init__(
        self,
        settings: WhatsAppSettings,
        client: WhatsAppClient,
        state: WhatsAppStateStore,
        handle: HandleMessage,
    ) -> None:
        self._settings, self._client, self._state, self._handle = settings, client, state, handle
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._recipient_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_error: str | None = None

    async def start(self) -> None:
        if self._task:
            return
        await self._state.start()
        self._stopping.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"whatsapp-poller-{self._settings.agent_name}"
        )

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._client.aclose()
        await self._state.aclose()

    def status(self) -> WhatsAppChannelStatus:
        return WhatsAppChannelStatus(
            configured=True,
            agent_name=self._settings.agent_name,
            running=self._task is not None and not self._task.done(),
            last_error=self._last_error,
        )

    async def capabilities(self) -> list[str]:
        return await self._state.capabilities_for(self._settings.agent_name)

    async def set_capabilities(self, capabilities: list[str]) -> None:
        await self._state.set_capabilities(self._settings.agent_name, capabilities)

    async def greeting(self) -> str:
        return await self._state.greeting_for(self._settings.agent_name)

    async def set_greeting(self, greeting: str) -> None:
        await self._state.set_greeting(self._settings.agent_name, greeting)

    async def run_once(self) -> None:
        await self._drain_pending()
        offset = await self._state.get_offset(self._settings.agent_name)
        batch = await self._client.updates(offset, self._settings.poll_timeout_seconds)
        if batch is None:
            return
        for inbound in batch.messages:
            await self._state.enqueue(self._settings.agent_name, inbound)
        # Persist the provider cursor only after its events are safely in the inbox.
        await self._state.set_offset(self._settings.agent_name, batch.next_offset)
        await self._drain_pending()

    async def _drain_pending(self) -> None:
        for inbound in await self._state.pending(self._settings.agent_name):
            await self._process(inbound)

    async def _process(self, inbound: WhatsAppInbound) -> None:
        if await self._state.completed(self._settings.agent_name, inbound.id):
            return
        if inbound.type.value == "reaction":
            await self._state.mark_completed(self._settings.agent_name, inbound)
            return
        conversation_id = await self._state.conversation_for(
            self._settings.agent_name, inbound.sender_id
        )
        capabilities = await self.capabilities()
        greeting = await self.greeting()
        # A status call is deliberately limited to messages that Artemis will answer.
        await self._client.mark_read(inbound.id, typing=True)
        response = await self._handle(
            IncomingMessage(
                conversation_id=conversation_id,
                channel=Channel(
                    name="whatsapp",
                    version="agent/v1",
                    allowed_capabilities=capabilities,
                    assistant_greeting=greeting,
                ),
                content=inbound.content,
            )
        )
        outgoing = response.message
        async with self._recipient_locks[inbound.sender_id]:
            await self._client.send_text(inbound.sender_id, outgoing, inbound.id)
        await self._state.mark_completed(self._settings.agent_name, inbound)

    async def _run(self) -> None:
        delay = 1.0
        while not self._stopping.is_set():
            try:
                await self.run_once()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                self._last_error = "WhatsApp polling failed; retrying with backoff"
                logger.exception("WhatsApp polling failed for configured agent")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
