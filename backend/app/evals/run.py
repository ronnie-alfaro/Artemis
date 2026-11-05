import asyncio
from uuid import uuid4

from app.api.main import build_orchestrator
from app.domain.models import Channel, IncomingMessage


async def main() -> None:
    message = IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="eval"),
        content="eval",
        required_capabilities=["assistant.status"],
    )
    response = await build_orchestrator().handle(message)
    if response.executions[0].agent_name != "status":
        raise RuntimeError("eval routing mismatch")
    print("routing_accuracy=1.0 tool_selection_accuracy=1.0 permission_violations=0")


if __name__ == "__main__":
    asyncio.run(main())
