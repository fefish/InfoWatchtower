from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.auth.guest import is_guest_user
from app.auth.service import (
    CORE_WORKSPACE_SECTIONS,
    DEFAULT_WORKSPACE_FEEDBACK_POLICY,
    WORKSPACE_DEFINITIONS,
    provision_workspace,
    user_to_read,
    write_audit,
)
from app.core.database import get_db_session
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceSection
from app.reports.publish import workspace_report_policy
from app.schemas.workspaces import (
    DEFAULT_REQUIRED_CONTENT_FIELDS,
    WorkspaceAuthMembershipMappingRead,
    WorkspaceAuthMembershipMappingUpdate,
    WorkspaceCreate,
    WorkspaceDepartmentMembershipTarget,
    WorkspaceDiscoverRead,
    WorkspaceFeedbackPolicyRead,
    WorkspaceFeedbackPolicyUpdate,
    WorkspaceLabelPolicyRead,
    WorkspaceLabelPolicyUpdate,
    WorkspaceMemberRead,
    WorkspaceMemberUpsert,
    WorkspaceRead,
    WorkspaceReportPolicyRead,
    WorkspaceReportPolicyUpdate,
    WorkspaceSectionRead,
    WorkspaceSubscriptionRead,
    WorkspaceUpdate,
    WorkspaceVisibilityUpdate,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
REPO_ROOT = Path(__file__).resolve().parents[4]
WORKSPACE_CREATOR_ROLES = {"super_admin", "editor_admin"}
SECTION_ROLE_VALUES = {"viewer", "member", "admin", "owner"}
# 阅读分区：viewer（游客）可见；其余分区默认 member 起（数据源/抓取/候选池/导出/
# 用户/审计/同步等管理分区对 viewer 整组隐藏）。可被 section.config_json.min_role 覆盖。
VIEWER_SECTION_KEYS = {
    "daily_reports",
    "weekly_reports",
    "historical_reports",
    "entity_milestones",
}


class WorkspaceSectionUpdate(BaseModel):
    enabled: bool


class WorkspaceSectionManageRead(BaseModel):
    section_key: str
    name: str
    enabled: bool


class WorkspaceSectionManageItem(BaseModel):
    """工作台配置中心「导航分区」卡片的管理视图：含停用分区与核心标记。"""

    section_key: str
    name: str
    group: str
    sort_order: int
    enabled: bool
    core: bool


def _global_role_codes(user: User) -> set[str]:
    return {role.code for role in user.roles}


def _is_super_admin(user: User) -> bool:
    return "super_admin" in _global_role_codes(user)


def _require_workspace_creator(current_user: User = Depends(get_current_user)) -> User:
    if _global_role_codes(current_user).isdisjoint(WORKSPACE_CREATOR_ROLES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires workspace creator role")
    return current_user


def _ensure_owner_membership(session: Session, workspace: Workspace, user: User) -> None:
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
        ),
    )
    if membership is None:
        session.add(
            WorkspaceMembership(
                workspace=workspace,
                user_id=user.id,
                workspace_role="owner",
                enabled=True,
            ),
        )
    else:
        membership.workspace_role = "owner"
        membership.enabled = True


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceRead]:
    statement = select(Workspace).where(Workspace.enabled.is_(True))
    if is_guest_user(current_user):
        # 游客不持有 membership：按隐式 viewer 视角列出全部 internal_public 工作台
        # （语义见 app/auth/guest.py），private 工作台对游客不可见。
        statement = statement.where(Workspace.visibility == "internal_public")
    elif not _is_super_admin(current_user):
        statement = (
            statement.join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(
                WorkspaceMembership.user_id == current_user.id,
                WorkspaceMembership.enabled.is_(True),
            )
        )
    workspaces = session.scalars(statement).all()
    workspaces = sorted(
        workspaces,
        key=lambda workspace: (
            (workspace.config_json or {}).get("sort_order", 1000),
            workspace.code,
        ),
    )
    return [_workspace_to_read(workspace, current_user=current_user, session=session) for workspace in workspaces]


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(_require_workspace_creator),
    session: Session = Depends(get_db_session),
) -> WorkspaceRead:
    existing = session.scalar(select(Workspace).where(Workspace.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workspace code already exists: {payload.code}",
        )

    workspace = provision_workspace(
        session,
        code=payload.code,
        name=payload.name.strip(),
        description=payload.description.strip(),
        workspace_type=payload.workspace_type,
        default_domain_code=payload.default_domain_code,
    )
    _ensure_owner_membership(session, workspace, current_user)
    write_audit(
        session,
        current_user,
        action="workspace.create",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "code": workspace.code,
            "name": workspace.name,
            "workspace_type": workspace.workspace_type,
            "default_domain_code": workspace.default_domain_code,
        },
    )
    session.commit()
    session.refresh(workspace)
    return _workspace_to_read(workspace, current_user=current_user, session=session)


