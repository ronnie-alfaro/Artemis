from __future__ import annotations

# ruff: noqa: E501
import re
from dataclasses import dataclass, field
from uuid import UUID

from app.application.approvals import ApprovalStore
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
from app.domain.seerr import MediaType, SeerrClient, SeerrClientError
from app.tools.registry import ToolRegistry
from app.tools.seerr import SeerrRequestTool


@dataclass
class ConversationState:
    candidates: list[tuple[MediaType, int, str, int | None]] = field(default_factory=list)


class SeerrAgent:
    definition = Agent(
        name="seerr",
        version="0.1.0",
        purpose="Selects Seerr media search and approved requests using typed capabilities.",
        capabilities=[
            AgentCapability(
                name="seerr.media",
                description="Search and request media via Seerr",
                help_text=(
                    "• Películas y series: escribe ‘quiero pedir <título>’. "
                    "Te mostraré opciones; responde con el número y luego ‘confirmo’ para enviarla."
                ),
            )
        ],
        permissions=[
            Permission(name="seerr.search.read", description="Search Seerr"),
            Permission(name="seerr.request.write", description="Request approved media"),
        ],
        risk_level=RiskLevel.WRITE,
    )

    def __init__(self, client: SeerrClient, tools: ToolRegistry, approvals: ApprovalStore) -> None:
        self._client, self._tools, self._approvals = client, tools, approvals
        self._states: dict[UUID, ConversationState] = {}

    def set_client(self, client: SeerrClient) -> None:
        self._client = client
        self._tools.replace(SeerrRequestTool(client), authorized_agents={"seerr"})

    def select(self, message: IncomingMessage) -> str | None:
        if message.conversation_id in self._states or self._approvals.pending_for_conversation(
            message.conversation_id, agent_name="seerr"
        ):
            return "seerr.media"
        intent = message.content.lower()
        if any(
            word in intent
            for word in ("pedir", "solicitar", "request", "película", "pelicula", "serie")
        ):
            return "seerr.media"
        return None

    async def run(self, request: AgentRequest) -> AgentResponse:
        content = request.message.content.strip()
        conversation_id = request.message.conversation_id
        state = self._states.setdefault(conversation_id, ConversationState())
        pending = self._approvals.pending_for_conversation(conversation_id, agent_name="seerr")
        if self._is_confirmation(content):
            return await self._confirm(request, pending)
        if content.lower() in {"no", "rechazo", "cancelar", "cancela"} and len(pending) == 1:
            self._approvals.reject(pending[0].id)
            await self._approvals.flush()
            return self._response(request, "La solicitud pendiente fue rechazada.")
        if state.candidates and content.isdigit():
            return await self._select(request, state, int(content))
        return await self._search(request, state, content)

    async def _search(
        self, request: AgentRequest, state: ConversationState, content: str
    ) -> AgentResponse:
        query = self._query(content)
        try:
            result = await self._client.search_media(query)
        except SeerrClientError as error:
            return self._response(request, error.safe_message, {"seerr_error": error.code.value})
        state.candidates = [
            (item.media_type, item.tmdb_id, item.title, item.year) for item in result.results[:5]
        ]
        if not state.candidates:
            return self._response(request, "No encontré resultados en Seerr. Prueba otro título.")
        options = "\n".join(
            f"{index}. {title} ({year or 'sin año'}) · {media_type.value} · TMDB {tmdb_id}"
            for index, (media_type, tmdb_id, title, year) in enumerate(state.candidates, 1)
        )
        return self._response(
            request,
            f"Encontré estas opciones:\n{options}\nResponde con el número que quieres solicitar.",
            {"tool": "seerr.search_media", "query": query},
        )

    async def _select(
        self, request: AgentRequest, state: ConversationState, selected: int
    ) -> AgentResponse:
        if not 1 <= selected <= len(state.candidates):
            return self._response(
                request, "Esa opción no existe; elige uno de los números mostrados."
            )
        media_type, tmdb_id, title, year = state.candidates[selected - 1]
        requester = f"rest:{request.message.conversation_id}"
        params = {
            "media_type": media_type.value,
            "tmdb_id": str(tmdb_id),
            "title": title,
            "year": str(year or ""),
            "requester": requester,
            "seasons": "serie completa" if media_type is MediaType.TV else "n/a",
            "quality_profile": "default",
        }
        approval = self._approvals.create(
            conversation_id=request.message.conversation_id,
            agent_name="seerr",
            tool_name="seerr.create_request",
            parameters=params,
            reason="Crear una solicitud de contenido en Seerr",
            idempotency_key=f"{request.message.conversation_id}:{media_type}:{tmdb_id}:{requester}",
        )
        await self._approvals.flush()
        return self._response(
            request,
            f"Preparé la solicitud de {title}. Requiere confirmación explícita antes de crearla. Responde “confirmo” para la operación {approval.id} antes de que expire.",
            {"approval_id": str(approval.id), "approval_status": approval.status.value},
        )

    async def _confirm(
        self, request: AgentRequest, pending: list[ApprovalRequest]
    ) -> AgentResponse:
        if len(pending) != 1:
            return self._response(
                request,
                "No hay una única operación pendiente que pueda confirmar. Selecciona un título o usa el identificador de aprobación en el control plane.",
            )
        approval = pending[0]
        approved = self._approvals.approve(approval.id)
        await self._approvals.flush()
        try:
            result = await self.approve_operation(approved)
        except SeerrClientError as error:
            return self._response(
                request,
                error.safe_message,
                {"approval_id": str(approved.id), "approval_status": "failed"},
            )
        return self._response(
            request,
            f"Solicitud creada en Seerr (ID {result['request_id']}, estado {result['status']}).",
            {
                "tool": "seerr.create_request",
                "approval_id": str(approved.id),
                "operation_id": str(approved.operation_id),
            },
        )

    async def approve_operation(self, approved: ApprovalRequest) -> dict[str, str]:
        params = approved.parameters
        payload = {
            "media_type": params["media_type"],
            "tmdb_id": int(params["tmdb_id"]),
            "requester": params["requester"],
        }
        try:
            result = await self._tools.invoke(
                ToolInvocation(
                    tool_name="seerr.create_request",
                    agent_name="seerr",
                    input=payload,
                    risk_level=RiskLevel.WRITE,
                    approval_id=approved.id,
                )
            )
        except SeerrClientError as error:
            if error.code.value == "duplicate" and error.request_id:
                status = await self._client.get_request_status(error.request_id)
                existing = {
                    "request_id": str(status.request_id),
                    "status": status.status,
                    "duplicate": "true",
                }
                self._approvals.mark_executed(approved.id, existing)
                await self._approvals.flush()
                return existing
            self._approvals.mark_failed(approved.id, {"error": error.code.value})
            await self._approvals.flush()
            raise
        self._approvals.mark_executed(approved.id, result.output)
        await self._approvals.flush()
        return result.output

    @staticmethod
    def _query(content: str) -> str:
        return (
            re.sub(
                r"^(quiero|puedo|podr[ií]as|me gustar[ií]a)?\s*(pedir|solicitar|ver)\s+",
                "",
                content,
                flags=re.IGNORECASE,
            ).strip()
            or content
        )

    @staticmethod
    def _is_confirmation(content: str) -> bool:
        return content.strip().lower() in {"sí", "si", "confirmo", "confirmar", "yes"}

    @staticmethod
    def _response(
        request: AgentRequest, content: str, metadata: dict[str, str] | None = None
    ) -> AgentResponse:
        return AgentResponse(
            result=AgentResult(
                agent_name="seerr",
                content=content,
                metadata={"execution_id": str(request.execution_id), **(metadata or {})},
            )
        )
