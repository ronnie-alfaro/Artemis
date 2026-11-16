"""Durable automatic interaction recording; embeddings never block message delivery."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.application.antigravity import AntigravityQueue
from app.application.codex import CodexQueue
from app.domain.models import ChatResponse, IncomingMessage
from app.infrastructure.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class InteractionMemory:
    def __init__(self, memory: MemoryManager,
                 queues: tuple[CodexQueue | AntigravityQueue, ...] = ()) -> None:
        self.memory = memory
        self.queues = queues
        self.directory = Path(memory.path) / "pending-interactions"
        self.task: asyncio.Task[None] | None = None

    def enqueue(self, message: IncomingMessage, response: ChatResponse) -> None:
        # Skill bridge invocations are synthetic, not new user interactions.
        if message.required_capabilities:
            return
        event_id = str(uuid5(NAMESPACE_URL,
                            f"{message.channel.name}:{message.conversation_id}:{message.id}"))
        answer = ("Respuesta diferida pendiente; no se registra como completada."
                  if response.message.deferred else response.message.content)
        text = (f"Interacción real del {message.received_at.isoformat()}.\n"
                f"Usuario: {message.content[:7500]}\nArtemis: {answer[:7500]}")
        payload = {
            "agent": message.channel.agent_name or "primary", "event_id": event_id,
            "text": text,
            "metadata": {"conversation_id": str(message.conversation_id),
                         "channel": message.channel.name,
                         "created_at": message.received_at.isoformat(),
                         "kind": "interaction"},
        }
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.directory / f"{event_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False))
        temporary.chmod(0o600)
        temporary.replace(target)

    def flush_results(self) -> None:
        # Keep the activation boundary across restarts; do not import old conversations.
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        boundary = self.directory / "enabled-since"
        if not boundary.exists():
            boundary.write_text(str(time.time()))
        since = float(boundary.read_text())
        for queue in self.queues:
            for job in queue.recent(1000):
                if job.created_at < since or job.status not in {"completed", "failed"}:
                    continue
                marker = queue.path(job.id, ".memory")
                if marker.exists():
                    continue
                try:
                    self.memory.remember_event(
                        getattr(job, "agent_name", None) or "primary",
                        f"result:{type(queue).__name__}:{job.id}",
                        f"Resultado real ({job.status}).\nUsuario: {job.prompt[:7500]}\n"
                        f"Artemis: {job.answer[:7500]}",
                        {"conversation_id": str(job.conversation_id), "channel": job.channel,
                         "created_at": str(job.created_at), "kind": "result"},
                    )
                    marker.write_text("saved")
                except Exception:
                    logger.warning("Resultado pendiente de memoria; se reintentará")

    def flush(self) -> None:
        for path in sorted(self.directory.glob("*.json"))[:100]:
            try:
                self.memory.remember_event(**json.loads(path.read_text()))
                path.unlink()
            except Exception:
                logger.warning("Memoria pendiente; se reintentará sin registrar su contenido")

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="interaction-memory")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.flush_results)
                await asyncio.to_thread(self.flush)
            except Exception:
                logger.warning("Memoria automática no disponible; se reintentará")
            await asyncio.sleep(5)
