from fastapi.testclient import TestClient

from app.api.main import create_app
from app.domain.whatsapp import WhatsAppChannelStatus


def test_chat_returns_status_response_and_request_id() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/chat", json={"content": "hello Artemis"})
    assert response.status_code == 200
    payload = response.json()
    assert "Hola, soy tu asistente" in payload["message"]["content"]
    assert payload["plan"]["nodes"][0]["capability"] == "assistant.status"
    assert payload["executions"][0]["status"] == "completed"
    assert response.headers["x-request-id"]


def test_unknown_capability_is_a_safe_error() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/chat", json={"content": "hello", "required_capabilities": ["unknown"]}
        )
    assert response.status_code == 422
    assert response.json()["code"] == "planning_error"


def test_whatsapp_status_is_safe_when_not_configured() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/channels/whatsapp")
    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "agent_name": None,
        "running": False,
        "last_error": None,
    }


def test_admin_token_protects_control_plane_api(monkeypatch) -> None:
    monkeypatch.setenv("ARTEMIS_ADMIN_TOKEN", "operator-secret")
    with TestClient(create_app()) as client:
        protected = client.get("/api/v1/channels/whatsapp")
        memory = client.get("/api/v1/memory/agent_memory")
        status = client.get("/api/v1/auth/status")
        authorized = client.get(
            "/api/v1/channels/whatsapp", headers={"Authorization": "Bearer operator-secret"}
        )
    assert memory.status_code == 401
    assert protected.status_code == 401
    assert status.json() == {"authentication_required": True}
    assert authorized.status_code == 200


def test_whatsapp_skill_save_accepts_mandatory_status_on_round_trip() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.saved: list[str] = []

        def status(self) -> WhatsAppChannelStatus:
            return WhatsAppChannelStatus(configured=True, agent_name="primary", running=True)

        async def capabilities(self) -> list[str]:
            return ["assistant.status", *self.saved]

        async def set_capabilities(self, capabilities: list[str]) -> None:
            self.saved = capabilities

    runtime = Runtime()
    app = create_app()
    with TestClient(app) as client:
        app.state.whatsapp = runtime
        app.state.karakeep_configured = True
        response = client.put(
            "/api/v1/agents/whatsapp/primary/skills",
            json={"capabilities": ["assistant.status", "karakeep.bookmarks"]},
        )
        loaded = client.get("/api/v1/agents/whatsapp/primary/skills")
    assert response.status_code == 200
    assert loaded.status_code == 200
    assert runtime.saved == ["karakeep.bookmarks"]
    assert loaded.json()["capabilities"] == ["assistant.status", "karakeep.bookmarks"]


def test_each_bot_has_a_persona_and_old_profile_updates_preserve_it():
    class Runtime:
        def __init__(self):
            self.personality = "Cercano y breve"
            self.welcome = "Hola"

        def status(self):
            return WhatsAppChannelStatus(configured=True, agent_name="primary", running=True)

        async def persona(self):
            return self.personality

        async def greeting(self):
            return self.welcome

        async def set_persona(self, value):
            self.personality = value

        async def set_greeting(self, value):
            self.welcome = value

    app = create_app()
    with TestClient(app) as client:
        whatsapp, telegram = Runtime(), Runtime()
        app.state.whatsapp, app.state.telegram = whatsapp, telegram
        response = client.put(
            "/api/v1/agents/telegram/primary/profile",
            json={"persona": "Hablas como pirata"},
        )
        assert response.status_code == 200
        assert response.json()["persona"] == "Hablas como pirata"
        assert whatsapp.personality == "Cercano y breve"
        client.put("/api/v1/agents/telegram/primary/profile", json={"greeting": "Bienvenido"})
        assert telegram.personality == "Hablas como pirata"
        invalid = client.put(
            "/api/v1/agents/telegram/primary/profile", json={"greeting": "Cambio", "persona": "   "}
        )
        assert invalid.status_code == 422
        assert telegram.welcome == "Bienvenido"
