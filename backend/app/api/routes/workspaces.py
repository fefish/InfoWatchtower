from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.core.database import get_db_session
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceSection
from app.schemas.workspaces import WorkspaceRead, WorkspaceSectionRead

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


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