@router.patch("/{workspace_code}", response_model=WorkspaceRead)
def update_workspace(
    workspace_code: str,
    payload: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceRead:
    """工作台基本信息（名称/描述/默认主题域）由工作台 admin/owner 维护
    （工作台配置中心「基本信息」卡片）；启停 `enabled` 属于全局生命周期
    操作，仍只允许 super_admin。
    """
    workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if payload.enabled is not None and not _is_super_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires super_admin")
    if not _is_super_admin(current_user):
        assert_workspace_member(session, current_user, workspace.code, min_role="admin")

    changes: dict[str, object] = {}
    if payload.name is not None:
        workspace.name = payload.name.strip()
        changes["name"] = workspace.name
    if payload.description is not None:
        workspace.description = payload.description.strip()
        changes["description"] = workspace.description
    if payload.default_domain_code is not None:
        workspace.default_domain_code = payload.default_domain_code.strip()
        changes["default_domain_code"] = workspace.default_domain_code
    if payload.enabled is not None:
        if workspace.code == "planning_intel" and not payload.enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="planning_intel cannot be disabled",
            )
        workspace.enabled = payload.enabled
        changes["enabled"] = workspace.enabled

    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace fields provided")

    write_audit(
        session,
        current_user,
        action="workspace.update",
        object_type="workspace",
        object_id=workspace.id,
        detail={"code": workspace.code, **changes},
    )
    session.commit()
    session.refresh(workspace)
    return _workspace_to_read(workspace, current_user=current_user, session=session)


@router.get("/{workspace_code}/members", response_model=list[WorkspaceMemberRead])
def list_workspace_members(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceMemberRead]:
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    rows = session.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.enabled.is_(True),
        )
        .order_by(User.username),
    ).all()
    return [
        WorkspaceMemberRead(
            user=user_to_read(user),
            workspace_role=membership.workspace_role,
            enabled=membership.enabled,
        )
        for membership, user in rows
    ]


@router.post("/{workspace_code}/members", response_model=WorkspaceMemberRead)
def upsert_workspace_member(
    workspace_code: str,
    payload: WorkspaceMemberUpsert,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceMemberRead:
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    target_user = session.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == target_user.id,
        ),
    )
    before_membership = _membership_snapshot(membership)
    if membership is None:
        membership = WorkspaceMembership(
            workspace=workspace,
            user_id=target_user.id,
            workspace_role=payload.workspace_role,
            enabled=True,
        )
        session.add(membership)
    else:
        if membership.workspace_role == "owner" and payload.workspace_role != "owner":
            owner_count = _workspace_owner_count(session, workspace)
            if owner_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot downgrade the last workspace owner",
                )
            if not payload.confirm_dangerous_change:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Dangerous owner role change requires confirmation",
                )
        membership.workspace_role = payload.workspace_role
        membership.enabled = True
    write_audit(
        session,
        current_user,
        action="workspace.member.upsert",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "user_id": target_user.id,
            "before": before_membership,
            "after": _membership_snapshot(membership),
        },
    )
    session.commit()
    session.refresh(target_user)
    session.refresh(membership)
    return WorkspaceMemberRead(
        user=user_to_read(target_user),
        workspace_role=membership.workspace_role,
        enabled=membership.enabled,
    )


