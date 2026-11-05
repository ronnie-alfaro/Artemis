from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from app.application.approvals import ApprovalStore
from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    ApprovalRequest,
    ApprovalStatus,
    IncomingMessage,
    Permission,
    ReactionOption,
    RiskLevel,
    ToolInvocation,
)
from app.domain.usenet import (
    DownloadItem,
    DownloadStatus,
    SearchItem,
    UsenetClient,
    UsenetClientError,
)
from app.tools.registry import ToolRegistry
from app.tools.usenet import ACTIONS, UsenetTool

CATEGORIES = {
    "movies": "2000",
    "peliculas": "2000",
    "pelicula": "2000",
    "cine": "2000",
    "tv": "5000",
    "series": "5000",
    "serie": "5000",
    "music": "3000",
    "musica": "3000",
    "audio": "3000",
    "books": "7000",
    "libros": "7000",
    "libro": "7000",
    "games": "1000",
    "juegos": "1000",
    "apps": "4000",
    "software": "4000",
}
CATEGORY_PATTERN = "|".join(CATEGORIES)
SEARCH = re.compile(r"^(?:quiero\s+)?(?:busca(?:r|me)?|search)\s+(.+)$", re.I)
SELECTION = re.compile(
    r"^(?:baja(?:r)?|descarga(?:r)?|detalles?(?: de)?)\s+(?:el\s+)?(\d+)[.!]?$", re.I
)
SEARCH_TTL = 15 * 60


def normalized(text: str) -> str:
    return (
        "".join(
            c
            for c in unicodedata.normalize("NFD", text.casefold())
            if unicodedata.category(c) != "Mn"
        )
        .strip()
        .strip("¿?¡!., ")
    )


@dataclass
class SearchState:
    items: list[SearchItem]
    created_at: float


