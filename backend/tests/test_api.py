from fastapi.testclient import TestClient

from app.api.main import create_app


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
        status = client.get("/api/v1/auth/status")
        authorized = client.get(
            "/api/v1/channels/whatsapp", headers={"Authorization": "Bearer operator-secret"}
        )
    assert protected.status_code == 401
    assert status.json() == {"authentication_required": True}
    assert authorized.status_code == 200
