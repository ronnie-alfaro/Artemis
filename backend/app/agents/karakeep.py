from __future__ import annotations

import re

from app.application.approvals import ApprovalStore
from app.domain.karakeep import KarakeepClient, KarakeepClientError
from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    ApprovalRequest,
    IncomingMessage,
    Permission,
    RiskLevel,
    ToolInvocation,
)
from app.tools.karakeep import KarakeepBookmarkTool
from app.tools.registry import ToolRegistry

_URL = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_SAVE_INTENT = ("guardar", "guarda", "save", "bookmark", "marcar", "lee luego")


class KarakeepAgent:
    definition = Agent(
        name="karakeep",
        version="0.1.0",
        purpose="Saves explicitly approved links to Karakeep bookmarks.",
        capabilities=[
            AgentCapability(
                name="karakeep.bookmarks",
                description="Save approved links as Karakeep bookmarks",
                help_text=(
                    "• Guardar enlaces: escribe ‘guarda https://ejemplo.com’. "
                    "Te mostraré el enlace; responde ‘confirmo’ "
                    "antes de añadirlo a Karakeep."
                ),
            )
        ],
        permissions=[
            Permission(name="karakeep.bookmark.write", description="Save an approved Karakeep link")
        ],
        risk_level=RiskLevel.WRITE,
    )

    def __init__(
        self, client: KarakeepClient, tools: ToolRegistry, approvals: ApprovalStore
    ) -> None:
        self._client, self._tools, self._approvals = client, tools, approvals

    def set_client(self, client: KarakeepClient) -> None:
        self._client = client
        self._tools.replace(KarakeepBookmarkTool(client), authorized_agents={"karakeep"})

    def select(self, message: IncomingMessage) -> str | None:
        if self._approvals.pending_for_conversation(message.conversation_id, agent_name="karakeep"):
            return "karakeep.bookmarks"
        intent = message.content.lower()
        if any(phrase in intent for phrase in _SAVE_INTENT) and self._url(message.content):
            return "karakeep.bookmarks"
        return None

    async def run(self, request: AgentRequest) -> AgentResponse:
        content = request.message.content.strip()
        pending = self._approvals.pending_for_conversation(
            request.message.conversation_id, agent_name="karakeep"
        )
        if self._is_confirmation(content):
            return await self._confirm(request, pending)
        if content.lower() in {"no", "rechazo", "cancelar", "cancela"} and len(pending) == 1:
            self._approvals.reject(pending[0].id)
            await self._approvals.flush()
            return self._response(request, "El guardado pendiente fue cancelado.")
        url = self._url(content)
        if not url:
            return self._response(
                request,
                "Para guardar un enlace, escribe por ejemplo: ‘guarda https://ejemplo.com’. "
                "Te pediré confirmación antes de añadirlo a Karakeep.",
            )
        approval = self._approvals.create(
            conversation_id=request.message.conversation_id,
            agent_name="karakeep",
            tool_name="karakeep.create_bookmark",
            parameters={"url": url},
            reason="Guardar un enlace en Karakeep",
            idempotency_key=f"{request.message.conversation_id}:karakeep:{url}",
        )
        await self._approvals.flush()
        return self._response(
            request,
            "Preparé guardar este enlace en Karakeep:\n"
            f"{url}\n\nResponde ‘confirmo’ para la operación {approval.id} antes de que expire.",
            {"approval_id": str(approval.id), "approval_status": approval.status.value},
        )

    async def _confirm(
        self, request: AgentRequest, pending: list[ApprovalRequest]
    ) -> AgentResponse:
        if len(pending) != 1:
            return self._response(
                request,
                "No hay un único enlace pendiente que pueda confirmar. Inicia un nuevo guardado o "
                "usa el identificador de aprobación en el control plane.",
            )
        approved = self._approvals.approve(pending[0].id)
        await self._approvals.flush()
        try:
            result = await self.approve_operation(approved)
        except KarakeepClientError as error:
            return self._response(
                request,
                error.safe_message,
                {"approval_id": str(approved.id), "approval_status": "failed"},
            )
        return self._response(
            request,
            f"Enlace guardado en Karakeep: {result['url']}",
            {
                "tool": "karakeep.create_bookmark",
                "approval_id": str(approved.id),
                "operation_id": str(approved.operation_id),
            },
        )

    async def approve_operation(self, approved: ApprovalRequest) -> dict[str, str]:
        try:
            result = await self._tools.invoke(
                ToolInvocation(
                    tool_name="karakeep.create_bookmark",
                    agent_name="karakeep",
                    input={"url": approved.parameters["url"]},
                    risk_level=RiskLevel.WRITE,
                    approval_id=approved.id,
                )
            )
        except KarakeepClientError as error:
            self._approvals.mark_failed(approved.id, {"error": error.code})
            await self._approvals.flush()
            raise
        self._approvals.mark_executed(approved.id, result.output)
        await self._approvals.flush()
        return result.output

    @staticmethod
    def _url(content: str) -> str | None:
        match = _URL.search(content)
        return match.group(0).rstrip(".,!?;:)") if match else None

    @staticmethod
    def _is_confirmation(content: str) -> bool:
        return content.strip().lower() in {"sí", "si", "confirmo", "confirmar", "yes"}

    @staticmethod
    def _response(
        request: AgentRequest, content: str, metadata: dict[str, str] | None = None
    ) -> AgentResponse:
        return AgentResponse(
            result=AgentResult(
                agent_name="karakeep",
                content=content,
                metadata={"execution_id": str(request.execution_id), **(metadata or {})},
            )
        )
