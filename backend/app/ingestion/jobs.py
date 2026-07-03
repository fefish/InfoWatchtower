from __future__ import annotations

import asyncio
from typing import Any

from app.core.database import get_session_factory
from app.ingestion.runs import (
    DEFAULT_BACKFILL_SOURCE_TYPES,
    DEFAULT_INGESTION_CONCURRENCY,
    DEFAULT_SOURCE_TIMEOUT_SECONDS,
    HistoricalBackfillRequest,
    WorkspaceIngestionRequest,
    run_historical_backfill,
    run_workspace_ingestion,
)

INGESTION_QUEUE_NAME = "infowatchtower"


def run_workspace_ingestion_job(
    workspace_code: str,
    source_types: list[str] | None = None,
    limit: int | None = None,
    concurrency: int = DEFAULT_INGESTION_CONCURRENCY,
    source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
    max_items_per_source: int | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        _run_workspace_ingestion_job(
            workspace_code,
            source_types or [],
            limit,
            concurrency,
            source_timeout_seconds,
            max_items_per_source,
        ),
    )


def run_historical_backfill_job(
    workspace_code: str,
    target_day_start: str = "",
    target_day_end: str = "",
    source_types: list[str] | None = None,
    limit: int | None = None,
    concurrency: int = DEFAULT_INGESTION_CONCURRENCY,
    source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
    backfill_mode: str = "rss_window",
    source_scope: str = "source_type",
    retry_policy: str = "manual_run_no_retry",
    include_undated: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        _run_historical_backfill_job(
            workspace_code,
            target_day_start,
            target_day_end,
            source_types or list(DEFAULT_BACKFILL_SOURCE_TYPES),
            limit,
            concurrency,
            source_timeout_seconds,
            backfill_mode,
            source_scope,
            retry_policy,
            include_undated,
        ),
    )


async def _run_workspace_ingestion_job(
    workspace_code: str,
    source_types: list[str],
    limit: int | None,
    concurrency: int,
    source_timeout_seconds: float,
    max_items_per_source: int | None,
) -> dict[str, Any]:
    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for ingestion jobs.")

    with session_factory() as session:
        run = await run_workspace_ingestion(
            session,
            WorkspaceIngestionRequest(
                workspace_code=workspace_code,
                source_types=source_types,
                limit=limit,
                concurrency=concurrency,
                source_timeout_seconds=source_timeout_seconds,
                max_items_per_source=max_items_per_source,
            ),
        )
        payload = {
            "id": run.id,
            "run_key": run.run_key,
            "workspace_code": run.workspace_code,
            "status": run.status,
            "source_total": run.source_total,
            "source_succeeded": run.source_succeeded,
            "source_failed": run.source_failed,
            "items_fetched": run.items_fetched,
            "raw_created": run.raw_created,
            "raw_updated": run.raw_updated,
        }
        session.commit()
        return payload


async def _run_historical_backfill_job(
    workspace_code: str,
    target_day_start: str,
    target_day_end: str,
    source_types: list[str],
    limit: int | None,
    concurrency: int,
    source_timeout_seconds: float,
    backfill_mode: str,
    source_scope: str,
    retry_policy: str,
    include_undated: bool,
) -> dict[str, Any]:
    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for ingestion jobs.")

    with session_factory() as session:
        run = await run_historical_backfill(
            session,
            HistoricalBackfillRequest(
                workspace_code=workspace_code,
                target_day_start=target_day_start,
                target_day_end=target_day_end,
                source_types=source_types,
                limit=limit,
                concurrency=concurrency,
                source_timeout_seconds=source_timeout_seconds,
                backfill_mode=backfill_mode,
                source_scope=source_scope,
                retry_policy=retry_policy,
                include_undated=include_undated,
            ),
        )
        payload = {
            "id": run.id,
            "run_key": run.run_key,
            "workspace_code": run.workspace_code,
            "status": run.status,
            "source_total": run.source_total,
            "source_succeeded": run.source_succeeded,
            "source_failed": run.source_failed,
            "items_fetched": run.items_fetched,
            "raw_created": run.raw_created,
            "raw_updated": run.raw_updated,
            "summary_json": run.summary_json or {},
        }
        session.commit()
        return payload
