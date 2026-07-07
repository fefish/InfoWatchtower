from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.auth.passwords import hash_password, verify_password
from app.core.config import REPO_ROOT, Settings
from app.core.privacy import redact_secret_like_values
from app.models.feedback import AuditLog
from app.models.identity import LoginAttempt, PasswordResetToken, Permission, Role, User, UserInvite
from app.models.labels import Label, LabelSet
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceSection
from app.reports.renditions import ensure_report_formats
from app.schemas.auth import InviteRead, RoleRead, UserRead, WorkspaceInviteTarget

ROLE_DEFINITIONS = {
    "super_admin": ("超级管理员", "Full system administration."),
    "editor_admin": ("编辑管理员", "Manage sources, reports and publishing."),
    "analyst": ("分析员", "Read and comment on intelligence work."),
    "viewer": ("查看者", "Read published content."),
}

PERMISSION_DEFINITIONS = {
    "users:manage": ("管理用户", "Assign roles and manage users."),
    "reports:manage": ("管理报告", "Create, edit and publish reports."),
    "sources:manage": ("管理数据源", "Create and edit data sources."),
    "exports:run": ("执行导出", "Run company SQL exports."),
    "content:read": ("查看内容", "Read dashboard content."),
}

ROLE_PERMISSIONS = {
    "super_admin": [
        "users:manage",
        "reports:manage",
        "sources:manage",
        "exports:run",
        "content:read",
    ],
    "editor_admin": ["reports:manage", "sources:manage", "exports:run", "content:read"],
    "analyst": ["content:read"],
    "viewer": ["content:read"],
}

WORKSPACE_ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

WORKSPACE_DEFINITIONS = {
    "planning_intel": {
        "name": "规划部情报工作台",
        "description": "行业信号、日报周报、专题洞察和内部需求闭环。",
        "workspace_type": "intelligence_workspace",
        "default_domain_code": "ai",
        "sort_order": 10,
        "extra_sections": [],
        # 建台初值：对登录用户开放发现/订阅（含游客只读浏览）。仅首次创建时写入，
        # 之后由 PATCH /api/workspaces/{code}/visibility 管理，重播种不回滚。
        "visibility": "internal_public",
    },
    "ai_tools": {
        "name": "AI 工具桌面",
        "description": "同一套情报日报周报能力下的 AI 工具观察工作范围。",
        "workspace_type": "intelligence_workspace",
        "default_domain_code": "ai",
        "sort_order": 20,
        "extra_sections": [],
        "visibility": "private",
    },
}

DEFAULT_WORKSPACE_LABEL_POLICY = {
    "label_set_code": "ai_sql_categories",
    "news_format_code": "company_sql_v1",
    "export_category_mode": "news_primary",
    "required_content_fields": [
        "background",
        "effects",
        "eventSummary",
        "technologyAndInnovation",
        "valueAndImpact",
    ],
    "default_category": "AI 应用",
    "fallback_category": "AI 应用",
    "tagging_stages": ["news_generation", "post_dedupe_labeling"],
}

DEFAULT_WORKSPACE_FEEDBACK_POLICY = {
    "viewer_can_react": True,
    "viewer_can_rate": True,
    "viewer_can_comment": True,
    "viewer_can_edit": False,
    "notify_on_comment": True,
    "notify_on_publish": False,
}

AI_TOOLS_PRIMARY_CATEGORIES = ["工具新功能", "工具新案例", "工具新技术"]
AI_TOOLS_SECONDARY_LABELS = ["cursor", "claude code", "opencode", "codex"]
AI_TOOLS_LABEL_POLICY = {
    "label_set_code": "ai_tools_categories",
    "news_format_code": "tool_intel_v1",
    "export_category_mode": "news_primary",
    "required_content_fields": [
        "background",
        "effects",
        "eventSummary",
        "technologyAndInnovation",
        "valueAndImpact",
    ],
    "allowed_primary_categories": AI_TOOLS_PRIMARY_CATEGORIES,
    "secondary_labels_by_primary": {
        category: AI_TOOLS_SECONDARY_LABELS
        for category in AI_TOOLS_PRIMARY_CATEGORIES
    },
    "default_category": "工具新功能",
    "fallback_category": "工具新功能",
    "tagging_stages": ["news_generation", "post_dedupe_labeling"],
}

