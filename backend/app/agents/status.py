from __future__ import annotations

from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    RiskLevel,
)


class StatusAgent:
    """Safe WhatsApp default: describes the agent instead of pretending to do work."""

    def __init__(self, skill_help: dict[str, str] | None = None) -> None:
        self._skill_help = skill_help or {}

    definition = Agent(
        name="status",
        version="0.1.0",
        purpose="Explain the configured WhatsApp agent and its available skills.",
        capabilities=[
            AgentCapability(
                name="assistant.status",
                description="Show the editable welcome message and available WhatsApp skills",
            )
        ],
        risk_level=RiskLevel.READ,
    )

    async def run(self, request: AgentRequest) -> AgentResponse:
        greeting = (
            request.message.channel.assistant_greeting or "Hola, soy tu asistente de WhatsApp."
        )
        capabilities = set(request.message.channel.allowed_capabilities)
        options = [
            self._skill_help[capability]
            for capability in sorted(capabilities)
            if capability in self._skill_help
        ]
        if options:
            content = f"{greeting}\n\nPuedo ayudarte con:\n" + "\n".join(options)
        else:
            content = f"{greeting}\n\nAhora mismo no tengo skills opcionales activados."
        content += "\n\nEscribe ‘ayuda’ en cualquier momento para ver estas opciones."
        return AgentResponse(
            result=AgentResult(
                agent_name="status",
                content=content,
                metadata={"execution_id": str(request.execution_id)},
            )
        )
