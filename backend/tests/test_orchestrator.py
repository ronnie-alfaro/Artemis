import asyncio
from uuid import uuid4

from app.api.main import build_orchestrator
from app.domain.models import Channel, IncomingMessage


def test_status_capability_routing_and_parallel_nodes() -> None:
    orchestrator = build_orchestrator()
    message = IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="test"),
        content="parallel",
        required_capabilities=["assistant.status", "assistant.status"],
    )
    response = asyncio.run(orchestrator.handle(message))
    assert len(response.executions) == 2
    assert all(execution.agent_name == "status" for execution in response.executions)


def test_help_interrupts_skill_routing_without_changing_pending_approval() -> None:
    orchestrator = build_orchestrator()
    conversation = uuid4()
    approval = orchestrator.approvals.create(
        conversation_id=conversation, agent_name="seerr",
        tool_name="seerr.create_request", parameters={}, reason="test",
        idempotency_key="help-test",
    )
    for content in ["ayuda", " AYUDA! ", "/help", "¿Qué puedes hacer?"]:
        response = asyncio.run(orchestrator.handle(IncomingMessage(
            conversation_id=conversation,
            channel=Channel(name="whatsapp", allowed_capabilities=[
                "assistant.status", "seerr.media", "karakeep.bookmarks",
            ]), content=content,
        )))
        assert response.executions[0].agent_name == "status"
        assert (
            "Seerr: Consulta pendientes y estados, solicita títulos y usa la API de Seerr."
            in response.message.content
        )
        assert "Karakeep: Busca y guarda enlaces." in response.message.content
        assert "Preparar una solicitud" not in response.message.content
        assert "Cancelar el guardado" not in response.message.content
        assert orchestrator.approvals.pending_for_conversation(conversation)[0].id == approval.id


def test_help_only_lists_assigned_skills() -> None:
    response = asyncio.run(build_orchestrator().handle(IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="whatsapp", allowed_capabilities=["assistant.status", "seerr.media"]),
        content="ayuda",
    )))
    assert "Seerr" in response.message.content
    assert "Karakeep" not in response.message.content


def test_help_lists_all_skills_for_unrestricted_channel() -> None:
    response = asyncio.run(build_orchestrator().handle(IncomingMessage(
        conversation_id=uuid4(), channel=Channel(name="rest"), content="ayuda",
    )))
    assert "Seerr" in response.message.content
    assert "Karakeep" in response.message.content
