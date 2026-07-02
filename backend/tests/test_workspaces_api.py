from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app


def make_client(monkeypatch, tmp_path):
    database_path = tmp_path / "workspaces.sqlite"
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


def test_super_admin_creates_extensible_workspace(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/workspaces",
        json={
            "code": "hardware_intel",
            "name": "硬件情报工作台",
            "description": "硬件与半导体方向的情报工作范围。",
            "default_domain_code": "hardware",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["code"] == "hardware_intel"
    assert payload["name"] == "硬件情报工作台"
    assert payload["default_domain_code"] == "hardware"
    assert payload["workspace_type"] == "intelligence_workspace"

    listed = client.get("/api/workspaces")
    assert listed.status_code == 200
    codes = [item["code"] for item in listed.json()]
    assert codes.index("planning_intel") < codes.index("hardware_intel")

    sections = client.get("/api/workspaces/hardware_intel/sections")
    assert sections.status_code == 200
    section_keys = [item["section_key"] for item in sections.json()]
    for core_key in [
        "dashboard",
        "source_management",
        "candidate_pool",
        "daily_reports",
        "weekly_reports",
        "historical_reports",
        "entity_milestones",
        "quality_archive",
        "exports",
        "users",
        "audit_logs",
    ]:
        assert core_key in section_keys

    policy = client.get("/api/workspaces/hardware_intel/label-policy")
    assert policy.status_code == 200
    policy_payload = policy.json()
    assert policy_payload["label_set_code"] == "ai_sql_categories"
    assert len(policy_payload["allowed_primary_categories"]) == 10


def test_create_workspace_validates_code_and_uniqueness(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    duplicate = client.post(
        "/api/workspaces",
        json={"code": "planning_intel", "name": "重复工作台", "description": ""},
    )
    assert duplicate.status_code == 409

    invalid = client.post(
        "/api/workspaces",
        json={"code": "Bad Code", "name": "非法标识", "description": ""},
    )
    assert invalid.status_code == 422


def test_create_workspace_requires_authentication(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/workspaces",
        json={"code": "no_auth", "name": "未登录", "description": ""},
    )
    assert response.status_code == 401


def test_new_workspace_can_configure_own_sources(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created_workspace = client.post(
        "/api/workspaces",
        json={
            "code": "policy_intel",
            "name": "政策情报工作台",
            "description": "",
            "default_domain_code": "policy",
        },
    )
    assert created_workspace.status_code == 201

    created_source = client.post(
        "/api/sources",
        json={
            "workspace_code": "policy_intel",
            "name": "示例政策 RSS",
            "source_type": "rss",
            "url": "https://example.com/policy.rss",
            "domain_code": "policy",
        },
    )
    assert created_source.status_code == 201
    source_payload = created_source.json()
    assert source_payload["created"] is True
    assert source_payload["source"]["workspace_link_enabled"] is True
    assert source_payload["source"]["domain_code"] == "policy"

    reused = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "同一个源换个名字",
            "source_type": "rss",
            "url": "https://example.com/policy.rss",
        },
    )
    assert reused.status_code == 201
    reused_payload = reused.json()
    assert reused_payload["created"] is False
    assert reused_payload["source"]["id"] == source_payload["source"]["id"]
    assert reused_payload["source"]["workspace_link_enabled"] is True

    listed = client.get("/api/sources", params={"workspace_code": "policy_intel"})
    assert listed.status_code == 200
    match = [item for item in listed.json() if item["id"] == source_payload["source"]["id"]]
    assert match
    assert match[0]["workspace_link_enabled"] is True
