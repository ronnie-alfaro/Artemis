"""Provider-neutral function calling; text parsing stays outside this boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from uuid import UUID

from app.application.approvals import ApprovalStore
from app.domain.models import (
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
    ToolInvocation,
    ToolResult,
    utcnow,
)
from app.domain.tool_calling import Arguments as Arguments
from app.domain.tool_calling import CallContext as CallContext
from app.domain.tool_calling import FunctionCall as FunctionCall
from app.tools.registry import ApprovalRequired, ToolRegistry


class NativeTools:
    def __init__(
        self,
        tools: ToolRegistry,
        approvals: ApprovalStore,
        enabled: Callable[[str, CallContext], bool],
    ) -> None:
        self.tools = tools
        self.approvals = approvals
        self.enabled = enabled
        self.contracts: dict[str, tuple[str, type[Arguments]]] = {}
        self._claimed: set[UUID] = set()

    def register(self, name: str, capability: str, arguments: type[Arguments]) -> None:
        self.tools.get(name)
        self.contracts[name] = (capability, arguments)

    def _validate(self, call: FunctionCall, context: CallContext) -> dict[str, object]:
        capability, model = self.contracts[call.name]
        if (
            capability not in context.capabilities
            or not self.enabled(capability, context)
            or not self.tools.can_invoke(call.name, context.agent)
        ):
            raise PermissionError("Tool disabled or unauthorized")
        return model.model_validate(call.arguments).model_dump(mode="json")

    def schemas(self, context: CallContext) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name.replace(".", "__"),
                    "description": self.tools.get(name).definition.description,
                    "parameters": model.model_json_schema(),
                },
            }
            for name, (capability, model) in self.contracts.items()
            if capability in context.capabilities
            and self.enabled(capability, context)
            and self.tools.can_invoke(name, context.agent)
        ]

    def _parameters(self, call: FunctionCall, context: CallContext) -> dict[str, str]:
        return {
            "arguments": json.dumps(
                self._validate(call, context), sort_keys=True, separators=(",", ":")
            )
        }

    def request_approval(self, call: FunctionCall, context: CallContext) -> ApprovalRequest:
        parameters = self._parameters(call, context)
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    str(context.conversation_id),
                    context.agent,
                    call.name,
                    call.id,
                    parameters,
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return self.approvals.create(
            conversation_id=context.conversation_id,
            agent_name=context.agent,
            tool_name=call.name,
            parameters=parameters,
            reason="Confirmar operación estructurada",
            idempotency_key=fingerprint,
        )

    async def execute(
        self, call: FunctionCall, context: CallContext, approval_id: UUID | None = None
    ) -> ToolResult:
        arguments = self._validate(call, context)
        definition = self.tools.get(call.name).definition
        mutation = definition.risk_level is not RiskLevel.READ
        if mutation:
            if approval_id is None:
                raise ApprovalRequired("Request confirmation before executing")
            approval = self.approvals.get(approval_id)
            if (
                approval.status is not ApprovalStatus.APPROVED
                or approval.expires_at <= utcnow()
                or approval.conversation_id != context.conversation_id
                or approval.agent_name != context.agent
                or approval.tool_name != call.name
                or approval.parameters != self._parameters(call, context)
                or approval_id in self._claimed
            ):
                raise ApprovalRequired("Approval does not match this operation")
            self._claimed.add(approval_id)  # Claim before the first await; no concurrent replay.
        try:
            async with asyncio.timeout(definition.timeout_seconds):
                result = await self.tools.invoke(
                    ToolInvocation(
                        tool_name=call.name,
                        agent_name=context.agent,
                        input=arguments,
                        risk_level=definition.risk_level,
                        approval_id=approval_id,
                    )
                )
        except BaseException:
            if mutation and approval_id:
                self.approvals.mark_failed(approval_id, {"error": "execution_failed"})
            raise
        if mutation and approval_id:
            self.approvals.mark_executed(approval_id, result.output)
        return result
