"""Natural AGY conversation and a server-side bridge to assigned Artemis capabilities."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.application.antigravity import AntigravityQueue
from app.application.approvals import ApprovalStore
from app.application.registry import AgentRegistry
from app.domain.curiosity import CAPABILITY as CURIOSITY_CAPABILITY
from app.domain.curiosity import catalog_has_query
from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    Channel,
    ChatResponse,
    IncomingMessage,
)
from app.domain.whatsapp import DEFAULT_PERSONA
from app.infrastructure.conversation_bridge import BridgeStore

logger = logging.getLogger(__name__)


class ConversationAgent:
    definition = Agent(
        name="conversation",
        version="0.1.0",
        purpose="Conversación natural con Codex y PERSONA del bot.",
        capabilities=[
            AgentCapability(
                name="assistant.conversation",
                description="Conversa y utiliza las habilidades asignadas",
            )
        ],
    )

    def __init__(
        self,
        queue: AntigravityQueue,
        registry: AgentRegistry,
        approvals: ApprovalStore,
    ) -> None:
        self.queue, self.registry, self.approvals = queue, registry, approvals
        self.learned_queries: Callable[[str, UUID], Awaitable[list[str]]] | None = None
        self.bridge_store: BridgeStore | None = None
        self.bridge_enabled: Callable[[], Awaitable[bool]] | None = None

    def catalog(self, allowed: list[str]) -> list[dict[str, str]]:
        return [
            {
                "capability": capability.name,
                "description": capability.description,
                "help": capability.help_text or "",
            }
            for agent in self.registry.list_agents()
            for capability in agent.capabilities
            if capability.name in allowed and not capability.name.startswith("assistant.")
        ]

    async def catalog_for(
        self, message: IncomingMessage, allowed: list[str]
    ) -> list[dict[str, str]]:
        skills = self.catalog([name for name in allowed if name != CURIOSITY_CAPABILITY])
        if CURIOSITY_CAPABILITY in allowed and self.learned_queries:
            queries = await self.learned_queries(message.channel.name, message.conversation_id)
            if queries:
                skills.append({
                    "capability": CURIOSITY_CAPABILITY,
                    "description": "Consulta las APIs aprendidas en este chat. "
                                   "Escoge un comando exacto si coincide con la petición.",
                    "help": "\n".join(queries),
                })
        return skills

    async def run(self, request: AgentRequest) -> AgentResponse:
        message = request.message
        try:
            if (self.bridge_store and self.bridge_enabled and message.channel.agent_name
                    and await self.bridge_enabled()):
                await self.bridge_store.enqueue(
                    message.id, message.channel.name, message.channel.agent_name,
                    message.conversation_id, {
                        "text": message.content,
                        "image_context": message.image_context,
                        "persona": message.channel.assistant_persona or DEFAULT_PERSONA,
                        "greeting": message.channel.assistant_greeting or "",
                        "skills": await self.catalog_for(message, [
                            c for c in message.channel.allowed_capabilities
                            if c not in {"codex.assistant", "antigravity.assistant"}
                        ]),
                        "approval_ids": [
                            str(item.id) for item in
                            self.approvals.pending_for_conversation(message.conversation_id)
                        ],
                    },
                )
                return AgentResponse(result=AgentResult(
                    agent_name="conversation", content="",
                    metadata={"execution_id": str(request.execution_id), "deferred": "true"},
                ))
            self.queue.submit(
                message.id,
                message.conversation_id,
                message.channel.name,
                (message.content + "\n\n" + message.image_context)
                if message.image_context else message.content,
                "assistant",
                persona=message.channel.assistant_persona or DEFAULT_PERSONA,
                agent_name=message.channel.agent_name,
                skills=await self.catalog_for(message, message.channel.allowed_capabilities),
                greeting=message.channel.assistant_greeting or "",
                approval_ids=[
                    str(approval.id)
                    for approval in self.approvals.pending_for_conversation(message.conversation_id)
                ],
            )
            content, deferred = "", "true"
        except ValueError:
            content = "No puedo conversar ahora mismo. Inténtalo de nuevo en un momento."
            deferred = "false"
        return AgentResponse(
            result=AgentResult(
                agent_name="conversation",
                content=content,
                metadata={"execution_id": str(request.execution_id), "deferred": deferred},
            )
        )


# Confirmation remains a user decision, never something the language model grants itself.
_CONFIRM = re.compile(
    r"^(?:sí|si|yes|confirmo|confirmar|confirmar solicitud|dale|adelante|hazlo|hágalo|hagalo|"
    r"procede|acepto|aprobado|confirmado|ok|okay|de acuerdo)"
    r"(?:[, ]+(?:por favor|gracias|dale|hazlo|adelante|confirmo|procede))*[.! ]*$",
    re.I,
)
_COMMAND_CONFIRM = re.compile(r"^(?:confirmo|confirmar|confirm|sí|si|yes|aprobar)\b", re.I)


class ConversationSkillWorker:
    def __init__(
        self,
        queue: AntigravityQueue,
        channel_for: Callable[[str], Any],
        handle: Callable[[IncomingMessage], Awaitable[ChatResponse]],
        approvals: ApprovalStore,
    ) -> None:
        self.queue, self.channel_for, self.handle = queue, channel_for, handle
        self.approvals = approvals
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="agy-assigned-skills")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> None:
        for job in reversed(self.queue.recent(1000)):
            if job.mode != "assistant" or job.status != "waiting_skill":
                continue
            controller = self.channel_for(job.channel)
            runtime = controller.runtime if controller else None
            if (
                runtime is None
                or runtime.status().agent_name != job.agent_name
                or await runtime.recipient_for_conversation(job.conversation_id) is None
            ):
                job.status, job.answer = (
                    "failed",
                    "La conversación o su bot ya no están disponibles.",
                )
                self.queue.save(job)
                continue
            allowed = await runtime.capabilities()
            capability = job.decision.get("capability", "")
            command = job.decision.get("command", "").strip()
            if capability not in allowed or capability not in {
                skill["capability"] for skill in job.skills
            }:
                result = "Esa habilidad ya no está asignada al bot. No se ejecutó ninguna acción."
            elif len(job.observations) >= 4:
                result = (
                    "Se alcanzó el límite de acciones de esta petición. Pide al usuario concretar."
                )
            elif not command or len(command) > 20000:
                result = "La habilidad necesita una petición válida. Pide al usuario más detalles."
            elif capability == CURIOSITY_CAPABILITY and not catalog_has_query(job.skills, command):
                result = "Esa consulta no estaba disponible al recibir el mensaje."
            elif _COMMAND_CONFIRM.match(command) and not (
                _CONFIRM.fullmatch(job.prompt.strip())
                and any(
                    str(approval.id) in job.approval_ids
                    for approval in self.approvals.pending_for_conversation(
                        job.conversation_id,
                        agent_name=capability.split(".")[0],
                    )
                )
            ):
                result = "La operación requiere confirmación del usuario. Pídesela sin ejecutarla."
            else:
                response = await self.handle(
                    IncomingMessage(
                        id=uuid5(NAMESPACE_URL, f"{job.id}:skill:{len(job.observations)}"),
                        conversation_id=job.conversation_id,
                        channel=Channel(name=job.channel, allowed_capabilities=allowed),
                        content=command,
                        image_context=("[Imagen temporal " + job.prompt.split(
                            "[Imagen temporal ", 1)[1]
                            if "[Imagen temporal " in job.prompt else ""),
                        ephemeral_image_context="[Imagen temporal " in job.prompt,
                        required_capabilities=[capability],
                    )
                )
                result = response.message.content
            if capability == CURIOSITY_CAPABILITY:
                job.decision = {}
                job.answer = result
                job.status = "completed"
                self.queue.save(job)
                continue
            job.observations.append(
                {"capability": capability, "command": command, "result": result[:12000]}
            )
            job.decision = {}
            job.status = "queued"
            self.queue.save(job)

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Requests remain in the durable queue for retry; do not log conversation contents.
                logger.warning("AGY skill bridge failed; queued requests will be retried")
            await asyncio.sleep(1)
