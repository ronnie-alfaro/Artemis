from __future__ import annotations

import asyncio
import base64
import time
import xmlrpc.client
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.api.main import build_orchestrator, create_app
from app.domain.models import Channel, IncomingMessage, RiskLevel, ToolInvocation, utcnow
from app.domain.usenet import (
    DownloadItem,
    DownloadStatus,
    SearchItem,
    UsenetClientError,
    UsenetConfigurationInput,
    UsenetSettings,
)
from app.infrastructure.usenet_config import PostgresUsenetConfigurationStore
from app.infrastructure.usenet_http import HttpUsenetClient

SETTINGS = dict(
    provider_url="https://provider.example/api",
    provider_api_key="provider-secret",
    nzbget_url="https://downloads.example/nzbget/xmlrpc",
    nzbget_username="operator",
    nzbget_password="download-secret",
)
NZB = (
    b'<?xml version="1.0"?><nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">'
    b'<file subject="test"><groups><group>test</group></groups><segments>'
    b'<segment bytes="1" number="1">id</segment></segments></file></nzb>'
)
FEED = (
    b'<rss xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/"><channel>'
    b"<item><title>Rocky 1976</title><guid>https://provider.example/details/abc123</guid>"
    b'<enclosure length="1073741824"/><newznab:attr name="category" value="2000"/>'
    b"<pubDate>Mon, 02 Nov 2026 00:00:00 GMT</pubDate></item></channel></rss>"
)


def http_client(handler) -> HttpUsenetClient:
    return HttpUsenetClient(
        UsenetSettings.model_validate(SETTINGS),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_provider_search_uses_category_and_encoded_query() -> None:
    def handler(request):
        assert request.url.params["t"] == "search"
        assert request.url.params["q"] == "Rocky & Creed"
        assert request.url.params["cat"] == "2000"
        assert request.url.params["limit"] == "10"
        assert request.url.params["apikey"] == "provider-secret"
        assert b"Rocky%20%26%20Creed" in request.url.query
        return httpx.Response(200, content=FEED)

    items = asyncio.run(http_client(handler).search("Rocky & Creed", "2000"))
    assert items[0].id == "abc123"
    assert items[0].title == "Rocky 1976"
    assert items[0].size_bytes == 1073741824


def test_download_transfers_file_content_without_provider_secrets() -> None:
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "GET":
            assert request.url.params["t"] == "get"
            assert request.url.params["id"] == "abc123"
            return httpx.Response(200, content=NZB)
        params, method = xmlrpc.client.loads(request.content)
        assert method == "append"
        assert params[0] == "Rocky.nzb"
        assert base64.b64decode(params[1]) == NZB
        assert params[6] == "artemis:abc123"
        assert params[-1] == []
        assert "provider-secret" not in request.content.decode()
        assert "provider-secret" not in str(request.url)
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, content=xmlrpc.client.dumps((42,), methodresponse=True))

    assert asyncio.run(http_client(handler).download("abc123", "Rocky")) == 42
    assert len(seen) == 2


@pytest.mark.parametrize(
    "content",
    [
        b'<error code="100" description="provider-secret"/>',
        b"<html>login</html>",
        b"not xml",
        b'<!DOCTYPE nzb [<!ENTITY x SYSTEM "file:///etc/passwd">]><nzb>&x;</nzb>',
    ],
)
def test_invalid_downloads_never_reach_downloader(content: bytes) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=content)

    with pytest.raises(UsenetClientError) as error:
        asyncio.run(http_client(handler).download("abc", "Rocky"))
    assert "provider-secret" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="download-secret"),
        httpx.Response(200, content=xmlrpc.client.dumps(xmlrpc.client.Fault(1, "download-secret"))),
        httpx.Response(200, text="<invalid>"),
    ],
)
def test_rpc_errors_are_safe(response: httpx.Response) -> None:
    with pytest.raises(UsenetClientError) as error:
        asyncio.run(http_client(lambda request: response).status())
    assert "download-secret" not in str(error.value)


def test_download_timeout_is_not_retried() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=NZB)
        raise httpx.ReadTimeout("secret", request=request)

    with pytest.raises(UsenetClientError) as error:
        asyncio.run(http_client(handler).download("abc", "Rocky"))
    assert error.value.code == "timeout"
    assert len(calls) == 2