# 导航垂直分组：today 今日速览 / collect 情报采集 / curate 编审工作流
# / library 资料库 / collab 协作 / system 系统
CORE_WORKSPACE_SECTIONS = [
    ("dashboard", "今日速览", "page", "/dashboard", 10, "today"),
    ("source_management", "数据源管理", "page", "/sources", 20, "collect"),
    ("ingestion_coverage", "抓取与覆盖", "page", "/ingestion-runs", 25, "collect"),
    ("candidate_pool", "候选池", "page", "/news", 30, "curate"),
    ("daily_reports", "日报", "page", "/daily-reports", 40, "curate"),
    ("weekly_reports", "周报", "page", "/weekly-reports", 50, "curate"),
    ("historical_reports", "历史报告库", "page", "/historical-reports", 52, "library"),
    ("entity_milestones", "实体大事记", "page", "/entity-milestones", 53, "library"),
    ("quality_archive", "质量归档", "page", "/quality-archive", 54, "library"),
    ("strategic_insights", "洞察研判", "page", "/insights", 55, "collab"),
    ("requirements", "内部需求", "page", "/requirements", 56, "collab"),
    ("topic_tasks", "指派任务", "page", "/tasks", 60, "collab"),
    ("sync", "同步", "page", "/sync", 68, "system"),
    ("exports", "SQL导出", "page", "/exports", 70, "system"),
    ("workspace_settings", "工作台配置", "page", "/workspace-settings", 75, "system"),
    ("users", "用户权限", "page", "/users", 80, "system"),
    ("audit_logs", "审计", "page", "/audit-logs", 90, "system"),
]

# 分区可见的最低工作台角色种子（写入 config_json.min_role，读取侧由
# workspaces 路由 _section_min_role 解析）。工作台配置中心是管理面板，
# 只对 admin/owner 暴露；其余分区沿用「阅读分区 viewer / 管理分区 member」默认。
SECTION_MIN_ROLE_SEED = {
    "workspace_settings": "admin",
}


@dataclass(frozen=True)
class ExternalIdentity:
    provider: str
    external_id: str
    employee_no: str | None
    username: str
    display_name: str
    department: str | None = None
    email: str | None = None


def user_to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        external_provider=user.external_provider,
        external_id=user.external_id,
        employee_no=user.employee_no,
        username=user.username,
        display_name=user.display_name,
        department=user.department,
        email=user.email,
        status=user.status,
        is_active=user.is_active,
        roles=sorted(role.code for role in user.roles),
    )


def role_to_read(role: Role) -> RoleRead:
    return RoleRead(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
    )


def provision_workspace(
    session: Session,
    *,
    code: str,
    name: str,
    description: str = "",
    workspace_type: str = "intelligence_workspace",
    default_domain_code: str = "ai",
) -> Workspace:
    """Create a new workspace with the shared core sections, the default
    label policy and owner memberships for existing super admins.

    The caller is responsible for uniqueness checks and the final commit.
    """
    workspace = Workspace(
        code=code,
        name=name,
        description=description,
        workspace_type=workspace_type,
        default_domain_code=default_domain_code,
        enabled=True,
    )
    session.add(workspace)
    session.flush()
    workspace.config_json = {
        "sort_order": _next_workspace_sort_order(session),
        "label_policy": _default_workspace_label_policy(),
        "feedback_policy": _default_workspace_feedback_policy(),
    }
    _ensure_workspace_sections(session, workspace, CORE_WORKSPACE_SECTIONS)
    _ensure_super_admin_workspace_memberships(session, {code: workspace})
    ensure_report_formats(session, code)
    session.flush()
    return workspace


