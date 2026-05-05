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
    assert imported.json() == {"created": 113, "updated": 0, "total": 113}

    sources = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert sources.status_code == 200
    payload = sources.json()
    assert len(payload) == 113
    assert {item["source_type"] for item in payload} == {
        "page_manual",
        "page_monitor",
        "paper_rss",
        "rss",
        "wiseflow",
    }

    repeated = client.post("/api/sources/import-legacy-seeds")
    assert repeated.status_code == 200
    assert repeated.json() == {"created": 0, "updated": 113, "total": 113}
