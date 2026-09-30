from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

# ruff: noqa: E501
from datetime import timedelta
from uuid import UUID, uuid4

from app.domain.models import ApprovalRequest, ApprovalStatus, RiskLevel, utcnow


class ApprovalStore:
    """Approval lifecycle with an optional durable write-through backend."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._items: dict[UUID, ApprovalRequest] = {}
        self._idempotency: dict[str, UUID] = {}
        self._persist: Callable[[ApprovalRequest], Awaitable[None]] | None = None
        self._pending: set[asyncio.Future[None]] = set()

    def bind_persistence(self, persist: Callable[[ApprovalRequest], Awaitable[None]]) -> None:
        self._persist = persist

    def hydrate(self, approvals: list[ApprovalRequest]) -> None:
        self._items = {approval.id: approval for approval in approvals}

    async def flush(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending)

    def _record(self, approval: ApprovalRequest) -> None:
        if not self._persist:
            return
        try:
            task: asyncio.Future[None] = asyncio.ensure_future(self._persist(approval))
        except RuntimeError:
            return
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def create(
        self,
        *,
        conversation_id: UUID,
        agent_name: str,
        tool_name: str,
        parameters: dict[str, str],
        reason: str,
        idempotency_key: str,
    ) -> ApprovalRequest:
        existing_id = self._idempotency.get(idempotency_key)
        if existing_id:
            return self.get(existing_id)
        approval = ApprovalRequest(
            conversation_id=conversation_id,
            operation_id=uuid4(),
            agent_name=agent_name,
            tool_name=tool_name,
            parameters=parameters,
            risk_level=RiskLevel.WRITE,
            reason=reason,
            expires_at=utcnow() + self._ttl,
        )
        self._items[approval.id] = approval
        self._idempotency[idempotency_key] = approval.id
        self._record(approval)
        return approval

    def get(self, approval_id: UUID) -> ApprovalRequest:
        item = self._items[approval_id]
        self._expire(item)
        self._record(item)
        return item

    def all_approvals(self) -> list[ApprovalRequest]:
        return [self.get(item_id) for item_id in self._items]

    def pending_for_conversation(self, conversation_id: UUID) -> list[ApprovalRequest]:
        return [
            item
            for item in self.all_approvals()
            if item.conversation_id == conversation_id and item.status is ApprovalStatus.PENDING
        ]

    def approve(self, approval_id: UUID) -> ApprovalRequest:
        item = self.get(approval_id)
        if item.status is not ApprovalStatus.PENDING:
            raise PermissionError(f"approval is {item.status}")
        item.status = ApprovalStatus.APPROVED
        self._record(item)
        return item

    def reject(self, approval_id: UUID) -> ApprovalRequest:
        item = self.get(approval_id)
        if item.status is not ApprovalStatus.PENDING:
            raise PermissionError(f"approval is {item.status}")
        item.status = ApprovalStatus.REJECTED
        self._record(item)
        return item

    def mark_executed(self, approval_id: UUID, result: dict[str, str]) -> ApprovalRequest:
        item = self.get(approval_id)
        item.status, item.result = ApprovalStatus.EXECUTED, result
        self._record(item)
        return item

    def mark_failed(self, approval_id: UUID, result: dict[str, str]) -> ApprovalRequest:
        item = self.get(approval_id)
        item.status, item.result = ApprovalStatus.FAILED, result
        self._record(item)
        return item

    @staticmethod
    def _expire(item: ApprovalRequest) -> None:
        if item.status is ApprovalStatus.PENDING and item.expires_at <= utcnow():
            item.status = ApprovalStatus.EXPIRED
