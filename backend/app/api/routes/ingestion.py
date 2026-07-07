from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import (
    assert_workspace_member,
    get_current_user,
    require_capability,
    require_super_admin,
)
from app.core.database import get_db_session
from app.ingestion.runs import (
    HistoricalBackfillRequest,
    InvalidBackfillRangeError,
    WorkspaceIngestionRequest,
    WorkspaceNotFoundError,
    run_historical_backfill,
    run_workspace_ingestion,
)
from app.ingestion.manual_import import preview_manual_import
from app.ingestion.retry import failed_source_retry_summary
from app.models.content import (
    DataSource,
    DedupeGroup,
    DedupeGroupItem,
    GeneratedNews,
    IngestionRun,
    NewsItem,
    RawItem,
    RecommendationItem,
    RecommendationRun,
)
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.schemas.ingestion import (
    HistoricalBackfillCreate,
    IngestionCoverageFunnelRead,
    IngestionCoverageRead,
    IngestionCoverageSourceRead,
    IngestionCoverageFailureTrendRead,
    IngestionCoverageTrendPointRead,
    IngestionCoverageTrendsRead,
    IngestionFailedSourceRetryRunRead,
    IngestionFailedSourceRetrySummaryRead,
    IngestionRunCreate,
    IngestionRunRead,
    IngestionRetryFailedCreate,
    ManualImportPreviewCreate,
    ManualImportPreviewErrorRead,
    ManualImportPreviewRead,
)

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)
INGESTION_CAPABILITY = Depends(require_capability("ingestion"))
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@router.get("/scheduler", response_model=dict)
def get_scheduler_config(_: User = CURRENT_USER) -> dict:
    """自动调度当前配置（只读快照）。修改需调整部署 env 并重启 scheduler 服务。"""
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "enabled": settings.ingestion_scheduler_enabled,
        "daily_time": settings.ingestion_scheduler_daily_time,
        "timezone": settings.ingestion_scheduler_timezone,
        "interval_seconds": settings.ingestion_scheduler_interval_seconds,
        "workspace_code": settings.ingestion_scheduler_workspace_code,
        "source_types": settings.ingestion_scheduler_source_types,
        "limit": settings.ingestion_scheduler_limit,
        "max_items_per_source": settings.ingestion_max_items_per_source,
        "job_mode": settings.scheduler_job_mode,
        "day_offset_days": settings.daily_pipeline_day_offset_days,
        "failed_source_auto_retry_enabled": settings.ingestion_failed_source_auto_retry_effective,
        "failed_source_retry_base_seconds": settings.ingestion_failed_source_retry_base_seconds,
        "failed_source_retry_max_attempts": settings.ingestion_failed_source_retry_max_attempts,
        "failed_source_retry_limit": settings.ingestion_failed_source_retry_limit,
        "config_hint": "在部署 .env 中调整 INGESTION_SCHEDULER_* 后重启 scheduler 服务生效",
    }


