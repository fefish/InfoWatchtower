"""工作台可见性（visibility）与自助订阅（discover/subscribe）。

语义（见 app/api/routes/workspaces.py 与 app/auth/guest.py）：

- visibility=private：仅成员可见；internal_public：登录用户可在 discover 发现
  并自助订阅为 viewer member，游客可只读浏览（不建 membership）。
- 订阅幂等；private/不存在的工作台订阅一律 404，不泄露存在性。
- 退订只移除自己的 viewer membership；角色高于 viewer 由管理员管理（400）。
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app


def make_client(monkeypatch, tmp_path, **env):
    database_path = tmp_path / "workspace_subscription.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_MODE", "public_password")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app())


def login_admin(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert response.status_code == 200
    return client


def invite_viewer(admin, username):
    """开一个 planning_intel viewer 用户（不属于其他工作台），返回其登录 client。"""
    invite = admin.post(
        "/api/auth/invites",
        json={
            "role_code": "viewer",
            "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
            "expires_in_days": 7,
        },
    )
    assert invite.status_code == 200
    client = TestClient(create_app())
    accepted = client.post(
        f"/api/auth/invites/{invite.json()['code']}/accept",
        json={
            "username": username,
            "display_name": username,
            "password": "strong-password",
        },
    )
    assert accepted.status_code == 200
    return client


def create_open_workspace(admin, code="open_intel", name="公开情报工作台"):
    created = admin.post(
        "/api/workspaces",
        json={"code": code, "name": name, "description": "自助订阅用"},
    )
    assert created.status_code == 201
    assert created.json()["visibility"] == "private"
    published = admin.patch(f"/api/workspaces/{code}/visibility", json={"visibility": "internal_public"})
    assert published.status_code == 200
    assert published.json()["visibility"] == "internal_public"


def discover_map(client):
    response = client.get("/api/workspaces/discover")
    assert response.status_code == 200
    return {item["code"]: item for item in response.json()}


def test_seed_visibility_defaults(monkeypatch, tmp_path):
    admin = login_admin(make_client(monkeypatch, tmp_path))

    listed = {item["code"]: item for item in admin.get("/api/workspaces").json()}
    # 种子口径：planning_intel 开放发现/订阅，ai_tools 保持 private
    assert listed["planning_intel"]["visibility"] == "internal_public"
    assert listed["ai_tools"]["visibility"] == "private"

    # 新建工作台默认 private，不进发现列表
    created = admin.post(
        "/api/workspaces",
        json={"code": "hardware_intel", "name": "硬件情报工作台", "description": ""},
    )
    assert created.status_code == 201
    assert created.json()["visibility"] == "private"
    assert "hardware_intel" not in discover_map(admin)


def test_discover_lists_internal_public_with_membership_flags(monkeypatch, tmp_path):
    admin = login_admin(make_client(monkeypatch, tmp_path))
    create_open_workspace(admin)
    viewer = invite_viewer(admin, "sub-viewer")

    discovered = discover_map(viewer)
    # private（ai_tools）永不出现在发现列表
    assert "ai_tools" not in discovered
    assert discovered["planning_intel"]["joined"] is True
    assert discovered["planning_intel"]["workspace_role"] == "viewer"
    assert discovered["planning_intel"]["member_count"] >= 2
    assert discovered["open_intel"]["joined"] is False
    assert discovered["open_intel"]["workspace_role"] is None


def test_subscribe_is_idempotent_and_grants_viewer_membership(monkeypatch, tmp_path):
    admin = login_admin(make_client(monkeypatch, tmp_path))
    create_open_workspace(admin)
    viewer = invite_viewer(admin, "sub-viewer")
    member_count_before = discover_map(viewer)["open_intel"]["member_count"]

    subscribed = viewer.post("/api/workspaces/open_intel/subscribe")
    assert subscribed.status_code == 200
    assert subscribed.json() == {
        "workspace_code": "open_intel",
        "workspace_role": "viewer",
        "subscribed": True,
    }

    # 幂等：重复订阅返回同一 membership，不叠加
    again = viewer.post("/api/workspaces/open_intel/subscribe")
    assert again.status_code == 200
    assert again.json()["workspace_role"] == "viewer"

    listed = {item["code"]: item for item in viewer.get("/api/workspaces").json()}
    assert listed["open_intel"]["current_user_workspace_role"] == "viewer"

    discovered = discover_map(viewer)
    assert discovered["open_intel"]["joined"] is True
    assert discovered["open_intel"]["member_count"] == member_count_before + 1

    # 已有更高角色的成员重复订阅不会被降级成 viewer
    owner_subscribe = admin.post("/api/workspaces/open_intel/subscribe")
    assert owner_subscribe.status_code == 200
    assert owner_subscribe.json()["workspace_role"] == "owner"


def test_subscribe_private_or_unknown_workspace_is_404(monkeypatch, tmp_path):
    admin = login_admin(make_client(monkeypatch, tmp_path))
    viewer = invite_viewer(admin, "sub-viewer")

    # private 与不存在同响应：不泄露工作台存在性
    private = viewer.post("/api/workspaces/ai_tools/subscribe")
    unknown = viewer.post("/api/workspaces/no_such_ws/subscribe")
    assert private.status_code == 404
    assert unknown.status_code == 404
    assert private.json() == unknown.json()


def test_unsubscribe_removes_own_viewer_membership_idempotently(monkeypatch, tmp_path):
    admin = login_admin(make_client(monkeypatch, tmp_path))
    create_open_workspace(admin)
    viewer = invite_viewer(admin, "sub-viewer")
    assert viewer.post("/api/workspaces/open_intel/subscribe").status_code == 200

    removed = viewer.delete("/api/workspaces/open_intel/subscribe")
    assert removed.status_code == 204
    assert "open_intel" not in {item["code"] for item in viewer.get("/api/workspaces").json()}
    assert discover_map(viewer)["open_intel"]["joined"] is False

    # 幂等：已不在成员列表时退订依然 204
    assert viewer.delete("/api/workspaces/open_intel/subscribe").status_code == 204

    # 退订后可重新订阅
    assert viewer.post("/api/workspaces/open_intel/subscribe").status_code == 200


def test_unsubscribe_above_viewer_role_is_managed_by_admins(monkeypatch, tmp_path):
    admin = login_admin(make_client(monkeypatch, tmp_path))
    create_open_workspace(admin)

    # admin 是 open_intel 的 owner：自助退订被拒，避免绕过最后 owner 保护
    rejected = admin.delete("/api/workspaces/open_intel/subscribe")
    assert rejected.status_code == 400
    assert "managed by workspace admins" in rejected.json()["detail"]


def test_visibility_patch_requires_workspace_admin(monkeypatch, tmp_path):
    admin = login_admin(make_client(monkeypatch, tmp_path))
    create_open_workspace(admin)
    viewer = invite_viewer(admin, "sub-viewer")

    forbidden = viewer.patch(
        "/api/workspaces/planning_intel/visibility",
        json={"visibility": "private"},
    )
    assert forbidden.status_code == 403

    invalid = admin.patch("/api/workspaces/open_intel/visibility", json={"visibility": "public"})
    assert invalid.status_code == 422

    hidden = admin.patch("/api/workspaces/open_intel/visibility", json={"visibility": "private"})
    assert hidden.status_code == 200
    assert hidden.json()["visibility"] == "private"
    # 改回 private 后：发现列表消失、订阅 404
    assert "open_intel" not in discover_map(viewer)
    assert viewer.post("/api/workspaces/open_intel/subscribe").status_code == 404


def test_guest_browses_internal_public_readonly_without_membership(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, AUTH_GUEST_ENABLED="true")
    login_admin(client)

    guest = TestClient(create_app())
    guest_login = guest.post("/api/auth/guest-login")
    assert guest_login.status_code == 200
    assert guest_login.json()["user"]["external_provider"] == "guest"

    # 游客按隐式 viewer 视角只看到 internal_public 工作台
    listed = guest.get("/api/workspaces")
    assert listed.status_code == 200
    listed_map = {item["code"]: item for item in listed.json()}
    assert set(listed_map) == {"planning_intel"}
    assert listed_map["planning_intel"]["current_user_workspace_role"] == "viewer"

    sections = guest.get("/api/workspaces/planning_intel/sections")
    assert sections.status_code == 200

    # private 工作台对游客不可读
    assert guest.get("/api/workspaces/ai_tools/sections").status_code == 403

    # 发现列表可看：joined 恒为 False（游客不建 membership），角色显示隐式 viewer
    discovered = discover_map(guest)
    assert discovered["planning_intel"]["joined"] is False
    assert discovered["planning_intel"]["workspace_role"] == "viewer"

    # 订阅是写操作：集中门禁 403 并提示注册后可用
    denied = guest.post("/api/workspaces/planning_intel/subscribe")
    assert denied.status_code == 403
    assert "注册" in denied.json()["detail"]

    # 游客不出现在成员列表（member_count 不包含游客）
    admin_members = client.get("/api/workspaces/planning_intel/members")
    assert admin_members.status_code == 200
    assert "guest" not in {item["user"]["username"] for item in admin_members.json()}
