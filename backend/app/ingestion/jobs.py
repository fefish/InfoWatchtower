from __future__ import annotations

import asyncio
from typing import Any

from app.core.database import get_session_factory
from app.ingestion.runs import (
    DEFAULT_INGESTION_CONCURRENCY,
    DEFAULT_SOURCE_TIMEOUT_SECONDS,
    WorkspaceIngestionRequest,
    run_workspace_ingestion,
)

INGESTION_QUEUE_NAME = "infowatchtower"


def run_workspace_ingestion_job(
    workspace_code: str = "planning_intel",
    source_types: list[str] | None = None,
    limit: int | None = None,
    concurrency: int = DEFAULT_INGESTION_CONCURRENCY,
    source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return asyncio.run(
        _run_workspace_ingestion_job(
            workspace_code,
            source_types or [],
            limit,
            concurrency,
            source_timeout_seconds,
        ),
    )


async def _run_workspace_ingestion_job(
    workspace_code: str,
    source_types: list[str],
    limit: int | None,
    concurrency: int,
    source_timeout_seconds: float,
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
