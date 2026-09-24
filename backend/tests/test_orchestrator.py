import asyncio
from uuid import uuid4

from app.api.main import build_orchestrator
from app.domain.models import Channel, IncomingMessage


def test_capability_routing_and_parallel_nodes() -> None:
    orchestrator = build_orchestrator()
    message = IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="test"),
        content="parallel",
        required_capabilities=["fake.echo", "fake.echo"],
    )
    response = asyncio.run(orchestrator.handle(message))
    assert len(response.executions) == 2
    assert all(execution.agent_name == "fake" for execution in response.executions)
