from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.ingestion.source_seeds import import_legacy_sources
from app.models.content import DataSource
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.models.identity import User
from app.schemas.sources import DataSourceRead, LegacySeedImportRead

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[DataSourceRead])
def list_sources(
    workspace_code: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[DataSourceRead]:
    statement = select(DataSource)
    if workspace_code:
        statement = (
            statement.join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
            .join(Workspace, Workspace.id == WorkspaceSourceLink.workspace_id)
            .where(Workspace.code == workspace_code)
        )
    if source_type:
        statement = statement.where(DataSource.source_type == source_type)
    statement = statement.order_by(DataSource.source_type, DataSource.name)
    return [_source_to_read(source) for source in session.scalars(statement).all()]


@router.post("/import-legacy-seeds", response_model=LegacySeedImportRead)
def import_legacy_seed_sources(
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LegacySeedImportRead:
    seed_root = Path(settings.legacy_seed_root)
    if not seed_root.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Legacy seed root does not exist: {seed_root}",
        )

    result = import_legacy_sources(session, seed_root)
    session.commit()
    return LegacySeedImportRead(created=result.created, updated=result.updated, total=result.total)


def _source_to_read(source: DataSource) -> DataSourceRead:
    metadata = source.metadata_json or {}
    return DataSourceRead(
        id=source.id,
        workspace_code=source.workspace_code,
        domain_code=source.domain_code,
        source_type=source.source_type,
        name=source.name,
        url=source.url,
        enabled=source.enabled,
        default_focus_id=source.default_focus_id,
        backfill_days=source.backfill_days,
        source_score=source.source_score,
        last_fetch_at=source.last_fetch_at,
        last_success_at=source.last_success_at,
        last_error=source.last_error,
        primary_category=str(metadata.get("primary_category") or ""),
        info_category=str(metadata.get("info_category") or ""),
    )
