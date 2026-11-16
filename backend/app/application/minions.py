"""Bounded asynchronous dispatcher. Remote executors must enforce worker-side policy."""

from __future__ import annotations

import asyncio
import secrets
from collections import deque
from typing import Any, Protocol
from uuid import UUID

from app.application.native_tools import CallContext, FunctionCall, NativeTools
from app.domain.minions import MinionEvent, MinionJob


class MinionExecutor(Protocol):
    async def execute(self, job: MinionJob) -> dict[str, Any]: ...


class LocalExecutor:
    def __init__(self, tools: NativeTools) -> None:
        self.tools = tools

    async def execute(self, job: MinionJob) -> dict[str, Any]:
        result = await self.tools.execute(job.call, job.context, job.approval_id)
        return result.model_dump(mode="json")


class MinionDispatcher:
    def __init__(
        self,
        targets: dict[str, MinionExecutor],
        *,
        parallelism: int = 4,
        capacity: int = 100,
        timeout: float = 120,
    ) -> None:
        if parallelism < 1 or capacity < 1 or timeout <= 0:
            raise ValueError("Invalid dispatcher limits")
        self.targets = dict(targets)
        self.capacity = capacity
        self.timeout = timeout
        self.jobs: dict[UUID, MinionJob] = {}
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.events: deque[MinionEvent] = deque(maxlen=1000)
        self._sequence = 0
        self._slots = asyncio.Semaphore(parallelism)

    def _emit(self, job: MinionJob) -> None:
        self._sequence += 1
        self.events.append(MinionEvent(sequence=self._sequence, minion=job.model_dump(mode="json")))

    def submit(
        self,
        call: FunctionCall,
        context: CallContext,
        *,
        target: str = "local",
        approval_id: UUID | None = None,
    ) -> MinionJob:
        if target not in self.targets:
            raise ValueError("Unknown configured target")
        if len(self.tasks) >= self.capacity:
            raise RuntimeError("Dispatcher capacity reached")
        mythology, name = secrets.choice(
            [
                ("griega", "Hermes"),
                ("nórdica", "Eir"),
                ("egipcia", "Thoth"),
                ("japonesa", "Inari"),
                ("maya", "Ixchel"),
            ]
        )
        job = MinionJob(
            name=f"{name}-{secrets.token_hex(4)}",
            mythology=mythology,
            task=call.name,
            target=target,
            call=call.model_copy(deep=True),
            context=context.model_copy(deep=True),
            approval_id=approval_id,
        )
        self.jobs[job.id] = job
        self._emit(job)
        task = asyncio.create_task(self._run(job))
        self.tasks[job.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job.id, None))
        # Retain only a bounded history; active jobs are never evicted.
        for key in list(self.jobs):
            if len(self.jobs) <= self.capacity:
                break
            if key not in self.tasks:
                del self.jobs[key]
        return job.model_copy(deep=True)

    async def _run(self, job: MinionJob) -> None:
        try:
            async with asyncio.timeout(self.timeout), self._slots:
                job.state = "running"
                self._emit(job)
                job.result = await self.targets[job.target].execute(job)
                job.state = "completed"
        except asyncio.CancelledError:
            job.state = "cancelled"
        except Exception:
            job.state = "failed"  # Never expose transport exceptions or credentials in telemetry.
        finally:
            self._emit(job)

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
