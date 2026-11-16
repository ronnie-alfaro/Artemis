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


def test_pending_http_paginates_and_resolves_movie_and_tv_titles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/api/v1/request":
            assert dict(request.url.params) == {
                "filter": "unavailable", "take": "10", "skip": "10", "sort": "added"
            }
            return httpx.Response(200, json={"pageInfo": {"results": 12}, "results": [
                {"id": 41, "type": "movie", "status": 1, "media": {"tmdbId": 1}},
                {"id": 42, "type": "tv", "status": 2, "media": {"tmdbId": 2}},
            ]})
        if request.url.path == "/api/v1/movie/1":
            return httpx.Response(200, json={"id": 1, "title": "Dune", "releaseDate": "2021-01-01"})
        assert request.url.path == "/api/v1/tv/2"
        return httpx.Response(200, json={"id": 2, "name": "Dark", "firstAirDate": "2017-01-01"})

    client = HttpSeerrClient(
        SeerrSettings(base_url="https://seerr.example", api_key="test-key"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = asyncio.run(client.list_pending_requests(2))
    assert result.total == 12
    assert result.page == 2
    assert [item.media.title for item in result.results] == ["Dune", "Dark"]
    assert result.results[0].status == "pendiente de aprobación"
    assert "disponibilidad" in result.results[1].status


@pytest.mark.parametrize("payload", [{}, {"results": [None]}, {"results": [], "pageInfo": {}}])
def test_pending_rejects_malformed_response(payload: object) -> None:
    client = HttpSeerrClient(
        SeerrSettings(base_url="https://seerr.example", api_key="test-key"),
        httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )),
    )
    with pytest.raises(SeerrClientError) as error:
        asyncio.run(client.list_pending_requests())
    assert error.value.code == SeerrClientErrorCode.UNEXPECTED


@pytest.mark.parametrize("empty", [False, True])
def test_pending_intent_is_read_only_and_preserves_local_approval(empty: bool) -> None:
    from app.domain.seerr import SeerrPendingRequest, SeerrPendingRequests

    class PendingSeerr(FakeSeerr):
        async def list_pending_requests(self, page: int = 1) -> SeerrPendingRequests:
            return SeerrPendingRequests(
                results=[] if empty else [SeerrPendingRequest(
                    request_id=42,
                    media=SeerrMedia(media_type=MediaType.TV, tmdb_id=2, title="Dark"),
                    status="pendiente de aprobación",
                )], total=0 if empty else 11, page=page,
            )

    fake = PendingSeerr()
    orchestrator, conversation = build_orchestrator(fake), uuid4()

    def send(content: str):
        return asyncio.run(orchestrator.handle(IncomingMessage(
            conversation_id=conversation, channel=Channel(name="rest"), content=content,
        )))

    first = send("ver títulos pendientes")
    assert first.executions[0].agent_name == "seerr"
    assert ("No hay títulos pendientes" if empty else "Dark") in first.message.content
    if not empty:
        assert "página 2" in first.message.content
    send("pedir Dune")
    selected = send("1")
    approval_id = UUID(selected.executions[0].result.metadata["approval_id"])
    send("solicitudes pendientes")
    assert orchestrator.approvals.get(approval_id).status.value == "pending"
    assert fake.created == 0
    assert "Solicitud creada" in send("confirmo").message.content


def test_pending_unconfigured_error() -> None:
    orchestrator = build_orchestrator()
    response = asyncio.run(orchestrator.handle(IncomingMessage(
        conversation_id=uuid4(), channel=Channel(name="rest"), content="ver títulos pendientes",
    )))
    assert "Seerr no está configurado" in response.message.content


