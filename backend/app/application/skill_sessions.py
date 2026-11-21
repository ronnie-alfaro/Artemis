from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.agents.tmdb import natural_query
from app.application.approvals import ApprovalStore
from app.application.github_sync import is_sync_command
from app.application.iteration import is_iteration_command
from app.domain.curiosity import CAPABILITY as CURIOSITY_CAPABILITY
from app.domain.curiosity import CHAT_CONTEXT_KEY, chat_command
from app.domain.models import IncomingMessage, ReactionOption
from app.domain.skills import (
    MEMORY_CAPABILITY,
    TERRAQUAKE_CAPABILITY,
    TMDB_CAPABILITY,
    SkillPresentation,
    help_target,
)

SKILL_CAPABILITIES = {
    "memory": MEMORY_CAPABILITY,
    "curiosity": CURIOSITY_CAPABILITY,
    "github": "github.repositories",
    "terraquake": TERRAQUAKE_CAPABILITY,
    "antigravity": "antigravity.assistant",
    "codex": "codex.assistant",
    "usenet": "usenet.downloads",
    "karakeep": "karakeep.bookmarks",
    "seerr": "seerr.media",
    "tmdb": TMDB_CAPABILITY,
}
_SWITCH = re.compile(r"^/?(?:utiliza|usar|usa)\s+(.+)$", re.IGNORECASE)
_SEARCH = re.compile(r"^(?:quiero\s+)?(?:busca(?:r|me)?|búscame|search)\s+", re.IGNORECASE)


class SkillSessionStore(Protocol):
    async def get(self, channel: str, conversation_id: UUID) -> str | None: ...

    async def set(self, channel: str, conversation_id: UUID, skill: str | None) -> None: ...


class MemorySkillSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, UUID], str] = {}

    async def get(self, channel: str, conversation_id: UUID) -> str | None:
        return self._sessions.get((channel, conversation_id))

    async def set(self, channel: str, conversation_id: UUID, skill: str | None) -> None:
        key = (channel, conversation_id)
        if skill is None:
            self._sessions.pop(key, None)
        else:
            self._sessions[key] = skill


