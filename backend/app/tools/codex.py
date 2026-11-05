from uuid import UUID

from app.application.codex import CodexQueue
from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult


class CodexTool:
    def __init__(self, queue: CodexQueue, create_tool: bool = False) -> None:
        self.queue, self.create_tool = queue, create_tool
        self.definition = Tool(
            name="codex.create_tool" if create_tool else "codex.ask",
            description=(
                "Implementa código y pruebas directamente en el proyecto Artemis."
                if create_tool
                else "Envía una tarea a Codex con escritura y ejecución de comandos."
            ),
            risk_level=RiskLevel.WRITE,
            requires_approval=False,
            input_example={
                "prompt": "Explica las herramientas de Artemis",
                "conversation_id": "UUID de la conversación",
                "channel": "whatsapp",
                "message_id": "UUID del mensaje",
            },
        )

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        data = invocation.input
        job = self.queue.submit(
            UUID(str(data["message_id"])),
            UUID(str(data["conversation_id"])),
            str(data["channel"]),
            str(data["prompt"]),
            "tool" if self.create_tool else "chat",
        )
        return ToolResult(
            invocation_id=invocation.id, output={"id": str(job.id), "status": job.status}
        )
