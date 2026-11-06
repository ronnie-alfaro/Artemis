from __future__ import annotations

import re
from typing import Literal

from app.application.codex import CodexQueue
from app.application.github_sync import SYNC_PROMPT, is_sync_command
from app.application.iteration import ITERATION_PROMPT, ITERATION_REPLY, is_iteration_command
from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    RiskLevel,
    ToolInvocation,
)
from app.tools.registry import ToolRegistry


class CodexAgent:
    definition = Agent(
        name="codex",
        version="0.1.0",
        purpose="Busca, revisa y modifica el proyecto real con Codex.",
        capabilities=[
            AgentCapability(
                name="codex.assistant",
                description="Preguntas y desarrollo de herramientas con Codex",
                help_text=(
                    "Codex: escribe ‘utiliza codex’ y después tu petición. "
                    "Puede buscar, ejecutar comandos y editar archivos del proyecto real. "
                    "Las acciones solicitadas se ejecutan sin confirmación adicional. "
                    "También puedes pedir ‘crear herramienta <descripción>’. "
                    "Usa ‘estado’,  ‘resultado <ID>’ o ‘salir’."
                ),
            )
        ],
    )

    def __init__(self, queue: CodexQueue, tools: ToolRegistry) -> None:
        self.queue, self.tools = queue, tools

    async def run(self, request: AgentRequest) -> AgentResponse:
        message = request.message
        text = message.content.strip()
        iteration = is_iteration_command(text)
        jobs = [
            job
            for job in self.queue.recent(1000)
            if job.channel == message.channel.name
            and job.conversation_id == message.conversation_id
        ]
        labels = {
            "queued": "En cola",
            "running": "En marcha",
            "completed": "Terminado",
            "failed": "Falló",
        }
        if text.casefold() in {"estado", "mis peticiones"}:
            content = (
                "\n".join(
                    f"{str(job.id)[:8]} · {labels[job.status]} · {job.prompt[:80]}"
                    for job in jobs[:5]
                )
                or "Por aquí todavía no hay peticiones. La calma antes del teclado."
            )
        elif text.casefold().startswith("resultado "):
            target = text.split(maxsplit=1)[1].strip().casefold()
            found = (
                [job for job in jobs if str(job.id).startswith(target)] if len(target) >= 8 else []
            )
            content = (
                (found[0].answer or labels[found[0].status])
                if len(found) == 1
                else (
                    "No encuentro esa petición en esta conversación. Usa ‘estado’ para ver sus ID."
                )
            )
            if len(content) > 3400:
                content = content[:3400] + "\n\nRespuesta completa en Habilidades → Codex."
        else:
            mode: Literal["chat", "tool"] = (
                "tool"
                if re.match(
                    r"^(?:crea(?:r)?|genera(?:r)?|implementa(?:r)?|desarrolla(?:r)?)\s+"
                    r"(?:una?\s+)?(?:nueva?\s+)?(?:herramienta|tool)\b",
                    text,
                    re.I,
                )
                else "chat"
            )
            try:
                result = await self.tools.invoke(
                    ToolInvocation(
                        tool_name="codex.create_tool" if mode == "tool" else "codex.ask",
                        agent_name="codex",
                        risk_level=RiskLevel.WRITE,
                        input={
                            "message_id": str(message.id),
                            "conversation_id": str(message.conversation_id),
                            "channel": message.channel.name,
                            "prompt": (
                                ITERATION_PROMPT
                                if iteration
                                else SYNC_PROMPT if is_sync_command(text) else text
                            ),
                        },
                    )
                )
                job_id = result.output["id"]
                content = ITERATION_REPLY if iteration else (
                    f"Petición {job_id[:8]} en mis manos. "
                    + (
                        "Voy a darle forma a esa herramienta y pasarle las pruebas. "
                        if mode == "tool"
                        else "Me pongo con ello; el teclado ya tiembla. "
                    )
                    + "Cuando lo tenga, te cuento por aquí."
                )
            except ValueError as error:
                content = str(error)
        return AgentResponse(
            result=AgentResult(
                agent_name="codex",
                content=content,
                metadata={"execution_id": str(request.execution_id)},
            )
        )
