from __future__ import annotations

import json

from app.application.approvals import ApprovalStore
from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.domain.usenet import UsenetClient, UsenetClientError

# Labels shown to operators and returned by the tool inventory use natural language.
ACTIONS = {
    "search": ("Buscar títulos por categoría (hasta 10 resultados).", RiskLevel.READ),
    "details": ("Ver los detalles de un resultado.", RiskLevel.READ),
    "queue": ("Consultar qué está bajando y su progreso.", RiskLevel.READ),
    "status": ("Consultar velocidad, espacio libre y estado de descarga.", RiskLevel.READ),
    "history": ("Ver las últimas descargas y sus resultados.", RiskLevel.READ),
    "download": ("Bajar un resultado seleccionado y aprobado.", RiskLevel.WRITE),
    "pause": ("Pausar las descargas con confirmación.", RiskLevel.WRITE),
    "resume": ("Reanudar las descargas con confirmación.", RiskLevel.WRITE),
}


class UsenetTool:
    def __init__(self, action: str, client: UsenetClient | None, approvals: ApprovalStore) -> None:
        description, risk = ACTIONS[action]
        self.definition = Tool(
            name=f"usenet.{action}", description=description, risk_level=risk, timeout_seconds=60,
            input_example=(
                {"query": "título", "category": ""} if action == "search"
                else {"item_id": "ID del resultado"} if action == "details" else {}
            ),
        )
        self.action, self._client, self._approvals = action, client, approvals

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        if self._client is None:
            raise UsenetClientError(
                "configuration",
                "Configura las conexiones del skill Usenet en Skills antes de usarlo.",
            )
        if self.definition.risk_level is RiskLevel.WRITE:
            if invocation.approval_id is None:
                raise PermissionError("La operación requiere confirmación.")
            approval = self._approvals.get(invocation.approval_id)
            if approval.agent_name != "usenet" or invocation.input != approval.parameters:
                raise PermissionError("La confirmación no corresponde a esta operación.")
        data = invocation.input
        output: dict[str, str]
        if self.action == "search":
            result = await self._client.search(str(data["query"]), str(data.get("category", "")))
            output = {"items": json.dumps([item.model_dump() for item in result])}
        elif self.action == "details":
            detail = await self._client.details(str(data["item_id"]))
            output = {"item": detail.model_dump_json()}
        elif self.action in {"queue", "history"}:
            downloads = await (
                self._client.queue() if self.action == "queue" else self._client.history()
            )
            output = {"items": json.dumps([item.model_dump() for item in downloads])}
        elif self.action == "status":
            output = {"status": (await self._client.status()).model_dump_json()}
        elif self.action == "download":
            identifier = await self._client.download(str(data["item_id"]), str(data["title"]))
            output = {"download_id": str(identifier), "title": str(data["title"])}
        else:
            if self.action == "pause":
                await self._client.pause()
            else:
                await self._client.resume()
            output = {"action": self.action}
        return ToolResult(invocation_id=invocation.id, output=output)
