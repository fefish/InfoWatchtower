"""发现搜索（discover?q=）与工作台加入码（workspace_join_codes）。

事实源 docs/backend/workspace-configuration-design.md §14，契约
config/contracts/workspace_model.json `join_code` / `discovery_and_subscription`。

覆盖 §14.4 验收标准：

1. discover?q= 命中 name/description，任何关键词都不返回 private 工作台；
2. admin 生成码 → 另一用户凭码加入 private 工作台成功、角色等于 default_role、
   use_count=1；重复加入幂等且不再计数、不降级已有角色；
3. 轮换后旧码立即 400；停用后 400；过期与用尽同文案 400（统一响应防枚举）；
4. default_role 传 admin/owner 返回 422；
5. 游客凭码加入 403 并提示注册；
6. 连续失败触发 429 限流；
7. 生成/轮换/停用/加入全部落审计；join_by_code 审计含 before/after 快照。
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.feedback import AuditLog
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceJoinCode, WorkspaceMembership

JOIN_CODE_INVALID_DETAIL = "加入码无效或已失效"
JOIN_CODE_ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def make_client(monkeypatch, tmp_path, **env):
    database_path = tmp_path / "workspace_join_codes.sqlite"
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
    return TestClient(create_app()), engine


def login_admin(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert response.status_code == 200
    return client


def invite_user(admin, username):
    """开一个 planning_intel viewer 的普通用户，返回其登录 client。"""
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
        json={"username": username, "display_name": username, "password": "strong-password"},
    )
    assert accepted.status_code == 200
    return client


def create_workspace(admin, code, name, description="", *, internal_public=False):
    created = admin.post(
        "/api/workspaces",
        json={"code": code, "name": name, "description": description},
    )
    assert created.status_code == 201
    assert created.json()["visibility"] == "private"
    if internal_public:
        published = admin.patch(
            f"/api/workspaces/{code}/visibility",
            json={"visibility": "internal_public"},
        )
        assert published.status_code == 200


def issue_join_code(admin, workspace_code, **payload):
    response = admin.post(f"/api/workspaces/{workspace_code}/join-code", json=payload)
    assert response.status_code == 200
    return response.json()


def join_by_code(client, code):
    return client.post("/api/workspaces/join-by-code", json={"code": code})


def discover_codes(client, q=None):
    params = {"q": q} if q is not None else None
    response = client.get("/api/workspaces/discover", params=params)
    assert response.status_code == 200
    return [item["code"] for item in response.json()]


def audit_logs(engine, action):
    Session = sessionmaker(bind=engine)
    with Session() as session:
        return [
            dict(log.detail_json or {})
            for log in session.scalars(
                select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at),
            ).all()
        ]


# ---- §14.1 发现搜索 ----


def test_discover_search_hits_name_and_description(monkeypatch, tmp_path):
    admin, _ = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    create_workspace(admin, "open_intel", "AI Radar 公开情报站", "跟踪大模型竞品动态", internal_public=True)
    create_workspace(admin, "secret_intel", "机密情报工作台", "内部专项跟踪")  # 保持 private

    # 命中 name（大小写不敏感 contains）
    assert "open_intel" in discover_codes(admin, q="ai radar")
    assert "open_intel" in discover_codes(admin, q="公开情报")
    # 命中 description
    assert "open_intel" in discover_codes(admin, q="竞品动态")
    # 未命中关键词过滤掉
    assert "open_intel" not in discover_codes(admin, q="不存在的关键词")
    # q 为空白等价于不过滤
    assert "open_intel" in discover_codes(admin, q="  ")


def test_discover_search_never_returns_private_workspaces(monkeypatch, tmp_path):
    admin, _ = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    create_workspace(admin, "secret_intel", "机密情报工作台", "内部专项跟踪")

    # private 工作台对任何关键词（含精确命中 name/description）都不出现
    for keyword in (None, "机密", "机密情报工作台", "内部专项", "secret"):
        assert "secret_intel" not in discover_codes(admin, q=keyword)


# ---- §14.3 加入码生成 / 轮换 / 停用 ----


def test_join_code_lifecycle_and_admin_gate(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    create_workspace(admin, "team_intel", "团队情报台")

    # 尚未生成时读到 null
    empty = admin.get("/api/workspaces/team_intel/join-code")
    assert empty.status_code == 200
    assert empty.json() is None

    issued = issue_join_code(admin, "team_intel", default_role="member", max_uses=5)
    assert len(issued["code"]) == 8
    assert set(issued["code"]) <= JOIN_CODE_ALPHABET
    assert issued["default_role"] == "member"
    assert issued["max_uses"] == 5
    assert issued["use_count"] == 0
    assert issued["created_by"]

    current = admin.get("/api/workspaces/team_intel/join-code")
    assert current.json()["code"] == issued["code"]

    # 轮换：单事务作废旧码、生成新码，审计标注 rotated_from
    rotated = issue_join_code(admin, "team_intel", default_role="viewer")
    assert rotated["code"] != issued["code"]
    assert admin.get("/api/workspaces/team_intel/join-code").json()["code"] == rotated["code"]
    creates = audit_logs(engine, "workspace.join_code.create")
    assert len(creates) == 2
    assert creates[0]["rotated_from"] is None
    assert creates[1]["rotated_from"] == issued["code"]

    # 停用：幂等 204，审计 workspace.join_code.disable
    assert admin.delete("/api/workspaces/team_intel/join-code").status_code == 204
    assert admin.get("/api/workspaces/team_intel/join-code").json() is None
    assert admin.delete("/api/workspaces/team_intel/join-code").status_code == 204
    disables = audit_logs(engine, "workspace.join_code.disable")
    assert len(disables) == 1
    assert disables[0]["code"] == rotated["code"]

    # 加入码管理是 workspace admin/owner 的能力：非成员普通用户 403
    outsider = invite_user(admin, "jc-outsider")
    assert outsider.get("/api/workspaces/team_intel/join-code").status_code == 403
    assert outsider.post("/api/workspaces/team_intel/join-code", json={}).status_code == 403


def test_join_code_default_role_rejects_admin_and_owner(monkeypatch, tmp_path):
    admin, _ = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    create_workspace(admin, "team_intel", "团队情报台")

    # admin/owner 必须走成员管理单人流程 + 危险确认，加入码只授 viewer|member
    for role in ("admin", "owner"):
        response = admin.post(
            "/api/workspaces/team_intel/join-code",
            json={"default_role": role},
        )
        assert response.status_code == 422


# ---- §14.3 join-by-code 语义 ----


def test_join_by_code_grants_default_role_in_private_workspace(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    create_workspace(admin, "team_intel", "团队情报台")  # private 也可凭码加入
    issued = issue_join_code(admin, "team_intel", default_role="member")

    user = invite_user(admin, "jc-member")
    joined = join_by_code(user, issued["code"])
    assert joined.status_code == 200
    assert joined.json() == {
        "workspace_code": "team_intel",
        "workspace_name": "团队情报台",
        "workspace_role": "member",
        "joined": True,
    }
    assert admin.get("/api/workspaces/team_intel/join-code").json()["use_count"] == 1

    # 重复加入幂等：不再计数、joined=False、角色不变
    repeat = join_by_code(user, issued["code"])
    assert repeat.status_code == 200
    assert repeat.json()["joined"] is False
    assert repeat.json()["workspace_role"] == "member"
    assert admin.get("/api/workspaces/team_intel/join-code").json()["use_count"] == 1

    # 加入审计带 before/after membership 快照（与 workspace.member.subscribe 同口径）
    joins = audit_logs(engine, "workspace.member.join_by_code")
    assert len(joins) == 1
    assert joins[0]["workspace_code"] == "team_intel"
    assert joins[0]["before"] is None
    assert joins[0]["after"] == {"workspace_role": "member", "enabled": True}


def test_join_by_code_never_downgrades_and_reenables_disabled_membership(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    create_workspace(admin, "team_intel", "团队情报台")
    member_code = issue_join_code(admin, "team_intel", default_role="member")["code"]

    user = invite_user(admin, "jc-keeper")
    assert join_by_code(user, member_code).json()["workspace_role"] == "member"

    # 轮换成 viewer 码后再次加入：已有 enabled membership 保持 member 不降级
    viewer_code = issue_join_code(admin, "team_intel", default_role="viewer")["code"]
    kept = join_by_code(user, viewer_code)
    assert kept.status_code == 200
    assert kept.json()["workspace_role"] == "member"
    assert kept.json()["joined"] is False
    assert admin.get("/api/workspaces/team_intel/join-code").json()["use_count"] == 0

    # 被移出（membership disabled）后凭码重新启用，角色取码上的 default_role
    Session = sessionmaker(bind=engine)
    with Session() as session:
        user_id = session.scalar(select(User).where(User.username == "jc-keeper")).id
    removed = admin.delete(f"/api/workspaces/team_intel/members/{user_id}")
    assert removed.status_code == 204
    rejoined = join_by_code(user, viewer_code)
    assert rejoined.status_code == 200
    assert rejoined.json()["joined"] is True
    assert rejoined.json()["workspace_role"] == "viewer"
    assert admin.get("/api/workspaces/team_intel/join-code").json()["use_count"] == 1
    with Session() as session:
        workspace_id = session.scalar(select(Workspace).where(Workspace.code == "team_intel")).id
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            ),
        )
        assert membership.enabled is True
        assert membership.workspace_role == "viewer"


def test_join_by_code_uniform_400_for_all_invalid_states(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    create_workspace(admin, "team_intel", "团队情报台")
    user = invite_user(admin, "jc-prober")

    def assert_invalid(code):
        response = join_by_code(user, code)
        assert response.status_code == 400
        # 统一响应体：不区分 不存在/disabled/过期/用尽，不泄露工作台存在性
        assert response.json() == {"detail": JOIN_CODE_INVALID_DETAIL}

    # 不存在
    assert_invalid("ZZZZ9999")

    # 轮换后旧码立即失效
    first = issue_join_code(admin, "team_intel")["code"]
    second = issue_join_code(admin, "team_intel")["code"]
    assert_invalid(first)

    # 停用后失效
    assert admin.delete("/api/workspaces/team_intel/join-code").status_code == 204
    assert_invalid(second)

    # 过期：把 active 码的 expires_at 拨到过去
    expiring = issue_join_code(admin, "team_intel", expires_in_days=1)["code"]
    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.scalar(select(WorkspaceJoinCode).where(WorkspaceJoinCode.code == expiring))
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()
    assert_invalid(expiring)

    # 用尽：max_uses=1，第一位用完后第二位同文案 400
    exhausted = issue_join_code(admin, "team_intel", max_uses=1)["code"]
    first_user = invite_user(admin, "jc-first")
    assert join_by_code(first_user, exhausted).status_code == 200
    assert_invalid(exhausted)


def test_join_by_code_guest_gets_register_hint(monkeypatch, tmp_path):
    admin, _ = make_client(monkeypatch, tmp_path, AUTH_GUEST_ENABLED="true")
    login_admin(admin)
    create_workspace(admin, "team_intel", "团队情报台")
    issued = issue_join_code(admin, "team_intel")

    guest = TestClient(create_app())
    assert guest.post("/api/auth/guest-login").status_code == 200
    response = join_by_code(guest, issued["code"])
    assert response.status_code == 403
    assert "注册" in response.json()["detail"]


def test_join_by_code_rate_limits_repeated_failures(monkeypatch, tmp_path):
    admin, _ = make_client(monkeypatch, tmp_path)
    login_admin(admin)
    user = invite_user(admin, "jc-bruteforce")

    # 15 分钟窗口内 10 次失败后同窗口 429（按 用户+IP 限流，防码枚举）
    for _ in range(10):
        assert join_by_code(user, "AAAA2222").status_code == 400
    limited = join_by_code(user, "AAAA2222")
    assert limited.status_code == 429

    # 未触发限流的另一个用户不受影响
    other = invite_user(admin, "jc-normal")
    assert join_by_code(other, "AAAA2222").status_code == 400
