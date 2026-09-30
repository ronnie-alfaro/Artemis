from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.application.registry import AgentRegistry
from app.domain.models import (
    AgentExecution,
    AgentRequest,
    ChatResponse,
    ExecutionPlan,
    ExecutionStatus,
    IncomingMessage,
    OutgoingMessage,
    PlanNode,
)


class PlanningError(ValueError):
    pass


@dataclass(frozen=True)
class CapabilityPlanner:
    registry: AgentRegistry
    selector: CapabilitySelector | None = None

    def plan(self, message: IncomingMessage) -> ExecutionPlan:
        nodes: list[PlanNode] = []
        capabilities = message.required_capabilities or [self._select(message)]
        for index, capability in enumerate(capabilities):
            candidates = self.registry.discover(capability)
            if not candidates:
                raise PlanningError(f"no healthy agent advertises capability '{capability}'")
            nodes.append(
                PlanNode(
                    id=f"node-{index}",
                    capability=capability,
                    agent_name=candidates[0].definition.name,
                )
            )
        return ExecutionPlan(conversation_id=message.conversation_id, nodes=nodes)

    def _select(self, message: IncomingMessage) -> str:
        allowed = message.channel.allowed_capabilities
        if self.selector:
            selected = self.selector.select(message)
            if selected and (not allowed or selected in allowed):
                return selected
        if allowed:
            if "assistant.status" in allowed:
                return "assistant.status"
            raise PlanningError("no bound capability matches this message")
        return "assistant.status"


class CapabilitySelector(Protocol):
    def select(self, message: IncomingMessage) -> str | None: ...


class DAGExecutor:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    async def execute(self, plan: ExecutionPlan, message: IncomingMessage) -> list[AgentExecution]:
        execution_id = uuid4()
        by_id = {node.id: node for node in plan.nodes}
        complete: set[str] = set()
        executions: list[AgentExecution] = []
        while len(complete) < len(by_id):
            runnable = [
                node
                for node in by_id.values()
                if node.id not in complete and set(node.dependencies) <= complete
            ]
            if not runnable:
                raise PlanningError("execution plan has a cyclic or unresolved dependency")
            batch = await asyncio.gather(
                *(self._run_node(node, message, execution_id) for node in runnable)
            )
            executions.extend(batch)
            complete.update(node.id for node in runnable)
        return executions

    async def _run_node(
        self, node: PlanNode, message: IncomingMessage, execution_id: UUID
    ) -> AgentExecution:
        agent = self._registry.get(node.agent_name)
        started = datetime.now(UTC)
        try:
            request = AgentRequest(execution_id=execution_id, node_id=node.id, message=message)
            response = await asyncio.wait_for(
                agent.run(request),
                timeout=agent.definition.timeout_seconds,
            )
            return AgentExecution(
                node_id=node.id,
                agent_name=node.agent_name,
                status=ExecutionStatus.COMPLETED,
                started_at=started,
                completed_at=datetime.now(UTC),
                result=response.result,
            )
        except Exception as error:
            return AgentExecution(
                node_id=node.id,
                agent_name=node.agent_name,
                status=ExecutionStatus.FAILED,
                started_at=started,
                completed_at=datetime.now(UTC),
                error=str(error),
            )


class Orchestrator:
    def __init__(self, planner: CapabilityPlanner, executor: DAGExecutor) -> None:
        self._planner = planner
        self._executor = executor

    async def handle(self, message: IncomingMessage) -> ChatResponse:
        plan = self._planner.plan(message)
        executions = await self._executor.execute(plan, message)
        plan.status = (
            ExecutionStatus.COMPLETED
            if all(item.result for item in executions)
            else ExecutionStatus.FAILED
        )
        fragments = [item.result.content for item in executions if item.result]
        content = (
            "\n\n".join(fragments) if fragments else "Artemis could not complete this request."
        )
        execution_id = uuid4()
        if executions and executions[0].result:
            execution_id = UUID(executions[0].result.metadata["execution_id"])
        return ChatResponse(
            message=OutgoingMessage(
                conversation_id=message.conversation_id, content=content, execution_id=execution_id
            ),
            plan=plan,
            executions=executions,
        )