def _next_workspace_sort_order(session: Session) -> int:
    orders = [
        int((workspace.config_json or {}).get("sort_order", 1000))
        for workspace in session.scalars(select(Workspace)).all()
    ]
    return (max(orders, default=0) // 10) * 10 + 10


def ensure_auth_seed(session: Session, settings: Settings) -> None:
    permissions = _ensure_permissions(session)
    roles = _ensure_roles(session, permissions)
    _ensure_bootstrap_admin(session, settings, roles)
    workspaces = _ensure_workspaces(session)
    _ensure_default_label_sets(session)
    _ensure_super_admin_workspace_memberships(session, workspaces)
    for code in workspaces:
        ensure_report_formats(session, code)
    session.commit()


def setup_needed(session: Session) -> bool:
    return session.scalar(select(User.id).limit(1)) is None


def create_initial_super_admin(
    session: Session,
    *,
    username: str,
    display_name: str,
    password: str,
) -> User:
    if not setup_needed(session):
        raise RuntimeError("setup_already_completed")
    permissions = _ensure_permissions(session)
    roles = _ensure_roles(session, permissions)
    workspaces = _ensure_workspaces(session)
    _ensure_default_label_sets(session)
    user = User(
        external_provider="local",
        external_id=username,
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        status="active",
        roles=[roles["super_admin"]],
    )
    session.add(user)
    session.flush()
    _ensure_super_admin_workspace_memberships(session, workspaces)
    for code in workspaces:
        ensure_report_formats(session, code)
    write_audit(
        session,
        user,
        action="setup.create_admin",
        object_type="user",
        object_id=user.id,
        detail={"username": username},
    )
    session.flush()
    return user


def try_ensure_auth_seed(session_factory, settings: Settings) -> None:
    if session_factory is None:
        return

    session = session_factory()
    try:
        ensure_auth_seed(session, settings)
    except SQLAlchemyError:
        session.rollback()
    finally:
        session.close()


def find_user_with_roles(session: Session, user_id: str) -> User | None:
    return session.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == user_id),
    )


def authenticate_password_user(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(
            User.username == username,
            User.is_active.is_(True),
            User.status.in_(("active", "must_change_password")),
        ),
    )
    if user and verify_password(password, user.password_hash):
        return user
    return None


def login_failure_count(session: Session, username: str, ip: str, *, window_minutes: int = 15) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    latest_success = session.scalar(
        select(func.max(LoginAttempt.created_at)).where(
            LoginAttempt.username == username,
            LoginAttempt.ip == ip,
            LoginAttempt.success.is_(True),
            LoginAttempt.created_at >= cutoff,
        ),
    )
    latest_success = _as_utc(latest_success)
    if latest_success is not None and latest_success > cutoff:
        cutoff = latest_success
    value = session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.username == username,
            LoginAttempt.ip == ip,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= cutoff,
        ),
    )
    return int(value or 0)


def record_login_attempt(session: Session, username: str, ip: str, *, success: bool) -> None:
    session.add(LoginAttempt(username=username, ip=ip, success=success))


def resolve_header_identity(
    session: Session,
    identity: ExternalIdentity,
    default_role: str,
    allow_provision: bool,
    default_workspace_codes: str = "",
    department_workspace_map: str = "",
) -> User | None:
    user = session.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(
            User.external_provider == identity.provider,
            User.external_id == identity.external_id,
        ),
    )
    if user is None:
        if not allow_provision:
            return None
        role = _get_role(session, default_role)
        user = User(
            external_provider=identity.provider,
            external_id=identity.external_id,
            employee_no=identity.employee_no,
            username=_unique_username(session, identity.username),
            display_name=identity.display_name,
            department=identity.department,
            email=identity.email,
            status="active",
            roles=[role],
        )
        session.add(user)
        session.flush()
    else:
        user.employee_no = identity.employee_no
        user.display_name = identity.display_name
        user.department = identity.department
        user.email = identity.email
    _apply_auto_workspace_memberships(
        session,
        user=user,
        department=identity.department,
        default_workspace_codes=default_workspace_codes,
        department_workspace_map=department_workspace_map,
    )
    return user


def mark_login(session: Session, user: User, action: str) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    session.add(
        AuditLog(
            user=user,
            workspace_code="global",
            action=action,
            object_type="user",
            object_id=user.id,
            detail_json={
                "external_provider": user.external_provider,
                "external_id_snapshot": user.external_id,
                "employee_no_snapshot": user.employee_no,
                "display_name_snapshot": user.display_name,
            },
        ),
    )


def write_audit(session: Session, user: User | None, action: str, object_type: str, object_id: str, detail):
    workspace_code = _audit_workspace_code(detail)
    safe_detail = redact_secret_like_values(detail if isinstance(detail, (dict, list)) else {})
    session.add(
        AuditLog(
            user=user,
            workspace_code=workspace_code,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail_json=safe_detail,
        ),
    )


def _audit_workspace_code(detail) -> str:
    if isinstance(detail, dict):
        value = detail.get("workspace_code")
        if isinstance(value, str) and value:
            return value
    return "global"


def set_user_roles(session: Session, target_user: User, role_codes: list[str]) -> None:
    roles = [_get_role(session, code) for code in sorted(set(role_codes))]
    target_user.roles = roles


