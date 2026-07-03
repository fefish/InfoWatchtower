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


def test_workspace_update_members_and_member_scoped_list(monkeypatch, tmp_path):
    admin = make_client(monkeypatch, tmp_path)

    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    editor_invite = admin.post(
        "/api/auth/invites",
        json={
            "role_code": "editor_admin",
            "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
            "expires_in_days": 7,
        },
    )
    assert editor_invite.status_code == 200
    editor = TestClient(create_app())
    accepted_editor = editor.post(
        f"/api/auth/invites/{editor_invite.json()['code']}/accept",
        json={
            "username": "workspace-owner",
            "display_name": "工作台 Owner",
            "password": "strong-password",
        },
    )
    assert accepted_editor.status_code == 200

    created = editor.post(
        "/api/workspaces",
        json={
            "code": "hardware_team",
            "name": "硬件团队桌面",
            "description": "硬件团队自助创建。",
            "default_domain_code": "hardware",
        },
    )
    assert created.status_code == 201

    renamed = admin.patch(
        "/api/workspaces/hardware_team",
        json={"name": "硬件情报团队", "enabled": False},
    )
    assert renamed.status_code == 200
    assert renamed.json()["enabled"] is False
    assert "hardware_team" not in [item["code"] for item in admin.get("/api/workspaces").json()]

    restored = admin.patch("/api/workspaces/hardware_team", json={"enabled": True})
    assert restored.status_code == 200
    assert restored.json()["enabled"] is True

    cannot_disable_planning = admin.patch("/api/workspaces/planning_intel", json={"enabled": False})
    assert cannot_disable_planning.status_code == 400

    viewer_invite = admin.post(
        "/api/auth/invites",
        json={
            "role_code": "viewer",
            "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
            "expires_in_days": 7,
        },
    )
    assert viewer_invite.status_code == 200
    viewer = TestClient(create_app())
    accepted_viewer = viewer.post(
        f"/api/auth/invites/{viewer_invite.json()['code']}/accept",
        json={
            "username": "hardware-member",
            "display_name": "硬件成员",
            "password": "strong-password",
        },
    )
    assert accepted_viewer.status_code == 200
    viewer_user_id = accepted_viewer.json()["user"]["id"]

    assert [item["code"] for item in viewer.get("/api/workspaces").json()] == ["planning_intel"]

    members_before = editor.get("/api/workspaces/hardware_team/members")
    assert members_before.status_code == 200
    members_before_payload = members_before.json()
    assert [item["user"]["username"] for item in members_before_payload] == [
        "admin",
        "workspace-owner",
    ]
    admin_user_id = next(
        item["user"]["id"]
        for item in members_before_payload
        if item["user"]["username"] == "admin"
    )
    candidates = editor.get("/api/users", params={"workspace_code": "hardware_team"})
    assert candidates.status_code == 200
    assert {"admin", "workspace-owner", "hardware-member"}.issubset(
        {item["username"] for item in candidates.json()}
    )
    viewer_candidates = viewer.get("/api/users", params={"workspace_code": "hardware_team"})
    assert viewer_candidates.status_code == 403

    added = editor.post(
        "/api/workspaces/hardware_team/members",
        json={"user_id": viewer_user_id, "workspace_role": "member"},
    )
    assert added.status_code == 200
    assert added.json()["workspace_role"] == "member"
    assert [item["code"] for item in viewer.get("/api/workspaces").json()] == [
        "planning_intel",
        "hardware_team",
    ]

    removed = editor.delete(f"/api/workspaces/hardware_team/members/{viewer_user_id}")
    assert removed.status_code == 204
    assert [item["code"] for item in viewer.get("/api/workspaces").json()] == ["planning_intel"]

    owner_user_id = accepted_editor.json()["user"]["id"]
    removed_admin_owner = editor.delete(f"/api/workspaces/hardware_team/members/{admin_user_id}")
    assert removed_admin_owner.status_code == 204
    last_owner = editor.delete(f"/api/workspaces/hardware_team/members/{owner_user_id}")
    assert last_owner.status_code == 400


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
