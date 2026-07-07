from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.core.config import get_settings
from app.core.database import get_db_session
from app.models.content import GeneratedNews, NewsItem, RecommendationItem, RecommendationRun
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.recommendations.service import (
    ContentAdmissionPreviewRequest,
    PublishedDailyReportError,
    RecommendationRunRequest,
    WorkspaceNotFoundError,
    preview_content_admission,
    run_daily_recommendation,
)
from app.scoring.content_scorer import build_content_scorer_policy_summary
from app.schemas.recommendations import (
    RecommendationItemDailyReportRead,
    RecommendationItemRead,
    RecommendationRunCreate,
    RecommendationRunCreateRead,
    RecommendationRunRead,
    ScorerPreviewCreate,
    ScorerPreviewRead,
    ScorerPolicyRead,
)

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.get("/scorer-policy", response_model=ScorerPolicyRead)
def get_scorer_policy(
    workspace_code: str = Query(...),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ScorerPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    summary = build_content_scorer_policy_summary(get_settings().content_scorer_config_path)
    return ScorerPolicyRead(workspace_code=workspace_code, **summary)


@router.post("/scorer-preview", response_model=ScorerPreviewRead)
def preview_scorer(
    payload: ScorerPreviewCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ScorerPreviewRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        result = preview_content_admission(
            session,
            ContentAdmissionPreviewRequest(
                workspace_code=payload.workspace_code,
                source_title=payload.source_title.strip(),
                summary=payload.summary,
                content=payload.content,
                source_type=payload.source_type,
                source_name=payload.source_name,
                source_url=payload.source_url,
                source_tier=payload.source_tier,
                source_channel_type=payload.source_channel_type,
                source_score=payload.source_score,
                source_tags=tuple(payload.source_tags),
                source_secondary_tags=tuple(payload.source_secondary_tags),
                board_relevance_json=payload.board_relevance_json,
                freshness_score=payload.freshness_score,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    admission = result.admission
    return ScorerPreviewRead(
        workspace_code=result.workspace_code,
        source_title=result.source_title,
        admission_level=admission.level,
        admission_score=admission.score,
        admission_pool=admission.pool,
        eligible_for_daily=admission.eligible_for_daily,
        noise_types=list(admission.noise_types),
        reject_reasons=list(admission.reject_reasons),
        positive_reasons=list(admission.positive_reasons),
        expert_routes=list(admission.expert_routes),
        scorer_breakdown=admission.scorer_breakdown,
    )


@router.post("/runs", response_model=RecommendationRunCreateRead)
def create_recommendation_run(
    payload: RecommendationRunCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RecommendationRunCreateRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        result = run_daily_recommendation(
            session,
            RecommendationRunRequest(
                workspace_code=payload.workspace_code,
                day_key=payload.day_key,
                limit=payload.limit,
                source_daily_limit=payload.source_daily_limit,
                create_daily_draft=payload.create_daily_draft,
                generation_timeout_seconds=payload.generation_timeout_seconds,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PublishedDailyReportError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    session.commit()
    run = _load_run(session, result.run.id)
    return RecommendationRunCreateRead(
        run=_run_to_read(run, session),
        daily_report_id=result.daily_report.id if result.daily_report else None,
        candidates_total=result.candidates_total,
        selected_total=result.selected_total,
        generated_total=result.generated_total,
    )


@router.get("/runs", response_model=list[RecommendationRunRead])
def list_recommendation_runs(
    workspace_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[RecommendationRunRead]:
    if workspace_code:
        assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    else:
        require_super_admin(current_user)
    statement = select(RecommendationRun).order_by(RecommendationRun.created_at.desc()).limit(limit)
    if workspace_code:
        statement = statement.where(RecommendationRun.workspace_code == workspace_code)
    runs = session.scalars(statement).all()
    return [_run_to_read(run, session, include_items=False) for run in runs]


@router.get("/runs/{run_id}", response_model=RecommendationRunRead)
def get_recommendation_run(
    run_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RecommendationRunRead:
    run = _load_run(session, run_id)
    assert_workspace_member(session, current_user, run.workspace_code, min_role="viewer")
    return _run_to_read(run, session)


def _load_run(session: Session, run_id: str) -> RecommendationRun:
    run = session.scalar(
        select(RecommendationRun)
        .options(
            selectinload(RecommendationRun.items)
            .selectinload(RecommendationItem.news_item)
            .selectinload(NewsItem.raw_item),
        )
        .where(RecommendationRun.id == run_id),
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation run not found",
        )
    return run


def _run_to_read(run: RecommendationRun, session: Session, include_items: bool = True) -> RecommendationRunRead:
    items = sorted(run.items, key=lambda item: item.rank) if include_items else []
    daily_report_by_item = _daily_report_trace_for_items(session, [item.id for item in items])
    return RecommendationRunRead(
        id=run.id,
        run_key=run.run_key,
        workspace_code=run.workspace_code,
        domain_code=run.domain_code,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        params_json=run.params_json or {},
        summary_json=run.summary_json or {},
        items=[
            RecommendationItemRead(
                id=item.id,
                news_item_id=item.news_item_id,
                dedupe_group_id=item.dedupe_group_id,
                rank=item.rank,
                quality_score=item.quality_score,
                topic_score=item.topic_score,
                freshness_score=item.freshness_score,
                feedback_score=item.feedback_score,
                diversity_score=item.diversity_score,
                source_score=item.source_score,
                heat_score=item.heat_score,
                final_score=item.final_score,
                selected=item.selected,
                recommendation_reason=item.recommendation_reason,
                admission_level=item.admission_level,
                admission_score=item.admission_score,
                admission_pool=item.admission_pool,
                noise_types=_string_list(item.noise_types_json),
                reject_reasons=_string_list(item.reject_reasons_json),
                scorer_breakdown=dict(item.scorer_breakdown_json or {}),
                expert_routes=_string_list(item.expert_routes_json),
                source_title=item.news_item.source_title,
                source_name=item.news_item.source_name,
                source_url=item.news_item.source_url,
                daily_report=daily_report_by_item.get(item.id),
            )
            for item in items
        ],
    )


def _daily_report_trace_for_items(
    session: Session,
    recommendation_item_ids: list[str],
) -> dict[str, RecommendationItemDailyReportRead]:
    if not recommendation_item_ids:
        return {}
    rows = session.execute(
        select(
            GeneratedNews.recommendation_item_id,
            GeneratedNews.id.label("generated_news_id"),
            GeneratedNews.generation_status,
            DailyReport.id.label("daily_report_id"),
            DailyReportItem.id.label("daily_report_item_id"),
            DailyReport.day_key,
            DailyReport.status.label("report_status"),
            DailyReportItem.adoption_status,
        )
        .join(DailyReportItem, DailyReportItem.generated_news_id == GeneratedNews.id)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .where(GeneratedNews.recommendation_item_id.in_(recommendation_item_ids))
        .order_by(desc(DailyReport.day_key), desc(DailyReportItem.updated_at)),
    ).all()
    traces: dict[str, RecommendationItemDailyReportRead] = {}
    for row in rows:
        if row.recommendation_item_id in traces:
            continue
        traces[row.recommendation_item_id] = RecommendationItemDailyReportRead(
            daily_report_id=row.daily_report_id,
            daily_report_item_id=row.daily_report_item_id,
            day_key=row.day_key,
            report_status=row.report_status,
            adoption_status=row.adoption_status,
            generated_news_id=row.generated_news_id,
            generation_status=row.generation_status,
        )
    return traces


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
