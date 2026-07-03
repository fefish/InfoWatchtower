from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.auth.service import write_audit
from app.core.database import get_db_session
from app.models.common import utc_now
from app.models.content import GeneratedNews
from app.models.feedback import Comment, EditorialAction, Rating, Reaction
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.recommendations.service import (
    DailyReportGenerationRerunRequest,
    DailyReportNotFoundError,
    regenerate_daily_report_generated_news,
)
from app.recommendations.service import (
    PublishedDailyReportError as GenerationPublishedDailyReportError,
)
from app.reports.weekly import (
    InvalidWeekKeyError,
    PublishedWeeklyReportError,
    WeeklyReportDraftRequest,
    WorkspaceNotFoundError,
    create_weekly_report_draft,
)
from app.schemas.reports import (
    CommentCreate,
    CommentRead,
    DailyReportGenerationRerunCreate,
    DailyReportGenerationRerunRead,
    DailyReportItemRead,
    DailyReportItemUpdate,
    DailyReportRead,
    GeneratedNewsRead,
    RatingCreate,
    RatingRead,
    ReactionCreate,
    WeeklyReportCreate,
    WeeklyReportItemRead,
    WeeklyReportItemUpdate,
    WeeklyReportRead,
)

router = APIRouter(prefix="/api", tags=["reports"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.get("/daily-reports", response_model=list[DailyReportRead])
def list_daily_reports(
    workspace_code: str = Query(default="planning_intel"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[DailyReportRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
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
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportRead:
    report = _load_daily_report(session, report_id)
    assert_workspace_member(session, current_user, report.workspace_code, min_role="viewer")
    return _daily_report_to_read(report)


@router.post("/daily-reports/{report_id}/publish", response_model=DailyReportRead)
def publish_daily_report(
    report_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportRead:
    report = _load_daily_report(session, report_id)
    assert_workspace_member(session, current_user, report.workspace_code, min_role="member")
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


@router.post(
    "/daily-reports/{report_id}/regenerate-generated-news",
    response_model=DailyReportGenerationRerunRead,
)
def regenerate_daily_report_news(
    report_id: str,
    payload: DailyReportGenerationRerunCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportGenerationRerunRead:
    report = _load_daily_report(session, report_id)
    assert_workspace_member(session, current_user, report.workspace_code, min_role="member")
    try:
        result = regenerate_daily_report_generated_news(
            session,
            DailyReportGenerationRerunRequest(
                report_id=report_id,
                item_ids=payload.item_ids,
                limit=payload.limit,
                replace_ready=payload.replace_ready,
                generation_timeout_seconds=payload.generation_timeout_seconds,
            ),
        )
    except DailyReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GenerationPublishedDailyReportError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    write_audit(
        session,
        current_user,
        "daily_report.regenerate_generated_news",
        "daily_report",
        report_id,
        {
            "attempted_total": result.attempted_total,
            "ready_total": result.ready_total,
            "fallback_total": result.fallback_total,
            "skipped_total": result.skipped_total,
        },
    )
    session.commit()
    return DailyReportGenerationRerunRead(
        report=_daily_report_to_read(_load_daily_report(session, report_id)),
        attempted_total=result.attempted_total,
        ready_total=result.ready_total,
        fallback_total=result.fallback_total,
        skipped_total=result.skipped_total,
    )


@router.get("/weekly-reports", response_model=list[WeeklyReportRead])
def list_weekly_reports(
    workspace_code: str = Query(default="planning_intel"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[WeeklyReportRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    reports = session.scalars(
        select(WeeklyReport)
        .options(*_weekly_report_options())
        .where(WeeklyReport.workspace_code == workspace_code)
        .order_by(WeeklyReport.week_key.desc(), WeeklyReport.created_at.desc())
        .limit(limit),
    ).all()
    return [_weekly_report_to_read(report) for report in reports]


@router.post("/weekly-reports", response_model=WeeklyReportRead)
def create_weekly_report(
    payload: WeeklyReportCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> WeeklyReportRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="member")
    try:
        report = create_weekly_report_draft(
            session,
            WeeklyReportDraftRequest(
                workspace_code=payload.workspace_code,
                week_key=payload.week_key,
                limit=payload.limit,
                include_unpublished_daily=payload.include_unpublished_daily,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidWeekKeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PublishedWeeklyReportError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    write_audit(
        session,
        current_user,
        "weekly_report.create_draft",
        "weekly_report",
        report.id,
        {"week_key": report.week_key, "workspace_code": report.workspace_code},
    )
    session.commit()
    return _weekly_report_to_read(_load_weekly_report(session, report.id))


@router.get("/weekly-reports/{report_id}", response_model=WeeklyReportRead)
def get_weekly_report(
    report_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> WeeklyReportRead:
    report = _load_weekly_report(session, report_id)
    assert_workspace_member(session, current_user, report.workspace_code, min_role="viewer")
    return _weekly_report_to_read(report)


@router.post("/weekly-reports/{report_id}/publish", response_model=WeeklyReportRead)
def publish_weekly_report(
    report_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> WeeklyReportRead:
    report = _load_weekly_report(session, report_id)
    assert_workspace_member(session, current_user, report.workspace_code, min_role="member")
    report.status = "published"
    report.published_at = utc_now()
    write_audit(
        session,
        current_user,
        "weekly_report.publish",
        "weekly_report",
        report.id,
        {"week_key": report.week_key, "workspace_code": report.workspace_code},
    )
    session.commit()
    return _weekly_report_to_read(_load_weekly_report(session, report_id))


@router.patch("/weekly-report-items/{item_id}", response_model=WeeklyReportItemRead)
def update_weekly_report_item(
    item_id: str,
    payload: WeeklyReportItemUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> WeeklyReportItemRead:
    item = _load_weekly_report_item(session, item_id)
    assert_workspace_member(session, current_user, item.weekly_report.workspace_code, min_role="member")
    before = _weekly_item_editor_snapshot(item)
    if payload.adoption_status is not None:
        item.adoption_status = payload.adoption_status
    if payload.sort_order is not None:
        item.sort_order = payload.sort_order
    if payload.editor_title is not None:
        item.editor_title = payload.editor_title
    if payload.editor_summary is not None:
        item.editor_summary = payload.editor_summary
    if payload.editor_content_json is not None:
        item.editor_content_json = payload.editor_content_json

    session.add(
        EditorialAction(
            user=current_user,
            object_type="weekly_report_item",
            object_id=item.id,
            action_type="edit",
            before_json=before,
            after_json=_weekly_item_editor_snapshot(item),
        ),
    )
    session.commit()
    return _weekly_report_item_to_read(_load_weekly_report_item(session, item.id))


@router.patch("/daily-report-items/{item_id}", response_model=DailyReportItemRead)
def update_daily_report_item(
    item_id: str,
    payload: DailyReportItemUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportItemRead:
    item = _load_daily_report_item(session, item_id)
    assert_workspace_member(session, current_user, item.daily_report.workspace_code, min_role="member")
    before = _item_editor_snapshot(item)
    if payload.adoption_status is not None:
        item.adoption_status = payload.adoption_status
    if payload.is_headline is not None:
        item.is_headline = payload.is_headline
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
    assert_workspace_member(session, current_user, item.daily_report.workspace_code, min_role="member")
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
    assert_workspace_member(session, current_user, item.daily_report.workspace_code, min_role="member")
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
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[CommentRead]:
    item = _load_daily_report_item(session, item_id)
    assert_workspace_member(session, current_user, item.daily_report.workspace_code, min_role="viewer")
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
    assert_workspace_member(session, current_user, item.daily_report.workspace_code, min_role="member")
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


def _weekly_report_options():
    return (
        selectinload(WeeklyReport.items)
        .selectinload(WeeklyReportItem.generated_news)
        .selectinload(GeneratedNews.recommendation_item),
        selectinload(WeeklyReport.items)
        .selectinload(WeeklyReportItem.daily_report_item)
        .selectinload(DailyReportItem.daily_report),
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


def _load_weekly_report(session: Session, report_id: str) -> WeeklyReport:
    report = session.scalar(
        select(WeeklyReport)
        .options(*_weekly_report_options())
        .where(WeeklyReport.id == report_id),
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly report not found")
    return report


def _load_daily_report_item(session: Session, item_id: str) -> DailyReportItem:
    item = session.scalar(
        select(DailyReportItem)
        .options(
            selectinload(DailyReportItem.daily_report),
            selectinload(DailyReportItem.generated_news).selectinload(GeneratedNews.news_item),
        )
        .where(DailyReportItem.id == item_id),
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Daily report item not found",
        )
    return item


def _load_weekly_report_item(session: Session, item_id: str) -> WeeklyReportItem:
    item = session.scalar(
        select(WeeklyReportItem)
        .options(
            selectinload(WeeklyReportItem.weekly_report),
            selectinload(WeeklyReportItem.generated_news).selectinload(
                GeneratedNews.recommendation_item,
            ),
            selectinload(WeeklyReportItem.daily_report_item).selectinload(
                DailyReportItem.daily_report,
            ),
        )
        .where(WeeklyReportItem.id == item_id),
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Weekly report item not found",
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


def _weekly_report_to_read(report: WeeklyReport) -> WeeklyReportRead:
    return WeeklyReportRead(
        id=report.id,
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        week_key=report.week_key,
        title=report.title,
        summary=report.summary,
        status=report.status,
        published_at=report.published_at,
        items=[
            _weekly_report_item_to_read(item)
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
        is_headline=bool(item.is_headline),
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


def _weekly_report_item_to_read(item: WeeklyReportItem) -> WeeklyReportItemRead:
    daily_report_item = item.daily_report_item
    return WeeklyReportItemRead(
        id=item.id,
        daily_report_item_id=item.daily_report_item_id,
        daily_day_key=(
            daily_report_item.daily_report.day_key
            if daily_report_item and daily_report_item.daily_report
            else None
        ),
        generated_news=(
            _generated_news_to_read(item.generated_news) if item.generated_news else None
        ),
        adoption_status=item.adoption_status,
        sort_order=item.sort_order,
        editor_title=item.editor_title,
        editor_summary=item.editor_summary,
        editor_content_json=item.editor_content_json,
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


def _weekly_item_editor_snapshot(item: WeeklyReportItem) -> dict:
    return {
        "adoption_status": item.adoption_status,
        "sort_order": item.sort_order,
        "editor_title": item.editor_title,
        "editor_summary": item.editor_summary,
        "editor_content_json": item.editor_content_json,
    }