class UsenetAgent:
    definition = Agent(
        name="usenet",
        version="0.1.0",
        purpose="Busca títulos y gestiona descargas confirmadas.",
        capabilities=[
            AgentCapability(
                name="usenet.downloads",
                description="Buscar, bajar y consultar descargas",
                help_text=(
                    "Descargas:\n"
                    "• Buscar: ‘busca Rocky en movies’ (hasta 10 resultados). "
                    "Categorías: películas, series, música, libros, juegos y software.\n"
                    "• Ver detalles: ‘detalles del 2’ o ‘detalles 2’.\n"
                    "• Bajar una opción: ‘baja el 2’ y luego ‘confirmo’.\n"
                    "• Ver la cola y el progreso: ‘qué está bajando’ o ‘qué bajo’.\n"
                    "• Consultar velocidad y espacio libre: ‘estado de descarga’.\n"
                    "• Ver las últimas descargas: ‘historial de descargas’.\n"
                    "• Pausar o reanudar: ‘pausa las descargas’ / ‘reanuda las descargas’, "
                    "y luego ‘confirmo’.\n"
                    "• Rechazar una operación pendiente: ‘cancelar’ o ‘no’."
                ),
            )
        ],
        permissions=[
            Permission(name=f"usenet.{action}", description=description)
            for action, (description, _) in ACTIONS.items()
        ],
        risk_level=RiskLevel.WRITE,
        timeout_seconds=90,
    )

    def __init__(
        self, client: UsenetClient | None, tools: ToolRegistry, approvals: ApprovalStore
    ) -> None:
        self._tools, self._approvals = tools, approvals
        self._states: dict[UUID, SearchState] = {}
        self._locks: defaultdict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._execution_lock = asyncio.Lock()
        for action in ACTIONS:
            tools.register(UsenetTool(action, client, approvals), authorized_agents={"usenet"})

    def reset_conversation(self, conversation_id: UUID) -> None:
        self._states.pop(conversation_id, None)

    def set_client(self, client: UsenetClient) -> None:
        # Saved choices belong to the previous provider connection.
        self._states.clear()
        for approval in self._approvals.all_approvals():
            if approval.agent_name == "usenet" and approval.status is ApprovalStatus.PENDING:
                self._approvals.reject(approval.id)
        for action in ACTIONS:
            self._tools.replace(
                UsenetTool(action, client, self._approvals), authorized_agents={"usenet"}
            )

    @staticmethod
    def _read_action(text: str) -> str | None:
        if text in {
            "que bajo",
            "que esta bajando",
            "que estoy bajando",
            "que se esta bajando",
            "descargas",
            "cola",
            "cola de descargas",
            "mis descargas",
        }:
            return "queue"
        if text in {
            "estado",
            "estado de descarga",
            "estado de descargas",
            "estado de la descarga",
            "estado de las descargas",
            "velocidad de descarga",
            "espacio libre",
        }:
            return "status"
        if text in {
            "historial",
            "historial de descargas",
            "ultimas descargas",
            "que se descargo",
            "que he bajado",
            "que baje",
        }:
            return "history"
        return None

    @staticmethod
    def _write_action(text: str) -> str | None:
        if text in {"pausa las descargas", "pausar descargas", "pausa descargas", "pausa todo"}:
            return "pause"
        if text in {
            "reanuda las descargas",
            "reanudar descargas",
            "reanuda descargas",
            "reanuda todo",
        }:
            return "resume"
        return None

    def select(self, message: IncomingMessage) -> str | None:
        text = normalized(message.content)
        if SEARCH.match(text) or SELECTION.match(text.replace("del ", "de el ")):
            return "usenet.downloads"
        if self._read_action(text) or self._write_action(text):
            return "usenet.downloads"
        if text in {"si", "confirmo", "confirmar", "yes", "no", "rechazo", "cancelar", "cancela"}:
            if self._approvals.pending_for_conversation(
                message.conversation_id, agent_name="usenet"
            ):
                return "usenet.downloads"
        return None

    async def run(self, request: AgentRequest) -> AgentResponse:
        async with self._locks[request.message.conversation_id]:
            try:
                return await self._run(request)
            except UsenetClientError as error:
                return self._response(request, error.safe_message, {"download_error": error.code})

    async def _read(self, action: str, **params: str) -> dict[str, str]:
        return (
            await self._tools.invoke(
                ToolInvocation(
                    tool_name=f"usenet.{action}",
                    agent_name="usenet",
                    input=dict(params),
                    risk_level=RiskLevel.READ,
                )
            )
        ).output

    async def _run(self, request: AgentRequest) -> AgentResponse:
        text = normalized(request.message.content)
        conversation = request.message.conversation_id
        pending = self._approvals.pending_for_conversation(conversation, agent_name="usenet")
        if text in {"si", "confirmo", "confirmar", "yes"}:
            if len(pending) != 1:
                return self._response(
                    request,
                    "No hay una única operación pendiente. Selecciona de nuevo qué quieres hacer.",
                )
            approved = self._approvals.approve(pending[0].id)
            await self._approvals.flush()
            result = await self.approve_operation(approved)
            if approved.tool_name == "usenet.download":
                content = (
                    f"Añadí {result['title']} a la cola (ID {result['download_id']}). "
                    "Consulta ‘qué está bajando’ para ver el progreso."
                )
            else:
                content = (
                    "Descargas pausadas."
                    if result["action"] == "pause"
                    else "Descargas reanudadas."
                )
            return self._response(request, content)
        if text in {"no", "rechazo", "cancelar", "cancela"}:
            if len(pending) == 1:
                self._approvals.reject(pending[0].id)
                await self._approvals.flush()
                return self._response(request, "Operación cancelada.")
            return self._response(request, "No hay una única operación pendiente que cancelar.")
        search = SEARCH.match(request.message.content.strip())
        if search:
            self._states.pop(conversation, None)
            query, category = self._search_query(search.group(1))
            data = await self._read("search", query=query, category=category)
            items = [SearchItem.model_validate(item) for item in json.loads(data["items"])][:10]
            self._states[conversation] = SearchState(items, time.monotonic())
            if not items:
                return self._response(
                    request, "No encontré resultados. Prueba otro título o categoría."
                )
            lines = [
                f"{index}. {item.title}\n   {item.size_bytes / 1024**3:.2f} GB · "
                f"categoría {item.category or 'sin especificar'}"
                for index, item in enumerate(items, 1)
            ]
            return self._response(
                request,
                "Encontré estas opciones:\n"
                + "\n".join(lines)
                + "\nDi ‘baja el 2’ para elegir una o ‘detalles 2’ para verla.",
                reaction_options=[
                    ReactionOption(emoji=f"{i}️⃣" if i < 10 else "🔟",
                                   label=item.title, command=f"baja el {i}")
                    for i, item in enumerate(items, 1)
                ],
            )
        selection = SELECTION.match(text.replace("del ", "de el "))
        if selection:
            state = self._states.get(conversation)
            if not state or time.monotonic() - state.created_at > SEARCH_TTL:
                self._states.pop(conversation, None)
                return self._response(
                    request, "Busca primero un título; las opciones duran 15 minutos."
                )
            index = int(selection.group(1))
            if not 1 <= index <= len(state.items):
                return self._response(
                    request, "Ese número no está en la lista. Elige una de las opciones mostradas."
                )
            item = state.items[index - 1]
            if text.startswith("detalle"):
                data = await self._read("details", item_id=item.id)
                detail = SearchItem.model_validate_json(data["item"])
                return self._response(
                    request,
                    f"{detail.title}\nTamaño: {detail.size_bytes / 1024**3:.2f} GB\n"
                    f"Categoría: {detail.category or 'sin especificar'}\n"
                    f"Publicado: {detail.published or 'sin fecha'}\n"
                    f"Para bajarlo, di ‘baja el {index}’.",
                )
            return await self._propose(
                request, "download", {"item_id": item.id, "title": item.title}
            )
        action = self._write_action(text)
        if action:
            return await self._propose(request, action, {})
        action = self._read_action(text)
        if action == "status":
            status = DownloadStatus.model_validate_json((await self._read(action))["status"])
            return self._response(
                request,
                f"Descargas {'pausadas' if status.paused else 'activas'}.\n"
                f"Velocidad: {status.speed_bytes / 1024**2:.2f} MB/s\n"
                f"Pendiente: {status.remaining_mb / 1024:.2f} GB\n"
                f"Espacio libre: {status.free_disk_mb / 1024:.2f} GB",
            )
        if action in {"queue", "history"}:
            data = await self._read(action)
            downloads = [DownloadItem.model_validate(item) for item in json.loads(data["items"])]
            if not downloads:
                return self._response(
                    request,
                    "La cola está vacía."
                    if action == "queue"
                    else "No hay descargas en el historial.",
                )
            lines = []
            for download in downloads[:10]:
                progress = (
                    max(0, min(100, 100 * (1 - download.remaining_mb / download.size_mb)))
                    if download.size_mb
                    else 0
                )
                label = self._status_label(download.status)
                lines.append(
                    f"• {download.title} · ID {download.id}\n  {label}"
                    + (
                        f" · {progress:.0f}% · quedan {download.remaining_mb / 1024:.2f} GB"
                        if action == "queue"
                        else ""
                    )
                )
            return self._response(
                request,
                ("En la cola:\n" if action == "queue" else "Últimas descargas:\n")
                + "\n".join(lines)
                + (f"\nMostrando 10 de {len(downloads)}." if len(downloads) > 10 else ""),
            )
        return self._response(
            request, self.definition.capabilities[0].help_text or "Escribe ‘ayuda’."
        )

    @staticmethod
    def _search_query(raw: str) -> tuple[str, str]:
        # Match the category suffix on normalized text but preserve title accents and casing.
        folded = normalized(raw)
        match = re.search(
            rf"\s+(?:en(?: la categoria)?|categoria)\s+({CATEGORY_PATTERN}|\d{{4}})$", folded
        )
        if match:
            category_name = match.group(1)
            query = raw[: match.start()].strip(' .,"')
            return query, CATEGORIES.get(category_name, category_name)
        return raw.strip(' .,"'), ""

    @staticmethod
    def _status_label(status: str) -> str:
        labels = {
            "DOWNLOADING": "Bajando",
            "QUEUED": "En espera",
            "PAUSED": "Pausada",
            "FETCHING": "Preparando",
            "UNPACKING": "Descomprimiendo",
            "REPAIRING": "Reparando",
            "MOVING": "Moviendo archivos",
            "PP_QUEUED": "Procesando",
            "PP_FINISHED": "Terminada",
        }
        if status.startswith("SUCCESS"):
            return "Completada"
        if status.startswith("FAILURE"):
            return "Fallida (" + status.split("/", 1)[-1] + ")"
        if status.startswith("DELETED"):
            return "Eliminada"
        return labels.get(status, status)

    async def _propose(
        self, request: AgentRequest, action: str, params: dict[str, str]
    ) -> AgentResponse:
        # Replace pending proposals so a plain 'confirmo' always has one concrete meaning.
        for pending in self._approvals.pending_for_conversation(
            request.message.conversation_id, agent_name="usenet"
        ):
            self._approvals.reject(pending.id)
        description = (
            f"Bajar {params['title']}"
            if action == "download"
            else (
                "Pausar todas las descargas"
                if action == "pause"
                else "Reanudar todas las descargas"
            )
        )
        approval = self._approvals.create(
            conversation_id=request.message.conversation_id,
            agent_name="usenet",
            tool_name=f"usenet.{action}",
            parameters=params,
            reason=description,
            idempotency_key=f"usenet:{request.message.id}:{action}",
        )
        await self._approvals.flush()
        return self._response(
            request,
            f"{description}.\nResponde ‘confirmo’ para hacerlo o ‘cancelar’. "
            "La confirmación vence en 5 minutos.",
            {"approval_id": str(approval.id)},
        )

    async def approve_operation(self, approval: ApprovalRequest) -> dict[str, str]:
        async with self._execution_lock:
            if approval.status is not ApprovalStatus.APPROVED or approval.agent_name != "usenet":
                raise PermissionError("La operación no está aprobada.")
            try:
                result = await self._tools.invoke(
                    ToolInvocation(
                        tool_name=approval.tool_name,
                        agent_name="usenet",
                        input=dict(approval.parameters),
                        risk_level=RiskLevel.WRITE,
                        approval_id=approval.id,
                    )
                )
            except (UsenetClientError, PermissionError) as error:
                self._approvals.mark_failed(
                    approval.id, {"error": getattr(error, "code", "unauthorized")}
                )
                await self._approvals.flush()
                raise
            self._approvals.mark_executed(approval.id, result.output)
            await self._approvals.flush()
            return result.output

    @staticmethod
    def _response(
        request: AgentRequest, content: str, metadata: dict[str, str] | None = None,
        reaction_options: list[ReactionOption] | None = None,
    ) -> AgentResponse:
        return AgentResponse(
            result=AgentResult(
                agent_name="usenet",
                content=content,
                reaction_options=reaction_options or [],
                metadata={"execution_id": str(request.execution_id), **(metadata or {})},
            )
        )
