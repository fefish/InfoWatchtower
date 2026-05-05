from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import AdapterRegistry, create_default_registry
from app.ingestion.fetch import SourceFetchError, fetch_source_to_raw_items
from app.models.common import utc_now
from app.models.content import DataSource, IngestionRun
from app.models.workspace import Workspace, WorkspaceSourceLink

DEFAULT_INGESTION_SOURCE_TYPES = ["rss", "paper_rss"]


@dataclass(frozen=True)
class WorkspaceIngestionRequest:
    workspace_code: str
    source_types: list[str]
    limit: int | None = None


class WorkspaceNotFoundError(ValueError):
    pass


async def run_workspace_ingestion(
    session: Session,
    request: WorkspaceIngestionRequest,
    registry: AdapterRegistry | None = None,
    started_at: datetime | None = None,
) -> IngestionRun:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == request.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {request.workspace_code}")

    started_at = started_at or utc_now()
    source_types = _normalize_source_types(request.source_types)
    sources = _workspace_sources(
        session=session,
        workspace=workspace,
        source_types=source_types,
        limit=request.limit,
    )
    registry = registry or create_default_registry()

    run = IngestionRun(
        run_key=_run_key(workspace.code, started_at),
        workspace_code=workspace.code,
        domain_code=workspace.default_domain_code,
        run_type="workspace_fetch",
        status="running",
        started_at=started_at,
        params_json={
            "workspace_code": workspace.code,
            "source_types": source_types,
            "limit": request.limit,
        },
    )
    session.add(run)
    session.flush()

    source_summaries = []
    totals = {
        "source_succeeded": 0,
        "source_failed": 0,
        "items_fetched": 0,
        "raw_created": 0,
        "raw_updated": 0,
    }
    for source in sources:
        try:
            result = await fetch_source_to_raw_items(session, source.id, registry, started_at)
        except (KeyError, SourceFetchError) as exc:
            totals["source_failed"] += 1
            source_summaries.append(
                {
                    "data_source_id": source.id,
                    "name": source.name,
                    "source_type": source.source_type,
                    "status": "failed",
                    "error": str(exc),
                    "fetched": 0,
                    "created": 0,
                    "updated": 0,
                },
            )
            continue

        totals["source_succeeded"] += 1
        totals["items_fetched"] += result.fetched
        totals["raw_created"] += result.created
        totals["raw_updated"] += result.updated
        source_summaries.append(
            {
                "data_source_id": source.id,
                "name": source.name,
                "source_type": source.source_type,
                "status": "completed",
                "fetched": result.fetched,
                "created": result.created,
                "updated": result.updated,
            },
        )

    run.source_total = len(sources)
    run.source_succeeded = totals["source_succeeded"]
    run.source_failed = totals["source_failed"]
    run.items_fetched = totals["items_fetched"]
    run.raw_created = totals["raw_created"]
    run.raw_updated = totals["raw_updated"]
    run.status = _run_status(run.source_total, run.source_succeeded, run.source_failed)
    run.completed_at = utc_now()
    run.summary_json = {
        "sources": source_summaries,
        "source_types": source_types,
    }
    session.flush()
    return run


def _workspace_sources(
    session: Session,
    workspace: Workspace,
    source_types: list[str],
    limit: int | None,
) -> list[DataSource]:
    statement = (
        select(DataSource)
        .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
        .where(
            WorkspaceSourceLink.workspace_id == workspace.id,
            WorkspaceSourceLink.enabled.is_(True),
            DataSource.enabled.is_(True),
        )
        .order_by(DataSource.source_type, DataSource.name)
    )
    if source_types:
        statement = statement.where(DataSource.source_type.in_(source_types))
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement).all())


def _normalize_source_types(source_types: list[str]) -> list[str]:
    normalized: list[str] = []
    for source_type in source_types or DEFAULT_INGESTION_SOURCE_TYPES:
        value = source_type.strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized or list(DEFAULT_INGESTION_SOURCE_TYPES)


def _run_key(workspace_code: str, started_at: datetime) -> str:
    compact_time = started_at.strftime("%Y%m%d%H%M%S%f")
    return f"{workspace_code}:ingestion:{compact_time}"


def _run_status(source_total: int, source_succeeded: int, source_failed: int) -> str:
    if source_total == 0:
        return "completed"
    if source_failed == 0:
        return "completed"
    if source_succeeded > 0:
        return "partial"
    return "failed"
