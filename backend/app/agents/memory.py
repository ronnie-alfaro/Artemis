from __future__ import annotations

import json
from uuid import UUID

from app.application.approvals import ApprovalStore
from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    ApprovalRequest,
    RiskLevel,
    ToolInvocation,
)
from app.domain.skills import MEMORY_CAPABILITY
from app.tools.registry import ToolRegistry

HELP = (
    "Usa «buscar TEXTO» para obtener recuerdos con su ID, «guardar TEXTO» para agregar y "
    "«actualizar ID TEXTO» para editar. Para editar, usa el ID exacto obtenido al buscar. "
    "Guardar y actualizar requieren confirmación posterior del usuario con «confirmo»."
)
COMMANDS = {"buscar": "search", "guardar": "remember", "actualizar": "update"}


class MemoryAgent:
    definition = Agent(
        name="memory",
        version="0.1.0",
        purpose="Gestiona recuerdos en Chroma de la conversación actual.",
        capabilities=[AgentCapability(
            name=MEMORY_CAPABILITY,
            description="Busca, agrega y actualiza recuerdos de esta conversación en Chroma.",
            help_text=HELP,
        )],
        timeout_seconds=95,
    )

    def __init__(self, tools: ToolRegistry, approvals: ApprovalStore) -> None:
        self.tools, self.approvals = tools, approvals

    async def approve_operation(self, approval: ApprovalRequest) -> dict[str, str]:
        try:
            result = await self.tools.invoke(ToolInvocation(
                tool_name=approval.tool_name, agent_name=self.definition.name,
                risk_level=RiskLevel.WRITE, approval_id=approval.id, input=approval.parameters,
            ))
        except Exception:
            self.approvals.mark_failed(approval.id, {"error": "memory_write_failed"})
            await self.approvals.flush()
            return {"error": "memory_write_failed"}
        self.approvals.mark_executed(approval.id, result.output)
        await self.approvals.flush()
        return result.output

    async def run(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(result=AgentResult(
            agent_name=self.definition.name, content=await self._command(request),
        ))

    async def _command(self, request: AgentRequest) -> str:
        message = request.message
        channel = message.channel
        if (channel.name not in {"whatsapp", "telegram"} or not channel.agent_name
                or MEMORY_CAPABILITY not in channel.allowed_capabilities):
            return "La habilidad de memoria no está asignada a esta conversación."
        scope = {"_bot": channel.agent_name, "_channel": channel.name,
                 "_conversation": str(message.conversation_id)}
        parts = message.content.strip().split(maxsplit=1)
        if not parts:
            return HELP
        command = parts[0].casefold()
        if message.content.strip().casefold().strip(".! ") in {
            "confirmo", "confirmar", "sí", "si", "yes", "confirm", "aprobar",
        }:
            return await self._confirm(message.conversation_id, scope)
        action = COMMANDS.get(command)
        if action is None or len(parts) != 2:
            return HELP

        text = parts[1]
        arguments = dict(scope)
        if action == "update":
            record = text.split(maxsplit=1)
            if len(record) != 2 or len(record[0]) > 200:
                return "Indica el ID del recuerdo y el texto nuevo."
            arguments["id"], text = record
        if len(text) > 16000:
            return "El texto del recuerdo puede tener hasta 16 000 caracteres."
        arguments["text"] = text
        name = f"memory.{action}"
        if action == "search":
            result = await self.tools.invoke(ToolInvocation(
                tool_name=name, agent_name=self.definition.name,
                risk_level=RiskLevel.READ, input=arguments,
            ))
            return result.output["result"]

        pending = self.approvals.pending_for_conversation(
            message.conversation_id, agent_name=self.definition.name,
        )
        if pending:
            return "Ya hay un cambio de memoria pendiente de confirmación."
        self.approvals.create(
            conversation_id=message.conversation_id, agent_name=self.definition.name,
            tool_name=name, parameters=arguments, reason="Confirmar cambio de memoria",
            idempotency_key=f"memory:{message.id}",
        )
        await self.approvals.flush()
        excerpt = text if len(text) <= 400 else text[:400] + "…"
        record = f" {arguments['id']}" if action == "update" else ""
        return (f"¿Confirmas {command} el recuerdo{record}?\n"
                f"«{excerpt}»\nResponde «confirmo» para aplicar el cambio.")

    async def _confirm(self, conversation: UUID, scope: dict[str, str]) -> str:
        pending = self.approvals.pending_for_conversation(
            conversation, agent_name=self.definition.name,
        )
        if (len(pending) != 1 or
                any(pending[0].parameters.get(key) != value for key, value in scope.items())):
            return "No hay un cambio de memoria pendiente para confirmar."
        result = await self.approve_operation(self.approvals.approve(pending[0].id))
        if "error" in result:
            return "No pude aplicar el cambio en Chroma."
        value = json.loads(result["result"])
        if pending[0].tool_name == "memory.update":
            return "Actualicé el recuerdo." if value else "No encontré ese ID en esta conversación."
        return f"Guardé el recuerdo con ID {value}."
