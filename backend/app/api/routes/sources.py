from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.ingestion.fetch import SourceFetchError, SourceNotFoundError, fetch_source_to_raw_items
from app.ingestion.source_seeds import import_legacy_sources
from app.models.content import DataSource
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.schemas.sources import DataSourceRead, LegacySeedImportRead, SourceFetchRead

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[DataSourceRead])
def list_sources(
    workspace_code: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    _: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[DataSourceRead]:
    statement = select(DataSource)
    if source_type:
        statement = statement.where(DataSource.source_type == source_type)
    statement = statement.order_by(DataSource.source_type, DataSource.name)
    sources = session.scalars(statement).all()
    links_by_source_id = _workspace_links_by_source_id(session, workspace_code)
    return [_source_to_read(source, links_by_source_id.get(source.id)) for source in sources]


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


@router.post("/{source_id}/fetch", response_model=SourceFetchRead)
async def fetch_source(
    source_id: str,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> SourceFetchRead:
    try:
        result = await fetch_source_to_raw_items(session, source_id)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SourceFetchError as exc:
        session.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    session.commit()
    return SourceFetchRead(
        data_source_id=result.data_source_id,
        source_type=result.source_type,
        fetched=result.fetched,
        created=result.created,
        updated=result.updated,
    )


def _workspace_links_by_source_id(
    session: Session,
    workspace_code: str | None,
) -> dict[str, WorkspaceSourceLink]:
    if not workspace_code:
        return {}
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    links = session.scalars(
        select(WorkspaceSourceLink).where(WorkspaceSourceLink.workspace_id == workspace.id),
    ).all()
    return {link.data_source_id: link for link in links}


def _source_to_read(source: DataSource, workspace_link: WorkspaceSourceLink | None = None) -> DataSourceRead:
    metadata = source.metadata_json or {}
    link_config = workspace_link.config_json if workspace_link else {}
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
        workspace_link_enabled=workspace_link.enabled if workspace_link else False,
        workspace_source_weight=workspace_link.source_weight if workspace_link else None,
        workspace_daily_limit=workspace_link.daily_limit if workspace_link else None,
        workspace_label_set_codes=list(link_config.get("label_set_codes") or []),
        workspace_default_label_paths=list(link_config.get("default_label_paths") or []),
        workspace_clustering_config=dict(link_config.get("clustering_config") or {}),
    )