def create_user_invite(
    session: Session,
    *,
    email: str | None,
    role_code: str,
    workspaces: list[WorkspaceInviteTarget],
    invited_by: User,
    expires_in_days: int,
    app_base_url: str,
) -> InviteRead:
    _get_role(session, role_code)
    workspace_targets = _normalize_workspace_targets(session, workspaces)
    invite = UserInvite(
        code=secrets.token_urlsafe(32)[:64],
        email=email,
        role_code=role_code,
        workspace_codes={"workspaces": [target.model_dump() for target in workspace_targets]},
        invited_by_id=invited_by.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
    )
    session.add(invite)
    session.flush()
    return invite_to_read(invite, app_base_url)


def invite_to_read(invite: UserInvite, app_base_url: str) -> InviteRead:
    return InviteRead(
        id=invite.id,
        code=invite.code,
        email=invite.email,
        role_code=invite.role_code,
        workspaces=_invite_targets(invite),
        invite_url=f"{app_base_url.rstrip('/')}/invite/{invite.code}",
        status=invite_status(invite),
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        revoked_at=invite.revoked_at,
    )


def invite_status(invite: UserInvite) -> str:
    if invite.revoked_at is not None:
        return "revoked"
    if invite.accepted_at is not None:
        return "accepted"
    if _as_utc(invite.expires_at) <= datetime.now(timezone.utc):
        return "expired"
    return "pending"


def accept_user_invite(
    session: Session,
    *,
    invite: UserInvite,
    username: str,
    display_name: str,
    password: str,
) -> User:
    status = invite_status(invite)
    if status != "pending":
        raise ValueError(status)
    existing = session.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise RuntimeError("username_conflict")
    role = _get_role(session, invite.role_code)
    user = User(
        external_provider="local",
        external_id=username,
        username=username,
        display_name=display_name,
        email=invite.email,
        password_hash=hash_password(password),
        status="active",
        roles=[role],
    )
    session.add(user)
    session.flush()
    for target in _invite_targets(invite):
        workspace = session.scalar(select(Workspace).where(Workspace.code == target.code, Workspace.enabled.is_(True)))
        if workspace is None:
            continue
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == user.id,
            ),
        )
        if membership is None:
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    workspace_role=target.workspace_role,
                    enabled=True,
                ),
            )
        else:
            membership.workspace_role = target.workspace_role
            membership.enabled = True
    invite.accepted_by_id = user.id
    invite.accepted_at = datetime.now(timezone.utc)
    session.flush()
    return user


def create_password_reset_token(session: Session, user: User, *, ttl_minutes: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        ),
    )
    return token


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(18)


def _unique_username(session: Session, desired: str) -> str:
    base = (desired or "user").strip()[:96] or "user"
    candidate = base
    suffix = 2
    while session.scalar(select(User.id).where(User.username == candidate)) is not None:
        candidate = f"{base}_{suffix}"[:128]
        suffix += 1
    return candidate


def _apply_auto_workspace_memberships(
    session: Session,
    *,
    user: User,
    department: str | None,
    default_workspace_codes: str,
    department_workspace_map: str,
) -> None:
    targets = {
        target.code: target
        for target in _auto_workspace_targets(
            department=department,
            default_workspace_codes=default_workspace_codes,
            department_workspace_map=department_workspace_map,
        )
    }
    for target in _stored_department_workspace_targets(session, department):
        existing = targets.get(target.code)
        if existing is None or WORKSPACE_ROLE_RANK[target.workspace_role] > WORKSPACE_ROLE_RANK[existing.workspace_role]:
            targets[target.code] = target
    if not targets:
        return
    for target in targets.values():
        workspace = session.scalar(
            select(Workspace).where(Workspace.code == target.code, Workspace.enabled.is_(True)),
        )
        if workspace is None:
            raise ValueError(f"Unknown workspace in auth membership mapping: {target.code}")
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == user.id,
            ),
        )
        if membership is None:
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    workspace_role=target.workspace_role,
                    enabled=True,
                ),
            )
            continue
        membership.enabled = True
        current_rank = WORKSPACE_ROLE_RANK.get(membership.workspace_role, -1)
        target_rank = WORKSPACE_ROLE_RANK.get(target.workspace_role, -1)
        if target_rank > current_rank:
            membership.workspace_role = target.workspace_role


def _stored_department_workspace_targets(session: Session, department: str | None) -> list[WorkspaceInviteTarget]:
    department = (department or "").strip()
    if not department:
        return []
    targets: list[WorkspaceInviteTarget] = []
    workspaces = session.scalars(select(Workspace).where(Workspace.enabled.is_(True))).all()
    for workspace in workspaces:
        raw_rows = ((workspace.config_json or {}).get("auth_membership_mapping") or {}).get("department_workspaces") or []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("department") or "").strip() != department:
                continue
            targets.append(_workspace_target(workspace.code, str(row.get("workspace_role") or "viewer")))
    return targets


