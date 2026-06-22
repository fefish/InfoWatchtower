from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.ingestion.fetch import SourceFetchError, SourceNotFoundError, fetch_source_to_raw_items
from app.ingestion.source_seeds import import_legacy_sources, import_tech_insight_loop_sources
from app.models.content import DataSource
from app.models.identity import User
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.schemas.sources import (
    DataSourceRead,
    DataSourceWorkspaceConfigUpdate,
    LegacySeedImportRead,
    SourceFetchRead,
    TechInsightLoopImportRead,
)

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


@router.post("/import-tech-insight-loop", response_model=TechInsightLoopImportRead)
def import_tech_insight_loop_seed_sources(
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TechInsightLoopImportRead:
    csv_path = Path(settings.tech_insight_loop_source_csv)
    if not csv_path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tech Insight Loop source CSV does not exist: {csv_path}",
        )

    result = import_tech_insight_loop_sources(session, csv_path)
    session.commit()
    return TechInsightLoopImportRead(
        created=result.created,
        updated=result.updated,
        total=result.total,
        fetchable=result.fetchable,
        metadata_only=result.metadata_only,
    )


@router.patch("/{source_id}/workspace-link", response_model=DataSourceRead)
def update_source_workspace_link(
    source_id: str,
    payload: DataSourceWorkspaceConfigUpdate,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> DataSourceRead:
    source = session.get(DataSource, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data source not found")

    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == payload.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    link = session.scalar(
        select(WorkspaceSourceLink).where(
            WorkspaceSourceLink.workspace_id == workspace.id,
            WorkspaceSourceLink.data_source_id == source.id,
        ),
    )
    if link is None:
        link = WorkspaceSourceLink(
            workspace=workspace,
            data_source=source,
            domain_code=source.domain_code,
        )
        session.add(link)

    link.enabled = payload.enabled
    link.source_weight = payload.source_weight
    link.daily_limit = payload.daily_limit
    link.domain_code = source.domain_code
    existing_config = link.config_json or {}
    link_config = {
        **existing_config,
        "clustering_config": existing_config.get("clustering_config", {}),
    }
    link_config.pop("label_set_codes", None)
    link_config.pop("default_label_paths", None)
    link.config_json = link_config
    session.commit()
    session.refresh(link)
    return _source_to_read(source, link)


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
        source_tags=_string_list(metadata.get("source_tags")),
        source_secondary_tags=_string_list(metadata.get("source_secondary_tags")),
        source_tier=str(metadata.get("source_tier") or ""),
        source_channel_type=str(metadata.get("source_channel_type") or ""),
        expert_routes=_string_list(metadata.get("expert_routes")),
        inclusion_recommendation=str(metadata.get("inclusion_recommendation") or ""),
        metadata_only=bool(metadata.get("metadata_only")),
        needs_entry=bool(metadata.get("needs_entry")),
        fetch_entry_status=str(metadata.get("fetch_entry_status") or ""),
        source_quality_notes=str(metadata.get("source_quality_notes") or ""),
        workspace_link_enabled=workspace_link.enabled if workspace_link else False,
        workspace_source_weight=workspace_link.source_weight if workspace_link else None,
        workspace_daily_limit=workspace_link.daily_limit if workspace_link else None,
        workspace_clustering_config=dict(link_config.get("clustering_config") or {}),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
