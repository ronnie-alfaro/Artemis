from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from test_webhooks import MemoryEvents

from app.api.main import create_app
from app.domain.models import RiskLevel, ToolInvocation


class Store(MemoryEvents):
    async def save_notification_settings(self, settings):
        self.saved_settings = settings


class Notifier:
    def __init__(self):
        self.settings = None
        self.wake_count = 0

    def configure(self, settings):
        self.settings = settings

    def wake(self):
        self.wake_count += 1

    async def recipient_available(self):
        return True


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv("ARTEMIS_ADMIN_TOKEN", "admin")
    monkeypatch.setenv("ARTEMIS_WEBHOOK_TOKEN", "hook")
    app = create_app()
    with TestClient(app) as client:
        store, notifier = Store(), Notifier()
        app.state.notifications.store = store
        app.state.notifications.notifier = notifier
        app.state.webhook_events = store
        app.state.webhook_notifier = notifier

        async def recipients():
            return ["user:owner", "user:second"]

        app.state.notifications.recipients = recipients
        client.headers["Authorization"] = "Bearer admin"
        yield client, app, store, notifier


def test_tool_is_registered_and_can_send_without_a_skill(context):
    client, app, store, notifier = context
    tools = client.get("/api/v1/tools").json()
    tool = next(item for item in tools if item["name"] == "notifications.send")
    assert tool["risk_level"] == "write" and not tool["requires_approval"]
    payload = {"title": "Aviso directo", "message": "Hola", "event_id": "manual-1"}
    first = client.post("/api/v1/tools/notifications/send", json=payload)
    second = client.post("/api/v1/tools/notifications/send", json=payload)
    assert first.status_code == 202
    assert first.json()["whatsapp_status"] == "pending"
    assert second.json()["id"] == first.json()["id"] and second.json()["duplicate"]
    assert len(store.items) == 1
    assert store.items[0].source == "manual"
    assert notifier.wake_count == 2
    assert app.state.orchestrator.approvals.all_approvals() == []


@pytest.mark.parametrize("skill", ["usenet", "karakeep", "seerr"])
def test_each_registered_skill_can_use_shared_tool_and_source_is_its_identity(context, skill):
    client, app, store, notifier = context
    result = asyncio.run(app.state.orchestrator.tools.invoke(ToolInvocation(
        tool_name="notifications.send", agent_name=skill, risk_level=RiskLevel.WRITE,
        input={"message": "Aviso del skill", "source": "forged", "recipient_id": "user:unknown"},
    )))
    assert result.output["whatsapp_status"] == "pending"
    assert store.items[0].source == skill
    assert app.state.notifications.settings.recipient_id is None
    with pytest.raises(PermissionError):
        asyncio.run(app.state.orchestrator.tools.invoke(ToolInvocation(
            tool_name="notifications.send", agent_name="unknown", risk_level=RiskLevel.WRITE,
            input={"message": "No autorizado"},
        )))


def test_shared_settings_control_tools_and_webhooks_and_reject_unknown_recipient(context):
    client, app, store, notifier = context
    saved = client.put("/api/v1/tools/notifications/configuration", json={
        "enabled": False, "channel": "whatsapp", "recipient_id": "user:owner",
    })
    assert saved.status_code == 200
    assert not store.saved_settings.enabled
    assert notifier.settings.recipient_id == "user:owner"
    assert not client.get("/api/v1/tools/notifications/configuration").json()["settings"]["enabled"]
    assert client.post(
        "/api/v1/tools/notifications/send", json={"message": "test"}
    ).status_code == 409
    webhook = client.post("/api/v1/webhooks/seerr", headers={"Authorization": "hook"},
                          json={"message": "Evento guardado"})
    assert webhook.status_code == 202
    assert webhook.json()["whatsapp_status"] == "not_requested"
    assert notifier.wake_count == 0
    assert client.put("/api/v1/tools/notifications/configuration", json={
        "enabled": True, "recipient_id": "user:unknown",
    }).status_code == 422
    assert not app.state.notifications.settings.enabled
    history = client.get("/api/v1/tools/notifications/history").json()
    assert len(history) == 1 and history[0]["source"] == "seerr"


def test_configuration_unavailable_and_authorization_are_reported(context):
    client, app, store, notifier = context
    response = client.post("/api/v1/tools/notifications/send", headers={"Authorization": "hook"},
                           json={"message": "not admin"})
    assert response.status_code == 401
    assert client.post("/api/v1/tools/notifications/send", json={"message": " "}).status_code == 422
    app.state.notifications.store = None
    assert client.post(
        "/api/v1/tools/notifications/send", json={"message": "test"}
    ).status_code == 503
    assert client.get("/api/v1/tools/notifications/history").status_code == 503