@router.post("/runs", response_model=IngestionRunRead, dependencies=[INGESTION_CAPABILITY])
async def create_ingestion_run(
    payload: IngestionRunCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> IngestionRunRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        run = await run_workspace_ingestion(
            session,
            WorkspaceIngestionRequest(
                workspace_code=payload.workspace_code,
                source_types=payload.source_types,
                limit=payload.limit,
                concurrency=payload.concurrency,
                source_timeout_seconds=payload.source_timeout_seconds,
                max_items_per_source=payload.max_items_per_source,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    session.commit()
    session.refresh(run)
    return _run_to_read(run)


@router.post(
    "/backfill-runs",
    response_model=IngestionRunRead,
    dependencies=[INGESTION_CAPABILITY],
)
async def create_historical_backfill_run(
    payload: HistoricalBackfillCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> IngestionRunRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        run = await run_historical_backfill(
            session,
            HistoricalBackfillRequest(
                workspace_code=payload.workspace_code,
                target_day_start=payload.target_day_start,
                target_day_end=payload.target_day_end,
                source_types=payload.source_types,
                limit=payload.limit,
                concurrency=payload.concurrency,
                source_timeout_seconds=payload.source_timeout_seconds,
                backfill_mode=payload.backfill_mode,
                source_scope=payload.source_scope,
                retry_policy=payload.retry_policy,
                include_undated=payload.include_undated,
                manual_items=payload.manual_items,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidBackfillRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    session.commit()
    session.refresh(run)
    return _run_to_read(run)


@router.post(
    "/manual-import-preview",
    response_model=ManualImportPreviewRead,
    dependencies=[INGESTION_CAPABILITY],
)
def preview_manual_import_payload(
    payload: ManualImportPreviewCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ManualImportPreviewRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == payload.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    enabled_sources = [
        source
        for source in _enabled_sources(session, workspace)
        if source.source_type in set(payload.source_types)
    ]
    enabled_source_ids = {source.id for source in enabled_sources}
    if not enabled_source_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前工作台在所选源类型下没有启用源，无法预览手工导入。",
        )
    if payload.default_data_source_id and payload.default_data_source_id not in enabled_source_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_data_source_id 不属于当前工作台所选源类型下的已启用源。",
        )

    preview = preview_manual_import(
        input_text=payload.input_text,
        input_format=payload.input_format,
        default_data_source_id=payload.default_data_source_id,
        enabled_source_ids=enabled_source_ids,
    )
    return ManualImportPreviewRead(
        workspace_code=payload.workspace_code,
        input_format=preview.input_format,
        filename=payload.filename,
        total_rows=preview.total_rows,
        accepted_count=preview.accepted_count,
        rejected_count=preview.rejected_count,
        accepted_items=preview.accepted_items,
        errors=[
            ManualImportPreviewErrorRead(
                row_number=error.row_number,
                code=error.code,
                message=error.message,
                raw_text=error.raw_text,
            )
            for error in preview.errors
        ],
        error_report_csv=preview.error_report_csv,
    )


@router.get("/runs", response_model=list[IngestionRunRead])
def list_ingestion_runs(
    workspace_code: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[IngestionRunRead]:
    if workspace_code:
        assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    else:
        require_super_admin(current_user)
    statement = select(IngestionRun).order_by(IngestionRun.created_at.desc())
    if workspace_code:
        statement = statement.where(IngestionRun.workspace_code == workspace_code)
    if run_type:
        statement = statement.where(IngestionRun.run_type == run_type)
    runs = session.scalars(statement.limit(limit)).all()
    return [_run_to_read(run) for run in runs]


@router.get("/runs/{run_id}", response_model=IngestionRunRead)
def get_ingestion_run(
    run_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> IngestionRunRead:
    run = session.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found")
    assert_workspace_member(session, current_user, run.workspace_code, min_role="viewer")
    return _run_to_read(run)


@router.post(
    "/runs/{run_id}/retry-failed-sources",
    response_model=IngestionRunRead,
    dependencies=[INGESTION_CAPABILITY],
)
async def retry_failed_ingestion_run(
    run_id: str,
    payload: IngestionRetryFailedCreate | None = None,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> IngestionRunRead:
    original = session.get(IngestionRun, run_id)
    if original is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found")
    assert_workspace_member(session, current_user, original.workspace_code, min_role="admin")

    failed_source_ids = _failed_run_source_ids(original)
    if not failed_source_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="本次运行没有可重试的失败源。",
        )

    retryable_sources = _retryable_failed_sources(
        session,
        workspace_code=original.workspace_code,
        failed_source_ids=failed_source_ids,
    )
    if not retryable_sources:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="失败源已被停用或不再属于当前工作台，无法重试。",
        )

    payload = payload or IngestionRetryFailedCreate()
    retry_source_ids = [source.id for source in retryable_sources]
    retry_source_types = _unique(source.source_type for source in retryable_sources)
    original_params = original.params_json or {}
    original_summary = original.summary_json or {}

    try:
        if original.run_type == "historical_backfill":
            backfill_mode = str(original_params.get("backfill_mode") or original_summary.get("backfill_mode") or "rss_window")
            if backfill_mode == "manual_import":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="manual_import 运行不能仅从 run summary 恢复原始手工条目，请重新上传手工补采数据。",
                )
            target_day_start = str(original_params.get("target_day_start") or original_summary.get("target_day_start") or "")
            target_day_end = str(original_params.get("target_day_end") or original_summary.get("target_day_end") or "")
            if not target_day_start or not target_day_end:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Historical backfill run is missing target_day_start/target_day_end",
                )
            run = await run_historical_backfill(
                session,
                HistoricalBackfillRequest(
                    workspace_code=original.workspace_code,
                    target_day_start=target_day_start,
                    target_day_end=target_day_end,
                    source_types=retry_source_types,
                    source_ids=retry_source_ids,
                    limit=None,
                    concurrency=payload.concurrency,
                    source_timeout_seconds=payload.source_timeout_seconds,
                    backfill_mode=backfill_mode,
                    source_scope="failed_sources",
                    retry_policy="retry_failed_sources",
                    include_undated=_bool_value(original_params.get("include_undated")),
                    manual_items=[],
                    retry_of_run_id=original.id,
                ),
            )
        elif original.run_type == "workspace_fetch":
            max_items_per_source = (
                payload.max_items_per_source
                if payload.max_items_per_source is not None
                else _optional_int(original_params.get("max_items_per_source"))
            )
            run = await run_workspace_ingestion(
                session,
                WorkspaceIngestionRequest(
                    workspace_code=original.workspace_code,
                    source_types=retry_source_types,
                    source_ids=retry_source_ids,
                    limit=None,
                    concurrency=payload.concurrency,
                    source_timeout_seconds=payload.source_timeout_seconds,
                    max_items_per_source=max_items_per_source,
                    retry_of_run_id=original.id,
                ),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported ingestion run_type for retry: {original.run_type}",
            )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidBackfillRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    session.commit()
    session.refresh(run)
    return _run_to_read(run)


@router.get("/coverage", response_model=IngestionCoverageRead)
def get_ingestion_coverage(
    workspace_code: str = Query(...),
    day_key: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> IngestionCoverageRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    resolved_day_key = day_key or _today_key()
    try:
        start_utc, end_utc = _day_bounds(resolved_day_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="day_key must use YYYY-MM-DD") from exc

    run = _coverage_run(session, workspace_code=workspace_code, run_id=run_id)
    enabled_sources = _enabled_sources(session, workspace)
    sources_by_id = {source.id: source for source in enabled_sources}
    source_ids = list(sources_by_id)

    raw_counts = _count_rows_by_source(
        session.execute(
            select(RawItem.data_source_id, func.count(RawItem.id))
            .where(
                RawItem.data_source_id.in_(source_ids),
                RawItem.published_at.is_not(None),
                RawItem.published_at >= start_utc,
                RawItem.published_at < end_utc,
            )
            .group_by(RawItem.data_source_id),
        ).all(),
    )

    news_items = session.scalars(
        select(NewsItem).where(
            NewsItem.workspace_code == workspace.code,
            _news_day_filter(start_utc, end_utc),
        ),
    ).all()
    news_counts: dict[str, int] = defaultdict(int)
    for item in news_items:
        news_counts[item.data_source_id] += 1

    winner_counts = _count_rows_by_source(
        session.execute(
            select(NewsItem.data_source_id, func.count(DedupeGroupItem.id))
            .join(DedupeGroupItem, DedupeGroupItem.news_item_id == NewsItem.id)
            .join(DedupeGroup, DedupeGroup.id == DedupeGroupItem.dedupe_group_id)
            .where(
                DedupeGroup.workspace_code == workspace.code,
                DedupeGroup.status == "active",
                DedupeGroupItem.is_winner.is_(True),
                NewsItem.workspace_code == workspace.code,
                NewsItem.active.is_(True),
                _news_day_filter(start_utc, end_utc),
            )
            .group_by(NewsItem.data_source_id),
        ).all(),
    )

    recommendation_run = _latest_recommendation_run(session, workspace.code, resolved_day_key)
    recommendation_counts: dict[str, int] = defaultdict(int)
    recommendation_selected_counts: dict[str, int] = defaultdict(int)
    generated_ready_counts: dict[str, int] = defaultdict(int)
    if recommendation_run is not None:
        recommendation_items = session.scalars(
            select(RecommendationItem)
            .options(
                selectinload(RecommendationItem.news_item),
                selectinload(RecommendationItem.generated_news),
            )
            .where(RecommendationItem.run_id == recommendation_run.id),
        ).all()
        for item in recommendation_items:
            source_id = item.news_item.data_source_id
            recommendation_counts[source_id] += 1
            if item.selected:
                recommendation_selected_counts[source_id] += 1
            if any(generated.generation_status == "ready" for generated in item.generated_news):
                generated_ready_counts[source_id] += 1

    daily_report = session.scalar(
        select(DailyReport).where(
            DailyReport.workspace_code == workspace.code,
            DailyReport.domain_code == workspace.default_domain_code,
            DailyReport.day_key == resolved_day_key,
        ),
    )
    daily_adopted_counts: dict[str, int] = defaultdict(int)
    if daily_report is not None:
        daily_items = session.scalars(
            select(DailyReportItem)
            .options(
                selectinload(DailyReportItem.generated_news).selectinload(GeneratedNews.news_item),
            )
            .where(DailyReportItem.daily_report_id == daily_report.id),
        ).all()
        for item in daily_items:
            if item.adoption_status != 2:
                continue
            source_id = item.generated_news.news_item.data_source_id
            daily_adopted_counts[source_id] += 1

    run_sources = _run_sources_by_id(run)
    coverage_sources = []
    for source in enabled_sources:
        run_source = run_sources.get(source.id, {})
        coverage_sources.append(
            IngestionCoverageSourceRead(
                data_source_id=source.id,
                name=source.name,
                source_type=source.source_type,
                run_status=str(run_source.get("status") or "not_run"),
                error=str(run_source.get("error") or source.last_error or ""),
                run_fetched=_number(run_source.get("fetched")),
                run_created=_number(run_source.get("created")),
                run_updated=_number(run_source.get("updated")),
                in_target_range=_number(run_source.get("in_target_range")),
                out_of_target_range=_number(run_source.get("out_of_target_range")),
                missing_published_at=_number(run_source.get("missing_published_at")),
                raw_in_target=raw_counts[source.id],
                news_items=news_counts[source.id],
                dedupe_winners=winner_counts[source.id],
                recommendation_candidates=recommendation_counts[source.id],
                recommendation_selected=recommendation_selected_counts[source.id],
                generated_ready=generated_ready_counts[source.id],
                daily_adopted=daily_adopted_counts[source.id],
            ),
        )

    coverage_sources.sort(
        key=lambda source: (
            source.run_status != "failed",
            -source.daily_adopted,
            -source.recommendation_selected,
            -source.news_items,
            source.source_type,
            source.name,
        ),
    )
    target_range = _target_range(run) or resolved_day_key
    return IngestionCoverageRead(
        workspace_code=workspace.code,
        day_key=resolved_day_key,
        run_id=run.id if run else None,
        run_key=run.run_key if run else None,
        run_type=run.run_type if run else None,
        run_status=run.status if run else None,
        target_range=target_range,
        recommendation_run_id=recommendation_run.id if recommendation_run else None,
        recommendation_run_key=recommendation_run.run_key if recommendation_run else None,
        daily_report_id=daily_report.id if daily_report else None,
        daily_report_status=daily_report.status if daily_report else None,
        funnel=IngestionCoverageFunnelRead(
            enabled_sources=len(sources_by_id),
            run_sources=run.source_total if run else 0,
            source_succeeded=run.source_succeeded if run else 0,
            source_failed=run.source_failed if run else 0,
            items_fetched=run.items_fetched if run else 0,
            raw_created=run.raw_created if run else 0,
            raw_updated=run.raw_updated if run else 0,
            raw_in_target=sum(raw_counts.values()),
            news_items=sum(news_counts.values()),
            dedupe_winners=sum(winner_counts.values()),
            recommendation_candidates=sum(recommendation_counts.values()),
            recommendation_selected=sum(recommendation_selected_counts.values()),
            generated_ready=sum(generated_ready_counts.values()),
            daily_adopted=sum(daily_adopted_counts.values()),
        ),
        sources=coverage_sources,
    )


@router.get("/coverage/trends", response_model=IngestionCoverageTrendsRead)
def get_ingestion_coverage_trends(
    workspace_code: str = Query(...),
    days: int = Query(default=14, ge=1, le=90),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> IngestionCoverageTrendsRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    today = datetime.now(BEIJING_TZ).date()
    start_day = today - timedelta(days=days - 1)
    start_utc = datetime.combine(start_day, time.min, BEIJING_TZ).astimezone(UTC)
    runs = session.scalars(
        select(IngestionRun)
        .where(
            IngestionRun.workspace_code == workspace.code,
            IngestionRun.created_at >= start_utc,
        )
        .order_by(IngestionRun.created_at.asc(), IngestionRun.id.asc()),
    ).all()

    day_buckets = {
        (start_day + timedelta(days=offset)).isoformat(): {
            "run_count": 0,
            "latest_run": None,
            "source_total": 0,
            "source_succeeded": 0,
            "source_failed": 0,
            "source_skipped_unimplemented": 0,
            "items_fetched": 0,
            "raw_created": 0,
            "raw_updated": 0,
        }
        for offset in range(days)
    }
    failed_sources: dict[str, dict[str, object]] = {}

    for run in runs:
        occurred_at = _run_occurred_at(run)
        day_key = occurred_at.astimezone(BEIJING_TZ).date().isoformat()
        bucket = day_buckets.get(day_key)
        if bucket is None:
            continue
        bucket["run_count"] = int(bucket["run_count"]) + 1
        latest_run = bucket["latest_run"]
        if latest_run is None or _run_occurred_at(run) >= _run_occurred_at(latest_run):
            bucket["latest_run"] = run
        bucket["source_total"] = int(bucket["source_total"]) + int(run.source_total or 0)
        bucket["source_succeeded"] = int(bucket["source_succeeded"]) + int(run.source_succeeded or 0)
        bucket["source_failed"] = int(bucket["source_failed"]) + int(run.source_failed or 0)
        bucket["source_skipped_unimplemented"] = int(bucket["source_skipped_unimplemented"]) + _number(
            (run.summary_json or {}).get("source_skipped_unimplemented"),
        )
        bucket["items_fetched"] = int(bucket["items_fetched"]) + int(run.items_fetched or 0)
        bucket["raw_created"] = int(bucket["raw_created"]) + int(run.raw_created or 0)
        bucket["raw_updated"] = int(bucket["raw_updated"]) + int(run.raw_updated or 0)

        for source in _failed_run_sources(run):
            source_id = str(source.get("data_source_id") or "").strip()
            if not source_id:
                continue
            record = failed_sources.setdefault(
                source_id,
                {
                    "data_source_id": source_id,
                    "name": str(source.get("name") or "未命名数据源"),
                    "source_type": str(source.get("source_type") or "unknown"),
                    "failure_count": 0,
                    "last_error": "",
                    "last_run_id": run.id,
                    "last_run_key": run.run_key,
                    "last_failed_at": occurred_at,
                },
            )
            record["failure_count"] = int(record["failure_count"]) + 1
            if occurred_at >= _ensure_aware_datetime(record["last_failed_at"]):
                record["name"] = str(source.get("name") or record["name"])
                record["source_type"] = str(source.get("source_type") or record["source_type"])
                record["last_error"] = str(source.get("error") or "")
                record["last_run_id"] = run.id
                record["last_run_key"] = run.run_key
                record["last_failed_at"] = occurred_at

    points = []
    for day_key, bucket in day_buckets.items():
        source_total = int(bucket["source_total"])
        source_succeeded = int(bucket["source_succeeded"])
        latest_run = bucket["latest_run"]
        points.append(
            IngestionCoverageTrendPointRead(
                day_key=day_key,
                run_count=int(bucket["run_count"]),
                latest_run_id=latest_run.id if latest_run else None,
                latest_run_key=latest_run.run_key if latest_run else None,
                latest_run_status=latest_run.status if latest_run else None,
                source_total=source_total,
                source_succeeded=source_succeeded,
                source_failed=int(bucket["source_failed"]),
                source_skipped_unimplemented=int(bucket["source_skipped_unimplemented"]),
                items_fetched=int(bucket["items_fetched"]),
                raw_created=int(bucket["raw_created"]),
                raw_updated=int(bucket["raw_updated"]),
                success_rate=round(source_succeeded / source_total, 4) if source_total else 0.0,
            ),
        )

    total_source_total = sum(point.source_total for point in points)
    total_source_succeeded = sum(point.source_succeeded for point in points)
    return IngestionCoverageTrendsRead(
        workspace_code=workspace.code,
        days=days,
        generated_at=datetime.now(UTC),
        total_runs=sum(point.run_count for point in points),
        total_source_failed=sum(point.source_failed for point in points),
        total_raw_created=sum(point.raw_created for point in points),
        average_success_rate=round(total_source_succeeded / total_source_total, 4) if total_source_total else 0.0,
        points=points,
        top_failed_sources=[
            IngestionCoverageFailureTrendRead(
                data_source_id=str(record["data_source_id"]),
                name=str(record["name"]),
                source_type=str(record["source_type"]),
                failure_count=int(record["failure_count"]),
                last_error=str(record["last_error"]),
                last_run_id=str(record["last_run_id"]),
                last_run_key=str(record["last_run_key"]),
                last_failed_at=_ensure_aware_datetime(record["last_failed_at"]),
            )
            for record in sorted(
                failed_sources.values(),
                key=lambda item: (-int(item["failure_count"]), str(item["name"])),
            )[:10]
        ],
    )


@router.get("/failed-source-retry-summary", response_model=IngestionFailedSourceRetrySummaryRead)
def get_failed_source_retry_summary(
    workspace_code: str = Query(...),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> IngestionFailedSourceRetrySummaryRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    from app.core.config import get_settings

    summary = failed_source_retry_summary(session, get_settings(), workspace_code=workspace.code)
    return IngestionFailedSourceRetrySummaryRead(
        workspace_code=workspace.code,
        generated_at=datetime.now(UTC),
        policy=dict(summary["policy"] or {}),
        due_count=int(summary["due_count"] or 0),
        blocked_count=int(summary["blocked_count"] or 0),
        next_retry_at=summary["next_retry_at"],
        runs=[
            IngestionFailedSourceRetryRunRead(
                run_id=str(row["run_id"]),
                run_key=str(row["run_key"]),
                run_type=str(row["run_type"]),
                status=str(row["status"]),
                failed_source_count=int(row["failed_source_count"] or 0),
                attempt_count=int(row["attempt_count"] or 0),
                last_attempt_at=row["last_attempt_at"],
                next_retry_at=row["next_retry_at"],
                blocked=bool(row["blocked"]),
                due=bool(row["due"]),
                latest_retry_run_id=row.get("latest_retry_run_id"),
                latest_retry_run_key=row.get("latest_retry_run_key"),
                latest_retry_status=row.get("latest_retry_status"),
            )
            for row in summary["runs"]
        ],
    )


def _run_to_read(run: IngestionRun) -> IngestionRunRead:
    return IngestionRunRead(
        id=run.id,
        run_key=run.run_key,
        workspace_code=run.workspace_code,
        domain_code=run.domain_code,
        run_type=run.run_type,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        source_total=run.source_total,
        source_succeeded=run.source_succeeded,
        source_failed=run.source_failed,
        items_fetched=run.items_fetched,
        raw_created=run.raw_created,
        raw_updated=run.raw_updated,
        params_json=run.params_json or {},
        summary_json=run.summary_json or {},
    )


def _failed_run_source_ids(run: IngestionRun) -> list[str]:
    source_ids: list[str] = []
    for source in _failed_run_sources(run):
        source_id = str(source.get("data_source_id") or "").strip()
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _failed_run_sources(run: IngestionRun) -> list[dict[str, object]]:
    sources = (run.summary_json or {}).get("sources")
    if not isinstance(sources, list):
        return []
    failed_sources: list[dict[str, object]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        if source.get("status") != "failed":
            continue
        failed_sources.append(source)
    return failed_sources


def _retryable_failed_sources(
    session: Session,
    *,
    workspace_code: str,
    failed_source_ids: list[str],
) -> list[DataSource]:
    sources = session.scalars(
        select(DataSource)
        .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
        .join(Workspace, Workspace.id == WorkspaceSourceLink.workspace_id)
        .where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
            WorkspaceSourceLink.enabled.is_(True),
            DataSource.enabled.is_(True),
            DataSource.id.in_(failed_source_ids),
        ),
    ).all()
    sources_by_id = {source.id: source for source in sources}
    return [sources_by_id[source_id] for source_id in failed_source_ids if source_id in sources_by_id]


def _unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _coverage_run(
    session: Session,
    *,
    workspace_code: str,
    run_id: str | None,
) -> IngestionRun | None:
    if run_id:
        run = session.get(IngestionRun, run_id)
        if run is None or run.workspace_code != workspace_code:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found")
        return run
    return session.scalar(
        select(IngestionRun)
        .where(IngestionRun.workspace_code == workspace_code)
        .order_by(desc(IngestionRun.created_at), desc(IngestionRun.id))
        .limit(1),
    )


def _enabled_sources(session: Session, workspace: Workspace) -> list[DataSource]:
    return list(
        session.scalars(
            select(DataSource)
            .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
            .where(
                WorkspaceSourceLink.workspace_id == workspace.id,
                WorkspaceSourceLink.enabled.is_(True),
                DataSource.enabled.is_(True),
            )
            .order_by(DataSource.source_type, DataSource.name),
        ).all(),
    )


def _latest_recommendation_run(
    session: Session,
    workspace_code: str,
    day_key: str,
) -> RecommendationRun | None:
    runs = session.scalars(
        select(RecommendationRun)
        .where(RecommendationRun.workspace_code == workspace_code)
        .order_by(desc(RecommendationRun.created_at), desc(RecommendationRun.id))
        .limit(100),
    ).all()
    for run in runs:
        if (run.params_json or {}).get("day_key") == day_key:
            return run
    return None


def _day_bounds(day_key: str) -> tuple[datetime, datetime]:
    parsed = date.fromisoformat(day_key)
    start = datetime.combine(parsed, time.min, BEIJING_TZ).astimezone(UTC)
    end = datetime.combine(parsed + timedelta(days=1), time.min, BEIJING_TZ).astimezone(UTC)
    return start, end


def _today_key() -> str:
    return datetime.now(BEIJING_TZ).date().isoformat()


def _run_occurred_at(run: IngestionRun) -> datetime:
    return _ensure_aware_datetime(run.completed_at or run.started_at or run.created_at)


def _ensure_aware_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return datetime.min.replace(tzinfo=UTC)


def _news_day_filter(start_utc: datetime, end_utc: datetime):
    return or_(
        and_(NewsItem.published_at.is_not(None), NewsItem.published_at >= start_utc, NewsItem.published_at < end_utc),
        and_(NewsItem.published_at.is_(None), NewsItem.created_at >= start_utc, NewsItem.created_at < end_utc),
    )


def _run_sources_by_id(run: IngestionRun | None) -> dict[str, dict[str, object]]:
    if run is None:
        return {}
    sources = (run.summary_json or {}).get("sources")
    if not isinstance(sources, list):
        return {}
    mapped: dict[str, dict[str, object]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("data_source_id") or "")
        if source_id:
            mapped[source_id] = source
    return mapped


def _target_range(run: IngestionRun | None) -> str:
    if run is None:
        return ""
    params = run.params_json or {}
    summary = run.summary_json or {}
    start = str(params.get("target_day_start") or summary.get("target_day_start") or "")
    end = str(params.get("target_day_end") or summary.get("target_day_end") or "")
    if start and end:
        return start if start == end else f"{start} 至 {end}"
    return ""


def _count_rows_by_source(rows: list[tuple[str, int]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for source_id, count in rows:
        counts[source_id] = int(count or 0)
    return counts


def _number(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0
