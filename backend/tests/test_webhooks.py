from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.domain.models import utcnow
from app.domain.webhooks import WebhookEvent


class MemoryEvents:
    def __init__(self):
        self.items = []

    async def receive(self, source, payload, notify=False):
        if payload.event_id:
            for item in self.items:
                if item.source == source and item.event_id == payload.event_id:
                    return item, True
        event = WebhookEvent(
            id=uuid4(), source=source, received_at=utcnow(),
            whatsapp_status="pending" if notify else "not_requested", **payload.model_dump()
        )
        self.items.append(event)
        return event, False

    async def recent(self, source, limit):
        return [
            item for item in reversed(self.items) if source is None or item.source == source
        ][:limit]


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.setenv("ARTEMIS_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("ARTEMIS_WEBHOOK_TOKEN", "webhook-secret")
    app = create_app()
    with TestClient(app) as client:
        app.state.webhook_events = MemoryEvents()
        app.state.notifications.store = app.state.webhook_events
        yield client



WEBHOOK_AUTH = {"Authorization": "Bearer webhook-secret"}
ADMIN_AUTH = {"Authorization": "Bearer admin-secret"}


def test_generic_webhook_is_stored_and_listed_without_admin_credential(webhook_client):
    receipt = webhook_client.post("/api/v1/webhooks/backups", headers=WEBHOOK_AUTH, json={
        "event": "backup.finished", "title": "Backup completo", "message": "Todo correcto",
        "event_id": "backup-42", "ignored_secret": "must-not-store-this",
    })
    assert receipt.status_code == 202
    assert receipt.json()["status"] == "received"
    assert receipt.json()["duplicate"] is False
    listing = webhook_client.get("/api/v1/webhooks/events", headers=ADMIN_AUTH)
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    event = listing.json()[0]
    assert event["id"] == receipt.json()["id"]
    assert event["source"] == "backups"
    assert event["event"] == "backup.finished"
    assert event["message"] == "Todo correcto"
    assert "must-not-store-this" not in listing.text


def test_seerr_default_payload_is_accepted_and_normalized(webhook_client):
    response = webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH, json={
        "notification_type": "MEDIA_AVAILABLE", "event": "Movie Request Now Available",
        "subject": "Dune", "message": "Ya disponible", "media": {"tmdbId": 693134},
    })
    assert response.status_code == 202
    event = webhook_client.get("/api/v1/webhooks/events", headers=ADMIN_AUTH).json()[0]
    assert event["source"] == "seerr"
    assert event["event"] == "MEDIA_AVAILABLE"
    assert event["title"] == "Dune"


def test_webhook_and_admin_credentials_are_separate(webhook_client):
    for headers in ({}, ADMIN_AUTH, {"Authorization": "Bearer wrong"}):
        assert webhook_client.post("/api/v1/webhooks/seerr", headers=headers,
                                   json={"message": "test"}).status_code == 401
    for path in ("/api/v1/webhooks/events", "/api/v1/webhooks/configuration", "/api/v1/agents"):
        assert webhook_client.get(path, headers=WEBHOOK_AUTH).status_code == 401
    assert webhook_client.put("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH).status_code == 401
    config = webhook_client.get("/api/v1/webhooks/configuration", headers=ADMIN_AUTH)
    assert config.json()["configured"] is True
    assert "secret" not in config.text


def test_webhook_disabled_or_storage_unavailable_returns_503(webhook_client, monkeypatch):
    monkeypatch.delenv("ARTEMIS_WEBHOOK_TOKEN")
    assert webhook_client.post(
        "/api/v1/webhooks/seerr", json={"message": "test"}
    ).status_code == 503
    monkeypatch.setenv("ARTEMIS_WEBHOOK_TOKEN", "webhook-secret")
    webhook_client.app.state.webhook_events = None
    assert webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH,
                               json={"message": "test"}).status_code == 503


def test_duplicate_ids_are_scoped_by_source(webhook_client):
    payload = {"message": "test", "event_id": "event-1"}
    first = webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH, json=payload)
    duplicate = webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH, json=payload)
    other = webhook_client.post("/api/v1/webhooks/other", headers=WEBHOOK_AUTH, json=payload)
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["id"] == first.json()["id"]
    assert other.json()["duplicate"] is False
    filtered = webhook_client.get(
        "/api/v1/webhooks/events?source=seerr&limit=1", headers=ADMIN_AUTH
    )
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["source"] == "seerr"
    assert webhook_client.get(
        "/api/v1/webhooks/events?limit=101", headers=ADMIN_AUTH
    ).status_code == 422


@pytest.mark.parametrize("payload", [{}, [], {"message": " "}, {"message": 123},
                                     {"message": "x" * 4097}, {"event": "", "title": "test"}])
def test_invalid_payloads_are_not_stored(webhook_client, payload):
    response = webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH, json=payload)
    assert response.status_code == 422
    assert webhook_client.get("/api/v1/webhooks/events", headers=ADMIN_AUTH).json() == []


def test_body_limits_and_media_type(webhook_client):
    assert webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH,
                               content="not json").status_code == 415
    headers = {**WEBHOOK_AUTH, "Content-Type": "application/json"}
    assert webhook_client.post("/api/v1/webhooks/seerr", headers=headers,
                               content="{").status_code == 422
    assert webhook_client.post("/api/v1/webhooks/seerr", headers=headers,
                               content='{"message":"' + "x" * 65536 + '"}').status_code == 413


def test_new_webhooks_queue_notifications_but_duplicate_does_not_create_another(webhook_client):
    class Notifier:
        def wake(self):
            pass

        async def recipient_available(self):
            return True

    webhook_client.app.state.webhook_notifier = Notifier()
    webhook_client.app.state.notifications.notifier = webhook_client.app.state.webhook_notifier
    payload = {"message": "Disponible", "event_id": "unique-event"}
    first = webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH, json=payload)
    second = webhook_client.post("/api/v1/webhooks/seerr", headers=WEBHOOK_AUTH, json=payload)
    assert first.json()["whatsapp_status"] == "pending"
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    events = webhook_client.get("/api/v1/webhooks/events", headers=ADMIN_AUTH).json()
    assert len(events) == 1 and events[0]["whatsapp_status"] == "pending"
    config = webhook_client.get("/api/v1/webhooks/configuration", headers=ADMIN_AUTH).json()
    assert config["whatsapp_enabled"] and config["whatsapp_recipient_available"]


def test_seerr_raw_authorization_token_is_accepted_only_for_ingestion(webhook_client):
    raw_auth = {"Authorization": "webhook-secret"}
    response = webhook_client.post(
        "/api/v1/webhooks/seerr", headers=raw_auth, json={"message": "Prueba sin prefijo"},
    )
    assert response.status_code == 202
    assert webhook_client.get("/api/v1/webhooks/events", headers=raw_auth).status_code == 401
    for token in ("wrong", "webhook-secret-extra", "webhook-secre", "bearer wrong"):
        rejected = webhook_client.post(
            "/api/v1/webhooks/seerr", headers={"Authorization": token}, json={"message": "test"},
        )
        assert rejected.status_code == 401
