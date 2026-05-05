from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import get_current_user, require_super_admin
from app.auth.service import write_audit
from app.core.database import get_db_session
from app.models.common import utc_now
from app.models.content import GeneratedNews
from app.models.feedback import Comment, EditorialAction, Rating, Reaction
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.schemas.reports import (
    CommentCreate,
    CommentRead,
    DailyReportItemRead,
    DailyReportItemUpdate,
    DailyReportRead,
    GeneratedNewsRead,
    RatingCreate,
    RatingRead,
    ReactionCreate,
)

router = APIRouter(prefix="/api", tags=["reports"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.get("/daily-reports", response_model=list[DailyReportRead])
def list_daily_reports(
    workspace_code: str = Query(default="planning_intel"),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[DailyReportRead]:
    reports = session.scalars(
        select(DailyReport)
        .options(_daily_report_options())
        .where(DailyReport.workspace_code == workspace_code)
        .order_by(DailyReport.day_key.desc(), DailyReport.created_at.desc())
        .limit(limit),
    ).all()
    return [_daily_report_to_read(report) for report in reports]


@router.get("/daily-reports/{report_id}", response_model=DailyReportRead)
def get_daily_report(
    report_id: str,
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportRead:
    return _daily_report_to_read(_load_daily_report(session, report_id))


@router.post("/daily-reports/{report_id}/publish", response_model=DailyReportRead)
def publish_daily_report(
    report_id: str,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> DailyReportRead:
    report = _load_daily_report(session, report_id)
    report.status = "published"
    report.published_at = utc_now()
    write_audit(
        session,
        current_user,
        "daily_report.publish",
        "daily_report",
        report.id,
        {"day_key": report.day_key, "workspace_code": report.workspace_code},
    )
    session.commit()
    return _daily_report_to_read(_load_daily_report(session, report_id))


@router.patch("/daily-report-items/{item_id}", response_model=DailyReportItemRead)
def update_daily_report_item(
    item_id: str,
    payload: DailyReportItemUpdate,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> DailyReportItemRead:
    item = _load_daily_report_item(session, item_id)
    before = _item_editor_snapshot(item)
    if payload.adoption_status is not None:
        item.adoption_status = payload.adoption_status
    if payload.sort_order is not None:
        item.sort_order = payload.sort_order
    if payload.editor_title is not None:
        item.editor_title = payload.editor_title
    if payload.editor_summary is not None:
        item.editor_summary = payload.editor_summary
    if payload.editor_key_points is not None:
        item.editor_key_points = payload.editor_key_points
    if payload.editor_content_json is not None:
        item.editor_content_json = payload.editor_content_json
    if payload.editor_notes is not None:
        item.editor_notes = payload.editor_notes

    session.add(
        EditorialAction(
            user=current_user,
            object_type="daily_report_item",
            object_id=item.id,
            action_type="edit",
            before_json=before,
            after_json=_item_editor_snapshot(item),
        ),
    )
    session.commit()
    return _daily_report_item_to_read(_load_daily_report_item(session, item.id))


@router.post("/daily-report-items/{item_id}/reactions")
def react_to_daily_report_item(
    item_id: str,
    payload: ReactionCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> dict[str, str | bool]:
    item = _load_daily_report_item(session, item_id)
    reaction = session.scalar(
        select(Reaction).where(
            Reaction.user_id == current_user.id,
            Reaction.daily_report_item_id == item.id,
            Reaction.reaction_type == payload.reaction_type,
        ),
    )
    if reaction is None:
        reaction = Reaction(
            user=current_user,
            daily_report_item=item,
            news_item=item.generated_news.news_item,
            reaction_type=payload.reaction_type,
        )
        session.add(reaction)
    reaction.active = payload.active
    session.commit()
    return {"id": reaction.id, "active": reaction.active}


@router.post("/daily-report-items/{item_id}/ratings", response_model=RatingRead)
def rate_daily_report_item(
    item_id: str,
    payload: RatingCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RatingRead:
    item = _load_daily_report_item(session, item_id)
    rating = session.scalar(
        select(Rating).where(
            Rating.user_id == current_user.id,
            Rating.daily_report_item_id == item.id,
            Rating.dimension == payload.dimension,
        ),
    )
    if rating is None:
        rating = Rating(
            user=current_user,
            daily_report_item=item,
            news_item=item.generated_news.news_item,
            dimension=payload.dimension,
            score=payload.score,
            comment=payload.comment,
        )
        session.add(rating)
    else:
        rating.score = payload.score
        rating.comment = payload.comment
    session.commit()
    return RatingRead(
        id=rating.id,
        dimension=rating.dimension,
        score=rating.score,
        comment=rating.comment,
    )


@router.get("/daily-report-items/{item_id}/comments", response_model=list[CommentRead])
def list_daily_report_item_comments(
    item_id: str,
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[CommentRead]:
    _load_daily_report_item(session, item_id)
    comments = session.scalars(
        select(Comment)
        .where(
            Comment.daily_report_item_id == item_id,
            Comment.status == "visible",
        )
        .order_by(Comment.created_at, Comment.id),
    ).all()
    return [_comment_to_read(comment) for comment in comments]


@router.post("/daily-report-items/{item_id}/comments", response_model=CommentRead)
def create_daily_report_item_comment(
    item_id: str,
    payload: CommentCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> CommentRead:
    item = _load_daily_report_item(session, item_id)
    parent = None
    if payload.parent_id:
        parent = session.get(Comment, payload.parent_id)
        if parent is None or parent.daily_report_item_id != item.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent comment not found",
            )
    comment = Comment(
        user=current_user,
        daily_report_item=item,
        news_item=item.generated_news.news_item,
        parent=parent,
        root=parent.root if parent and parent.root else parent,
        body=payload.body,
    )
    session.add(comment)
    session.commit()
    return _comment_to_read(comment)


def _daily_report_options():
    return (
        selectinload(DailyReport.items)
        .selectinload(DailyReportItem.generated_news)
        .selectinload(GeneratedNews.recommendation_item)
    )


def _load_daily_report(session: Session, report_id: str) -> DailyReport:
    report = session.scalar(
        select(DailyReport)
        .options(_daily_report_options())
        .where(DailyReport.id == report_id),
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")
    return report


def _load_daily_report_item(session: Session, item_id: str) -> DailyReportItem:
    item = session.scalar(
        select(DailyReportItem)
        .options(selectinload(DailyReportItem.generated_news).selectinload(GeneratedNews.news_item))
        .where(DailyReportItem.id == item_id),
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Daily report item not found",
        )
    return item


def _daily_report_to_read(report: DailyReport) -> DailyReportRead:
    return DailyReportRead(
        id=report.id,
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        day_key=report.day_key,
        title=report.title,
        summary=report.summary,
        status=report.status,
        published_at=report.published_at,
        items=[
            _daily_report_item_to_read(item)
            for item in sorted(
                report.items,
                key=lambda item: (item.sort_order, item.created_at, item.id),
            )
        ],
    )


def _daily_report_item_to_read(item: DailyReportItem) -> DailyReportItemRead:
    ratings = item.ratings or []
    rating_avg = sum(rating.score for rating in ratings) / len(ratings) if ratings else 0.0
    return DailyReportItemRead(
        id=item.id,
        generated_news=_generated_news_to_read(item.generated_news),
        adoption_status=item.adoption_status,
        sort_order=item.sort_order,
        editor_title=item.editor_title,
        editor_summary=item.editor_summary,
        editor_key_points=item.editor_key_points,
        editor_content_json=item.editor_content_json,
        editor_notes=item.editor_notes,
        reaction_count=sum(1 for reaction in item.reactions if reaction.active),
        rating_count=len(ratings),
        rating_avg=round(rating_avg, 2),
        comment_count=sum(1 for comment in item.comments if comment.status == "visible"),
    )


def _generated_news_to_read(item: GeneratedNews) -> GeneratedNewsRead:
    return GeneratedNewsRead(
        id=item.id,
        category=item.category,
        title=item.title,
        summary=item.summary,
        key_points=item.key_points,
        content_json=item.content_json or {},
        source_url=item.source_url,
        generation_status=item.generation_status,
        news_item_id=item.news_item_id,
        recommendation_item_id=item.recommendation_item_id,
    )


def _comment_to_read(comment: Comment) -> CommentRead:
    return CommentRead(
        id=comment.id,
        user_id=comment.user_id,
        body=comment.body,
        status=comment.status,
        parent_id=comment.parent_id,
        root_id=comment.root_id,
        created_at=comment.created_at,
    )


def _item_editor_snapshot(item: DailyReportItem) -> dict:
    return {
        "adoption_status": item.adoption_status,
        "sort_order": item.sort_order,
        "editor_title": item.editor_title,
        "editor_summary": item.editor_summary,
        "editor_key_points": item.editor_key_points,
        "editor_content_json": item.editor_content_json,
        "editor_notes": item.editor_notes,
    }