@router.delete("/{workspace_code}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_member(
    workspace_code: str,
    user_id: str,
    confirm_dangerous_change: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
    if membership.workspace_role == "owner":
        owner_count = _workspace_owner_count(session, workspace)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last workspace owner",
            )
        if not confirm_dangerous_change:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dangerous owner removal requires confirmation",
            )
    before_membership = _membership_snapshot(membership)
    membership.enabled = False
    write_audit(
        session,
        current_user,
        action="workspace.member.remove",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "user_id": user_id,
            "before": before_membership,
            "after": _membership_snapshot(membership),
        },
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_code}/auth-membership-mapping", response_model=WorkspaceAuthMembershipMappingRead)
def get_workspace_auth_membership_mapping(
    workspace_code: str,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> WorkspaceAuthMembershipMappingRead:
    workspace = _get_enabled_workspace(session, workspace_code)
    return _workspace_auth_membership_mapping_to_read(workspace)


@router.patch("/{workspace_code}/auth-membership-mapping", response_model=WorkspaceAuthMembershipMappingRead)
def update_workspace_auth_membership_mapping(
    workspace_code: str,
    payload: WorkspaceAuthMembershipMappingUpdate,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> WorkspaceAuthMembershipMappingRead:
    workspace = _get_enabled_workspace(session, workspace_code)
    rows = _normalize_auth_membership_mapping(payload.department_workspaces)
    config = dict(workspace.config_json or {})
    before = dict(config.get("auth_membership_mapping") or {})
    config["auth_membership_mapping"] = {"department_workspaces": [row.model_dump() for row in rows]}
    workspace.config_json = config
    write_audit(
        session,
        current_user,
        action="workspace.auth_membership_mapping.update",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "before": before,
            "after": config["auth_membership_mapping"],
        },
    )
    session.commit()
    session.refresh(workspace)
    return _workspace_auth_membership_mapping_to_read(workspace)


@router.get("/{workspace_code}/sections", response_model=list[WorkspaceSectionRead])
def list_workspace_sections(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceSectionRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    sections = session.scalars(
        select(WorkspaceSection)
        .where(WorkspaceSection.workspace_id == workspace.id)
        .order_by(WorkspaceSection.sort_order, WorkspaceSection.section_key),
    ).all()
    return [
        _section_to_read(section)
        for section in sections
        if _section_effective_enabled(section)
    ]


@router.get("/{workspace_code}/sections/manage", response_model=list[WorkspaceSectionManageItem])
def list_workspace_sections_manage(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceSectionManageItem]:
    """导航分区管理视图（workspace admin+）：与 GET /sections 不同，
    包含已停用的可选模块（否则停用后无法再启用）并标记核心分区。
    """
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    core_keys = _core_section_keys(workspace.code)
    sections = session.scalars(
        select(WorkspaceSection)
        .where(WorkspaceSection.workspace_id == workspace.id)
        .order_by(WorkspaceSection.sort_order, WorkspaceSection.section_key),
    ).all()
    return [
        WorkspaceSectionManageItem(
            section_key=section.section_key,
            name=section.name,
            group=str((section.config_json or {}).get("group") or "system"),
            sort_order=section.sort_order,
            enabled=_section_effective_enabled(section),
            core=section.section_key in core_keys,
        )
        for section in sections
    ]


@router.patch("/{workspace_code}/sections/{section_key}", response_model=WorkspaceSectionManageRead)
def update_workspace_section(
    workspace_code: str,
    section_key: str,
    payload: WorkspaceSectionUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceSectionManageRead:
    """启停工作台分区（owner/admin 或 super_admin）。

    可选模块（数据库注册、默认关闭，如 tool_catalog）可自由启停；
    核心分区（数据源/日报等默认分区）承载主链路导航，禁止停用。
    """
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    section = session.scalar(
        select(WorkspaceSection).where(
            WorkspaceSection.workspace_id == workspace.id,
            WorkspaceSection.section_key == section_key,
        ),
    )
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace section not found")
    if not payload.enabled and section_key in _core_section_keys(workspace.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Core workspace sections cannot be disabled",
        )

    before_enabled = _section_effective_enabled(section)
    section.enabled = payload.enabled
    # bootstrap 播种（auth/service._ensure_workspace_sections）会重置 enabled 列：
    # 核心分区强制开、定义外分区强制关。用户的启停决定持久化在 config_json.user_enabled，
    # 读取侧以它为准，重启/重播种后不回滚。
    section.config_json = {**(section.config_json or {}), "user_enabled": payload.enabled}
    write_audit(
        session,
        current_user,
        action="workspace.section.update",
        object_type="workspace_section",
        object_id=section.id,
        detail={
            "workspace_code": workspace.code,
            "section_key": section.section_key,
            "before": {"enabled": before_enabled},
            "after": {"enabled": payload.enabled},
        },
    )
    session.commit()
    session.refresh(section)
    return WorkspaceSectionManageRead(
        section_key=section.section_key,
        name=section.name,
        enabled=_section_effective_enabled(section),
    )


@router.get("/{workspace_code}/label-policy", response_model=WorkspaceLabelPolicyRead)
def get_workspace_label_policy(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceLabelPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = _get_enabled_workspace(session, workspace_code)
    return _workspace_label_policy_to_read(workspace)


@router.patch("/{workspace_code}/label-policy", response_model=WorkspaceLabelPolicyRead)
def update_workspace_label_policy(
    workspace_code: str,
    payload: WorkspaceLabelPolicyUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceLabelPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    allowed_categories = _normalize_policy_categories(payload.allowed_primary_categories)
    if not allowed_categories:
        allowed_categories = _taxonomy_categories()
    secondary_labels = _normalize_secondary_labels(
        payload.secondary_labels_by_primary,
        allowed_categories,
    )
    required_content_fields = _normalize_required_content_fields(payload.required_content_fields)
    if payload.news_format_code == "company_sql_v1":
        missing_fields = [
            field
            for field in DEFAULT_REQUIRED_CONTENT_FIELDS
            if field not in required_content_fields
        ]
        if missing_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_sql_v1 required_content_fields cannot remove SQL fields",
            )
    if payload.default_category not in allowed_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_category must be in allowed_primary_categories",
        )
    if payload.fallback_category not in allowed_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fallback_category must be in allowed_primary_categories",
        )

    config = dict(workspace.config_json or {})
    config["label_policy"] = {
        "label_set_code": payload.label_set_code,
        "news_format_code": payload.news_format_code,
        "export_category_mode": _normalize_export_category_mode(payload.export_category_mode),
        "required_content_fields": required_content_fields,
        "allowed_primary_categories": allowed_categories,
        "secondary_labels_by_primary": secondary_labels,
        "default_category": payload.default_category,
        "fallback_category": payload.fallback_category,
        "tagging_stages": ["news_generation", "post_dedupe_labeling"],
    }
    workspace.config_json = config
    session.commit()
    session.refresh(workspace)
    return _workspace_label_policy_to_read(workspace)


@router.get("/{workspace_code}/feedback-policy", response_model=WorkspaceFeedbackPolicyRead)
def get_workspace_feedback_policy(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceFeedbackPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = _get_enabled_workspace(session, workspace_code)
    return _workspace_feedback_policy_to_read(workspace)


@router.patch("/{workspace_code}/feedback-policy", response_model=WorkspaceFeedbackPolicyRead)
def update_workspace_feedback_policy(
    workspace_code: str,
    payload: WorkspaceFeedbackPolicyUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceFeedbackPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    policy = _normalize_feedback_policy(payload.model_dump())
    config = dict(workspace.config_json or {})
    before = dict(config.get("feedback_policy") or {})
    config["feedback_policy"] = policy
    workspace.config_json = config
    write_audit(
        session,
        current_user,
        action="workspace.feedback_policy.update",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "before": before,
            "after": policy,
        },
    )
    session.commit()
    session.refresh(workspace)
    return _workspace_feedback_policy_to_read(workspace)


@router.get("/{workspace_code}/report-policy", response_model=WorkspaceReportPolicyRead)
def get_workspace_report_policy(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceReportPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = _get_enabled_workspace(session, workspace_code)
    return _workspace_report_policy_to_read(workspace)


@router.patch("/{workspace_code}/report-policy", response_model=WorkspaceReportPolicyRead)
def update_workspace_report_policy(
    workspace_code: str,
    payload: WorkspaceReportPolicyUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceReportPolicyRead:
    """报告策略（与 label/feedback policy 同级，存 workspaces.config_json.report_policy）。

    auto_publish_daily 默认 true：每日流水线出稿即自动发布（actor=system）。
    关掉后回到人工发布工作流。
    """
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    config = dict(workspace.config_json or {})
    before = dict(config.get("report_policy") or {})
    policy = {"auto_publish_daily": bool(payload.auto_publish_daily)}
    config["report_policy"] = policy
    workspace.config_json = config
    write_audit(
        session,
        current_user,
        action="workspace.report_policy.update",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "before": before,
            "after": policy,
        },
    )
    session.commit()
    session.refresh(workspace)
    return _workspace_report_policy_to_read(workspace)


def _workspace_report_policy_to_read(workspace: Workspace) -> WorkspaceReportPolicyRead:
    policy = workspace_report_policy(workspace)
    return WorkspaceReportPolicyRead(
        workspace_code=workspace.code,
        auto_publish_daily=bool(policy.get("auto_publish_daily")),
    )


# --- 工作台发现与自助订阅（visibility=internal_public，规格见 workspace_model 契约） ---


@router.get("/discover", response_model=list[WorkspaceDiscoverRead])
def discover_workspaces(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceDiscoverRead]:
    """登录用户可发现的 internal_public 工作台列表（含是否已加入与成员数）。

    private 工作台永不出现在发现列表（不泄露存在性）。游客可浏览该列表，
    但 joined 恒为 False 且不能订阅（共享游客账号不建 membership）。
    """
    workspaces = session.scalars(
        select(Workspace).where(
            Workspace.enabled.is_(True),
            Workspace.visibility == "internal_public",
        ),
    ).all()
    workspaces = sorted(
        workspaces,
        key=lambda workspace: (
            (workspace.config_json or {}).get("sort_order", 1000),
            workspace.code,
        ),
    )
    guest = is_guest_user(current_user)
    items: list[WorkspaceDiscoverRead] = []
    for workspace in workspaces:
        membership = None
        if not guest:
            membership = session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == current_user.id,
                    WorkspaceMembership.enabled.is_(True),
                ),
            )
        items.append(
            WorkspaceDiscoverRead(
                code=workspace.code,
                name=workspace.name,
                description=workspace.description,
                member_count=_workspace_member_count(session, workspace),
                joined=membership is not None,
                workspace_role=(
                    "viewer" if guest else (membership.workspace_role if membership else None)
                ),
            ),
        )
    return items


@router.post("/{workspace_code}/subscribe", response_model=WorkspaceSubscriptionRead)
def subscribe_workspace(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceSubscriptionRead:
    """登录用户自助订阅 internal_public 工作台，成为 viewer member（幂等）。

    - private 或不存在的工作台一律 404，不泄露存在性；
    - 已是成员时不改动既有角色，直接返回当前 membership；
    - 曾被移出（membership disabled）的用户可重新以 viewer 订阅；
    - 游客在 get_current_user 的集中写门禁被 403 拦截（注册后可订阅）。
    """
    workspace = _get_subscribable_workspace(session, workspace_code)
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == current_user.id,
        ),
    )
    if membership is not None and membership.enabled:
        return WorkspaceSubscriptionRead(
            workspace_code=workspace.code,
            workspace_role=membership.workspace_role,
            subscribed=True,
        )
    before_membership = _membership_snapshot(membership)
    if membership is None:
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=current_user.id,
            workspace_role="viewer",
            enabled=True,
        )
        session.add(membership)
    else:
        membership.workspace_role = "viewer"
        membership.enabled = True
    write_audit(
        session,
        current_user,
        action="workspace.member.subscribe",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "user_id": current_user.id,
            "before": before_membership,
            "after": _membership_snapshot(membership),
        },
    )
    session.commit()
    session.refresh(membership)
    return WorkspaceSubscriptionRead(
        workspace_code=workspace.code,
        workspace_role=membership.workspace_role,
        subscribed=True,
    )


