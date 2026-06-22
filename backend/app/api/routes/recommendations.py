from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.database import get_db_session
from app.models.content import NewsItem, RecommendationItem, RecommendationRun
from app.models.identity import User
from app.recommendations.service import (
    PublishedDailyReportError,
    RecommendationRunRequest,
    WorkspaceNotFoundError,
    run_daily_recommendation,
)
from app.schemas.recommendations import (
    RecommendationItemRead,
    RecommendationRunCreate,
    RecommendationRunCreateRead,
    RecommendationRunRead,
)

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.post("/runs", response_model=RecommendationRunCreateRead)
def create_recommendation_run(
    payload: RecommendationRunCreate,
    _: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> RecommendationRunCreateRead:
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
        run=_run_to_read(run),
        daily_report_id=result.daily_report.id if result.daily_report else None,
        candidates_total=result.candidates_total,
        selected_total=result.selected_total,
        generated_total=result.generated_total,
    )


@router.get("/runs", response_model=list[RecommendationRunRead])
def list_recommendation_runs(
    workspace_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[RecommendationRunRead]:
    statement = select(RecommendationRun).order_by(RecommendationRun.created_at.desc()).limit(limit)
    if workspace_code:
        statement = statement.where(RecommendationRun.workspace_code == workspace_code)
    runs = session.scalars(statement).all()
    return [_run_to_read(run, include_items=False) for run in runs]


@router.get("/runs/{run_id}", response_model=RecommendationRunRead)
def get_recommendation_run(
    run_id: str,
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RecommendationRunRead:
    return _run_to_read(_load_run(session, run_id))


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


def _run_to_read(run: RecommendationRun, include_items: bool = True) -> RecommendationRunRead:
    items = sorted(run.items, key=lambda item: item.rank) if include_items else []
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
            )
            for item in items
        ],
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