def _auto_workspace_targets(
    *,
    department: str | None,
    default_workspace_codes: str,
    department_workspace_map: str,
) -> list[WorkspaceInviteTarget]:
    targets: dict[str, WorkspaceInviteTarget] = {}
    for target in _parse_default_workspace_targets(default_workspace_codes):
        targets[target.code] = target
    department = (department or "").strip()
    if department:
        for target_department, target in _parse_department_workspace_targets(department_workspace_map):
            if target_department != department:
                continue
            existing = targets.get(target.code)
            if existing is None or WORKSPACE_ROLE_RANK[target.workspace_role] > WORKSPACE_ROLE_RANK[existing.workspace_role]:
                targets[target.code] = target
    return list(targets.values())


def _parse_default_workspace_targets(raw: str) -> list[WorkspaceInviteTarget]:
    targets = []
    for item in [part.strip() for part in raw.split(",") if part.strip()]:
        parts = [part.strip() for part in item.split(":")]
        if len(parts) == 1:
            code, role = parts[0], "viewer"
        elif len(parts) == 2:
            code, role = parts
        else:
            raise ValueError(f"Invalid AUTH_DEFAULT_WORKSPACE_CODES item: {item}")
        targets.append(_workspace_target(code, role))
    return targets


def parse_default_workspace_targets(raw: str) -> list[WorkspaceInviteTarget]:
    return _parse_default_workspace_targets(raw)


def _parse_department_workspace_targets(raw: str) -> list[tuple[str, WorkspaceInviteTarget]]:
    targets = []
    for item in [part.strip() for part in raw.split(",") if part.strip()]:
        parts = [part.strip() for part in item.split(":")]
        if len(parts) == 2:
            department, code = parts
            role = "viewer"
        elif len(parts) == 3:
            department, code, role = parts
        else:
            raise ValueError(f"Invalid AUTH_DEPARTMENT_WORKSPACE_MAP item: {item}")
        if not department:
            raise ValueError(f"Invalid AUTH_DEPARTMENT_WORKSPACE_MAP department: {item}")
        targets.append((department, _workspace_target(code, role)))
    return targets


def parse_department_workspace_targets(raw: str) -> list[tuple[str, WorkspaceInviteTarget]]:
    return _parse_department_workspace_targets(raw)


def _workspace_target(code: str, role: str) -> WorkspaceInviteTarget:
    code = code.strip()
    role = role.strip() or "viewer"
    if not code:
        raise ValueError("Workspace code cannot be empty in auth membership mapping")
    if role not in WORKSPACE_ROLE_RANK:
        raise ValueError(f"Invalid workspace role in auth membership mapping: {role}")
    return WorkspaceInviteTarget(code=code, workspace_role=role)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _invite_targets(invite: UserInvite) -> list[WorkspaceInviteTarget]:
    raw_targets = (invite.workspace_codes or {}).get("workspaces") or []
    targets = []
    for item in raw_targets:
        if not isinstance(item, dict):
            continue
        targets.append(
            WorkspaceInviteTarget(
                code=str(item.get("code") or ""),
                workspace_role=str(item.get("workspace_role") or "member"),
            ),
        )
    return [target for target in targets if target.code]


def _normalize_workspace_targets(
    session: Session,
    targets: list[WorkspaceInviteTarget],
) -> list[WorkspaceInviteTarget]:
    normalized = targets
    if not normalized:
        raise ValueError("At least one workspace target is required")
    result = []
    for target in normalized:
        workspace = session.scalar(select(Workspace).where(Workspace.code == target.code, Workspace.enabled.is_(True)))
        if workspace is None:
            raise ValueError(f"Unknown workspace: {target.code}")
        result.append(
            WorkspaceInviteTarget(
                code=target.code,
                workspace_role=target.workspace_role or "member",
            ),
        )
    return result


def _ensure_permissions(session: Session) -> dict[str, Permission]:
    existing = {
        permission.code: permission
        for permission in session.scalars(select(Permission)).all()
    }
    for code, (name, description) in PERMISSION_DEFINITIONS.items():
        if code not in existing:
            existing[code] = Permission(code=code, name=name, description=description)
            session.add(existing[code])
    session.flush()
    return existing


