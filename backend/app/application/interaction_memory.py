"""Durable queue for selected first-person memories."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.domain.models import ChatResponse, IncomingMessage
from app.infrastructure.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

_SAVE = re.compile(
    r"^(?:artemis[, ]+)?/?(?:recuerda|memoriza|guarda en (?:tu )?memoria|"
    r"guarda esto en (?:tu )?memoria|quiero que recuerdes)\s*(?:[:—]\s*|\s+)(.+)$",
    re.I | re.S,
)
_PRAISE = re.compile(
    r"(?:artemis[, ]+)?(?:muy buen trabajo|buen trabajo|bien hecho)(?:[, ]+artemis)?[.!¡ ]*",
    re.I,
)
_MILESTONE = re.compile(
    r"(?:artemis[, ]+)?(?:aprendiste a (.+)|ahora (?:tienes|cuentas con) (.+))",
    re.I,
)


class InteractionMemory:
    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory
        self.directory = Path(memory.path) / "pending-selected-memories"
        self.task: asyncio.Task[None] | None = None

    @staticmethod
    def is_explicit(message: IncomingMessage) -> bool:
        return not (message.required_capabilities or message.ephemeral_image_context) and bool(
            _SAVE.fullmatch(message.content.strip())
        )

    def enqueue(self, message: IncomingMessage, response: ChatResponse | None = None) -> bool:
        if message.required_capabilities or message.ephemeral_image_context:
            return False
        content = message.content.strip()
        explicit = _SAVE.fullmatch(content)
        learned = _MILESTONE.fullmatch(content)
        executions = response.executions if response else []
        integration = next(
            (item.result.metadata["learned_integration"] for item in executions
             if item.result and "learned_integration" in item.result.metadata),
            None,
        )
        if explicit:
            detail = re.sub(r"^que\s+", "", explicit[1].strip(), flags=re.I).strip()
            if not detail:
                return False
            kind, note = "requested", f"Quiero recordar lo que me dijo el usuario: «{detail}»"
        elif _PRAISE.fullmatch(content):
            kind, note = "feedback", "El usuario me felicitó por mi trabajo."
        elif integration:
            kind = "learning"
            note = f"Aprendí a consultar la integración {integration} con Curiosidad."
        elif learned:
            kind = "learning"
            note = f"Aprendí a {learned[1]}" if learned[1] else f"Ahora cuento con {learned[2]}"
        else:
            return False
        event_id = str(uuid5(NAMESPACE_URL,
                            f"{message.channel.name}:{message.conversation_id}:{message.id}"))
        payload = {
            "agent": message.channel.agent_name or "primary", "event_id": event_id,
            "text": note[:16000],
            "metadata": {"created_at": message.received_at.isoformat(), "kind": kind},
        }
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.directory / f"{event_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False))
        temporary.chmod(0o600)
        temporary.replace(target)
        return explicit is not None

    def flush(self) -> None:
        for path in sorted(self.directory.glob("*.json"))[:100]:
            try:
                self.memory.remember_event(**json.loads(path.read_text()))
                path.unlink()
            except Exception:
                logger.warning("Recuerdo pendiente; se reintentará sin registrar su contenido")

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="selected-memory")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        while True:
            await asyncio.to_thread(self.flush)
            await asyncio.sleep(5)
