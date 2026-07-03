from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.core.database import get_db_session
from app.ingestion.runs import (
    HistoricalBackfillRequest,
    InvalidBackfillRangeError,
    WorkspaceIngestionRequest,
    WorkspaceNotFoundError,
    run_historical_backfill,
    run_workspace_ingestion,
)
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
    IngestionRunCreate,
    IngestionRunRead,
)

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@router.post("/runs", response_model=IngestionRunRead)
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


@router.post("/backfill-runs", response_model=IngestionRunRead)
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


@router.get("/coverage", response_model=IngestionCoverageRead)
def get_ingestion_coverage(
    workspace_code: str = Query(default="planning_intel"),
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
