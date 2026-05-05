from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.auth.passwords import hash_password
from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.identity import Role, User
from app.models.labels import Label, LabelSet
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceSection


def make_client(monkeypatch, tmp_path, **env):
    database_path = tmp_path / "auth.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME", "规划部管理员")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app()), engine


def test_public_password_login_sets_session_and_returns_current_user(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")

    response = client.post("/api/auth/login", json={"username": "admin", "password": "password"})

    assert response.status_code == 200
    assert "infowatchtower_session" in response.headers["set-cookie"]
    payload = response.json()
    assert payload["user"]["display_name"] == "规划部管理员"
    assert payload["user"]["roles"] == ["super_admin"]

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"


def test_auth_seed_creates_default_workspaces(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspaces = session.scalars(select(Workspace).order_by(Workspace.code)).all()
        assert [workspace.code for workspace in workspaces] == ["ai_tools", "planning_intel"]
        memberships = session.scalars(select(WorkspaceMembership)).all()
        assert len(memberships) == 2
        for workspace in workspaces:
            enabled_sections = {
                section.section_key
                for section in session.scalars(
                    select(WorkspaceSection).where(
                        WorkspaceSection.workspace_id == workspace.id,
                        WorkspaceSection.enabled.is_(True),
                    ),
                ).all()
            }
            assert {
                "dashboard",
                "source_management",
                "candidate_pool",
                "daily_reports",
                "weekly_reports",
                "exports",
                "users",
                "audit_logs",
            }.issubset(enabled_sections)
            assert {"sources", "topics", "tool_catalog", "tool_runs"}.isdisjoint(enabled_sections)


def test_authenticated_user_can_load_workspace_sections(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    workspaces = client.get("/api/workspaces")
    assert workspaces.status_code == 200
    assert [item["code"] for item in workspaces.json()] == ["planning_intel", "ai_tools"]

    sections = client.get("/api/workspaces/ai_tools/sections")
    assert sections.status_code == 200
    section_keys = [item["section_key"] for item in sections.json()]
    assert section_keys == [
        "dashboard",
        "source_management",
        "candidate_pool",
        "daily_reports",
        "weekly_reports",
        "exports",
        "users",
        "audit_logs",
    ]
    assert "topics" not in section_keys
    assert "tool_catalog" not in section_keys
    assert "tool_runs" not in section_keys


def test_auth_seed_creates_default_label_set(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        label_set = session.scalar(select(LabelSet).where(LabelSet.code == "ai_sql_categories"))
        assert label_set is not None
        assert label_set.workspace_code == "shared"
        assert session.scalar(select(Label).where(Label.name == "基础竞争力")) is not None


def test_super_admin_can_list_roles_and_update_user_roles(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        viewer_role = session.scalar(select(Role).where(Role.code == "viewer"))
        user = User(
            external_provider="local",
            external_id="analyst",
            username="analyst",
            display_name="分析员",
            password_hash=hash_password("password"),
            status="active",
            roles=[viewer_role],
        )
        session.add(user)
        session.commit()
        user_id = user.id

    roles = client.get("/api/roles")
    assert roles.status_code == 200
    assert {item["code"] for item in roles.json()} == {
        "analyst",
        "editor_admin",
        "super_admin",
        "viewer",
    }

    updated = client.patch(f"/api/users/{user_id}/roles", json={"role_codes": ["analyst"]})
    assert updated.status_code == 200
    assert updated.json()["roles"] == ["analyst"]


def test_intranet_header_auto_provisions_viewer(monkeypatch, tmp_path):
    client, _ = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="intranet_header",
        AUTH_AUTO_PROVISION="true",
        AUTH_DEFAULT_ROLE="viewer",
    )

    response = client.get(
        "/api/auth/me",
        headers={
            "X-Employee-No": "E001",
            "X-Employee-Name": "%E5%86%85%E7%BD%91%E7%94%A8%E6%88%B7",
            "X-Department": "%E8%A7%84%E5%88%92%E9%83%A8",
            "X-Email": "e001@example.com",
        },
    )

    assert response.status_code == 200
    payload = response.json()["user"]
    assert payload["external_provider"] == "intranet_header"
    assert payload["external_id"] == "E001"
    assert payload["employee_no"] == "E001"
    assert payload["display_name"] == "内网用户"
    assert payload["roles"] == ["viewer"]