def _ensure_roles(session: Session, permissions: dict[str, Permission]) -> dict[str, Role]:
    existing = {
        role.code: role
        for role in session.scalars(select(Role).options(selectinload(Role.permissions))).all()
    }
    for code, (name, description) in ROLE_DEFINITIONS.items():
        role = existing.get(code)
        if role is None:
            role = Role(code=code, name=name, description=description)
            session.add(role)
            existing[code] = role
        role.permissions = [permissions[item] for item in ROLE_PERMISSIONS[code]]
    session.flush()
    return existing


def _ensure_bootstrap_admin(
    session: Session,
    settings: Settings,
    roles: dict[str, Role],
) -> None:
    if not settings.auth_bootstrap_admin_password:
        return

    user_count = session.scalar(select(User.id).limit(1))
    if user_count is not None:
        return

    username = settings.auth_bootstrap_admin_username
    user = User(
        external_provider="local",
        external_id=username,
        username=username,
        display_name=settings.auth_bootstrap_admin_display_name,
        password_hash=hash_password(settings.auth_bootstrap_admin_password),
        status="active",
        roles=[roles["super_admin"]],
    )
    session.add(user)


def _get_role(session: Session, code: str) -> Role:
    role = session.scalar(select(Role).where(Role.code == code))
    if role is None:
        raise ValueError(f"Unknown role: {code}")
    return role


def _ensure_workspaces(session: Session) -> dict[str, Workspace]:
    existing = {
        workspace.code: workspace
        for workspace in session.scalars(select(Workspace).options(selectinload(Workspace.sections))).all()
    }
    for code, definition in WORKSPACE_DEFINITIONS.items():
        workspace = existing.get(code)
        if workspace is None:
            workspace = Workspace(
                code=code,
                name=definition["name"],
                description=definition["description"],
                workspace_type=definition["workspace_type"],
                default_domain_code=definition["default_domain_code"],
                enabled=True,
                # visibility 只在建台时赋种子初值；已存在的工作台不回滚
                # 用户通过 visibility API 做出的公开/私有决定。
                visibility=str(definition.get("visibility") or "private"),
            )
            session.add(workspace)
            existing[code] = workspace
            session.flush()
        else:
            workspace.name = definition["name"]
            workspace.description = definition["description"]
            workspace.workspace_type = definition["workspace_type"]
            workspace.default_domain_code = definition["default_domain_code"]
            workspace.enabled = True
        existing_config = workspace.config_json or {}
        existing_policy = existing_config.get("label_policy")
        existing_feedback_policy = existing_config.get("feedback_policy")
        workspace.config_json = {
            **existing_config,
            "sort_order": definition["sort_order"],
            "label_policy": _workspace_label_policy_for_seed(code, existing_policy),
            "feedback_policy": _workspace_feedback_policy_for_seed(existing_feedback_policy),
        }
        _ensure_workspace_sections(
            session,
            workspace,
            [*CORE_WORKSPACE_SECTIONS, *definition["extra_sections"]],
        )
    session.flush()
    return existing


def _default_workspace_label_policy() -> dict:
    taxonomy = _news_taxonomy()
    return {
        **DEFAULT_WORKSPACE_LABEL_POLICY,
        "allowed_primary_categories": taxonomy["categories"],
        "secondary_labels_by_primary": {},
    }


def _default_workspace_feedback_policy() -> dict:
    return dict(DEFAULT_WORKSPACE_FEEDBACK_POLICY)


def _workspace_feedback_policy_for_seed(existing_policy: dict | None) -> dict:
    return {
        **DEFAULT_WORKSPACE_FEEDBACK_POLICY,
        **dict(existing_policy or {}),
    }


def _workspace_label_policy_for_seed(workspace_code: str, existing_policy: dict | None) -> dict:
    if workspace_code == "ai_tools":
        if not existing_policy or existing_policy.get("label_set_code") != "ai_tools_categories":
            return _copy_policy(AI_TOOLS_LABEL_POLICY)
        return _merge_policy_defaults(existing_policy, AI_TOOLS_LABEL_POLICY)
    if existing_policy and existing_policy.get("label_set_code") == "ai_sql_categories":
        return _merge_policy_defaults(existing_policy, _default_workspace_label_policy())
    return _default_workspace_label_policy()


