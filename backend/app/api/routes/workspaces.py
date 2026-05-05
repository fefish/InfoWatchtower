from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.database import get_db_session
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceSection
from app.schemas.workspaces import (
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
        key=lambda workspace: ((workspace.config_json or {}).get("sort_order", 1000), workspace.code),
    )
    return [_workspace_to_read(workspace) for workspace in workspaces]


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
        "allowed_primary_categories": allowed_categories,
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
    )


def _taxonomy_categories() -> list[str]:
    taxonomy_path = REPO_ROOT / "config" / "taxonomy" / "news_categories.json"
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    return list(taxonomy.get("categories") or [])


def _normalize_policy_categories(categories: list[str]) -> list[str]:
    normalized: list[str] = []
    for category in categories:
        value = category.strip()
        if not value:
            continue
        if value not in normalized:
            normalized.append(value)
    return normalized


def _workspace_label_policy_to_read(workspace: Workspace) -> WorkspaceLabelPolicyRead:
    categories = _taxonomy_categories()
    config = workspace.config_json or {}
    policy = config.get("label_policy") or {}
    allowed_categories = list(policy.get("allowed_primary_categories") or categories)
    default_category = str(policy.get("default_category") or "AI 应用")
    fallback_category = str(policy.get("fallback_category") or "AI 应用")
    if default_category not in allowed_categories:
        default_category = allowed_categories[0] if allowed_categories else "AI 应用"
    if fallback_category not in allowed_categories:
        fallback_category = default_category
    return WorkspaceLabelPolicyRead(
        workspace_code=workspace.code,
        label_set_code=str(policy.get("label_set_code") or "ai_sql_categories"),
        allowed_primary_categories=allowed_categories,
        default_category=default_category,
        fallback_category=fallback_category,
        tagging_stages=list(policy.get("tagging_stages") or ["news_generation", "post_dedupe_labeling"]),
    )