@pytest.mark.parametrize("path", [
    "https://evil.example/api/v1/request", "//evil.example/api/v1/request",
    "/api/v1/../auth", "/api/v1/%2e%2e/auth", "/api/v1/request#fragment",
    "/api/v1/request\\evil", "/api/v1/request\r\nX-Test: yes",
])
def test_api_rejects_paths_outside_seerr(path: str) -> None:
    from pydantic import ValidationError

    from app.domain.seerr import SeerrApiInput

    with pytest.raises(ValidationError):
        SeerrApiInput(path=path)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_api_http_methods_body_and_empty_response(method: str) -> None:
    from app.domain.seerr import SeerrApiInput

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == method
        assert request.url.path == "/api/v1/request/42"
        assert request.url.params["filter"] == "pending"
        assert request.headers["X-Api-Key"] == "test-key"
        if method != "GET":
            assert request.content == b'{"seasons":[1]}'
        return httpx.Response(204) if method == "DELETE" else httpx.Response(200, json={"id": 42})

    client = HttpSeerrClient(
        SeerrSettings(base_url="https://seerr.example", api_key="test-key"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = asyncio.run(client.api_request(SeerrApiInput(
        method=method, path="/api/v1/request/42?filter=pending",
        body=None if method == "GET" else {"seasons": [1]},
    )))
    assert result == (None if method == "DELETE" else {"id": 42})


def test_api_e2e_reads_confirmations_cancel_replay_and_redaction() -> None:
    class ApiSeerr(FakeSeerr):
        def __init__(self):
            super().__init__()
            self.calls = []

        async def api_request(self, request):
            self.calls.append(request)
            return {"id": 42, "nested": {"apiKey": "sensitive-value"}}

    fake = ApiSeerr()
    orchestrator, conversation = build_orchestrator(fake), uuid4()

    def send(content):
        return asyncio.run(orchestrator.handle(IncomingMessage(
            conversation_id=conversation, channel=Channel(name="rest"), content=content,
        )))

    assert "pending" in send("estado solicitud 42").message.content
    read = send("seerr api GET /api/v1/request?filter=pending")
    assert '"id": 42' in read.message.content
    assert "sensitive-value" not in read.message.content
    assert len(fake.calls) == 1
    prepared = send('seerr api PUT /api/v1/request/42 {"seasons":[1]}')
    assert len(fake.calls) == 1
    approval_id = UUID(prepared.executions[0].result.metadata["approval_id"])
    assert orchestrator.approvals.get(approval_id).status.value == "pending"
    done = send("confirmo")
    assert "ejecutada" in done.message.content
    assert "sensitive-value" not in done.message.content
    assert fake.calls[-1].body == {"seasons": [1]}
    assert orchestrator.approvals.get(approval_id).status.value == "executed"
    send("confirmo")
    assert len(fake.calls) == 2
    send("seerr api DELETE /api/v1/request/42")
    send("cancelar")
    send("confirmo")
    assert len(fake.calls) == 2
    send("seerr api POST /api/v1/request {invalid}")
    assert len(fake.calls) == 2


@pytest.mark.parametrize("status,label", [(1, "pendiente de aprobación"), (2, "aprobada"), (3, "rechazada")])
def test_request_status_includes_availability(status: int, label: str) -> None:
    client = HttpSeerrClient(
        SeerrSettings(base_url="https://seerr.example", api_key="test-key"),
        httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": status, "media": {"status": 5}})
        )),
    )
    result = asyncio.run(client.get_request_status(42))
    assert label in result.status
    assert "contenido: disponible" in result.status


def test_api_write_tool_requires_approval() -> None:
    from app.tools.seerr import SeerrApiTool

    tools = ToolRegistry(ApprovalStore())
    tools.register(SeerrApiTool(FakeSeerr()), authorized_agents={"seerr"})
    with pytest.raises(ApprovalRequired):
        asyncio.run(tools.invoke(ToolInvocation(
            tool_name="seerr.api_write", agent_name="seerr", risk_level=RiskLevel.ADMIN,
            input={"method": "DELETE", "path": "/api/v1/request/42"},
        )))


@pytest.mark.parametrize("payload", [{}, {"status": True}, {"status": []}, {"status": 7}])
def test_status_rejects_invalid_response(payload: object) -> None:
    client = HttpSeerrClient(
        SeerrSettings(base_url="https://seerr.example", api_key="test-key"),
        httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )),
    )
    with pytest.raises(SeerrClientError):
        asyncio.run(client.get_request_status(42))


def test_api_control_plane_approval_executes_once() -> None:
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    class ApiSeerr(FakeSeerr):
        async def api_request(self, request):
            self.created += 1
            return None

    fake = ApiSeerr()
    app = create_app()
    orchestrator = build_orchestrator(fake)
    app.state.orchestrator = orchestrator
    prepared = asyncio.run(orchestrator.handle(IncomingMessage(
        conversation_id=uuid4(), channel=Channel(name="rest"),
        content="seerr api DELETE /api/v1/request/42",
    )))
    approval_id = prepared.executions[0].result.metadata["approval_id"]
    client = TestClient(app)
    response = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "executed"
    assert fake.created == 1
    with pytest.raises(PermissionError, match="executed"):
        client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert fake.created == 1