def _merge_policy_defaults(policy: dict, default_policy: dict) -> dict:
    return {
        **default_policy,
        **policy,
        "secondary_labels_by_primary": policy.get("secondary_labels_by_primary")
        or default_policy.get("secondary_labels_by_primary", {}),
        "required_content_fields": policy.get("required_content_fields")
        or default_policy.get("required_content_fields", []),
        "tagging_stages": policy.get("tagging_stages")
        or default_policy.get("tagging_stages", ["news_generation", "post_dedupe_labeling"]),
        "export_category_mode": policy.get("export_category_mode")
        or default_policy.get("export_category_mode", "news_primary"),
    }


def _copy_policy(policy: dict) -> dict:
    return {
        **policy,
        "allowed_primary_categories": list(policy["allowed_primary_categories"]),
        "required_content_fields": list(policy.get("required_content_fields", [])),
        "secondary_labels_by_primary": {
            primary: list(labels)
            for primary, labels in policy.get("secondary_labels_by_primary", {}).items()
        },
        "tagging_stages": list(policy["tagging_stages"]),
    }


def _ensure_workspace_sections(
    session: Session,
    workspace: Workspace,
    section_definitions: list[tuple[str, str, str, str, int, str]],
) -> None:
    existing = {section.section_key: section for section in workspace.sections}
    desired_keys = {section_key for section_key, *_ in section_definitions}
    for section_key, name, section_type, route_path, sort_order, group in section_definitions:
        seeded_config: dict = {"group": group}
        min_role = SECTION_MIN_ROLE_SEED.get(section_key)
        if min_role is not None:
            seeded_config["min_role"] = min_role
        section = existing.get(section_key)
        if section is None:
            section = WorkspaceSection(
                workspace=workspace,
                section_key=section_key,
                name=name,
                section_type=section_type,
                route_path=route_path,
                sort_order=sort_order,
                enabled=True,
                config_json=seeded_config,
            )
            session.add(section)
        else:
            section.name = name
            section.section_type = section_type
            section.route_path = route_path
            section.sort_order = sort_order
            section.enabled = True
            section.config_json = {**(section.config_json or {}), **seeded_config}

    for section_key, section in existing.items():
        if section_key not in desired_keys:
            section.enabled = False


def _ensure_super_admin_workspace_memberships(
    session: Session,
    workspaces: dict[str, Workspace],
) -> None:
    super_admins = session.scalars(
        select(User).options(selectinload(User.roles)).where(User.is_active.is_(True)),
    ).all()
    for user in super_admins:
        if "super_admin" not in {role.code for role in user.roles}:
            continue
        existing_workspace_ids = {
            membership.workspace_id
            for membership in session.scalars(
                select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id),
            ).all()
        }
        for workspace in workspaces.values():
            if workspace.id not in existing_workspace_ids:
                session.add(
                    WorkspaceMembership(
                        workspace=workspace,
                        user_id=user.id,
                        workspace_role="owner",
                        enabled=True,
                    ),
                )


def _ensure_default_label_sets(session: Session) -> None:
    news_taxonomy = _news_taxonomy()
    source_taxonomy = _source_tag_taxonomy()
    _ensure_label_set(
        session=session,
        workspace_code="planning_intel",
        domain_code="ai",
        code="ai_sql_categories",
        name="AI SQL 一级标签",
        description="规划部成品新闻和公司 SQL 导出的 10 个一级标签。",
        categories=news_taxonomy["categories"],
        secondary_labels_by_primary={},
    )
    _ensure_label_set(
        session=session,
        workspace_code="planning_intel",
        domain_code="ai",
        code="planning_source_tags",
        name="规划部数据源方向标签",
        description="只用于数据源覆盖范围、过滤、评分先验和看板展示，不写入 generated_news.category。",
        categories=source_taxonomy["tags"],
        secondary_labels_by_primary=source_taxonomy["secondary_tags_by_primary"],
        target_types=["data_source", "workspace_source_link"],
    )
    _ensure_label_set(
        session=session,
        workspace_code="ai_tools",
        domain_code="ai",
        code="ai_tools_categories",
        name="AI 工具观察标签",
        description="AI 工具桌面的一级/二级标签策略。",
        categories=AI_TOOLS_PRIMARY_CATEGORIES,
        secondary_labels_by_primary=AI_TOOLS_LABEL_POLICY["secondary_labels_by_primary"],
    )
    _ensure_domain_pack_label_sets(session)


def _news_taxonomy() -> dict[str, object]:
    taxonomy_path = REPO_ROOT / "config" / "taxonomy" / "news_categories.json"
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    return {
        "categories": list(taxonomy.get("categories") or []),
    }


