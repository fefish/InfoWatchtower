from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app


def make_client(monkeypatch, tmp_path):
    database_path = tmp_path / "sources.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_MODE", "public_password")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    monkeypatch.setenv(
        "LEGACY_SEED_ROOT",
        str(Path(__file__).resolve().parents[2] / "config" / "seeds" / "legacy"),
    )
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app())


def test_super_admin_imports_and_lists_legacy_sources(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post("/api/sources/import-legacy-seeds")
    assert imported.status_code == 200
    assert imported.json() == {"created": 294, "updated": 67, "total": 361}

    sources = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert sources.status_code == 200
    payload = sources.json()
    assert len(payload) == 294
    assert sum(1 for item in payload if item["workspace_link_enabled"]) == 294
    assert "workspace_label_set_codes" not in payload[0]
    assert "workspace_default_label_paths" not in payload[0]
    assert {item["source_type"] for item in payload} == {
        "page_manual",
        "page_monitor",
        "paper_rss",
        "rss",
        "wiseflow",
    }

    ai_tool_sources = client.get("/api/sources", params={"workspace_code": "ai_tools"})
    assert ai_tool_sources.status_code == 200
    ai_tool_payload = ai_tool_sources.json()
    assert len(ai_tool_payload) == 294
    assert sum(1 for item in ai_tool_payload if item["workspace_link_enabled"]) == 294

    updated = client.patch(
        f"/api/sources/{payload[0]['id']}/workspace-link",
        json={
            "workspace_code": "planning_intel",
            "enabled": True,
            "source_weight": 1.5,
            "daily_limit": 3,
        },
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["workspace_source_weight"] == 1.5
    assert updated_payload["workspace_daily_limit"] == 3
    assert "workspace_label_set_codes" not in updated_payload
    assert "workspace_default_label_paths" not in updated_payload

    repeated = client.post("/api/sources/import-legacy-seeds")
    assert repeated.status_code == 200
    assert repeated.json() == {"created": 0, "updated": 361, "total": 361}


def test_super_admin_can_create_zero_limit_ingestion_run(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post("/api/sources/import-legacy-seeds")
    assert imported.status_code == 200

    created = client.post(
        "/api/ingestion/runs",
        json={
            "workspace_code": "planning_intel",
            "source_types": ["rss", "paper_rss"],
            "limit": 0,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["workspace_code"] == "planning_intel"
    assert payload["status"] == "completed"
    assert payload["source_total"] == 0
    assert payload["params_json"]["source_types"] == ["rss", "paper_rss"]

    listed = client.get("/api/ingestion/runs", params={"workspace_code": "planning_intel"})
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == payload["id"]

    detail = client.get(f"/api/ingestion/runs/{payload['id']}")
    assert detail.status_code == 200
    assert detail.json()["run_key"] == payload["run_key"]