class FakeDownloads:
    def __init__(self):
        self.searches = []
        self.started = []
        self.paused = False

    async def search(self, query, category=""):
        self.searches.append((query, category))
        return [
            SearchItem(id=str(i), title=f"Rocky {i}", size_bytes=1024**3, category="2000")
            for i in range(1, 11)
        ]

    async def details(self, item_id):
        return SearchItem(id=item_id, title=f"Rocky {item_id}", category="2000")

    async def download(self, item_id, title):
        self.started.append((item_id, title))
        return 42

    async def queue(self):
        return [
            DownloadItem(id=42, title="Rocky", status="DOWNLOADING", size_mb=100, remaining_mb=25)
        ]

    async def history(self):
        return [DownloadItem(id=40, title="Creed", status="SUCCESS/ALL")]

    async def status(self):
        return DownloadStatus(
            paused=self.paused, speed_bytes=1024**2, remaining_mb=100, free_disk_mb=10000
        )

    async def pause(self):
        self.paused = True

    async def resume(self):
        self.paused = False


def send(orchestrator, conversation, content, capabilities=None):
    return asyncio.run(
        orchestrator.handle(
            IncomingMessage(
                conversation_id=conversation,
                channel=Channel(
                    name="whatsapp",
                    allowed_capabilities=capabilities or ["assistant.status", "usenet.downloads"],
                ),
                content=content,
            )
        )
    )


def test_search_select_confirm_flow_and_replay() -> None:
    fake = FakeDownloads()
    orchestrator = build_orchestrator(usenet_client=fake)
    conversation = uuid4()
    result = send(orchestrator, conversation, "busca Rocky en la categoría movies")
    assert "10. Rocky 10" in result.message.content
    assert fake.searches == [("Rocky", "2000")]
    assert "Rocky 2" in send(orchestrator, conversation, "detalles del 2").message.content
    proposed = send(orchestrator, conversation, "baja el 2")
    assert "confirmo" in proposed.message.content
    assert fake.started == []
    send(orchestrator, conversation, "ayuda")
    assert fake.started == []
    confirmed = send(orchestrator, conversation, "confirmo")
    assert "ID 42" in confirmed.message.content
    assert fake.started == [("2", "Rocky 2")]
    send(orchestrator, conversation, "confirmo")
    assert len(fake.started) == 1


def test_selection_is_conversation_scoped_and_expires() -> None:
    orchestrator = build_orchestrator(usenet_client=FakeDownloads())
    conversation = uuid4()
    send(orchestrator, conversation, "busca Rocky en películas")
    assert "Busca primero" in send(orchestrator, uuid4(), "baja el 2").message.content
    assert "número no está" in send(orchestrator, conversation, "baja el 11").message.content
    orchestrator.usenet_agent._states[conversation].created_at = time.monotonic() - 1000
    assert "Busca primero" in send(orchestrator, conversation, "baja el 2").message.content


def test_cancel_and_expired_approval_do_not_download() -> None:
    fake = FakeDownloads()
    orchestrator = build_orchestrator(usenet_client=fake)
    conversation = uuid4()
    send(orchestrator, conversation, "busca Rocky")
    send(orchestrator, conversation, "baja el 2")
    send(orchestrator, conversation, "cancelar")
    send(orchestrator, conversation, "confirmo")
    assert fake.started == []
    send(orchestrator, conversation, "baja el 3")
    approval = orchestrator.approvals.pending_for_conversation(conversation)[0]
    approval.expires_at = utcnow() - timedelta(seconds=1)
    send(orchestrator, conversation, "confirmo")
    assert fake.started == []


def test_queue_history_pause_resume_and_help() -> None:
    fake = FakeDownloads()
    orchestrator = build_orchestrator(usenet_client=fake)
    conversation = uuid4()
    assert "75%" in send(orchestrator, conversation, "qué está bajando").message.content
    assert "MB/s" in send(orchestrator, conversation, "estado de descarga").message.content
    assert (
        "Completada" in send(orchestrator, conversation, "historial de descargas").message.content
    )
    send(orchestrator, conversation, "pausa las descargas")
    assert fake.paused is False
    send(orchestrator, conversation, "confirmo")
    assert fake.paused is True
    send(orchestrator, conversation, "reanuda las descargas")
    send(orchestrator, conversation, "confirmo")
    assert fake.paused is False
    assert "baja el 2" not in send(orchestrator, conversation, "ayuda").message.content
    assert "baja el 2" in send(orchestrator, conversation, "ayuda Usenet").message.content


def test_channel_without_skill_does_not_search_or_advertise_it() -> None:
    fake = FakeDownloads()
    orchestrator = build_orchestrator(usenet_client=fake)
    response = send(orchestrator, uuid4(), "busca Rocky", ["assistant.status", "seerr.media"])
    assert fake.searches == []
    assert response.executions[0].agent_name == "status"
    assert "baja el 2" not in response.message.content


