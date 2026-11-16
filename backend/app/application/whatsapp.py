from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.application.image_ingestion import ImageIngestion, ImageUnavailable
from app.application.whatsapp_formatting import whatsapp_chunks
from app.domain.models import (
    Channel,
    ChatResponse,
    ExecutionPlan,
    IncomingMessage,
    OutgoingMessage,
)
from app.domain.whatsapp import (
    WhatsAppChannelStatus,
    WhatsAppInbound,
    WhatsAppMessageType,
    WhatsAppSettings,
)
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
        *,
        channel_name: str = "whatsapp",
        images: ImageIngestion | None = None,
        allowed_recipient_ids: frozenset[str] | None = None,
    ) -> None:
        self._settings, self._client, self._state, self._handle = settings, client, state, handle
        self.images = images
        self._allowed_recipient_ids = allowed_recipient_ids
        self._channel_name = channel_name
        self._agent_key = (settings.agent_name if channel_name == "whatsapp"
                           else f"{channel_name}:{settings.agent_name}")
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._recipient_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_error: str | None = None

    async def start(self) -> None:
        if self._task:
            return
        await self._state.start()
        # Agent search candidates are process-local; old menus cannot survive a restart.
        await self._state.clear_reaction_menus(self._agent_key)
        self._stopping.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"{self._channel_name}-poller-{self._agent_key}"
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
        return await self._state.capabilities_for(self._agent_key)

    async def set_capabilities(self, capabilities: list[str]) -> None:
        await self._state.set_capabilities(self._agent_key, capabilities)

    async def persona(self) -> str:
        return await self._state.persona_for(self._agent_key)

    async def set_persona(self, persona: str) -> None:
        await self._state.set_persona(self._agent_key, persona)

    async def greeting(self) -> str:
        greeting = await self._state.greeting_for(self._agent_key)
        if self._channel_name == "telegram" and greeting == "Hola, soy tu asistente de WhatsApp.":
            return "Hola, soy tu asistente de Telegram."
        return greeting

    async def set_greeting(self, greeting: str) -> None:
        await self._state.set_greeting(self._agent_key, greeting)

    async def notification_recipients(self) -> list[str]:
        participants = await self._state.participants_for(self._agent_key)
        return [value for value in participants
                if self._allowed_recipient_ids is None or value in self._allowed_recipient_ids]

    async def notification_recipient(self, preferred: str | None = None) -> str | None:
        participants = await self.notification_recipients()
        if preferred:
            return preferred if preferred in participants else None
        return participants[0] if len(participants) == 1 else None

    async def recipient_for_conversation(self, conversation_id: UUID) -> str | None:
        for recipient in await self.notification_recipients():
            if (
                await self._state.conversation_for(self._agent_key, recipient)
                == conversation_id
            ):
                return recipient
        return None

    async def send_notification(self, recipient_id: str, content: str) -> None:
        conversation_id = await self._state.conversation_for(
            self._agent_key, recipient_id
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
        purge = getattr(self._state, "purge_expired_images", None)
        if purge:
            await purge()
        await self._drain_pending()
        offset = await self._state.get_offset(self._agent_key)
        batch = await self._client.updates(offset, self._settings.poll_timeout_seconds)
        if batch is None:
            return
        for inbound in batch.messages:
            await self._state.enqueue(self._agent_key, inbound)
        # Persist the provider cursor only after its events are safely in the inbox.
        await self._state.set_offset(self._agent_key, batch.next_offset)
        await self._drain_pending()

    async def _drain_pending(self) -> None:
        for inbound in await self._state.pending(self._agent_key):
            await self._process(inbound)

    async def _process(self, inbound: WhatsAppInbound) -> None:
        if (self._allowed_recipient_ids is not None
                and inbound.sender_id not in self._allowed_recipient_ids):
            await self._state.mark_completed(self._agent_key, inbound)
            return
        if await self._state.completed(self._agent_key, inbound.id):
            return
        content = inbound.content
        if inbound.type.value == "reaction":
            option = await self._state.claim_reaction(self._agent_key, inbound)
            if option is None:
                await self._state.mark_completed(self._agent_key, inbound)
                return
            content = option.command
        else:
            await self._state.clear_reaction_menus(self._agent_key, inbound.sender_id)
        conversation_id = await self._state.conversation_for(
            self._agent_key, inbound.sender_id
        )
        capabilities = await self.capabilities()
        greeting = await self.greeting()
        # A status call is deliberately limited to messages that Artemis will answer.
        await self._client.mark_read(inbound.id, typing=True)
        records = []
        passive_answer = None
        scope = f"{self._channel_name}:{self._agent_key}:{conversation_id}"
        agent = self._settings.agent_name
        if inbound.type == WhatsAppMessageType.IMAGE:
            instruction = (inbound.text or (inbound.attachments[0].caption
                           if inbound.attachments else "") or "").strip()
            try:
                if not self.images or not inbound.attachments:
                    raise ImageUnavailable("No tengo disponible el análisis de imágenes.")
                try:
                    created = float(inbound.timestamp)
                    if not math.isfinite(created) or created <= 0:
                        raise ValueError("Invalid provider timestamp")
                    created = min(created, time.time())
                except ValueError:
                    created = time.time()
                for index, attachment in enumerate(inbound.attachments):
                    records.append(await self.images.ingest(
                        self._client, attachment, scope=scope, agent=agent,
                        event_id=f"{inbound.id}:{index}", created_at=created,
                    ))
                if not instruction:
                    passive_answer = "\n\n".join(
                        f"Imagen `{r['id']}` (disponible 7 días).\n{r['description']}"
                        for r in records
                    )
                else:
                    content = instruction
            except ValueError as error:
                passive_answer = (str(error) if isinstance(error, ImageUnavailable)
                                  else "No pude obtener la imagen. No ejecuté acciones.")
        elif self.images:
            records = await self.images.references(content, scope, agent)
            if not records and re.search(r"img-[a-f0-9]{24}", content, re.I):
                passive_answer = "No encuentro esa imagen aquí o ya caducó. Reenvíamela."
        if len(records) > 1 and inbound.type != WhatsAppMessageType.IMAGE:
            passive_answer = "Encontré varias imágenes. ¿Cuál quieres usar? " + ", ".join(
                r["id"] for r in records)
        if passive_answer is not None:
            # Hard boundary: no planner, session, skill, queue or approval is invoked.
            response = ChatResponse(
                message=OutgoingMessage(conversation_id=conversation_id,
                                        execution_id=uuid4(), content=passive_answer),
                plan=ExecutionPlan(conversation_id=conversation_id, nodes=[]), executions=[],
            )
        else:
            response = await self._handle(
                IncomingMessage(
                    id=uuid5(NAMESPACE_URL, f"{self._channel_name}:{self._agent_key}:{inbound.id}"),
                    conversation_id=conversation_id,
                    channel=Channel(
                        name=self._channel_name, version="agent/v1",
                        allowed_capabilities=capabilities, assistant_greeting=greeting,
                        assistant_persona=await self.persona(), natural_conversation=True,
                        agent_name=agent,
                    ),
                    content=content, ephemeral_image_context=bool(records),
                    image_context=ImageIngestion.context(records),
                )
            )
        outgoing = response.message
        if outgoing.deferred:
            await self._state.mark_completed(self._agent_key, inbound)
            return
        if self._channel_name == "telegram":
            outgoing = outgoing.model_copy(update={"reaction_options": []})
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
                    self._agent_key, inbound.sender_id, sent_id, outgoing.reaction_options
                )
        await self._state.mark_completed(self._agent_key, inbound)

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
                self._last_error = (
                    f"La conexión con {self._channel_name} falló; se reintentará automáticamente"
                )
                logger.error("Channel polling failed for configured agent: %s", self._channel_name)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
