from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.application.whatsapp_formatting import whatsapp_chunks
from app.domain.models import Channel, ChatResponse, IncomingMessage, OutgoingMessage
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
        # Agent search candidates are process-local; old menus cannot survive a restart.
        await self._state.clear_reaction_menus(self._settings.agent_name)
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

    async def notification_recipients(self) -> list[str]:
        return await self._state.participants_for(self._settings.agent_name)

    async def notification_recipient(self, preferred: str | None = None) -> str | None:
        participants = await self._state.participants_for(self._settings.agent_name)
        if preferred:
            return preferred if preferred in participants else None
        return participants[0] if len(participants) == 1 else None

    async def recipient_for_conversation(self, conversation_id: UUID) -> str | None:
        for recipient in await self.notification_recipients():
            if (
                await self._state.conversation_for(self._settings.agent_name, recipient)
                == conversation_id
            ):
                return recipient
        return None

    async def send_notification(self, recipient_id: str, content: str) -> None:
        conversation_id = await self._state.conversation_for(
            self._settings.agent_name, recipient_id
        )
        message = OutgoingMessage(
            conversation_id=conversation_id,
            execution_id=uuid4(),
            content=content,
        )
        async with self._recipient_locks[recipient_id]:
            for chunk in whatsapp_chunks(message.content):
                await self._client.send_text(
                    recipient_id, message.model_copy(update={"content": chunk})
                )

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
        content = inbound.content
        if inbound.type.value == "reaction":
            option = await self._state.claim_reaction(self._settings.agent_name, inbound)
            if option is None:
                await self._state.mark_completed(self._settings.agent_name, inbound)
                return
            content = option.command
        else:
            await self._state.clear_reaction_menus(self._settings.agent_name, inbound.sender_id)
        conversation_id = await self._state.conversation_for(
            self._settings.agent_name, inbound.sender_id
        )
        capabilities = await self.capabilities()
        greeting = await self.greeting()
        # A status call is deliberately limited to messages that Artemis will answer.
        await self._client.mark_read(inbound.id, typing=True)
        response = await self._handle(
            IncomingMessage(
                id=uuid5(NAMESPACE_URL, f"whatsapp:{self._settings.agent_name}:{inbound.id}"),
                conversation_id=conversation_id,
                channel=Channel(
                    name="whatsapp",
                    version="agent/v1",
                    allowed_capabilities=capabilities,
                    assistant_greeting=greeting,
                ),
                content=content,
            )
        )
        outgoing = response.message
        menu = ""
        content = outgoing.content
        if outgoing.reaction_options:
            missing = []
            for index, option in enumerate(outgoing.reaction_options, 1):
                numbered = f"{index}. {option.label}"
                bulleted = f"• {option.label}:"
                if numbered in content:
                    content = content.replace(numbered, f"{option.emoji} {option.label}", 1)
                elif bulleted in content:
                    content = content.replace(bulleted, f"{option.emoji} {option.label}:", 1)
                else:
                    missing.append(f"{option.emoji} {option.label[:160]}")
            menu = ("\n\n" + "\n".join(missing) if missing else "")
            menu += ("\n\nReacciona con el emoji de tu elección (usa ＋ para buscarlo). "
                     "También puedes escribir tu elección. Opciones válidas durante 15 minutos.")
        # Keep all choices together in the final message, even for long search results.
        chunks = whatsapp_chunks(content)
        if menu:
            if len(chunks) > 1:
                menu = "\n\n" + "\n".join(
                    f"{option.emoji} {option.label[:160]}"
                    for option in outgoing.reaction_options
                ) + "\n\nReacciona aquí con el emoji elegido. Opciones válidas durante 15 minutos."
            combined = chunks[-1] + menu
            if len(combined) <= 4096:
                chunks[-1] = combined
            else:
                choices = "\n".join(
                    f"{option.emoji} {option.label[:160]}"
                    for option in outgoing.reaction_options
                )
                chunks.extend(whatsapp_chunks(choices + "\n\nReacciona aquí con el emoji elegido. "
                                               "Opciones válidas durante 15 minutos."))
        async with self._recipient_locks[inbound.sender_id]:
            for chunk in chunks:
                sent_id = await self._client.send_text(
                    inbound.sender_id, outgoing.model_copy(update={"content": chunk}), inbound.id
                )
            if outgoing.reaction_options:
                await self._state.save_reaction_menu(
                    self._settings.agent_name, inbound.sender_id, sent_id, outgoing.reaction_options
                )
        await self._state.mark_completed(self._settings.agent_name, inbound)

    async def _run(self) -> None:
        delay = 1.0
        while not self._stopping.is_set():
            try:
                await self.run_once()
                self._last_error = None
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                self._last_error = "La conexión con WhatsApp falló; se reintentará automáticamente"
                logger.exception("WhatsApp polling failed for configured agent")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
