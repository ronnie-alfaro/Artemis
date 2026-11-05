from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_notifications_tool import Notifier
from test_notifications_tool import Store as NotificationStore

from app.api.main import create_app
from app.application.reminders import ReminderWorker
from app.domain.models import RiskLevel, Tool, ToolResult, utcnow
from app.domain.reminders import Reminder, ReminderCreate, ToolTrigger


class MemoryReminders:
    def __init__(self):
        self.items = {}
        self.claims = {}

    async def create(self, payload):
        identifier = payload.request_id or uuid4()
        if identifier in self.items:
            return self.items[identifier]
        reminder = Reminder(
            id=identifier,
            message=payload.message,
            trigger=payload.trigger,
            status="active",
            next_check_at=getattr(payload.trigger, "at", utcnow()),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.items[identifier] = reminder
        return reminder

    async def get(self, identifier):
        return self.items.get(identifier)

    async def list(self):
        return [item for item in self.items.values() if item.status != "cancelled"]

    async def set_state(self, identifier, status):
        item = self.items.get(identifier)
        if item is None or item.status not in {"active", "paused"}:
            return None
        item.status = status
        self.claims.pop(identifier, None)
        return item

    async def claim_due(self):
        for item in self.items.values():
            if item.status in {"active", "firing"} and item.next_check_at <= utcnow():
                if item.id not in self.claims:
                    claim = uuid4()
                    self.claims[item.id] = claim
                    return item.model_copy(deep=True), claim
        return None

    async def checked(self, identifier, claim, next_check, preview, fingerprint, error=None):
        if self.claims.get(identifier) != claim:
            return
        item = self.items[identifier]
        item.next_check_at, item.last_error = next_check, error
        item.last_checked_at = utcnow()
        if preview is not None:
            item.last_value = preview
        if fingerprint is not None:
            item.last_hash = fingerprint
        self.claims.pop(identifier)

    async def begin_fire(self, identifier, claim, preview, fingerprint):
        item = self.items[identifier]
        if self.claims.get(identifier) != claim or item.status != "active":
            return False
        item.status = "firing"
        item.last_value, item.last_hash = preview, fingerprint
        return True

    async def completed(self, identifier, claim, notification_id):
        if self.claims.get(identifier) == claim:
            item = self.items[identifier]
            item.status, item.notification_id = "completed", notification_id
            item.next_check_at = None
            self.claims.pop(identifier)


class ReadStatus:
    definition = Tool(name="test.status", description="Read test state", risk_level=RiskLevel.READ)

    def __init__(self):
        self.state = "running"
        self.fail = False
        self.calls = 0
        self.during_read = None

    async def invoke(self, invocation):
        self.calls += 1
        if self.during_read:
            await self.during_read()
        if self.fail:
            raise RuntimeError("must not leak credential detail")
        assert invocation.input == {"id": 42}
        return ToolResult(
            invocation_id=invocation.id,
            output={"item": json.dumps({"id": 42, "status": self.state})},
        )


def tool_trigger():
    return {
        "kind": "tool",
        "tool_name": "test.status",
        "input": {"id": 42},
        "condition": {"path": "item.status", "operator": "equals", "value": "done"},
        "interval_seconds": 60,
    }


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setenv("ARTEMIS_ADMIN_TOKEN", "admin")
    app = create_app()
    with TestClient(app) as client:
        service = app.state.reminders
        service.store = MemoryReminders()
        app.state.notifications.store = NotificationStore()
        app.state.notifications.notifier = Notifier()
        tool = ReadStatus()
        service.tools.register(tool, authorized_agents={"test-skill"})
        client.headers["Authorization"] = "Bearer admin"
        yield client, app, tool


def test_create_preview_catalog_and_manage_reminders(context):
    client, app, tool = context
    catalog = client.get("/api/v1/tools/reminders/catalog").json()
    assert "test.status" in [item["name"] for item in catalog]
    assert all(item["risk_level"] == "read" for item in catalog)
    assert (
        client.post("/api/v1/tools/reminders/preview", json=tool_trigger()).json()["matched"]
        is False
    )
    tool.state = "done"
    assert (
        client.post("/api/v1/tools/reminders/preview", json=tool_trigger()).json()["matched"]
        is True
    )
    request_id = str(uuid4())
    payload = {"message": "Terminó la tarea", "trigger": tool_trigger(), "request_id": request_id}
    response = client.post("/api/v1/tools/reminders", json=payload)
    assert response.status_code == 201
    identifier = response.json()["id"]
    assert identifier == request_id
    assert client.post("/api/v1/tools/reminders", json=payload).json()["id"] == identifier
    assert len(client.get("/api/v1/tools/reminders").json()) == 1
    assert (
        client.patch(f"/api/v1/tools/reminders/{identifier}", json={"status": "paused"}).json()[
            "status"
        ]
        == "paused"
    )
    assert (
        client.patch(f"/api/v1/tools/reminders/{identifier}", json={"status": "active"}).json()[
            "status"
        ]
        == "active"
    )
    assert client.delete(f"/api/v1/tools/reminders/{identifier}").status_code == 204
    assert client.get("/api/v1/tools/reminders").json() == []


def test_time_validation_and_write_tools_cannot_be_used_as_triggers(context):
    client, app, tool = context
    past = {"kind": "time", "at": (utcnow() - timedelta(minutes=1)).isoformat()}
    assert (
        client.post(
            "/api/v1/tools/reminders", json={"message": "Test", "trigger": past}
        ).status_code
        == 422
    )
    naive = {"kind": "time", "at": "2030-01-01T10:00:00"}
    assert (
        client.post(
            "/api/v1/tools/reminders", json={"message": "Test", "trigger": naive}
        ).status_code
        == 422
    )
    for name in ("usenet.download", "notifications.send", "reminders.create", "does.not.exist"):
        trigger = {**tool_trigger(), "tool_name": name}
        assert (
            client.post(
                "/api/v1/tools/reminders", json={"message": "Test", "trigger": trigger}
            ).status_code
            == 422
        )
        assert client.post("/api/v1/tools/reminders/preview", json=trigger).status_code == 422
    assert (
        client.get("/api/v1/tools/reminders", headers={"Authorization": "wrong"}).status_code == 401
    )


def test_time_trigger_queues_one_notification_and_completes(context):
    client, app, tool = context

    async def scenario():
        reminder = await app.state.reminders.create(
            ReminderCreate.model_validate(
                {
                    "message": "Aviso por hora",
                    "trigger": {"kind": "time", "at": utcnow() + timedelta(seconds=1)},
                }
            )
        )
        reminder.next_check_at = utcnow() - timedelta(seconds=1)
        worker = ReminderWorker(app.state.reminders)
        assert await worker.run_once()
        assert reminder.status == "completed" and reminder.notification_id is not None
        assert not await worker.run_once()
        assert len(app.state.notifications.store.items) == 1
        assert app.state.notifications.store.items[0].message == "Aviso por hora"

    asyncio.run(scenario())


def test_tool_frequency_error_recovery_and_single_shot_delivery(context):
    client, app, tool = context

    async def scenario():
        service = app.state.reminders
        reminder = await service.create(
            ReminderCreate(
                message="La tarea terminó", trigger=ToolTrigger.model_validate(tool_trigger())
            )
        )
        worker = ReminderWorker(service)
        tool.fail = True
        await worker.run_once()
        assert reminder.status == "active" and "credential" not in reminder.last_error
        assert reminder.next_check_at >= utcnow() + timedelta(seconds=59)
        assert not await worker.run_once()
        tool.fail = False
        reminder.next_check_at = utcnow() - timedelta(seconds=1)
        await worker.run_once()
        assert reminder.status == "active" and reminder.last_error is None
        tool.state = "done"
        reminder.next_check_at = utcnow() - timedelta(seconds=1)
        await worker.run_once()
        assert reminder.status == "completed"
        assert not await worker.run_once()
        assert len(app.state.notifications.store.items) == 1

    asyncio.run(scenario())


def test_pause_during_tool_call_prevents_a_stale_check_from_sending(context):
    client, app, tool = context

    async def scenario():
        service = app.state.reminders
        reminder = await service.create(
            ReminderCreate(message="Terminado", trigger=ToolTrigger.model_validate(tool_trigger()))
        )
        tool.state = "done"

        async def pause():
            await service.store.set_state(reminder.id, "paused")

        tool.during_read = pause
        await ReminderWorker(service).run_once()
        assert reminder.status == "paused"
        assert app.state.notifications.store.items == []

    asyncio.run(scenario())


def test_disabled_notifications_retain_fired_reminder_until_queue_is_available(context):
    client, app, tool = context

    async def scenario():
        service = app.state.reminders
        reminder = await service.create(
            ReminderCreate(message="Terminado", trigger=ToolTrigger.model_validate(tool_trigger()))
        )
        tool.state = "done"
        app.state.notifications.settings.enabled = False
        worker = ReminderWorker(service)
        await worker.run_once()
        assert reminder.status == "firing" and reminder.last_error
        assert app.state.notifications.store.items == []
        app.state.notifications.settings.enabled = True
        reminder.next_check_at = utcnow() - timedelta(seconds=1)
        tool.state = "running"
        await worker.run_once()
        assert reminder.status == "completed"
        assert len(app.state.notifications.store.items) == 1

    asyncio.run(scenario())
