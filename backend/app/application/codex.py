from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field

from app.application.whatsapp_formatting import whatsapp_chunks

logger = logging.getLogger(__name__)


class CodexJob(BaseModel):
    id: UUID
    conversation_id: UUID
    channel: str
    prompt: str = Field(min_length=1, max_length=20000)
    mode: Literal["chat", "tool"] = "chat"
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    created_at: float
    answer: str = ""
    has_patch: bool = False
    delivered: bool = False


class CodexQueue:
    def __init__(self, directory: str | None = None) -> None:
        self.directory = Path(directory) if directory else None

    @property
    def available(self) -> bool:
        if not self.directory:
            return False
        try:
            return time.time() - (self.directory / "heartbeat").stat().st_mtime < 45
        except OSError:
            return False

    def path(self, job_id: UUID, suffix: str = ".json") -> Path:
        if self.directory is None:
            raise ValueError("El servicio Codex no está configurado.")
        return self.directory / f"{job_id}{suffix}"

    def load(self, job_id: UUID) -> CodexJob | None:
        try:
            return CodexJob.model_validate_json(self.path(job_id).read_text())
        except FileNotFoundError:
            return None

    def save(self, job: CodexJob) -> None:
        target = self.path(job.id)
        temporary = target.with_suffix(".api.tmp")
        temporary.write_text(job.model_dump_json())
        temporary.chmod(0o660)
        os.replace(temporary, target)

    def recent(self, limit: int = 30) -> list[CodexJob]:
        if self.directory is None:
            return []
        jobs = [
            CodexJob.model_validate_json(path.read_text()) for path in self.directory.glob("*.json")
        ]
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)[:limit]

    def submit(
        self,
        message_id: UUID,
        conversation_id: UUID,
        channel: str,
        prompt: str,
        mode: Literal["chat", "tool"],
    ) -> CodexJob:
        job_id = uuid5(NAMESPACE_URL, f"artemis-codex:{channel}:{conversation_id}:{message_id}")
        previous = self.load(job_id)
        if previous:
            return previous
        if not self.available:
            raise ValueError("Codex no está conectado. Revisa su servicio en Habilidades → Codex.")
        pending = [job for job in self.recent(1000) if job.status in {"queued", "running"}]
        if len(pending) >= 10:
            raise ValueError("Codex tiene diez peticiones pendientes. Espera a que termine alguna.")
        job = CodexJob(
            id=job_id,
            conversation_id=conversation_id,
            channel=channel,
            prompt=prompt,
            mode=mode,
            created_at=time.time(),
        )
        self.save(job)
        return job


class CodexChannel(Protocol):
    async def recipient_for_conversation(self, conversation_id: UUID) -> str | None: ...
    async def send_notification(self, recipient_id: str, content: str) -> None: ...


class CodexDeliveryWorker:
    """Return each result to its originating conversation, never a global recipient."""

    def __init__(self, queue: CodexQueue, channel: CodexChannel) -> None:
        self.queue, self.channel = queue, channel
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="codex-results")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> None:
        for job in reversed(self.queue.recent(1000)):
            if (
                job.channel not in {"whatsapp", "telegram"}
                or job.delivered
                or job.status not in {"completed", "failed"}
            ):
                continue
            recipient = await self.channel.recipient_for_conversation(job.conversation_id)
            if not recipient:
                continue
            # Persist progress per chunk, so a later chunk failing does not resend earlier ones.
            progress = self.queue.path(job.id, ".delivery")
            sent = int(progress.read_text()) if progress.exists() else 0
            text = f"*Artemis* · `{str(job.id)[:8]}`\n\n{job.answer}"
            if job.has_patch:
                text += "\n\nParche disponible en Habilidades → Codex."
            chunks = whatsapp_chunks(text, 3400)
            for index in range(sent, len(chunks)):
                await self.channel.send_notification(recipient, chunks[index])
                progress.write_text(str(index + 1))
            job.delivered = True
            self.queue.save(job)

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("No se pudo entregar un resultado de Codex; se reintentará")
            await asyncio.sleep(3)
