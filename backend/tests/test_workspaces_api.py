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

    feedback_policy = client.get("/api/workspaces/hardware_intel/feedback-policy")
    assert feedback_policy.status_code == 200
    assert feedback_policy.json()["viewer_can_comment"] is True


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
    owner_without_confirmation = editor.delete(f"/api/workspaces/hardware_team/members/{admin_user_id}")
    assert owner_without_confirmation.status_code == 409
    removed_admin_owner = editor.delete(
        f"/api/workspaces/hardware_team/members/{admin_user_id}",
        params={"confirm_dangerous_change": "true"},
    )
    assert removed_admin_owner.status_code == 204
    last_owner = editor.delete(f"/api/workspaces/hardware_team/members/{owner_user_id}")
    assert last_owner.status_code == 400


def test_workspace_auth_membership_mapping_is_editable_by_super_admin(monkeypatch, tmp_path):
    admin = make_client(monkeypatch, tmp_path)

    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    empty = admin.get("/api/workspaces/ai_tools/auth-membership-mapping")
    assert empty.status_code == 200
    assert empty.json() == {"workspace_code": "ai_tools", "department_workspaces": []}

    updated = admin.patch(
        "/api/workspaces/ai_tools/auth-membership-mapping",
        json={
            "department_workspaces": [
                {"department": " 战略部 ", "workspace_role": "viewer"},
                {"department": "战略部", "workspace_role": "member"},
                {"department": "硬件部", "workspace_role": "admin"},
            ],
        },
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "workspace_code": "ai_tools",
        "department_workspaces": [
            {"department": "战略部", "workspace_role": "member"},
            {"department": "硬件部", "workspace_role": "admin"},
        ],
    }

    audit = admin.get("/api/audit-logs", params={"action": "workspace.auth_membership_mapping.update"})
    assert audit.status_code == 200
    assert audit.json()[0]["detail_json"]["workspace_code"] == "ai_tools"

    editor_invite = admin.post(
        "/api/auth/invites",
        json={
            "role_code": "editor_admin",
            "workspaces": [{"code": "planning_intel", "workspace_role": "admin"}],
            "expires_in_days": 7,
        },
    )
    editor = TestClient(create_app())
    assert editor.post(
        f"/api/auth/invites/{editor_invite.json()['code']}/accept",
        json={
            "username": "workspace-admin",
            "display_name": "工作台管理员",
            "password": "strong-password",
        },
    ).status_code == 200

    forbidden = editor.patch(
        "/api/workspaces/ai_tools/auth-membership-mapping",
        json={"department_workspaces": [{"department": "测试部", "workspace_role": "viewer"}]},
    )
    assert forbidden.status_code == 403


def test_workspace_feedback_policy_is_admin_scoped(monkeypatch, tmp_path):
    admin = make_client(monkeypatch, tmp_path)

    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

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
            "username": "feedback-viewer",
            "display_name": "反馈浏览者",
            "password": "strong-password",
        },
    )
    assert accepted_viewer.status_code == 200

    readable = viewer.get("/api/workspaces/planning_intel/feedback-policy")
    assert readable.status_code == 200
    assert readable.json()["viewer_can_react"] is True

    viewer_update = viewer.patch(
        "/api/workspaces/planning_intel/feedback-policy",
        json={"viewer_can_comment": False},
    )
    assert viewer_update.status_code == 403

    updated = admin.patch(
        "/api/workspaces/planning_intel/feedback-policy",
        json={
            "viewer_can_react": False,
            "viewer_can_rate": False,
            "viewer_can_comment": False,
            "viewer_can_edit": False,
            "notify_on_comment": True,
            "notify_on_publish": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["viewer_can_react"] is False
    assert updated.json()["notify_on_publish"] is True

    reread = viewer.get("/api/workspaces/planning_intel/feedback-policy")
    assert reread.status_code == 200
    assert reread.json()["viewer_can_comment"] is False


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


# --- workspace_sections 管理 API ---


def _register_optional_section(engine, workspace_code="planning_intel", section_key="tool_catalog"):
    """契约口径：可选模块是数据库注册、默认关闭的 workspace_sections 记录。"""
    from sqlalchemy import select

    from app.models.workspace import Workspace, WorkspaceSection

    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
        assert workspace is not None
        session.add(
            WorkspaceSection(
                workspace_id=workspace.id,
                section_key=section_key,
                name="工具目录",
                section_type="page",
                route_path="/tools/catalog",
                sort_order=95,
                enabled=False,
                config_json={"group": "system"},
            ),
        )
        session.commit()


def _section_keys(client, workspace_code="planning_intel"):
    response = client.get(f"/api/workspaces/{workspace_code}/sections")
    assert response.status_code == 200
    return [item["section_key"] for item in response.json()]


def test_section_management_toggles_optional_module(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    engine = get_engine()
    assert engine is not None
    _register_optional_section(engine)

    # 可选模块默认关闭，不出现在导航分区里
    assert "tool_catalog" not in _section_keys(client)

    enabled = client.patch(
        "/api/workspaces/planning_intel/sections/tool_catalog",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"section_key": "tool_catalog", "name": "工具目录", "enabled": True}
    assert "tool_catalog" in _section_keys(client)

    # bootstrap 重播种会把定义外分区的 enabled 列重置为 False，
    # 但用户在管理 API 里的启停决定（config_json.user_enabled）不回滚
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    assert "tool_catalog" in _section_keys(client)

    disabled = client.patch(
        "/api/workspaces/planning_intel/sections/tool_catalog",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert "tool_catalog" not in _section_keys(client)


def test_section_management_rejects_disabling_core_sections(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    for core_key in ("source_management", "daily_reports"):
        rejected = client.patch(
            f"/api/workspaces/planning_intel/sections/{core_key}",
            json={"enabled": False},
        )
        assert rejected.status_code == 400, core_key
        assert "cannot be disabled" in rejected.json()["detail"]
        assert core_key in _section_keys(client)

    # 核心分区显式启用是幂等操作，不报错
    accepted = client.patch(
        "/api/workspaces/planning_intel/sections/daily_reports",
        json={"enabled": True},
    )
    assert accepted.status_code == 200

    missing = client.patch(
        "/api/workspaces/planning_intel/sections/nonexistent_section",
        json={"enabled": True},
    )
    assert missing.status_code == 404


def test_section_management_requires_workspace_admin(monkeypatch, tmp_path):
    admin = make_client(monkeypatch, tmp_path)
    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    engine = get_engine()
    assert engine is not None
    _register_optional_section(engine)

    from sqlalchemy import select

    from app.auth.passwords import hash_password
    from app.models.identity import Role, User
    from app.models.workspace import Workspace, WorkspaceMembership

    Session = sessionmaker(bind=engine)
    with Session() as session:
        viewer_role = session.scalar(select(Role).where(Role.code == "viewer"))
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        viewer = User(
            external_provider="local",
            external_id="section-viewer",
            username="section-viewer",
            display_name="分区只读用户",
            password_hash=hash_password("password"),
            status="active",
            roles=[viewer_role],
        )
        session.add(viewer)
        session.flush()
        session.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=viewer.id,
                workspace_role="viewer",
                enabled=True,
            ),
        )
        session.commit()

    viewer_client = TestClient(create_app())
    viewer_login = viewer_client.post(
        "/api/auth/login",
        json={"username": "section-viewer", "password": "password"},
    )
    assert viewer_login.status_code == 200

    rejected = viewer_client.patch(
        "/api/workspaces/planning_intel/sections/tool_catalog",
        json={"enabled": True},
    )
    assert rejected.status_code == 403
