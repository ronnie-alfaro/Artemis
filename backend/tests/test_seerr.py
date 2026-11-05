# ruff: noqa: E501

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.main import build_orchestrator
from app.application.approvals import ApprovalStore
from app.domain.models import Channel, IncomingMessage, RiskLevel, ToolInvocation, utcnow
from app.domain.seerr import (
    MediaType,
    SeerrClientError,
    SeerrClientErrorCode,
    SeerrMedia,
    SeerrRequestInput,
    SeerrRequestResult,
    SeerrRequestStatus,
    SeerrSearchResult,
    SeerrSettings,
)
from app.infrastructure.seerr_http import HttpSeerrClient
from app.tools.registry import ApprovalRequired, ToolRegistry
from app.tools.seerr import SeerrRequestTool


class FakeSeerr:
    def __init__(self) -> None:
        self.created = 0

    async def search_media(self, query: str) -> SeerrSearchResult:
        return SeerrSearchResult(
            results=[
                SeerrMedia(
                    media_type=MediaType.MOVIE, tmdb_id=693134, title="Dune: Part Two", year=2024
                ),
                SeerrMedia(media_type=MediaType.MOVIE, tmdb_id=438631, title="Dune", year=2021),
            ]
        )

    async def get_media_details(self, media_type: MediaType, tmdb_id: int) -> SeerrMedia:
        return SeerrMedia(media_type=media_type, tmdb_id=tmdb_id, title="Dune", year=2024)

    async def create_request(self, request: SeerrRequestInput) -> SeerrRequestResult:
        self.created += 1
        return SeerrRequestResult(request_id=42, status="pending")

    async def get_request_status(self, request_id: int) -> SeerrRequestStatus:
        return SeerrRequestStatus(request_id=request_id, status="pending")


def test_http_client_sends_api_key_and_normalizes_search() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["X-Api-Key"]
        assert request.url.path == "/api/v1/search"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": 1, "mediaType": "movie", "title": "Dune", "releaseDate": "2024-03-01"}
                ]
            },
        )

    client = HttpSeerrClient(
        SeerrSettings.model_validate({"base_url": "https://seerr.example", "api_key": "test-key"}),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = asyncio.run(client.search_media("Dune"))
    assert seen["key"] == "test-key"
    assert result.results[0].title == "Dune"
    assert result.results[0].year == 2024


@pytest.mark.parametrize(
    "status,code",
    [
        (401, SeerrClientErrorCode.UNAUTHORIZED),
        (403, SeerrClientErrorCode.FORBIDDEN),
        (404, SeerrClientErrorCode.NOT_FOUND),
        (409, SeerrClientErrorCode.DUPLICATE),
    ],
)
def test_http_client_maps_safe_errors(status: int, code: SeerrClientErrorCode) -> None:
    client = HttpSeerrClient(
        SeerrSettings.model_validate({"base_url": "https://seerr.example", "api_key": "secret"}),
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text="do not leak")
            )
        ),
    )
    with pytest.raises(SeerrClientError) as error:
        asyncio.run(client.search_media("Dune"))
    assert error.value.code is code
    assert "leak" not in error.value.safe_message


def test_write_tool_requires_current_approval_and_agent_authorization() -> None:
    fake, approvals = FakeSeerr(), ApprovalStore()
    tools = ToolRegistry(approvals)
    tools.register(SeerrRequestTool(fake), authorized_agents={"seerr"})
    invocation = ToolInvocation(
        tool_name="seerr.create_request",
        agent_name="other",
        input={"media_type": "movie", "tmdb_id": 1, "requester": "r"},
        risk_level=RiskLevel.WRITE,
    )
    with pytest.raises(PermissionError):
        asyncio.run(tools.invoke(invocation))
    invocation.agent_name = "seerr"
    with pytest.raises(ApprovalRequired):
        asyncio.run(tools.invoke(invocation))


def test_e2e_search_selection_approval_and_idempotency() -> None:
    fake = FakeSeerr()
    orchestrator, conversation = build_orchestrator(fake), uuid4()

    def send(content: str):
        return asyncio.run(
            orchestrator.handle(
                IncomingMessage(
                    conversation_id=conversation, channel=Channel(name="rest"), content=content
                )
            )
        )

    search = send("quiero pedir Dune 2")
    assert search.executions[0].agent_name == "seerr"
    assert "Dune: Part Two" in search.message.content
    pending = send("1")
    approval_id = pending.executions[0].result.metadata["approval_id"]
    final = send("confirmo")
    assert "Solicitud creada" in final.message.content
    approval = orchestrator.approvals.get(UUID(approval_id))
    assert approval.status.value == "executed"
    assert fake.created == 1
    again = send("confirmo")
    assert "No hay una única operación" in again.message.content
    assert fake.created == 1


def test_expired_and_rejected_confirmation_do_not_execute() -> None:
    orchestrator, conversation = build_orchestrator(FakeSeerr()), uuid4()

    def send(content: str):
        return asyncio.run(
            orchestrator.handle(
                IncomingMessage(
                    conversation_id=conversation, channel=Channel(name="rest"), content=content
                )
            )
        )

    send("solicitar Dune")
    pending = send("1")
    approval_id = UUID(pending.executions[0].result.metadata["approval_id"])
    approval = orchestrator.approvals.get(approval_id)
    approval.expires_at = utcnow() - timedelta(seconds=1)
    expired = send("confirmo")
    assert "No hay una única operación" in expired.message.content


def test_unconfigured_seerr_returns_a_safe_configuration_error() -> None:
    orchestrator, conversation = build_orchestrator(), uuid4()
    response = asyncio.run(
        orchestrator.handle(
            IncomingMessage(
                conversation_id=conversation,
                channel=Channel(name="test"),
                content="quiero pedir Dune",
            )
        )
    )
    assert "Seerr no está configurado" in response.message.content


def test_connection_checks_authenticated_user_without_search() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/me"
        assert request.headers["X-Api-Key"] == "test-key"
        return httpx.Response(200, json={"id": 1})

    client = HttpSeerrClient(
        SeerrSettings.model_validate({"base_url": "http://seerr:5055", "api_key": "test-key"}),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    asyncio.run(client.test_connection())


@pytest.mark.parametrize("status", [401, 403])
def test_connection_rejects_invalid_credentials(status: int) -> None:
    client = HttpSeerrClient(
        SeerrSettings.model_validate({"base_url": "http://seerr:5055", "api_key": "invalid"}),
        httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"message": "denied"})
        )),
    )
    with pytest.raises(SeerrClientError):
        asyncio.run(client.test_connection())


@pytest.mark.parametrize(
    "query,encoded",
    [
        ("dog stars", b"query=dog%20stars"),
        ("Amélie & Dog+Stars?", b"query=Am%C3%A9lie%20%26%20Dog%2BStars%3F"),
    ],
)
def test_search_encodes_spaces_and_reserved_characters(query: str, encoded: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.query == encoded
        assert request.url.params["query"] == query
        return httpx.Response(200, json={"results": []})

    client = HttpSeerrClient(
        SeerrSettings.model_validate({"base_url": "http://seerr:5055", "api_key": "test-key"}),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert asyncio.run(client.search_media(query)).results == []
