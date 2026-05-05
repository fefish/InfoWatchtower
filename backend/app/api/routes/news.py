from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import get_current_user, require_super_admin
from app.core.database import get_db_session
from app.models.content import DedupeGroup, DedupeGroupItem, NewsItem
from app.models.identity import User
from app.normalization.news import (
    NewsNormalizationRequest,
    WorkspaceNotFoundError,
    normalize_workspace_raw_items,
)
from app.schemas.news import (
    DedupeGroupItemRead,
    DedupeGroupRead,
    NewsItemRead,
    NewsNormalizeCreate,
    NewsNormalizeRead,
)

router = APIRouter(prefix="/api", tags=["news"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.post("/news-items/normalize", response_model=NewsNormalizeRead)
def normalize_news_items(
    payload: NewsNormalizeCreate,
    _: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> NewsNormalizeRead:
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
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[NewsItemRead]:
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
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[DedupeGroupRead]:
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
    return [_dedupe_group_to_read(group) for group in groups]


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


def _dedupe_group_to_read(group: DedupeGroup) -> DedupeGroupRead:
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
    )
