from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.auth.passwords import hash_password, verify_password
from app.core.config import REPO_ROOT, Settings
from app.models.feedback import AuditLog
from app.models.identity import Permission, Role, User
from app.models.labels import Label, LabelSet
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceSection
from app.schemas.auth import RoleRead, UserRead

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

WORKSPACE_DEFINITIONS = {
    "planning_intel": {
        "name": "规划部情报工作台",
        "description": "行业信号、日报周报、专题洞察和内部需求闭环。",
        "workspace_type": "intelligence_workspace",
        "default_domain_code": "ai",
        "sort_order": 10,
        "extra_sections": [],
    },
    "ai_tools": {
        "name": "AI 工具桌面",
        "description": "同一套情报日报周报能力下的 AI 工具观察工作范围。",
        "workspace_type": "intelligence_workspace",
        "default_domain_code": "ai",
        "sort_order": 20,
        "extra_sections": [],
    },
}

DEFAULT_WORKSPACE_LABEL_POLICY = {
    "label_set_code": "ai_sql_categories",
    "news_format_code": "company_sql_v1",
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

AI_TOOLS_PRIMARY_CATEGORIES = ["工具新功能", "工具新案例", "工具新技术"]
AI_TOOLS_SECONDARY_LABELS = ["cursor", "claude code", "opencode", "codex"]
AI_TOOLS_LABEL_POLICY = {
    "label_set_code": "ai_tools_categories",
    "news_format_code": "tool_intel_v1",
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

CORE_WORKSPACE_SECTIONS = [
    ("dashboard", "工作台", "page", "/dashboard", 10),
    ("source_management", "数据源管理", "page", "/sources", 20),
    ("candidate_pool", "候选池", "page", "/news", 30),
    ("daily_reports", "日报", "page", "/daily-reports", 40),
    ("weekly_reports", "周报", "page", "/weekly-reports", 50),
    ("exports", "SQL导出", "page", "/exports", 70),
    ("users", "用户权限", "page", "/users", 80),
    ("audit_logs", "审计", "page", "/audit-logs", 90),
]


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
        roles=sorted(role.code for role in user.roles),
    )


def role_to_read(role: Role) -> RoleRead:
    return RoleRead(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
    )


def ensure_auth_seed(session: Session, settings: Settings) -> None:
    permissions = _ensure_permissions(session)
    roles = _ensure_roles(session, permissions)
    _ensure_bootstrap_admin(session, settings, roles)
    workspaces = _ensure_workspaces(session)
    _ensure_default_label_sets(session)
    _ensure_super_admin_workspace_memberships(session, workspaces)
    session.commit()


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
        .where(User.username == username, User.is_active.is_(True), User.status == "active"),
    )
    if user and verify_password(password, user.password_hash):
        return user
    return None


def resolve_header_identity(
    session: Session,
    identity: ExternalIdentity,
    default_role: str,
    allow_provision: bool,
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
            username=identity.username,
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
    return user


def mark_login(session: Session, user: User, action: str) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    session.add(
        AuditLog(
            user=user,
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
    session.add(
        AuditLog(
            user=user,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail_json=detail,
        ),
    )


def set_user_roles(session: Session, target_user: User, role_codes: list[str]) -> None:
    roles = [_get_role(session, code) for code in sorted(set(role_codes))]
    target_user.roles = roles


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
        workspace.config_json = {
            **existing_config,
            "sort_order": definition["sort_order"],
            "label_policy": _workspace_label_policy_for_seed(code, existing_policy),
        }
        _ensure_workspace_sections(
            session,
            workspace,
            [*CORE_WORKSPACE_SECTIONS, *definition["extra_sections"]],
        )
    session.flush()
    return existing


def _default_workspace_label_policy() -> dict:
    taxonomy_path = REPO_ROOT / "config" / "taxonomy" / "news_categories.json"
    categories = json.loads(taxonomy_path.read_text(encoding="utf-8"))["categories"]
    return {
        **DEFAULT_WORKSPACE_LABEL_POLICY,
        "allowed_primary_categories": categories,
        "secondary_labels_by_primary": {},
    }


def _workspace_label_policy_for_seed(workspace_code: str, existing_policy: dict | None) -> dict:
    if workspace_code == "ai_tools":
        if not existing_policy or existing_policy.get("label_set_code") != "ai_tools_categories":
            return _copy_policy(AI_TOOLS_LABEL_POLICY)
        return _merge_policy_defaults(existing_policy, AI_TOOLS_LABEL_POLICY)
    if existing_policy:
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
    section_definitions: list[tuple[str, str, str, str, int]],
) -> None:
    existing = {section.section_key: section for section in workspace.sections}
    desired_keys = {section_key for section_key, *_ in section_definitions}
    for section_key, name, section_type, route_path, sort_order in section_definitions:
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
            )
            session.add(section)
        else:
            section.name = name
            section.section_type = section_type
            section.route_path = route_path
            section.sort_order = sort_order
            section.enabled = True

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
    taxonomy_path = REPO_ROOT / "config" / "taxonomy" / "news_categories.json"
    categories = json.loads(taxonomy_path.read_text(encoding="utf-8"))["categories"]
    _ensure_label_set(
        session=session,
        workspace_code="shared",
        domain_code="ai",
        code="ai_sql_categories",
        name="AI SQL 一级标签",
        description="兼容当前公司 SQL 导出的 10 个一级标签。",
        categories=categories,
        secondary_labels_by_primary={},
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


def _ensure_label_set(
    session: Session,
    workspace_code: str,
    domain_code: str,
    code: str,
    name: str,
    description: str,
    categories: list[str],
    secondary_labels_by_primary: dict[str, list[str]],
) -> None:
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
            target_types={
                "target_types": [
                    "data_source",
                    "workspace_source_link",
                    "news_item",
                    "dedupe_group",
                    "daily_report_item",
                    "weekly_report_item",
                ],
            },
            enabled=True,
        )
        session.add(label_set)
        session.flush()
    else:
        label_set.workspace_code = workspace_code
        label_set.domain_code = domain_code
        label_set.name = name
        label_set.description = description
        label_set.scope_type = "domain"
        label_set.enabled = True

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