def test_download_requires_matching_approved_parameters() -> None:
    fake = FakeDownloads()
    orchestrator = build_orchestrator(usenet_client=fake)
    conversation = uuid4()
    send(orchestrator, conversation, "busca Rocky")
    send(orchestrator, conversation, "baja el 2")
    approval = orchestrator.approvals.pending_for_conversation(conversation)[0]
    orchestrator.approvals.approve(approval.id)
    with pytest.raises(PermissionError):
        asyncio.run(
            orchestrator.tools.invoke(
                ToolInvocation(
                    tool_name="usenet.download",
                    agent_name="usenet",
                    approval_id=approval.id,
                    risk_level=RiskLevel.WRITE,
                    input={"item_id": "3", "title": "Rocky 3"},
                )
            )
        )
    assert fake.started == []


class ConfigurationPool:
    encrypted = None

    async def fetchrow(self, query):
        return {"encrypted_settings": self.encrypted} if self.encrypted else None

    async def execute(self, query, encrypted):
        self.encrypted = encrypted

    async def close(self):
        pass


def test_configuration_encryption_and_secret_preservation() -> None:
    pool = ConfigurationPool()
    store = PostgresUsenetConfigurationStore("postgresql://test", Fernet.generate_key().decode())
    store._pool = pool

    async def check():
        await store.save(UsenetConfigurationInput.model_validate(SETTINGS))
        assert b"provider-secret" not in pool.encrypted
        assert b"download-secret" not in pool.encrypted
        loaded = await store.load()
        assert loaded.provider_api_key.get_secret_value() == "provider-secret"
        updated = {
            **SETTINGS,
            "provider_api_key": None,
            "nzbget_password": None,
            "nzbget_username": "new",
        }
        loaded = await store.save(UsenetConfigurationInput.model_validate(updated))
        assert loaded.nzbget_password.get_secret_value() == "download-secret"
        assert loaded.nzbget_username == "new"

    asyncio.run(check())


def test_configuration_api_does_not_return_secrets_and_reports_each_connection(monkeypatch) -> None:
    store = PostgresUsenetConfigurationStore("postgresql://test", Fernet.generate_key().decode())
    store._pool = ConfigurationPool()

    async def provider(self):
        raise UsenetClientError("unauthorized", "El buscador rechazó las credenciales.")

    async def downloader(self):
        return None

    monkeypatch.setattr(HttpUsenetClient, "test_provider", provider)
    monkeypatch.setattr(HttpUsenetClient, "test_downloader", downloader)
    app = create_app()
    with TestClient(app) as client:
        app.state.usenet_configuration = store
        assert client.get("/api/v1/skills/usenet/configuration").json()["configured"] is False
        missing = client.put(
            "/api/v1/skills/usenet/configuration", json={**SETTINGS, "provider_api_key": None}
        )
        assert missing.status_code == 422
        saved = client.put("/api/v1/skills/usenet/configuration", json=SETTINGS)
        assert saved.status_code == 200
        assert app.state.usenet_configured is True
        tested = client.post("/api/v1/skills/usenet/configuration/test")
        assert tested.json()["downloader_test"] == "Conexión verificada"
        assert "rechazó" in tested.json()["provider_test"]
        for response in [saved, tested, client.get("/api/v1/skills/usenet/configuration")]:
            assert "provider-secret" not in response.text
            assert "download-secret" not in response.text
            assert "provider_api_key" not in response.json()


def test_approved_download_can_be_executed_from_control_plane_after_restart() -> None:
    fake = FakeDownloads()
    app = create_app()
    orchestrator = app.state.orchestrator
    orchestrator.usenet_agent.set_client(fake)
    approval = orchestrator.approvals.create(
        conversation_id=uuid4(),
        agent_name="usenet",
        tool_name="usenet.download",
        parameters={"item_id": "2", "title": "Rocky 2"},
        reason="Bajar Rocky 2",
        idempotency_key="saved",
    )
    # No in-memory search is needed: selected identity is durable in the approval.
    with TestClient(app) as client:
        read = client.get(f"/api/v1/approvals/{approval.id}")
        assert read.status_code == 200
        assert fake.started == []
        approved = client.post(f"/api/v1/approvals/{approval.id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "executed"
        assert fake.started == [("2", "Rocky 2")]


def test_changing_connection_invalidates_old_choices_and_pending_proposals() -> None:
    fake = FakeDownloads()
    orchestrator = build_orchestrator(usenet_client=fake)
    conversation = uuid4()
    send(orchestrator, conversation, "busca Rocky")
    send(orchestrator, conversation, "baja el 2")
    replacement = FakeDownloads()
    orchestrator.usenet_agent.set_client(replacement)
    send(orchestrator, conversation, "confirmo")
    assert replacement.started == []
    assert orchestrator.approvals.pending_for_conversation(conversation) == []
    assert "Busca primero" in send(orchestrator, conversation, "baja el 2").message.content
