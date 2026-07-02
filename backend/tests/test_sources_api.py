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
    monkeypatch.setenv(
        "TECH_INSIGHT_LOOP_SOURCE_CSV",
        str(
            Path(__file__).resolve().parents[2]
            / "config"
            / "seeds"
            / "tech_insight_loop"
            / "sources_full_zh.csv",
        ),
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


def test_super_admin_imports_tech_insight_loop_sources(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post("/api/sources/import-tech-insight-loop")
    assert imported.status_code == 200
    assert imported.json() == {
        "created": 363,
        "updated": 23,
        "total": 386,
        "fetchable": 355,
        "metadata_only": 31,
    }

    sources = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert sources.status_code == 200
    payload = sources.json()
    assert len(payload) == 363
    assert sum(1 for item in payload if item["workspace_link_enabled"]) == 332
    assert any(
        item["name"] == "机器之心"
        and item["metadata_only"] is True
        and item["needs_entry"] is True
        and item["workspace_link_enabled"] is False
        and item["source_tier"] == "P0"
        and item["source_channel_type"]
        and isinstance(item["expert_routes"], list)
        for item in payload
    )

    repeated = client.post("/api/sources/import-tech-insight-loop")
    assert repeated.status_code == 200
    assert repeated.json() == {
        "created": 0,
        "updated": 386,
        "total": 386,
        "fetchable": 355,
        "metadata_only": 31,
    }


def test_super_admin_creates_and_edits_custom_source(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "自建测试 RSS",
            "source_type": "rss",
            "url": "https://example.com/custom.rss",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["created"] is True
    source = payload["source"]
    assert source["source_type"] == "rss"
    assert source["url"] == "https://example.com/custom.rss"
    assert source["backfill_days"] == 7
    assert source["workspace_link_enabled"] is True

    bad_type = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "非法类型",
            "source_type": "csv",
            "url": "https://example.com/bad.csv",
        },
    )
    assert bad_type.status_code == 400

    bad_url = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "非法地址",
            "source_type": "rss",
            "url": "ftp://example.com/bad.rss",
        },
    )
    assert bad_url.status_code == 400

    conflict = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "重复地址",
            "source_type": "rss",
            "url": "https://example.com/custom.rss",
            "reuse_existing": False,
        },
    )
    assert conflict.status_code == 409

    patched = client.patch(
        f"/api/sources/{source['id']}",
        params={"workspace_code": "planning_intel"},
        json={"name": "自建测试 RSS v2", "backfill_days": 14},
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload["name"] == "自建测试 RSS v2"
    assert patched_payload["backfill_days"] == 14
    assert patched_payload["workspace_link_enabled"] is True

    empty = client.patch(f"/api/sources/{source['id']}", json={})
    assert empty.status_code == 400


def test_patch_url_fills_entry_for_metadata_only_source(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post("/api/sources/import-tech-insight-loop")
    assert imported.status_code == 200

    sources = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert sources.status_code == 200
    target = next(item for item in sources.json() if item["name"] == "机器之心")
    assert target["needs_entry"] is True
    assert target["metadata_only"] is True

    patched = client.patch(
        f"/api/sources/{target['id']}",
        params={"workspace_code": "planning_intel"},
        json={"url": "https://example.com/jiqizhixin.rss"},
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload["url"] == "https://example.com/jiqizhixin.rss"
    assert patched_payload["needs_entry"] is False
    assert patched_payload["metadata_only"] is False
    assert patched_payload["fetch_entry_status"] == "manual_entry_added"

    reimported = client.post("/api/sources/import-tech-insight-loop")
    assert reimported.status_code == 200

    after_reimport = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert after_reimport.status_code == 200
    survivor = next(item for item in after_reimport.json() if item["id"] == target["id"])
    assert survivor["url"] == "https://example.com/jiqizhixin.rss"
    assert survivor["needs_entry"] is False
    assert survivor["metadata_only"] is False
    assert survivor["fetch_entry_status"] == "manual_entry_added"


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

    coverage = client.get(
        "/api/ingestion/coverage",
        params={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "run_id": payload["id"],
        },
    )
    assert coverage.status_code == 200
    coverage_payload = coverage.json()
    assert coverage_payload["run_id"] == payload["id"]
    assert coverage_payload["funnel"]["enabled_sources"] == 294
    assert coverage_payload["funnel"]["run_sources"] == 0
    assert coverage_payload["sources"][0]["data_source_id"]
