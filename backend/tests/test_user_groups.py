from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.auth.passwords import hash_password
from app.main import create_app
from app.models.feedback import AuditLog
from app.models.identity import Role, User
from app.models.workspace import Workspace, WorkspaceMembership
from tests.test_auth import make_client


def _create_local_user(
    engine,
    username: str,
    password: str,
    *,
    role_code: str = "viewer",
    workspace_role: str | None = None,
    workspace_code: str = "planning_intel",
) -> User:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        role = session.scalar(select(Role).where(Role.code == role_code))
        user = User(
            external_provider="local",
            external_id=username,
            username=username,
            display_name=username.title(),
            password_hash=hash_password(password),
            status="active",
            roles=[role],
        )
        session.add(user)
        session.flush()
        if workspace_role:
            workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    workspace_role=workspace_role,
                    enabled=True,
                ),
            )
        session.commit()
        session.refresh(user)
        return user


def _login(username: str, password: str) -> TestClient:
    client = TestClient(create_app())
    assert client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    ).status_code == 200
    return client


def test_user_group_crud_and_member_management(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    alice = _create_local_user(engine, "group-alice", "password-123")
    bob = _create_local_user(engine, "group-bob", "password-123")

    created = client.post(
        "/api/user-groups",
        json={"code": "planning_team", "name": "规划团队", "description": "规划部核心协作组"},
    )
    assert created.status_code == 201
    assert created.json()["code"] == "planning_team"
    assert created.json()["member_count"] == 0

    duplicated = client.post(
        "/api/user-groups",
        json={"code": "planning_team", "name": "重复组"},
    )
    assert duplicated.status_code == 409

    added = client.post("/api/user-groups/planning_team/members", json={"user_id": alice.id})
    assert added.status_code == 200
    assert added.json()["member_count"] == 1
    # 重复加入同一成员保持幂等。
    re_added = client.post("/api/user-groups/planning_team/members", json={"user_id": alice.id})
    assert re_added.status_code == 200
    assert re_added.json()["member_count"] == 1
    assert client.post("/api/user-groups/planning_team/members", json={"user_id": bob.id}).status_code == 200
    assert client.post(
        "/api/user-groups/planning_team/members",
        json={"user_id": "missing-user"},
    ).status_code == 404

    listed = client.get("/api/user-groups")
    assert listed.status_code == 200
    assert [(item["code"], item["member_count"]) for item in listed.json()] == [("planning_team", 2)]

    detail = client.get("/api/user-groups/planning_team")
    assert detail.status_code == 200
    assert {member["username"] for member in detail.json()["members"]} == {"group-alice", "group-bob"}

    renamed = client.patch("/api/user-groups/planning_team", json={"name": "规划团队 v2"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "规划团队 v2"

    removed = client.delete(f"/api/user-groups/planning_team/members/{bob.id}")
    assert removed.status_code == 204
    assert client.get("/api/user-groups/planning_team").json()["member_count"] == 1

    deleted = client.delete("/api/user-groups/planning_team")
    assert deleted.status_code == 204
    assert client.get("/api/user-groups").json() == []

    Session = sessionmaker(bind=engine)
    with Session() as session:
        actions = {row.action for row in session.scalars(select(AuditLog)).all()}
    assert {
        "user_group.create",
        "user_group.update",
        "user_group.member.add",
        "user_group.member.remove",
        "user_group.delete",
    } <= actions


def test_user_group_management_requires_manager_roles(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    _create_local_user(engine, "group-editor", "password-123", role_code="editor_admin")
    _create_local_user(engine, "group-viewer", "password-123", role_code="viewer", workspace_role="admin")

    editor_client = _login("group-editor", "password-123")
    created = editor_client.post(
        "/api/user-groups",
        json={"code": "editor_team", "name": "采编团队"},
    )
    assert created.status_code == 201

    viewer_client = _login("group-viewer", "password-123")
    assert viewer_client.get("/api/user-groups").status_code == 403
    denied = viewer_client.post(
        "/api/user-groups",
        json={"code": "viewer_team", "name": "不该建成"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Requires super_admin or editor_admin"


def test_bulk_add_group_members_to_workspace_is_idempotent(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    newcomer = _create_local_user(engine, "bulk-newcomer", "password-123")
    existing_admin = _create_local_user(engine, "bulk-existing-admin", "password-123", workspace_role="admin")
    inactive = _create_local_user(engine, "bulk-inactive", "password-123")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.get(User, inactive.id).is_active = False
        session.commit()

    assert client.post("/api/user-groups", json={"code": "bulk_team", "name": "批量组"}).status_code == 201
    for user in (newcomer, existing_admin, inactive):
        assert client.post("/api/user-groups/bulk_team/members", json={"user_id": user.id}).status_code == 200

    first = client.post(
        "/api/workspaces/planning_intel/members/bulk",
        json={"group_code": "bulk_team", "workspace_role": "member"},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["added_count"] == 1
    assert payload["reactivated_count"] == 0
    # 已在台成员保持原角色、停用账号跳过。
    assert payload["skipped_count"] == 2

    second = client.post(
        "/api/workspaces/planning_intel/members/bulk",
        json={"group_code": "bulk_team", "workspace_role": "member"},
    )
    assert second.status_code == 200
    assert second.json()["added_count"] == 0
    assert second.json()["skipped_count"] == 3

    members = client.get("/api/workspaces/planning_intel/members")
    assert members.status_code == 200
    roles_by_username = {row["user"]["username"]: row["workspace_role"] for row in members.json()}
    assert roles_by_username["bulk-newcomer"] == "member"
    # 幂等展开不降级已有 admin。
    assert roles_by_username["bulk-existing-admin"] == "admin"
    assert "bulk-inactive" not in roles_by_username

    with Session() as session:
        audit = session.scalars(
            select(AuditLog).where(AuditLog.action == "workspace.member.bulk_upsert"),
        ).all()
    assert len(audit) == 2
    assert audit[0].detail_json["group_code"] == "bulk_team"
    assert audit[0].detail_json["added_user_ids"] == [newcomer.id]


def test_bulk_add_requires_workspace_admin_and_rejects_owner_role(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    member = _create_local_user(engine, "bulk-plain-member", "password-123", workspace_role="member")
    assert client.post("/api/user-groups", json={"code": "guard_team", "name": "守护组"}).status_code == 201

    member_client = _login("bulk-plain-member", "password-123")
    denied = member_client.post(
        "/api/workspaces/planning_intel/members/bulk",
        json={"group_code": "guard_team", "workspace_role": "member"},
    )
    assert denied.status_code == 403

    owner_rejected = client.post(
        "/api/workspaces/planning_intel/members/bulk",
        json={"group_code": "guard_team", "workspace_role": "owner"},
    )
    assert owner_rejected.status_code == 422

    missing_group = client.post(
        "/api/workspaces/planning_intel/members/bulk",
        json={"group_code": "missing_team", "workspace_role": "member"},
    )
    assert missing_group.status_code == 404