@dataclass
class SkillSessionRouter:
    presentations: dict[str, SkillPresentation]
    approvals: ApprovalStore
    reset_conversation: Callable[[UUID], None]
    store: SkillSessionStore = field(default_factory=MemorySkillSessionStore)
    bridge_commands: Callable[[], Awaitable[bool]] | None = None

    def _available(self, message: IncomingMessage) -> dict[str, str]:
        allowed = message.channel.allowed_capabilities
        return {skill: capability for skill, capability in SKILL_CAPABILITIES.items()
                if capability in allowed or (not allowed and capability != CURIOSITY_CAPABILITY)}

    @staticmethod
    def _status(
        message: IncomingMessage, content: str, options: list[ReactionOption] | None = None,
    ) -> tuple[IncomingMessage, dict[str, str]]:
        return message.model_copy(update={
            "required_capabilities": ["assistant.status"],
        }), {"status_message": content,
             "status_reaction_options": json.dumps([o.model_dump() for o in options or []])}

    async def _leave(self, message: IncomingMessage) -> int:
        pending = self.approvals.pending_for_conversation(message.conversation_id)
        for approval in pending:
            self.approvals.reject(approval.id)
        await self.approvals.flush()
        self.reset_conversation(message.conversation_id)
        await self.store.set(message.channel.name, message.conversation_id, None)
        return len(pending)

    async def route(self, message: IncomingMessage) -> tuple[IncomingMessage, dict[str, str]]:
        # The bridge/API has already selected a capability. Its command is payload for
        # that agent, even when it starts with session words such as "utiliza".
        if message.required_capabilities:
            return message, {}
        if chat_command(message.content) is not None:
            if (message.channel.name not in {"whatsapp", "telegram"}
                    or CURIOSITY_CAPABILITY not in message.channel.allowed_capabilities):
                return self._status(message, "Curiosidad no está asignada a esta conversación.")
            return message.model_copy(update={
                "required_capabilities": [CURIOSITY_CAPABILITY],
            }), {CHAT_CONTEXT_KEY: "true"}
        available = self._available(message)
        if is_iteration_command(message.content) or is_sync_command(message.content):
            if "codex" not in available:
                return self._status(message, "Codex no está asignado a esta conversación.")
            # This global command keeps the active skill and its pending operations intact.
            return message.model_copy(update={"required_capabilities": ["codex.assistant"]}), {}
        if (message.channel.natural_conversation and self.bridge_commands
                and await self.bridge_commands()):
            text = message.content.strip()
            command = text.casefold().strip("¿?¡!., ")
            active = await self.store.get(message.channel.name, message.conversation_id)
            if (active or _SWITCH.fullmatch(text) or help_target(text) is not None
                    or command in {"ayuda", "help", "salir", "estado"} or text.startswith("/")):
                message = message.model_copy(update={
                    "channel": message.channel.model_copy(update={"natural_conversation": False}),
                    "content": text.removeprefix("/"),
                })
        if message.channel.natural_conversation:
            return message.model_copy(update={
                "required_capabilities": ["assistant.conversation"],
            }), {}
        active = await self.store.get(message.channel.name, message.conversation_id)
        revoked = active is not None and active not in available
        if revoked:
            await self._leave(message)
            active = None
        text = message.content.strip()
        switch = _SWITCH.fullmatch(text)
        if switch:
            target = switch.group(1).strip().casefold()
            skill = next((key for key in available if target in {
                key, available[key], self.presentations[key].name.casefold(),
            }), None)
            if skill is None:
                names = ", ".join(self.presentations[key].name for key in available)
                return self._status(message, "Esa habilidad no está disponible. " + (
                    f"Puedes utilizar: {names}." if names else "No tienes habilidades asignadas."
                ))
            cancelled = 0
            if skill != active:
                cancelled = await self._leave(message)
                await self.store.set(message.channel.name, message.conversation_id, skill)
            name = self.presentations[skill].name
            content = f"{name} activo. Todos tus comandos se enviarán a esta habilidad."
            content += (
                "\nEscribe ‘ayuda’ para ver sus comandos o ‘salir’ para volver al modo general."
            )
            if cancelled:
                content += f"\nSe cancelaron {cancelled} confirmaciones pendientes."
            return self._status(message, content)
        if text.casefold() in {"salir", "/salir"}:
            cancelled = await self._leave(message)
            content = "Modo general activo. Escribe ‘utiliza HABILIDAD’ para elegir uno o ‘ayuda’."
            if cancelled:
                content += f"\nSe cancelaron {cancelled} confirmaciones pendientes."
            return self._status(message, content)
        if revoked:
            return self._status(message, "La habilidad activa ya no está asignada. "
                                "Volviste al modo general. Escribe ‘ayuda’.")
        normalized = text.casefold().strip("¿?¡!., ")
        if active and normalized in {"ayuda", "/ayuda", "help", "/help"}:
            return message.model_copy(update={"content": f"ayuda {active}"}), {
                "status_footer": "Habilidad activa. Escribe ‘salir’ para volver al modo general.",
            }
        if help_target(text) is not None or normalized in {
            "ayuda", "/ayuda", "help", "/help", "qué puedes hacer", "que puedes hacer",
        }:
            return message, {}
        if active == "tmdb" and "seerr" in available:
            seerr_command = normalized.startswith("seerr api ")
            seerr_confirmation = normalized in {"confirmo", "confirmar", "cancelar"}
            if seerr_command or (seerr_confirmation and self.approvals.pending_for_conversation(
                message.conversation_id, agent_name="seerr",
            )):
                return message.model_copy(update={
                    "required_capabilities": [available["seerr"]],
                }), {}
        if active:
            return message.model_copy(update={"required_capabilities": [available[active]]}), {}
        if ("tmdb" in available and _SEARCH.match(text) and len(text) <= 200
                and natural_query(text) is not None
                and not re.search(r"\b(?:karakeep|seerr|marcadores|enlaces)\b", text, re.I)):
            return message, {}
        if _SEARCH.match(text) and len(available) > 1 and not re.search(
            r"\ben\s+(?:karakeep|(?:mis\s+)?(?:bookmarks|marcadores)|(?:mis\s+)?enlaces)\b",
            text, re.IGNORECASE
        ):
            names = ", ".join(self.presentations[key].name for key in available)
            return self._status(message, f"¿En qué habilidad quieres buscar? Disponibles: {names}. "
                                "Escribe ‘utiliza HABILIDAD’ y después repite la búsqueda.",
                                [ReactionOption(emoji=f"{i}️⃣",
                                                label=self.presentations[key].name,
                                                command=f"utiliza {key}")
                                 for i, key in enumerate(available, 1)])
        return message, {}
