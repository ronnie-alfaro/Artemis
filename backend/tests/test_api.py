from fastapi.testclient import TestClient

from app.api.main import create_app


def test_chat_returns_typed_trace_and_request_id() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/chat", json={"content": "hello Artemis"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["message"]["content"] == "FakeAgent response: hello Artemis"
    assert payload["plan"]["nodes"][0]["capability"] == "fake.echo"
    assert payload["executions"][0]["status"] == "completed"
    assert response.headers["x-request-id"]


def test_unknown_capability_is_a_safe_error() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/chat", json={"content": "hello", "required_capabilities": ["unknown"]}
        )
    assert response.status_code == 422
    assert response.json()["code"] == "planning_error"
