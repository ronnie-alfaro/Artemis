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
    assert "Karakeep is not configured" in confirmation.message.content
