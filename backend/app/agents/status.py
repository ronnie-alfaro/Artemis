from __future__ import annotations

import json

from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    ReactionOption,
    RiskLevel,
)
from app.domain.skills import DEFAULT_PRESENTATIONS, help_target


class StatusAgent:
    """Safe WhatsApp default: describes the agent instead of pretending to do work."""

    def __init__(self, skill_help: dict[str, str] | None = None) -> None:
        self._skill_help = skill_help or {}
        self.presentations = {
            key: value.model_copy() for key, value in DEFAULT_PRESENTATIONS.items()
        }

    definition = Agent(
        name="status",
        version="0.1.0",
        purpose="Explica el agente de WhatsApp y sus habilidades disponibles.",
        capabilities=[
            AgentCapability(
                name="assistant.status",
                description="Muestra el saludo y las habilidades disponibles en WhatsApp",
            )
        ],
        risk_level=RiskLevel.READ,
    )

    async def run(self, request: AgentRequest) -> AgentResponse:
        greeting = (
            request.message.channel.assistant_greeting or "Hola, soy tu asistente de WhatsApp."
        )
        capabilities = set(request.message.channel.allowed_capabilities) or set(self._skill_help)
        target = help_target(request.message.content)
        visible = [key for key in sorted(capabilities) if key in self._skill_help]
        reaction_options: list[ReactionOption] = []
        if target:
            match = next(
                (
                    key
                    for key in visible
                    if target
                    in {
                        key.casefold(),
                        key.split(".")[0].casefold(),
                        self.presentations[key.split(".")[0]].name.casefold(),
                    }
                ),
                None,
            )
            if match:
                name = self.presentations[match.split(".")[0]].name
                detail = self._skill_help[match]
                if ":\n" in detail:
                    detail = detail.split(":\n", 1)[1]
                content = f"{name}\n\n{detail}"
            else:
                content = "No encuentro esa habilidad entre las disponibles. Escribe ‘ayuda’."
        else:
            options = []
            for capability in visible:
                presentation = self.presentations.get(capability.split(".")[0])
                options.append(
                    f"• {presentation.name}: {presentation.description}"
                    if presentation
                    else self._skill_help[capability]
                )
            reaction_options = [
                ReactionOption(emoji=f"{i}️⃣",
                               label=self.presentations[key.split(".")[0]].name,
                               command=f"utiliza {key.split('.')[0]}")
                for i, key in enumerate(visible[:10], 1)
                if key.split(".")[0] in self.presentations
            ]
            if options:
                content = f"{greeting}\n\nPuedo ayudarte con:\n" + "\n".join(options)
            else:
                content = f"{greeting}\n\nAhora mismo no tengo habilidades opcionales activadas."
            content += (
                "\n\nEscribe ‘utiliza HABILIDAD’ para activarla "
                "o ‘ayuda HABILIDAD’ para ver sus comandos."
            )
        content = request.context.get("status_message", content)
        if request.context.get("status_footer"):
            content += "\n\n" + request.context["status_footer"]
        return AgentResponse(
            result=AgentResult(
                agent_name="status",
                content=content,
                reaction_options=(
                    [ReactionOption.model_validate(value) for value in json.loads(
                        request.context.get("status_reaction_options", "[]")
                    )] if "status_message" in request.context else reaction_options
                ),
                metadata={"execution_id": str(request.execution_id)},
            )
        )
