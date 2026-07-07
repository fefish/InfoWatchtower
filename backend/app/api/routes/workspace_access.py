"""工作台加入码（workspace join codes，workspace-configuration-design §14）。

已注册用户的团队自助入台入口，与全局邀请码（user_invites）互补：邀请码面向
未注册的具体个人（建号 + 全局角色），加入码只授 membership——不建号、不改全局
角色、只授 viewer/member。private 与 internal_public 工作台都可凭码加入。

语义要点：

- 每台至多一个 active 码；「轮换」= 单事务内旧码置 disabled + 生成新码；
- join-by-code 对 码不存在/disabled/过期/用尽/工作台停用 统一返回同一 400
  文案，不区分原因、不泄露目标工作台存在性（防枚举）；
- 加入幂等不降级：enabled membership 保持原角色（joined=false 且不计数），
  disabled membership 以码上 default_role 重新启用，非成员按 default_role 新建；
- 失败尝试按「用户 + IP」限流（15 分钟窗口 10 次失败后 429），复用
  login_attempts 表机制；
- 审计：workspace.join_code.create（轮换在 detail 标注 rotated_from）、
  workspace.join_code.disable、workspace.member.join_by_code（带 before/after
  membership 快照，口径同 workspace.member.subscribe）。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import _client_ip, assert_workspace_member, get_current_user
from app.auth.service import login_failure_count, record_login_attempt, write_audit
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceJoinCode, WorkspaceMembership
from app.schemas.workspaces import (
    WorkspaceJoinByCodeRead,
    WorkspaceJoinByCodeRequest,
    WorkspaceJoinCodeCreate,
    WorkspaceJoinCodeRead,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# 8 位大写字母+数字，剔除易混字符 0/O/1/I
JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 8
# 统一失效文案：不存在/disabled/过期/用尽/工作台停用同一响应体（防枚举）
JOIN_CODE_INVALID_DETAIL = "加入码无效或已失效"
JOIN_FAILURE_LIMIT = 10
# 失败限流复用 login_attempts 表：username 列写入带前缀的用户 id 作为限流键
JOIN_ATTEMPT_KEY_PREFIX = "join_code:"


@router.get("/{workspace_code}/join-code", response_model=WorkspaceJoinCodeRead | None)
def get_join_code(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceJoinCodeRead | None:
    """当前 active 加入码（workspace admin/owner；super_admin 绕过 membership）。"""
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    active = _active_join_code(session, workspace)
    if active is None:
        return None
    return _join_code_to_read(session, active)


@router.post("/{workspace_code}/join-code", response_model=WorkspaceJoinCodeRead)
def create_or_rotate_join_code(
    workspace_code: str,
    payload: WorkspaceJoinCodeCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceJoinCodeRead:
    """生成加入码；已有 active 码时视为轮换（旧码同事务置 disabled）。

    default_role 只允许 viewer|member（schema pattern 422 拦截），admin/owner
    必须走成员管理单人流程 + 危险确认。历史码保留不删（审计追溯）。
    """
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    now = datetime.now(timezone.utc)
    old = _active_join_code(session, workspace)
    if old is not None:
        old.status = "disabled"
        old.disabled_at = now
    expires_at = None
    if payload.expires_in_days is not None:
        expires_at = now + timedelta(days=payload.expires_in_days)
    join_code = WorkspaceJoinCode(
        workspace_id=workspace.id,
        code=_generate_unique_code(session),
        default_role=payload.default_role,
        expires_at=expires_at,
        max_uses=payload.max_uses,
        use_count=0,
        status="active",
        created_by_id=current_user.id,
    )
    session.add(join_code)
    write_audit(
        session,
        current_user,
        "workspace.join_code.create",
        "workspace",
        workspace.id,
        {
            "workspace_code": workspace.code,
            "code": join_code.code,
            "default_role": join_code.default_role,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "max_uses": payload.max_uses,
            "rotated_from": old.code if old is not None else None,
        },
    )
    # 单事务：旧码作废与新码生成一次 commit 落库，轮换不产生两码并存窗口
    session.commit()
    session.refresh(join_code)
    return _join_code_to_read(session, join_code)


@router.delete("/{workspace_code}/join-code", status_code=status.HTTP_204_NO_CONTENT)
def disable_join_code(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    """幂等停用当前 active 码（无 active 码时同样 204）。"""
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    active = _active_join_code(session, workspace)
    if active is not None:
        active.status = "disabled"
        active.disabled_at = datetime.now(timezone.utc)
        write_audit(
            session,
            current_user,
            "workspace.join_code.disable",
            "workspace",
            workspace.id,
            {"workspace_code": workspace.code, "code": active.code},
        )
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/join-by-code", response_model=WorkspaceJoinByCodeRead)
def join_by_code(
    payload: WorkspaceJoinByCodeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> WorkspaceJoinByCodeRead:
    """任意已登录用户凭码加入工作台（游客在中央写门禁被 403 拦截并提示注册）。

    幂等 upsert membership，永不降级；仅真实新增或重新启用时 use_count += 1。
    加入码只是 membership 入口，不改变任何全局角色、RBAC 或部署形态语义。
    """
    ip = _client_ip(request, settings)
    rate_key = f"{JOIN_ATTEMPT_KEY_PREFIX}{current_user.id}"
    if login_failure_count(session, rate_key, ip) >= JOIN_FAILURE_LIMIT:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts")

    now = datetime.now(timezone.utc)
    submitted = payload.code.strip().upper()
    join_code = session.scalar(select(WorkspaceJoinCode).where(WorkspaceJoinCode.code == submitted))
    workspace = session.get(Workspace, join_code.workspace_id) if join_code is not None else None
    if (
        join_code is None
        or join_code.status != "active"
        or (join_code.expires_at is not None and _as_utc(join_code.expires_at) <= now)
        or (join_code.max_uses is not None and join_code.use_count >= join_code.max_uses)
        or workspace is None
        or not workspace.enabled
    ):
        record_login_attempt(session, rate_key, ip, success=False)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=JOIN_CODE_INVALID_DETAIL)

    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == current_user.id,
        ),
    )
    if membership is not None and membership.enabled:
        # 已有 enabled membership：保持原角色不降级、不计数
        record_login_attempt(session, rate_key, ip, success=True)
        session.commit()
        return WorkspaceJoinByCodeRead(
            workspace_code=workspace.code,
            workspace_name=workspace.name,
            workspace_role=membership.workspace_role,
            joined=False,
        )

    before_membership = _membership_snapshot(membership)
    if membership is None:
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=current_user.id,
            workspace_role=join_code.default_role,
            enabled=True,
        )
        session.add(membership)
    else:
        membership.workspace_role = join_code.default_role
        membership.enabled = True
    join_code.use_count += 1
    write_audit(
        session,
        current_user,
        "workspace.member.join_by_code",
        "workspace",
        workspace.id,
        {
            "workspace_code": workspace.code,
            "user_id": current_user.id,
            "code": join_code.code,
            "before": before_membership,
            "after": _membership_snapshot(membership),
        },
    )
    record_login_attempt(session, rate_key, ip, success=True)
    session.commit()
    session.refresh(membership)
    return WorkspaceJoinByCodeRead(
        workspace_code=workspace.code,
        workspace_name=workspace.name,
        workspace_role=membership.workspace_role,
        joined=True,
    )


def _generate_unique_code(session: Session, *, attempts: int = 20) -> str:
    for _ in range(attempts):
        code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))
        existing = session.scalar(select(WorkspaceJoinCode.id).where(WorkspaceJoinCode.code == code))
        if existing is None:
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate a unique join code",
    )


def _active_join_code(session: Session, workspace: Workspace) -> WorkspaceJoinCode | None:
    return session.scalar(
        select(WorkspaceJoinCode).where(
            WorkspaceJoinCode.workspace_id == workspace.id,
            WorkspaceJoinCode.status == "active",
        ),
    )


def _join_code_to_read(session: Session, join_code: WorkspaceJoinCode) -> WorkspaceJoinCodeRead:
    creator = session.get(User, join_code.created_by_id)
    return WorkspaceJoinCodeRead(
        code=join_code.code,
        default_role=join_code.default_role,
        expires_at=join_code.expires_at,
        max_uses=join_code.max_uses,
        use_count=join_code.use_count,
        created_at=join_code.created_at,
        created_by=creator.display_name if creator else None,
    )


def _get_enabled_workspace(session: Session, workspace_code: str) -> Workspace:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


def _membership_snapshot(membership: WorkspaceMembership | None) -> dict | None:
    if membership is None:
        return None
    return {"workspace_role": membership.workspace_role, "enabled": membership.enabled}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
