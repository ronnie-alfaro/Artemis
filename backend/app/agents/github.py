from __future__ import annotations

import json
import re

from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    RiskLevel,
    ToolInvocation,
)
from app.tools.github import GitHubError
from app.tools.registry import ToolRegistry

HELP = (
    "GitHub · Consultas:\n"
    "• ‘repos’ o ‘listar repos’ para ver tus repositorios.\n"
    "• ‘commits dueño/repo’, ‘ramas dueño/repo’, ‘issues dueño/repo’ "
    "o ‘prs dueño/repo’.\n"
    "• Añade ‘página 2’ para continuar (10 registros por página).\n"
    "Activa con ‘utiliza github’. Las consultas no modifican GitHub."
)


class GitHubAgent:
    definition = Agent(
        name="github", version="0.1.0", purpose="Consulta GitHub desde el chat.",
        capabilities=[AgentCapability(
            name="github.repositories", description="Repositorios y actividad de GitHub",
            help_text=HELP,
        )], risk_level=RiskLevel.READ,
    )

    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools

    async def run(self, request: AgentRequest) -> AgentResponse:
        match = re.fullmatch(
            r"(?:(?:listar|lista|ver)\s+)?"
            r"(repos|repositorios|commits|ramas|branches|issues|prs|pulls)"
            r"(?:\s+([A-Za-z0-9_-]+/[A-Za-z0-9_.-]+))?"
            r"(?:\s+p[áa]gina\s+([0-9]{1,4}))?",
            request.message.content.strip(), re.IGNORECASE,
        )
        content = HELP
        if match:
            action = {"repositorios": "repos", "ramas": "branches", "prs": "pulls"}.get(
                match[1].lower(), match[1].lower()
            )
            try:
                result = await self._tools.invoke(ToolInvocation(
                    tool_name="github.read", agent_name="github", risk_level=RiskLevel.READ,
                    input={"action": action, "repo": match[2] or "", "page": int(match[3] or 1)},
                ))
                items = json.loads(result.output["items"])
                lines = [f"GitHub · {action} · página {result.output['page']}"]
                lines.extend(
                    item["title"] + (f"\n{item['url']}" if item["url"] else "")
                    for item in items
                )
                if not items:
                    lines.append("Sin resultados en esta página.")
                if result.output["has_more"] == "true":
                    lines.append("Hay más; repite el comando con la siguiente página.")
                content = "\n".join(lines)
            except (GitHubError, ValueError) as error:
                content = str(error)
        return AgentResponse(result=AgentResult(
            agent_name="github", content=content,
            metadata={"execution_id": str(request.execution_id)},
        ))
