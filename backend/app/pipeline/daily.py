from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import AdapterRegistry
from app.core.database import get_session_factory
from app.ingestion.jobs import ingestion_capability_skip
from app.ingestion.runs import (
    DEFAULT_INGESTION_CONCURRENCY,
    DEFAULT_SOURCE_TIMEOUT_SECONDS,
    WorkspaceIngestionRequest,
    run_workspace_ingestion,
)
from app.models.content import IngestionRun
from app.models.workspace import Workspace
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
from app.reports.publish import auto_publish_daily_enabled, publish_daily_report


@dataclass(frozen=True)
class DailyPipelineRequest:
    workspace_code: str
    day_key: str | None = None
    source_types: list[str] | None = None
    ingestion_limit: int | None = None
    ingestion_concurrency: int = DEFAULT_INGESTION_CONCURRENCY
    ingestion_source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS
    ingestion_max_items_per_source: int | None = None
    recommendation_limit: int = 15
    source_daily_limit: int = 2
    generation_timeout_seconds: float = 45.0
    create_daily_draft: bool = True
    run_ingestion: bool = True
    # None = 跟随工作台策略 report_policy.auto_publish_daily（默认 true，用户口径
    # “每天 12 点默认直接推送”）。手动 API 触发（生成日报草稿按钮）显式传 False，
    # 保持草稿工作流不被自动发布截断。
    auto_publish_daily: bool | None = None


@dataclass(frozen=True)
class DailyPipelineResult:
    ingestion_run: IngestionRun | None
    normalization: NewsNormalizationResult
    recommendation: RecommendationRunResult
    auto_published: bool = False


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
                concurrency=request.ingestion_concurrency,
                source_timeout_seconds=request.ingestion_source_timeout_seconds,
                max_items_per_source=request.ingestion_max_items_per_source,
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
            generation_timeout_seconds=request.generation_timeout_seconds,
        ),
    )
    auto_published = _maybe_auto_publish_daily_report(session, request, recommendation)
    return DailyPipelineResult(
        ingestion_run=ingestion_run,
        normalization=normalization,
        recommendation=recommendation,
        auto_published=auto_published,
    )


def _maybe_auto_publish_daily_report(
    session: Session,
    request: DailyPipelineRequest,
    recommendation: RecommendationRunResult,
) -> bool:
    """流水线出稿后按策略自动发布（actor=system，audit=daily_report.auto_publish）。"""
    report = recommendation.daily_report
    if report is None or report.status == "published":
        return False
    if request.auto_publish_daily is None:
        workspace = session.scalar(
            select(Workspace).where(Workspace.code == request.workspace_code),
        )
        if workspace is None or not auto_publish_daily_enabled(workspace):
            return False
    elif not request.auto_publish_daily:
        return False
    publish_daily_report(
        session,
        report,
        actor=None,
        audit_action="daily_report.auto_publish",
    )
    return True


def run_daily_pipeline_job(
    workspace_code: str,
    source_types: list[str] | None = None,
    ingestion_limit: int | None = None,
    ingestion_concurrency: int = DEFAULT_INGESTION_CONCURRENCY,
    ingestion_source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
    ingestion_max_items_per_source: int | None = None,
    recommendation_limit: int = 15,
    source_daily_limit: int = 2,
    generation_timeout_seconds: float = 45.0,
    create_daily_draft: bool = True,
    run_ingestion: bool = True,
    day_key: str | None = None,
) -> dict[str, Any]:
    # 日报管线含采集阶段（intranet 消费远端成稿，不本地跑管线），与采集 job 同门
    skipped = ingestion_capability_skip("daily_pipeline", workspace_code)
    if skipped is not None:
        return skipped
    return asyncio.run(
        _run_daily_pipeline_job(
            workspace_code=workspace_code,
            source_types=source_types or [],
            ingestion_limit=ingestion_limit,
            ingestion_concurrency=ingestion_concurrency,
            ingestion_source_timeout_seconds=ingestion_source_timeout_seconds,
            ingestion_max_items_per_source=ingestion_max_items_per_source,
            recommendation_limit=recommendation_limit,
            source_daily_limit=source_daily_limit,
            generation_timeout_seconds=generation_timeout_seconds,
            create_daily_draft=create_daily_draft,
            run_ingestion=run_ingestion,
            day_key=day_key,
        ),
    )


async def _run_daily_pipeline_job(
    workspace_code: str,
    source_types: list[str],
    ingestion_limit: int | None,
    ingestion_concurrency: int,
    ingestion_source_timeout_seconds: float,
    ingestion_max_items_per_source: int | None,
    recommendation_limit: int,
    source_daily_limit: int,
    generation_timeout_seconds: float,
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
                ingestion_concurrency=ingestion_concurrency,
                ingestion_source_timeout_seconds=ingestion_source_timeout_seconds,
                ingestion_max_items_per_source=ingestion_max_items_per_source,
                recommendation_limit=recommendation_limit,
                source_daily_limit=source_daily_limit,
                generation_timeout_seconds=generation_timeout_seconds,
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
    daily_report = recommendation.daily_report
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
        "daily_report_id": daily_report.id if daily_report else None,
        "daily_report_status": daily_report.status if daily_report else None,
        "auto_published": result.auto_published,
        "candidates_total": recommendation.candidates_total,
        "selected_total": recommendation.selected_total,
        "generated_total": recommendation.generated_total,
    }
