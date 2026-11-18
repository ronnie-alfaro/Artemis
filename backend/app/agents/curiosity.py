import re
from uuid import UUID

from pydantic import ValidationError

from app.domain.curiosity import CAPABILITY, CHAT_CONTEXT_KEY, COMMAND_NAME, chat_command
from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    RiskLevel,
    ToolInvocation,
)
from app.tools.curiosity import CuriosityError, CuriosityTool
from app.tools.registry import ToolRegistry

_MOUNT = re.compile(rf"integrar ({COMMAND_NAME}) (https://[^\s]+)(?:[^\S\n]*\n(.+))?", re.I | re.S)
_LEARN = re.compile(r"aprender (https://[^\s]+)(?:[^\S\n]*\n(.+))?", re.I | re.S)
_CALL = re.compile(rf"consultar ({COMMAND_NAME}) ({COMMAND_NAME})", re.I)
_REMOVE = re.compile(rf"retirar ({COMMAND_NAME})", re.I)

HELP = (
    "• Aprende esta API https://ejemplo.com/openapi.json\n"
    "• Curiosidad integrar NOMBRE URL_OPENAPI_JSON\n"
    "• Curiosidad consultar NOMBRE OPERACIÓN\n"
    "• Curiosidad retirar NOMBRE"
)


class CuriosityAgent:
    definition = Agent(
        name="curiosity",
        version="0.1.0",
        purpose="Integra y consulta APIs de lectura desde el chat.",
        capabilities=[
            AgentCapability(
                name=CAPABILITY,
                description="Integra y consulta APIs mediante comandos directos.",
                help_text=HELP,
            )
        ],
        timeout_seconds=15,
    )

    def __init__(self, tools: ToolRegistry, adapter: CuriosityTool) -> None:
        self._tools = tools
        self.adapter = adapter

    async def run(self, request: AgentRequest) -> AgentResponse:
        message = request.message
        content = HELP
        command = chat_command(message.content)
        if (
            message.channel.name not in {"whatsapp", "telegram"}
            or CAPABILITY not in message.channel.allowed_capabilities
        ):
            content = "Curiosidad no está asignada a esta conversación."
        elif command is not None:
            direct = request.context.get(CHAT_CONTEXT_KEY) == "true"
            try:
                if (
                    direct
                    or CAPABILITY in message.required_capabilities
                    and _CALL.fullmatch(command)
                ):
                    content = await self._handle(
                        message.channel.name, message.conversation_id, command
                    )
            except CuriosityError as error:
                content = str(error)
            except ValidationError:
                content = "La documentación supera los límites admitidos o está vacía."
        return AgentResponse(
            result=AgentResult(
                agent_name="curiosity",
                content=content,
                metadata={"execution_id": str(request.execution_id)},
            )
        )

    async def _handle(self, channel: str, conversation: UUID, command: str) -> str:
        learn = _LEARN.fullmatch(command)
        mount = _MOUNT.fullmatch(command)
        api = None
        if mount:
            api = await self.adapter.mount(
                channel, conversation, mount[1].lower(), mount[2], mount[3]
            )
        elif learn:
            api = await self.adapter.mount(channel, conversation, None, learn[1], learn[2])
        if api:
            operations = "\n".join(
                f"• Curiosidad consultar {api.name} {item.operation}" for item in api.operations
            )
            return f"Integración de lectura guardada. Prueba una operación:\n{operations}"
        if match := _CALL.fullmatch(command):
            result = await self._tools.invoke(
                ToolInvocation(
                    tool_name=self.adapter.definition.name,
                    agent_name="curiosity",
                    risk_level=RiskLevel.READ,
                    input={
                        "channel": channel,
                        "conversation": str(conversation),
                        "name": match[1].lower(),
                        "operation": match[2],
                    },
                )
            )
            return result.output["data"]
        if match := _REMOVE.fullmatch(command):
            removed = await self.adapter.remove(channel, conversation, match[1].lower())
            return "Integración retirada." if removed else "No encuentro esa integración."
        return HELP
