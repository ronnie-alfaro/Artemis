from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.main import build_orchestrator
from app.domain.karakeep import KarakeepBookmark, KarakeepClientError, KarakeepSettings
from app.domain.models import Channel, IncomingMessage
from app.infrastructure.karakeep_http import HttpKarakeepClient


class FakeKarakeep:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.queries: list[str] = []
        self.results = [KarakeepBookmark(
            id="saved-1", title="Docker tutorial", url="https://example.com/docker",
            description="Una guía para empezar.",
        )]

    async def search_bookmarks(self, query: str) -> list[KarakeepBookmark]:
        self.queries.append(query)
        return self.results

    async def list_lists(self) -> None:
        return None

    async def create_link(self, url: str, title: str | None = None) -> KarakeepBookmark:
        self.created.append(url)
        return KarakeepBookmark(id="bookmark-42", url=url, title=title)


def test_http_client_sends_bearer_key_and_creates_link() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        seen["path"] = request.url.path
        seen["payload"] = request.content
        return httpx.Response(201, json={"id": "bookmark-42", "url": "https://example.com"})

    client = HttpKarakeepClient(
        KarakeepSettings.model_validate(
            {"base_url": "https://karakeep.example", "api_key": "test-key"}
        ),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = asyncio.run(client.create_link("https://example.com"))
    assert seen["authorization"] == "Bearer test-key"
    assert seen["path"] == "/api/v1/bookmarks"
    assert seen["payload"] == b'{"type":"link","url":"https://example.com"}'
    assert result.id == "bookmark-42"


def test_http_client_maps_safe_authentication_errors() -> None:
    client = HttpKarakeepClient(
        KarakeepSettings.model_validate(
            {"base_url": "https://karakeep.example", "api_key": "secret"}
        ),
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(401, text="do not leak"))
        ),
    )
    with pytest.raises(KarakeepClientError) as error:
        asyncio.run(client.list_lists())
    assert error.value.code == "unauthorized"
    assert "leak" not in error.value.safe_message


def test_e2e_save_requires_confirmation_then_creates_bookmark() -> None:
    fake, conversation = FakeKarakeep(), uuid4()
    orchestrator = build_orchestrator(karakeep_client=fake)

    def send(content: str):
        return asyncio.run(
            orchestrator.handle(
                IncomingMessage(
                    conversation_id=conversation,
                    channel=Channel(name="rest"),
                    content=content,
                )
            )
        )

    pending = send("guarda https://example.com/hello")
    assert pending.executions[0].agent_name == "karakeep"
    approval_id = pending.executions[0].result.metadata["approval_id"]
    final = send("confirmo")
    assert "Enlace guardado" in final.message.content
    assert orchestrator.approvals.get(UUID(approval_id)).status.value == "executed"
    assert fake.created == ["https://example.com/hello"]


def test_unconfigured_karakeep_returns_a_safe_configuration_error() -> None:
    orchestrator, conversation = build_orchestrator(), uuid4()
    response = asyncio.run(
        orchestrator.handle(
            IncomingMessage(
                conversation_id=conversation,
                channel=Channel(name="test"),
                content="guarda https://example.com",
            )
        )
    )
    pending = response.executions[0].result.metadata["approval_id"]
    confirmation = asyncio.run(
        orchestrator.handle(
            IncomingMessage(
                conversation_id=conversation,
                channel=Channel(name="test"),
                content="confirmo",
            )
        )
    )
    assert pending
    assert "Karakeep no está configurado" in confirmation.message.content


