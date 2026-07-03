from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user
from app.core.database import get_db_session
from app.models.content import (
    DedupeGroup,
    DedupeGroupItem,
    GeneratedNews,
    NewsItem,
    RecommendationItem,
    RecommendationRun,
)
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.normalization.news import (
    NewsNormalizationRequest,
    WorkspaceNotFoundError,
    normalize_workspace_raw_items,
)
from app.schemas.news import (
    DedupeGroupDailyReportRead,
    DedupeGroupItemRead,
    DedupeGroupRead,
    DedupeGroupRecommendationRead,
    NewsItemRead,
    NewsNormalizeCreate,
    NewsNormalizeRead,
)

router = APIRouter(prefix="/api", tags=["news"])
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.post("/news-items/normalize", response_model=NewsNormalizeRead)
def normalize_news_items(
    payload: NewsNormalizeCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> NewsNormalizeRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        result = normalize_workspace_raw_items(
            session,
            NewsNormalizationRequest(
                workspace_code=payload.workspace_code,
                source_types=payload.source_types,
                limit=payload.limit,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    session.commit()
    return NewsNormalizeRead(**result.__dict__)


@router.get("/news-items", response_model=list[NewsItemRead])
def list_news_items(
    workspace_code: str = Query(default="planning_intel"),
    active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[NewsItemRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    statement = (
        select(NewsItem)
        .where(NewsItem.workspace_code == workspace_code)
        .order_by(NewsItem.published_at.desc(), NewsItem.created_at.desc(), NewsItem.id)
        .limit(limit)
    )
    if active is not None:
        statement = statement.where(NewsItem.active.is_(active))
    return [_news_to_read(item) for item in session.scalars(statement).all()]


@router.get("/dedupe-groups", response_model=list[DedupeGroupRead])
def list_dedupe_groups(
    workspace_code: str = Query(default="planning_intel"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[DedupeGroupRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    groups = session.scalars(
        select(DedupeGroup)
        .options(
            selectinload(DedupeGroup.winner_news_item),
            selectinload(DedupeGroup.items).selectinload(DedupeGroupItem.news_item),
        )
        .where(DedupeGroup.workspace_code == workspace_code)
        .order_by(DedupeGroup.updated_at.desc(), DedupeGroup.id)
        .limit(limit),
    ).all()
    return [_dedupe_group_to_read(session, group) for group in groups]


def _news_to_read(item: NewsItem) -> NewsItemRead:
    return NewsItemRead(
        id=item.id,
        workspace_code=item.workspace_code,
        domain_code=item.domain_code,
        raw_item_id=item.raw_item_id,
        data_source_id=item.data_source_id,
        source_type=item.source_type,
        source_name=item.source_name,
        source_url=item.source_url,
        canonical_url=item.canonical_url,
        source_title=item.source_title,
        normalized_title=item.normalized_title,
        summary=item.summary,
        author=item.author,
        published_at=item.published_at,
        focus_id=item.focus_id,
        dedupe_key=item.dedupe_key,
        active=item.active,
        duplicate_of_id=item.duplicate_of_id,
        normalization_status=item.normalization_status,
        normalization_notes=item.normalization_notes,
    )


def _dedupe_group_to_read(session: Session, group: DedupeGroup) -> DedupeGroupRead:
    winner = group.winner_news_item
    items = sorted(group.items, key=lambda item: (not item.is_winner, -item.rank_score, item.id))
    return DedupeGroupRead(
        id=group.id,
        workspace_code=group.workspace_code,
        domain_code=group.domain_code,
        dedupe_key=group.dedupe_key,
        winner_news_item_id=group.winner_news_item_id,
        winner_title=winner.source_title if winner else None,
        item_count=group.item_count,
        status=group.status,
        items=[
            DedupeGroupItemRead(
                id=item.id,
                news_item_id=item.news_item_id,
                is_winner=item.is_winner,
                duplicate_reason=item.duplicate_reason,
                rank_score=item.rank_score,
                title=item.news_item.source_title,
                source_name=item.news_item.source_name,
                source_url=item.news_item.source_url,
            )
            for item in items
        ],
        recommendation=_recommendation_trace(session, group.winner_news_item_id),
        daily_report=_daily_report_trace(session, group.winner_news_item_id),
    )


def _recommendation_trace(
    session: Session,
    news_item_id: str | None,
) -> DedupeGroupRecommendationRead | None:
    if not news_item_id:
        return None
    item = session.scalar(
        select(RecommendationItem)
        .join(RecommendationRun)
        .options(selectinload(RecommendationItem.run))
        .where(RecommendationItem.news_item_id == news_item_id)
        .order_by(desc(RecommendationRun.created_at), RecommendationItem.rank)
        .limit(1),
    )
    if item is None:
        return None
    day_key = (item.run.params_json or {}).get("day_key")
    return DedupeGroupRecommendationRead(
        run_id=item.run_id,
        run_key=item.run.run_key,
        day_key=str(day_key) if day_key else None,
        recommendation_item_id=item.id,
        rank=item.rank,
        selected=item.selected,
        final_score=item.final_score,
        quality_score=item.quality_score,
        topic_score=item.topic_score,
        freshness_score=item.freshness_score,
        feedback_score=item.feedback_score,
        diversity_score=item.diversity_score,
        source_score=item.source_score,
        heat_score=item.heat_score,
        recommendation_reason=item.recommendation_reason,
        admission_level=item.admission_level,
        admission_score=item.admission_score,
        admission_pool=item.admission_pool,
        noise_types=_string_list(item.noise_types_json),
        reject_reasons=_string_list(item.reject_reasons_json),
        scorer_breakdown=dict(item.scorer_breakdown_json or {}),
        expert_routes=_string_list(item.expert_routes_json),
    )


def _daily_report_trace(
    session: Session,
    news_item_id: str | None,
) -> DedupeGroupDailyReportRead | None:
    if not news_item_id:
        return None
    item = session.scalar(
        select(DailyReportItem)
        .join(GeneratedNews, GeneratedNews.id == DailyReportItem.generated_news_id)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .options(
            selectinload(DailyReportItem.daily_report),
            selectinload(DailyReportItem.generated_news),
        )
        .where(GeneratedNews.news_item_id == news_item_id)
        .order_by(desc(DailyReport.day_key), desc(DailyReportItem.created_at))
        .limit(1),
    )
    if item is None:
        return None
    return DedupeGroupDailyReportRead(
        daily_report_id=item.daily_report_id,
        daily_report_item_id=item.id,
        day_key=item.daily_report.day_key,
        report_status=item.daily_report.status,
        adoption_status=item.adoption_status,
        generated_news_id=item.generated_news_id,
        generation_status=item.generated_news.generation_status,
        category=item.generated_news.category,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
