from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_engine
from app.main import create_app


def test_healthz_without_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "infowatchtower-backend"
    assert payload["database"]["status"] == "not_configured"
