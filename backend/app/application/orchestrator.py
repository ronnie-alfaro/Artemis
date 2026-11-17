from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.application.interaction_memory import InteractionMemory
from app.application.registry import AgentRegistry
from app.application.skill_sessions import SkillSessionRouter
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
from app.domain.skills import help_target


class PlanningError(ValueError):
    pass


@dataclass(frozen=True)
class CapabilityPlanner:
    registry: AgentRegistry
    selector: CapabilitySelector | None = None

    def plan(self, message: IncomingMessage) -> ExecutionPlan:
        nodes: list[PlanNode] = []
        help_requested = message.content.strip().casefold().strip("¿?¡!., ") in {
            "ayuda", "/ayuda", "help", "/help", "qué puedes hacer", "que puedes hacer",
        }
        help_requested = help_requested or help_target(message.content) is not None
        help_requested = help_requested and not message.channel.natural_conversation
        capabilities = (
            ["assistant.status"] if help_requested
            else message.required_capabilities or [self._select(message)]
        )
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
            raise PlanningError("Ninguna habilidad asignada coincide con este mensaje")
        return "assistant.status"


class CapabilitySelector(Protocol):
    def select(self, message: IncomingMessage) -> str | None: ...


class CompositeCapabilitySelector:
    def __init__(self, *selectors: CapabilitySelector) -> None:
        self._selectors = selectors

    def select(self, message: IncomingMessage) -> str | None:
        for selector in self._selectors:
            selected = selector.select(message)
            if selected:
                return selected
        return None


class DAGExecutor:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    async def execute(
        self, plan: ExecutionPlan, message: IncomingMessage, context: dict[str, str] | None = None
    ) -> list[AgentExecution]:
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
                *(self._run_node(node, message, execution_id, context or {}) for node in runnable)
            )
            executions.extend(batch)
            complete.update(node.id for node in runnable)
        return executions

    async def _run_node(
        self, node: PlanNode, message: IncomingMessage, execution_id: UUID, context: dict[str, str]
    ) -> AgentExecution:
        agent = self._registry.get(node.agent_name)
        started = datetime.now(UTC)
        try:
            request = AgentRequest(
                execution_id=execution_id, node_id=node.id, message=message, context=context
            )
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
    def __init__(
        self, planner: CapabilityPlanner, executor: DAGExecutor,
        skill_sessions: SkillSessionRouter | None = None,
        interaction_memory: InteractionMemory | None = None,
    ) -> None:
        self.interaction_memory = interaction_memory
        self.skill_sessions = skill_sessions
        self._conversation_locks: defaultdict[tuple[str, UUID], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self._planner = planner
        self._executor = executor

    async def handle(self, message: IncomingMessage) -> ChatResponse:
        async with self._conversation_locks[(message.channel.name, message.conversation_id)]:
            response = await self._handle(message)
            if self.interaction_memory:
                try:
                    await asyncio.to_thread(self.interaction_memory.enqueue, message, response)
                except Exception:
                    logging.getLogger(__name__).warning(
                        "No se pudo encolar la interacción en memoria")
            return response

    async def _handle(self, message: IncomingMessage) -> ChatResponse:
        context: dict[str, str] = {}
        if self.skill_sessions:
            message, context = await self.skill_sessions.route(message)
        plan = self._planner.plan(message)
        if message.image_context:
            context["image_context"] = message.image_context
        executions = await self._executor.execute(plan, message, context)
        plan.status = (
            ExecutionStatus.COMPLETED
            if all(item.result for item in executions)
            else ExecutionStatus.FAILED
        )
        fragments = [item.result.content for item in executions if item.result]
        content = (
            "\n\n".join(fragments) if fragments else "Artemis no pudo completar la petición."
        )
        execution_id = uuid4()
        if executions and executions[0].result:
            execution_id = UUID(executions[0].result.metadata["execution_id"])
        return ChatResponse(
            message=OutgoingMessage(
                conversation_id=message.conversation_id, content=content, execution_id=execution_id,
                deferred=bool(len(executions) == 1 and executions[0].result
                              and executions[0].result.metadata.get("deferred") == "true"),
                reaction_options=(executions[0].result.reaction_options
                                  if len(executions) == 1 and executions[0].result else []),
            ),
            plan=plan,
            executions=executions,
        )
