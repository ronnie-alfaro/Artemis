"""Prepare scoped context in the API and delegate prompt construction to Rust."""
import asyncio
import re
from datetime import UTC, datetime
from hashlib import sha256
from time import time
from typing import Any

from app.domain.context_builder import ContextInput, ContextSettings
from app.domain.whatsapp import DEFAULT_PERSONA
from app.infrastructure.memory_manager import MemoryManager

_SECRET = re.compile(
    r"(?i)\b(?:bearer\s+[\w.+=/-]{12,}|(?:api[_ -]?key|password|secret|token)\s*[:=]"
    r"\s*[^\s,\"']{8,}|(?:gh[pousr]_|github_pat_|sk-)[\w-]{16,})"
)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET.sub("[credencial omitida]", value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def propose_core(original: str, maximum: int = 150) -> str:
    # Use complete sentences when possible and preserve the first identity clause.
    limit = maximum * 3
    sentences = re.split(r"(?<=[.!?])\s+|\n+", original.strip())
    chosen: list[str] = []
    for sentence in sentences:
        if len((" ".join([*chosen, sentence])).encode()) <= limit:
            chosen.append(sentence)
    if not chosen or chosen[0] != sentences[0]:
        truncated = original.encode()[:limit].decode(errors="ignore")
        return truncated.rsplit(" ", 1)[0] or truncated
    return " ".join(chosen)


class ContextSource:
    def __init__(self, store, memory: MemoryManager):
        self.store = store
        self.memory = memory

    async def versions(self, agent_id: str) -> list[dict]:
        return await asyncio.wait_for(asyncio.to_thread(self.memory.persona_versions, agent_id), 3)

    async def save_persona(self, agent_id: str, original: str, extended: str, core: str) -> str:
        updated = datetime.now(UTC).isoformat()
        version = digest(f"{updated}\0{extended}\0{core}")
        records = [
            ("extended", digest(original), original, "original"),
            ("extended", version, extended, "editor"),
            ("core", version, core, "editor"),
        ]
        for kind, revision, text, source in records:
            await asyncio.to_thread(
                self.memory.save_persona_version, agent_id, text, {
                    "version": f"{revision}:{kind}", "revision": revision,
                    "persona_type": kind, "source": source, "status": "available",
                    "language": "es", "updated_at": updated, "source_hash": digest(text)
                    if kind == "extended" else digest(extended),
                },
            )
        return version

    async def persona(self, agent_id: str, original: str, maximum: int) -> tuple[str, str, str]:
        try:
            versions = await self.versions(agent_id)
            candidates = [item for item in versions if item["persona_type"] == "core"
                          and item["source_hash"] == digest(original)]
            if candidates:
                active = max(candidates, key=lambda item: item["updated_at"])
                extended = next(item["text"] for item in versions
                                if item["persona_type"] == "extended"
                                and item["revision"] == active["revision"]
                                and item["source_hash"] == digest(original))
                return active["text"], extended, active["revision"]
        except Exception:
            return propose_core(original, maximum), original, "channel-fallback"
        return propose_core(original, maximum), original, "channel-proposed"

    async def memories(self, row, text: str, settings: ContextSettings) -> list[str]:
        policy = settings.components["memory"]
        if (not settings.semantic_memory or not settings.max_memories or len(text.strip()) < 8
                or not policy.enabled or policy.recovery == "never"):
            return []
        try:
            matches = await asyncio.wait_for(asyncio.to_thread(
                self.memory.context_memories, row["bot"], row["channel"],
                str(row["conversation"]), text[:2000], settings.max_memories * 3,
            ), timeout=2)
        except Exception:
            return []
        scored = []
        for item in matches:
            similarity = 1 - item["distance"]
            if policy.recovery != "always" and similarity < settings.memory_threshold:
                continue
            try:
                created = datetime.fromisoformat(item["created_at"]).timestamp()
            except (ValueError, TypeError, KeyError):
                created = 0
            recency = 1 / (1 + max(0, time() - created) / 86400 / 30)
            importance = 0.05 if item.get("kind") in {"learning", "requested"} else 0
            scored.append((similarity + settings.memory_recency * recency + importance,
                           redact(item["text"][:900])))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [text for _, text in scored[:settings.max_memories]]

    async def prepare(self, row, context: dict, instructions: str,
                      settings: dict[str, ContextSettings], *, persist: bool) -> tuple:
        # Retrieve bounded candidates using the least restrictive requested settings.
        entries = list(settings.values())
        history_options = max(entries, key=lambda item: item.recent_turns)
        history, summary, summarized = await self.store.history(
            row, history_options, persist=persist,
        )
        original = context["persona"] or DEFAULT_PERSONA
        max_core = min(item.components["core"].maximum for item in entries)
        core, extended, revision = await self.persona(
            f"{row['channel']}:{row['bot']}", original, max_core,
        )
        memory_options = min(entries, key=lambda item: (
            not item.semantic_memory, item.memory_threshold, -item.max_memories,
        ))
        memories = await self.memories(row, context["message"], memory_options)
        runtime_settings = {}
        for provider, options in settings.items():
            effective = options.runtime()
            if options.adaptive_calibration:
                overhead = await self.store.calibration(row["channel"], row["bot"], provider)
                spare = options.budget - options.response_reserve - options.tool_reserve
                spare -= options.safety_margin + 512
                effective["safety_margin"] += min(overhead, max(0, spare), 3000)
            runtime_settings[provider] = effective
        inventory = ", ".join(skill["capability"] for skill in context["skills"])
        instructions += (
            "\nInventario completo de habilidades conversacionales asignadas a este bot: "
            f"{inventory or 'ninguna'}. Usa este inventario para responder qué puedes hacer. "
            "El bloque tools contiene los contratos utilizables en este turno. "
            "Una habilidad fuera de tools sigue asignada aunque su contrato no esté visible."
        )
        data = ContextInput(
            core=core, extended=extended, instructions=instructions, history=history,
            greeting=context["greeting"], message=context["message"],
            image_context=context["image_context"], summary=summary, memories=memories,
            skills=context["skills"], observations=context["observations"],
            approvals=context.get("approvals", []), actions_remaining=context["actions_remaining"],
            settings=runtime_settings,
        )
        return redact(data.model_dump()), revision, summarized
