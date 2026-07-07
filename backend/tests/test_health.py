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


def test_readyz_ready_when_database_connects(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'readyz.sqlite'}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"]["status"] == "ok"
    assert payload["deploy_mode"] == "standalone"
    assert payload["capabilities"]["ingestion"] is True


def test_readyz_returns_503_without_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unready"
    assert payload["database"]["status"] == "not_configured"


def test_readyz_returns_503_when_database_unreachable(monkeypatch):
    # sqlite 打不开目标目录 → SQLAlchemyError → 就绪判定必须失败
    monkeypatch.setenv("DATABASE_URL", "sqlite:////nonexistent-dir/infowatchtower/readyz.sqlite")
    get_settings.cache_clear()
    get_engine.cache_clear()
    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unready"
    assert payload["database"]["status"] == "error"


def test_healthz_keeps_liveness_semantics_when_database_unreachable(monkeypatch):
    # /healthz 是存活探针：数据库失联进程仍算活着，不能连带被摘
    monkeypatch.setenv("DATABASE_URL", "sqlite:////nonexistent-dir/infowatchtower/healthz.sqlite")
    get_settings.cache_clear()
    get_engine.cache_clear()
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["database"]["status"] == "error"
