from __future__ import annotations

import re
from typing import Literal

from app.application.antigravity import AntigravityQueue
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


class AntigravityAgent:
    definition = Agent(
        name="antigravity",
        version="0.1.0",
        purpose="Conversa con Antigravity y prepara nuevas herramientas para Artemis.",
        capabilities=[
            AgentCapability(
                name="antigravity.assistant",
                description="Preguntas y desarrollo de herramientas con Antigravity",
                help_text=(
                    "Antigravity: escribe ‘utiliza antigravity’ y después tu petición. "
                    "Puede buscar, ejecutar comandos y editar archivos del proyecto real. "
                    "Las acciones solicitadas se ejecutan sin confirmación adicional. "
                    "Usa ‘estado’, ‘resultado <ID>’ o ‘salir’."
                ),
            )
        ],
    )

    def __init__(self, queue: AntigravityQueue, tools: ToolRegistry) -> None:
        self.queue, self.tools = queue, tools

    async def run(self, request: AgentRequest) -> AgentResponse:
        message = request.message
        text = message.content.strip()
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
                or "No tienes peticiones de Antigravity todavía."
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
                content = content[:3400] + "\n\nRespuesta completa en Habilidades → Antigravity."
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
                        tool_name="antigravity.create_tool"
                        if mode == "tool"
                        else "antigravity.ask",
                        agent_name="antigravity",
                        risk_level=RiskLevel.WRITE,
                        input={
                            "message_id": str(message.id),
                            "conversation_id": str(message.conversation_id),
                            "channel": message.channel.name,
                            "prompt": text + ("\n\n" + message.image_context
                                              if message.image_context else ""),
                        },
                    )
                )
                job_id = result.output["id"]
                content = (
                    f"Petición {job_id[:8]} recibida. "
                    + (
                        "Antigravity ejecutará la tarea en el proyecto. "
                        if mode == "tool"
                        else "Antigravity está preparando la respuesta. "
                    )
                    + "Te avisaré por este chat cuando termine."
                )
            except ValueError as error:
                content = str(error)
        return AgentResponse(
            result=AgentResult(
                agent_name="antigravity",
                content=content,
                metadata={"execution_id": str(request.execution_id)},
            )
        )