@router.delete("/{workspace_code}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe_workspace(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    """退订：移除自己的 viewer membership（幂等）。

    角色高于 viewer 的成员由管理员管理（400），避免 owner/admin 自助退订
    绕过「最后一个 owner」等成员管理保护。
    """
    workspace = _get_enabled_workspace(session, workspace_code)
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    if membership is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if membership.workspace_role != "viewer":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Roles above viewer are managed by workspace admins",
        )
    before_membership = _membership_snapshot(membership)
    membership.enabled = False
    write_audit(
        session,
        current_user,
        action="workspace.member.unsubscribe",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "user_id": current_user.id,
            "before": before_membership,
            "after": _membership_snapshot(membership),
        },
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{workspace_code}/visibility", response_model=WorkspaceRead)
def update_workspace_visibility(
    workspace_code: str,
    payload: WorkspaceVisibilityUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceRead:
    """工作台可见性（owner/admin）：private 仅成员可见；internal_public 可被
    登录用户发现/订阅、被游客只读浏览。种子只赋初值，此处的决定不被重播种回滚。
    """
    workspace = _get_enabled_workspace(session, workspace_code)
    assert_workspace_member(session, current_user, workspace.code, min_role="admin")
    before = workspace.visibility
    workspace.visibility = payload.visibility
    write_audit(
        session,
        current_user,
        action="workspace.visibility.update",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "before": {"visibility": before},
            "after": {"visibility": payload.visibility},
        },
    )
    session.commit()
    session.refresh(workspace)
    return _workspace_to_read(workspace, current_user=current_user, session=session)


def _get_subscribable_workspace(session: Session, workspace_code: str) -> Workspace:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None or workspace.visibility != "internal_public":
        # private 与不存在同响应：不向非成员泄露工作台存在性
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


def _workspace_member_count(session: Session, workspace: Workspace) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    return int(value or 0)


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


def _workspace_owner_count(session: Session, workspace: Workspace) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.workspace_role == "owner",
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    return int(value or 0)


def _membership_snapshot(membership: WorkspaceMembership | None) -> dict | None:
    if membership is None:
        return None
    return {"workspace_role": membership.workspace_role, "enabled": membership.enabled}


def _workspace_auth_membership_mapping_to_read(workspace: Workspace) -> WorkspaceAuthMembershipMappingRead:
    raw_rows = ((workspace.config_json or {}).get("auth_membership_mapping") or {}).get("department_workspaces") or []
    rows = _normalize_auth_membership_mapping(
        [
            WorkspaceDepartmentMembershipTarget(
                department=str(row.get("department") or ""),
                workspace_role=str(row.get("workspace_role") or "viewer"),
            )
            for row in raw_rows
            if isinstance(row, dict)
        ],
    )
    return WorkspaceAuthMembershipMappingRead(workspace_code=workspace.code, department_workspaces=rows)


def _normalize_auth_membership_mapping(
    rows: list[WorkspaceDepartmentMembershipTarget],
) -> list[WorkspaceDepartmentMembershipTarget]:
    normalized: dict[str, WorkspaceDepartmentMembershipTarget] = {}
    role_rank = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
    for row in rows:
        department = " ".join(row.department.split())
        if not department:
            continue
        candidate = WorkspaceDepartmentMembershipTarget(
            department=department,
            workspace_role=row.workspace_role,
        )
        existing = normalized.get(department)
        if existing is None or role_rank[candidate.workspace_role] > role_rank[existing.workspace_role]:
            normalized[department] = candidate
    return sorted(normalized.values(), key=lambda item: (item.department, item.workspace_role))


def _workspace_to_read(
    workspace: Workspace,
    *,
    current_user: User | None = None,
    session: Session | None = None,
) -> WorkspaceRead:
    return WorkspaceRead(
        code=workspace.code,
        name=workspace.name,
        description=workspace.description,
        workspace_type=workspace.workspace_type,
        default_domain_code=workspace.default_domain_code,
        enabled=workspace.enabled,
        visibility=workspace.visibility,
        current_user_workspace_role=_current_workspace_role(session, workspace, current_user),
    )


def _current_workspace_role(
    session: Session | None,
    workspace: Workspace,
    current_user: User | None,
) -> str | None:
    if current_user is None:
        return None
    if is_guest_user(current_user):
        # 游客隐式 viewer 视角（不建 membership）；前端导航/路由守卫按 viewer 过滤。
        return "viewer" if workspace.visibility == "internal_public" else None
    if session is None:
        return "owner" if _is_super_admin(current_user) else None
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == current_user.id,
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    if membership is not None:
        return membership.workspace_role
    if _is_super_admin(current_user):
        return "owner"
    return None


def _core_section_keys(workspace_code: str) -> set[str]:
    """核心分区键：全局核心分区 + 该工作台定义内的附加分区（bootstrap 会强制启用）。"""
    keys = {section_key for section_key, *_ in CORE_WORKSPACE_SECTIONS}
    definition = WORKSPACE_DEFINITIONS.get(workspace_code) or {}
    keys.update(section_key for section_key, *_ in definition.get("extra_sections", []))
    return keys


def _section_effective_enabled(section: WorkspaceSection) -> bool:
    """分区的生效启停：config_json.user_enabled（管理 API 写入）优先于 enabled 列。

    enabled 列每次 bootstrap 播种都会被重置（核心分区强制 True、定义外分区强制
    False），单看它无法保留用户决定；user_enabled 存在 config_json 里不会被播种覆盖。
    """
    override = (section.config_json or {}).get("user_enabled")
    if isinstance(override, bool):
        return override
    return section.enabled


def _section_min_role(section: WorkspaceSection) -> str:
    """分区可见的最低工作台角色：config_json.min_role 覆盖 > 阅读分区 viewer > member。

    数据驱动：前端 AppShell 导航与路由守卫按该字段过滤，viewer（游客）只看到
    日报/周报/历史报告/实体大事记等阅读分区。
    """
    override = (section.config_json or {}).get("min_role")
    if isinstance(override, str) and override in SECTION_ROLE_VALUES:
        return override
    return "viewer" if section.section_key in VIEWER_SECTION_KEYS else "member"


def _section_to_read(section: WorkspaceSection) -> WorkspaceSectionRead:
    return WorkspaceSectionRead(
        section_key=section.section_key,
        name=section.name,
        section_type=section.section_type,
        route_path=section.route_path,
        sort_order=section.sort_order,
        group=str((section.config_json or {}).get("group") or "system"),
        min_role=_section_min_role(section),
    )


def _taxonomy_categories() -> list[str]:
    taxonomy_path = REPO_ROOT / "config" / "taxonomy" / "news_categories.json"
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    return list(taxonomy.get("categories") or [])


def _taxonomy_secondary_labels() -> dict[str, list[str]]:
    return {}


def _normalize_export_category_mode(value: str) -> str:
    mode = (value or "news_primary").strip()
    if mode != "news_primary":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="export_category_mode must be news_primary",
        )
    return mode


def _normalize_policy_categories(categories: list[str]) -> list[str]:
    normalized: list[str] = []
    for category in categories:
        value = category.strip()
        if not value:
            continue
        if value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_secondary_labels(
    labels_by_primary: dict[str, list[str]],
    allowed_categories: list[str],
) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    allowed = set(allowed_categories)
    for primary, labels in labels_by_primary.items():
        primary_value = primary.strip()
        if primary_value not in allowed:
            continue
        clean_labels: list[str] = []
        for label in labels:
            value = label.strip()
            if value and value not in clean_labels:
                clean_labels.append(value)
        if clean_labels:
            normalized[primary_value] = clean_labels
    return normalized


def _normalize_required_content_fields(fields: list[str]) -> list[str]:
    normalized: list[str] = []
    for field in fields:
        value = field.strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized or list(DEFAULT_REQUIRED_CONTENT_FIELDS)


def _workspace_label_policy_to_read(workspace: Workspace) -> WorkspaceLabelPolicyRead:
    categories = _taxonomy_categories()
    config = workspace.config_json or {}
    policy = config.get("label_policy") or {}
    if workspace.code == "planning_intel" and policy.get("label_set_code") not in {None, "ai_sql_categories"}:
        policy = {}
    allowed_categories = list(policy.get("allowed_primary_categories") or categories)
    raw_secondary_labels = (
        policy.get("secondary_labels_by_primary")
        if "secondary_labels_by_primary" in policy
        else _taxonomy_secondary_labels()
    )
    secondary_labels = _normalize_secondary_labels(
        dict(raw_secondary_labels or {}),
        allowed_categories,
    )
    default_category = str(policy.get("default_category") or "AI 应用")
    fallback_category = str(policy.get("fallback_category") or "AI 应用")
    if default_category not in allowed_categories:
        default_category = allowed_categories[0] if allowed_categories else "AI 应用"
    if fallback_category not in allowed_categories:
        fallback_category = default_category
    return WorkspaceLabelPolicyRead(
        workspace_code=workspace.code,
        label_set_code=str(policy.get("label_set_code") or "ai_sql_categories"),
        news_format_code=str(policy.get("news_format_code") or "company_sql_v1"),
        export_category_mode=_normalize_export_category_mode(str(policy.get("export_category_mode") or "news_primary")),
        required_content_fields=_normalize_required_content_fields(
            list(policy.get("required_content_fields") or DEFAULT_REQUIRED_CONTENT_FIELDS),
        ),
        allowed_primary_categories=allowed_categories,
        secondary_labels_by_primary=secondary_labels,
        default_category=default_category,
        fallback_category=fallback_category,
        tagging_stages=list(
            policy.get("tagging_stages") or ["news_generation", "post_dedupe_labeling"],
        ),
    )


def _normalize_feedback_policy(policy: dict) -> dict:
    normalized = {
        **DEFAULT_WORKSPACE_FEEDBACK_POLICY,
        **dict(policy or {}),
    }
    return {
        "viewer_can_react": bool(normalized.get("viewer_can_react")),
        "viewer_can_rate": bool(normalized.get("viewer_can_rate")),
        "viewer_can_comment": bool(normalized.get("viewer_can_comment")),
        "viewer_can_edit": bool(normalized.get("viewer_can_edit")),
        "notify_on_comment": bool(normalized.get("notify_on_comment")),
        "notify_on_publish": bool(normalized.get("notify_on_publish")),
    }


def _workspace_feedback_policy_to_read(workspace: Workspace) -> WorkspaceFeedbackPolicyRead:
    config = workspace.config_json or {}
    policy = _normalize_feedback_policy(dict(config.get("feedback_policy") or {}))
    return WorkspaceFeedbackPolicyRead(workspace_code=workspace.code, **policy)
