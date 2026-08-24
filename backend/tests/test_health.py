from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_running_status() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend"}
