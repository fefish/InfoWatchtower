from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.adapters import AdapterRegistry
from app.core.database import get_session_factory
from app.ingestion.runs import WorkspaceIngestionRequest, run_workspace_ingestion
from app.models.content import IngestionRun
from app.normalization.news import (
    NewsNormalizationRequest,
    NewsNormalizationResult,
    normalize_workspace_raw_items,
)
from app.recommendations.service import (
    RecommendationRunRequest,
    RecommendationRunResult,
    run_daily_recommendation,
)


@dataclass(frozen=True)
class DailyPipelineRequest:
    workspace_code: str = "planning_intel"
    day_key: str | None = None
    source_types: list[str] | None = None
    ingestion_limit: int | None = None
    recommendation_limit: int = 15
    source_daily_limit: int = 2
    create_daily_draft: bool = True
    run_ingestion: bool = True


@dataclass(frozen=True)
class DailyPipelineResult:
    ingestion_run: IngestionRun | None
    normalization: NewsNormalizationResult
    recommendation: RecommendationRunResult


async def run_daily_pipeline(
    session: Session,
    request: DailyPipelineRequest,
    registry: AdapterRegistry | None = None,
) -> DailyPipelineResult:
    source_types = request.source_types or []
    ingestion_run = None
    if request.run_ingestion:
        ingestion_run = await run_workspace_ingestion(
            session,
            WorkspaceIngestionRequest(
                workspace_code=request.workspace_code,
                source_types=source_types,
                limit=request.ingestion_limit,
            ),
            registry=registry,
        )

    normalization = normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(
            workspace_code=request.workspace_code,
            source_types=source_types,
            limit=None,
        ),
    )
    recommendation = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code=request.workspace_code,
            day_key=request.day_key,
            limit=request.recommendation_limit,
            source_daily_limit=request.source_daily_limit,
            create_daily_draft=request.create_daily_draft,
        ),
    )
    return DailyPipelineResult(
        ingestion_run=ingestion_run,
        normalization=normalization,
        recommendation=recommendation,
    )


def run_daily_pipeline_job(
    workspace_code: str = "planning_intel",
    source_types: list[str] | None = None,
    ingestion_limit: int | None = None,
    recommendation_limit: int = 15,
    source_daily_limit: int = 2,
    create_daily_draft: bool = True,
    run_ingestion: bool = True,
    day_key: str | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        _run_daily_pipeline_job(
            workspace_code=workspace_code,
            source_types=source_types or [],
            ingestion_limit=ingestion_limit,
            recommendation_limit=recommendation_limit,
            source_daily_limit=source_daily_limit,
            create_daily_draft=create_daily_draft,
            run_ingestion=run_ingestion,
            day_key=day_key,
        ),
    )


async def _run_daily_pipeline_job(
    workspace_code: str,
    source_types: list[str],
    ingestion_limit: int | None,
    recommendation_limit: int,
    source_daily_limit: int,
    create_daily_draft: bool,
    run_ingestion: bool,
    day_key: str | None,
) -> dict[str, Any]:
    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for daily pipeline jobs.")

    with session_factory() as session:
        result = await run_daily_pipeline(
            session,
            DailyPipelineRequest(
                workspace_code=workspace_code,
                day_key=day_key,
                source_types=source_types,
                ingestion_limit=ingestion_limit,
                recommendation_limit=recommendation_limit,
                source_daily_limit=source_daily_limit,
                create_daily_draft=create_daily_draft,
                run_ingestion=run_ingestion,
            ),
        )
        payload = daily_pipeline_payload(result)
        session.commit()
        return payload


def daily_pipeline_payload(result: DailyPipelineResult) -> dict[str, Any]:
    ingestion = result.ingestion_run
    recommendation = result.recommendation
    return {
        "workspace_code": recommendation.run.workspace_code,
        "day_key": recommendation.run.params_json.get("day_key"),
        "ingestion_run_id": ingestion.id if ingestion else None,
        "ingestion_status": ingestion.status if ingestion else "skipped",
        "raw_scanned": result.normalization.raw_scanned,
        "news_created": result.normalization.news_created,
        "news_updated": result.normalization.news_updated,
        "raw_skipped": result.normalization.raw_skipped,
        "dedupe_groups_updated": result.normalization.dedupe_groups_updated,
        "recommendation_run_id": recommendation.run.id,
        "daily_report_id": recommendation.daily_report.id if recommendation.daily_report else None,
        "candidates_total": recommendation.candidates_total,
        "selected_total": recommendation.selected_total,
        "generated_total": recommendation.generated_total,
    }