def _source_tag_taxonomy() -> dict[str, object]:
    taxonomy_path = REPO_ROOT / "config" / "taxonomy" / "source_tags.json"
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    return {
        "tags": list(taxonomy.get("tags") or []),
        "secondary_tags_by_primary": dict(taxonomy.get("secondary_tags_by_primary") or {}),
    }


def _ensure_label_set(
    session: Session,
    workspace_code: str,
    domain_code: str,
    code: str,
    name: str,
    description: str,
    categories: list[str],
    secondary_labels_by_primary: dict[str, list[str]],
    target_types: list[str] | None = None,
    config_json: dict | None = None,
) -> None:
    label_targets = target_types or [
        "data_source",
        "workspace_source_link",
        "news_item",
        "dedupe_group",
        "daily_report_item",
        "weekly_report_item",
    ]
    label_set = session.scalar(
        select(LabelSet).where(
            LabelSet.workspace_code == workspace_code,
            LabelSet.domain_code == domain_code,
            LabelSet.code == code,
        ),
    )
    if label_set is None:
        label_set = LabelSet(
            workspace_code=workspace_code,
            domain_code=domain_code,
            code=code,
            name=name,
            description=description,
            scope_type="domain",
            target_types={"target_types": label_targets},
            enabled=True,
            config_json=dict(config_json or {}),
        )
        session.add(label_set)
        session.flush()
    else:
        label_set.workspace_code = workspace_code
        label_set.domain_code = domain_code
        label_set.name = name
        label_set.description = description
        label_set.scope_type = "domain"
        label_set.target_types = {"target_types": label_targets}
        label_set.enabled = True
        label_set.config_json = dict(config_json or {})

    existing_labels = {label.code: label for label in label_set.labels}
    primary_labels: dict[str, Label] = {}
    for index, category in enumerate(categories, start=1):
        label = existing_labels.get(category)
        if label is None:
            label = Label(
                label_set=label_set,
                code=category,
                name=category,
                label_level=1,
                parent_label_id=None,
                sort_order=index,
                enabled=True,
            )
            session.add(label)
        else:
            label.name = category
            label.label_level = 1
            label.parent_label_id = None
            label.sort_order = index
            label.enabled = True
        primary_labels[category] = label

    secondary_sort_base = 1000
    for primary_index, category in enumerate(categories, start=1):
        parent_label = primary_labels[category]
        secondary_labels = secondary_labels_by_primary.get(category, [])
        for secondary_index, secondary in enumerate(secondary_labels, start=1):
            secondary_code = f"{category}:{secondary}"
            label = existing_labels.get(secondary_code)
            if label is None:
                label = Label(
                    label_set=label_set,
                    code=secondary_code,
                    name=secondary,
                    label_level=2,
                    parent_label=parent_label,
                    sort_order=secondary_sort_base + primary_index * 100 + secondary_index,
                    enabled=True,
                )
                session.add(label)
            else:
                label.name = secondary
                label.label_level = 2
                label.parent_label = parent_label
                label.sort_order = secondary_sort_base + primary_index * 100 + secondary_index
                label.enabled = True


def _ensure_domain_pack_label_sets(session: Session) -> None:
    pack_dir = REPO_ROOT / "config" / "domain_packs"
    if not pack_dir.exists():
        return
    for pack_path in sorted(pack_dir.glob("*.json")):
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        domain_code = str(pack.get("domain_code") or pack_path.stem).strip()
        if not domain_code:
            continue
        boards = list(pack.get("boards") or [])
        scoring = dict(pack.get("scoring") or {})
        for label_set in pack.get("label_sets") or []:
            if not isinstance(label_set, dict):
                continue
            categories = [
                str(category).strip()
                for category in label_set.get("categories") or []
                if str(category).strip()
            ]
            code = str(label_set.get("code") or f"{domain_code}_categories").strip()
            if not categories or not code:
                continue
            _ensure_label_set(
                session=session,
                workspace_code=str(label_set.get("workspace_code") or "shared"),
                domain_code=str(label_set.get("domain_code") or domain_code),
                code=code,
                name=str(label_set.get("name") or code),
                description=str(label_set.get("description") or ""),
                categories=categories,
                secondary_labels_by_primary=dict(label_set.get("secondary_labels_by_primary") or {}),
                target_types=list(label_set.get("target_types") or []),
                config_json={
                    "domain_pack": domain_code,
                    "boards": boards,
                    "scoring": scoring,
                },
            )
