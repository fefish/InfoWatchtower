from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.auth.service import provision_workspace, write_audit
from app.core.database import get_db_session
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceSection
from app.schemas.workspaces import (
    DEFAULT_REQUIRED_CONTENT_FIELDS,
    WorkspaceCreate,
    WorkspaceLabelPolicyRead,
    WorkspaceLabelPolicyUpdate,
    WorkspaceRead,
    WorkspaceSectionRead,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
REPO_ROOT = Path(__file__).resolve().parents[4]


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceRead]:
    workspaces = session.scalars(
        select(Workspace)
        .where(Workspace.enabled.is_(True))
    ).all()
    workspaces = sorted(
        workspaces,
        key=lambda workspace: (
            (workspace.config_json or {}).get("sort_order", 1000),
            workspace.code,
        ),
    )
    return [_workspace_to_read(workspace) for workspace in workspaces]


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(require_super_admin),
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
    return _workspace_to_read(workspace)


@router.get("/{workspace_code}/sections", response_model=list[WorkspaceSectionRead])
def list_workspace_sections(
    workspace_code: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[WorkspaceSectionRead]:
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
        .where(
            WorkspaceSection.workspace_id == workspace.id,
            WorkspaceSection.enabled.is_(True),
        )
        .order_by(WorkspaceSection.sort_order, WorkspaceSection.section_key),
    ).all()
    return [_section_to_read(section) for section in sections]


@router.get("/{workspace_code}/label-policy", response_model=WorkspaceLabelPolicyRead)
def get_workspace_label_policy(
    workspace_code: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> WorkspaceLabelPolicyRead:
    workspace = _get_enabled_workspace(session, workspace_code)
    return _workspace_label_policy_to_read(workspace)


@router.patch("/{workspace_code}/label-policy", response_model=WorkspaceLabelPolicyRead)
def update_workspace_label_policy(
    workspace_code: str,
    payload: WorkspaceLabelPolicyUpdate,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> WorkspaceLabelPolicyRead:
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


def _workspace_to_read(workspace: Workspace) -> WorkspaceRead:
    return WorkspaceRead(
        code=workspace.code,
        name=workspace.name,
        description=workspace.description,
        workspace_type=workspace.workspace_type,
        default_domain_code=workspace.default_domain_code,
    )


def _section_to_read(section: WorkspaceSection) -> WorkspaceSectionRead:
    return WorkspaceSectionRead(
        section_key=section.section_key,
        name=section.name,
        section_type=section.section_type,
        route_path=section.route_path,
        sort_order=section.sort_order,
        group=str((section.config_json or {}).get("group") or "system"),
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