def test_http_search_uses_api_and_parses_link_and_text_bookmarks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/bookmarks/search"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert dict(request.url.params) == {
            "q": "docker & compose", "limit": "5", "sortOrder": "relevance",
            "includeContent": "false",
        }
        return httpx.Response(200, json={"bookmarks": [
            {"id": "1", "title": None, "summary": "Resumen guardado", "content": {
                "type": "link", "url": "https://example.com", "title": "Título de la página",
            }},
            {"id": "2", "title": "Una nota", "content": {"type": "text", "text": "Texto"}},
        ], "nextCursor": None})

    client = HttpKarakeepClient(
        KarakeepSettings(base_url="https://karakeep.example", api_key="test-key"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    results = asyncio.run(client.search_bookmarks("docker & compose"))
    assert results[0].title == "Título de la página"
    assert results[0].url == "https://example.com"
    assert results[0].description == "Resumen guardado"
    assert results[1].url is None


@pytest.mark.parametrize("payload", [{}, {"bookmarks": None}, {"bookmarks": [{}]}])
def test_http_search_rejects_malformed_results(payload) -> None:
    client = HttpKarakeepClient(
        KarakeepSettings(base_url="https://karakeep.example", api_key="test-key"),
        httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        )),
    )
    with pytest.raises(KarakeepClientError):
        asyncio.run(client.search_bookmarks("docker"))


@pytest.mark.parametrize("command", [
    "busca docker en mis bookmarks", "busca en karakeep docker",
    "BUSCA docker EN MIS ENLACES GUARDADOS", "busca docker en karakeep",
])
def test_whatsapp_search_returns_saved_links_without_approval(command: str) -> None:
    fake = FakeKarakeep()
    orchestrator = build_orchestrator(karakeep_client=fake)
    conversation = uuid4()
    # A pending save must survive the read operation.
    pending = orchestrator.approvals.create(
        conversation_id=conversation, agent_name="karakeep",
        tool_name="karakeep.create_bookmark", parameters={"url": "https://example.com"},
        reason="test", idempotency_key="search-test",
    )
    response = asyncio.run(orchestrator.handle(IncomingMessage(
        conversation_id=conversation,
        channel=Channel(name="whatsapp", allowed_capabilities=["karakeep.bookmarks"]),
        content=command,
    )))
    assert response.executions[0].agent_name == "karakeep"
    assert "1. Docker tutorial" in response.message.content
    assert "https://example.com/docker" in response.message.content
    assert "Una guía para empezar." in response.message.content
    assert fake.queries == ["docker"]
    assert fake.created == []
    assert orchestrator.approvals.pending_for_conversation(conversation) == [pending]


def test_search_handles_empty_query_no_results_and_unconfigured_client() -> None:
    fake = FakeKarakeep()
    fake.results = []
    orchestrator = build_orchestrator(karakeep_client=fake)

    def send(content, runtime=orchestrator):
        return asyncio.run(runtime.handle(IncomingMessage(
            conversation_id=uuid4(), channel=Channel(name="whatsapp"), content=content,
        ))).message.content

    assert "Indica qué buscar" in send("busca en karakeep")
    assert fake.queries == []
    assert "No encontré marcadores" in send("busca en karakeep inexistente")
    assert "no está configurado" in send("busca en karakeep docker", build_orchestrator())


def test_search_does_not_expose_bookmarks_to_unbound_channel() -> None:
    fake = FakeKarakeep()
    response = asyncio.run(build_orchestrator(karakeep_client=fake).handle(IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="whatsapp", allowed_capabilities=["assistant.status"]),
        content="busca en karakeep docker",
    )))
    assert response.executions[0].agent_name == "status"
    assert fake.queries == []


def test_search_response_fits_whatsapp_and_keeps_urls_intact() -> None:
    fake = FakeKarakeep()
    fake.results = [KarakeepBookmark(
        id=str(index), title="Título" * 100,
        url="https://example.com/" + "a" * 2000, description="Texto" * 200,
    ) for index in range(5)]
    response = asyncio.run(build_orchestrator(karakeep_client=fake).handle(IncomingMessage(
        conversation_id=uuid4(), channel=Channel(name="whatsapp"),
        content="busca en karakeep docker",
    )))
    assert len(response.message.content) <= 4096
    assert fake.results[0].url in response.message.content
    assert "Acota la búsqueda" in response.message.content
