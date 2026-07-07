from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.auth.service import write_audit
from app.collaboration.notifications import (
    record_comment_activity,
    record_dedupe_group_adoption_changed_activity,
    record_rating_activity,
    record_reaction_activity,
    record_weekly_report_item_updated_activity,
    record_weekly_report_publish_activity,
)
from app.core.database import get_db_session
from app.models.common import utc_now
from app.models.content import DedupeGroup, GeneratedNews, RecommendationItem, RecommendationRun
from app.models.feedback import Comment, EditorialAction, Rating, Reaction
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.models.workspace import Workspace
from app.recommendations.service import (
    DailyReportGenerationRerunRequest,
    DailyReportNotFoundError,
    _create_generated_news,
    _normalize_generation_timeout,
    regenerate_daily_report_generated_news,
)
from app.recommendations.service import (
    PublishedDailyReportError as GenerationPublishedDailyReportError,
)
from app.reports.publish import publish_daily_report as publish_daily_report_service
from app.reports.publish import rebuild_daily_report_renditions
from app.reports.weekly import (
    InvalidWeekKeyError,
    PublishedWeeklyReportError,
    WeeklyReportDraftRequest,
    WorkspaceNotFoundError,
    create_weekly_report_draft,
    refresh_weekly_report_summary,
    weekly_item_score,
)
from app.schemas.reports import (
    CommentCreate,
    CommentRead,
    DailyReportBulkAdoptCreate,
    DailyReportBulkAdoptRead,
    DailyReportBulkAdoptSkippedItem,
    DailyReportBulkRejectCreate,
    DailyReportGenerationRerunCreate,
    DailyReportGenerationRerunRead,
    DailyReportItemRead,
    DailyReportItemUpdate,
    DailyReportRead,
    DailyReportUpdate,
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
    workspace_code: str = Query(...),
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
    # 发布走共享服务：置状态 + 里程碑候选沉淀 + 审计 + renditions 投影。
    # 每日流水线自动发布（actor=system）复用同一条链路（app/reports/publish.py）。
    publish_daily_report_service(session, report, actor=current_user)
    session.commit()
    return _daily_report_to_read(_load_daily_report(session, report_id))


@router.patch("/daily-reports/{report_id}", response_model=DailyReportRead)
def update_daily_report(
    report_id: str,
    payload: DailyReportUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportRead:
    """修订日报标题/摘要。draft 允许 member+；published 收紧为 admin+ 的发布后修订。

    发布后修订只放开报告层字段：写 post_publish_revision 编辑审计并重投影
    renditions，raw/generated_news 与公司 SQL 出口不受影响。
    """
    report = _load_daily_report(session, report_id)
    published = report.status == "published"
    assert_workspace_member(
        session,
        current_user,
        report.workspace_code,
        min_role="admin" if published else "member",
    )
    before = {"title": report.title, "summary": report.summary}
    if payload.title is not None:
        report.title = payload.title.strip()
    if payload.summary is not None:
        report.summary = payload.summary.strip()
    after = {"title": report.title, "summary": report.summary}
    if before == after:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No daily report fields provided",
        )
    session.add(
        EditorialAction(
            user=current_user,
            object_type="daily_report",
            object_id=report.id,
            action_type="post_publish_revision" if published else "edit",
            before_json=before,
            after_json=after,
        ),
    )
    if published:
        rebuild_daily_report_renditions(session, report)
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


@router.post("/daily-reports/bulk-adopt-from-candidates", response_model=DailyReportBulkAdoptRead)
def bulk_adopt_daily_report_candidates(
    payload: DailyReportBulkAdoptCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportBulkAdoptRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="member")
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == payload.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    report = _load_or_create_daily_draft_for_bulk_adopt(
        session,
        workspace=workspace,
        day_key=payload.day_key,
    )
    if report.status == "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Daily report is already published",
        )

    created_total = 0
    updated_total = 0
    skipped_items: list[DailyReportBulkAdoptSkippedItem] = []
    next_sort_order = _next_daily_report_sort_order(report)
    timeout_seconds = _normalize_generation_timeout(payload.generation_timeout_seconds)
    seen_group_ids: set[str] = set()
    for group_id in payload.dedupe_group_ids:
        if group_id in seen_group_ids:
            continue
        seen_group_ids.add(group_id)
        group = _load_workspace_dedupe_group(session, payload.workspace_code, group_id)
        if group is None or group.winner_news_item_id is None:
            skipped_items.append(
                DailyReportBulkAdoptSkippedItem(
                    dedupe_group_id=group_id,
                    reason="missing_winner",
                ),
            )
            continue
        recommendation_item = _latest_recommendation_item_for_news(
            session,
            workspace_code=payload.workspace_code,
            news_item_id=group.winner_news_item_id,
        )
        if recommendation_item is None:
            skipped_items.append(
                DailyReportBulkAdoptSkippedItem(
                    dedupe_group_id=group_id,
                    reason="missing_recommendation",
                ),
            )
            continue
        generated = _latest_generated_news_for_recommendation(session, recommendation_item.id)
        if generated is None:
            generated = _create_generated_news(
                session,
                workspace,
                recommendation_item,
                generation_timeout_seconds=timeout_seconds,
            )
            session.flush()

        existing = _daily_report_item_for_generated_news(session, report.id, generated.id)
        changed_item: DailyReportItem | None = None
        if existing is None:
            changed_item = DailyReportItem(
                daily_report=report,
                generated_news=generated,
                workspace_code=workspace.code,
                domain_code=generated.domain_code,
                visibility_scope=generated.visibility_scope,
                sync_policy=generated.sync_policy,
                adoption_status=2,
                sort_order=next_sort_order,
            )
            session.add(changed_item)
            created_total += 1
            next_sort_order += 1
        elif existing.adoption_status != 2:
            existing.adoption_status = 2
            changed_item = existing
            updated_total += 1
        if changed_item is not None:
            session.flush()
            record_dedupe_group_adoption_changed_activity(
                session,
                actor=current_user,
                group=group,
                daily_report_item=changed_item,
                action_type="bulk_adopt_from_candidates",
            )

    session.add(
        EditorialAction(
            user=current_user,
            object_type="daily_report",
            object_id=report.id,
            action_type="bulk_adopt_from_candidates",
            after_json={
                "workspace_code": payload.workspace_code,
                "day_key": payload.day_key,
                "dedupe_group_ids": list(seen_group_ids),
                "created_total": created_total,
                "updated_total": updated_total,
                "skipped_total": len(skipped_items),
            },
        ),
    )
    session.commit()
    return DailyReportBulkAdoptRead(
        report=_daily_report_to_read(_load_daily_report(session, report.id)),
        created_total=created_total,
        updated_total=updated_total,
        skipped_total=len(skipped_items),
        skipped_items=skipped_items,
    )


@router.post("/daily-reports/bulk-reject-from-candidates", response_model=DailyReportBulkAdoptRead)
def bulk_reject_daily_report_candidates(
    payload: DailyReportBulkRejectCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportBulkAdoptRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="member")
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == payload.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    report = _load_or_create_daily_draft_for_bulk_adopt(
        session,
        workspace=workspace,
        day_key=payload.day_key,
    )
    if report.status == "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Daily report is already published",
        )

    created_total = 0
    updated_total = 0
    skipped_items: list[DailyReportBulkAdoptSkippedItem] = []
    next_sort_order = _next_daily_report_sort_order(report)
    seen_group_ids: set[str] = set()
    for group_id in payload.dedupe_group_ids:
        if group_id in seen_group_ids:
            continue
        seen_group_ids.add(group_id)
        group = _load_workspace_dedupe_group(session, payload.workspace_code, group_id)
        if group is None or group.winner_news_item_id is None:
            skipped_items.append(
                DailyReportBulkAdoptSkippedItem(
                    dedupe_group_id=group_id,
                    reason="missing_winner",
                ),
            )
            continue
        recommendation_item = _latest_recommendation_item_for_news(
            session,
            workspace_code=payload.workspace_code,
            news_item_id=group.winner_news_item_id,
        )
        if recommendation_item is None:
            skipped_items.append(
                DailyReportBulkAdoptSkippedItem(
                    dedupe_group_id=group_id,
                    reason="missing_recommendation",
                ),
            )
            continue
        generated = _latest_generated_news_for_recommendation(session, recommendation_item.id)
        if generated is None:
            generated = _create_rejected_generated_news_placeholder(session, workspace, recommendation_item)
            session.flush()

        existing = _daily_report_item_for_generated_news(session, report.id, generated.id)
        changed_item: DailyReportItem | None = None
        if existing is None:
            changed_item = DailyReportItem(
                daily_report=report,
                generated_news=generated,
                workspace_code=workspace.code,
                domain_code=generated.domain_code,
                visibility_scope=generated.visibility_scope,
                sync_policy=generated.sync_policy,
                adoption_status=0,
                sort_order=next_sort_order,
                editor_notes="候选池批量剔除。",
            )
            session.add(changed_item)
            created_total += 1
            next_sort_order += 1
        elif existing.adoption_status != 0:
            existing.adoption_status = 0
            existing.editor_notes = (existing.editor_notes or "候选池批量剔除。").strip()
            changed_item = existing
            updated_total += 1
        if changed_item is not None:
            session.flush()
            record_dedupe_group_adoption_changed_activity(
                session,
                actor=current_user,
                group=group,
                daily_report_item=changed_item,
                action_type="bulk_reject_from_candidates",
            )

    session.add(
        EditorialAction(
            user=current_user,
            object_type="daily_report",
            object_id=report.id,
            action_type="bulk_reject_from_candidates",
            after_json={
                "workspace_code": payload.workspace_code,
                "day_key": payload.day_key,
                "dedupe_group_ids": list(seen_group_ids),
                "created_total": created_total,
                "updated_total": updated_total,
                "skipped_total": len(skipped_items),
            },
        ),
    )
    session.commit()
    return DailyReportBulkAdoptRead(
        report=_daily_report_to_read(_load_daily_report(session, report.id)),
        created_total=created_total,
        updated_total=updated_total,
        skipped_total=len(skipped_items),
        skipped_items=skipped_items,
    )


@router.get("/weekly-reports", response_model=list[WeeklyReportRead])
def list_weekly_reports(
    workspace_code: str = Query(...),
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
    was_published = report.status == "published"
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
    if not was_published and _workspace_feedback_policy(session, report.workspace_code).get("notify_on_publish"):
        record_weekly_report_publish_activity(session, actor=current_user, report=report)
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
    record_weekly_report_item_updated_activity(
        session,
        actor=current_user,
        item=item,
        before_json=before,
        after_json=_weekly_item_editor_snapshot(item),
    )
    refresh_weekly_report_summary(_load_weekly_report(session, item.weekly_report.id))
    session.commit()
    return _weekly_report_item_to_read(_load_weekly_report_item(session, item.id))


@router.patch("/daily-report-items/{item_id}", response_model=DailyReportItemRead)
def update_daily_report_item(
    item_id: str,
    payload: DailyReportItemUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyReportItemRead:
    """编辑日报条目（报告层字段）。

    发布后修订底线：published 日报不可删除、raw/generated_news 不可动，但报告层的
    采信状态/头条/排序/editor 覆盖字段允许 workspace admin+ 继续修订——每次写
    post_publish_revision 编辑审计，并自动重投影 renditions（公司 SQL 导出读当前
    采信态，契约不变）。draft 仍是 member+ 的常规编辑。
    """
    item = _load_daily_report_item(session, item_id)
    published = item.daily_report.status == "published"
    assert_workspace_member(
        session,
        current_user,
        item.daily_report.workspace_code,
        min_role="admin" if published else "member",
    )
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
            action_type="post_publish_revision" if published else "edit",
            before_json=before,
            after_json=_item_editor_snapshot(item),
        ),
    )
    if published:
        rebuild_daily_report_renditions(session, item.daily_report)
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
    _assert_feedback_allowed(session, current_user, item.daily_report.workspace_code, "react")
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
    session.flush()
    record_reaction_activity(session, actor=current_user, item=item, reaction=reaction)
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
    _assert_feedback_allowed(session, current_user, item.daily_report.workspace_code, "rate")
    rating = session.scalar(
        select(Rating).where(
            Rating.user_id == current_user.id,
            Rating.daily_report_item_id == item.id,
            Rating.dimension == payload.dimension,
        ),
    )
    created = rating is None
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
    session.flush()
    record_rating_activity(session, actor=current_user, item=item, rating=rating, created=created)
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
    _assert_feedback_allowed(session, current_user, item.daily_report.workspace_code, "comment")
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
    session.flush()
    record_comment_activity(session, actor=current_user, item=item, comment=comment, parent=parent)
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


def _load_or_create_daily_draft_for_bulk_adopt(
    session: Session,
    *,
    workspace: Workspace,
    day_key: str,
) -> DailyReport:
    report = session.scalar(
        select(DailyReport)
        .options(_daily_report_options())
        .where(
            DailyReport.workspace_code == workspace.code,
            DailyReport.domain_code == workspace.default_domain_code,
            DailyReport.day_key == day_key,
        ),
    )
    if report is not None:
        return report
    report = DailyReport(
        workspace_code=workspace.code,
        domain_code=workspace.default_domain_code,
        day_key=day_key,
        title=f"{day_key} {workspace.name} 日报",
        summary="由候选池批量采信生成的日报草稿。",
        status="draft",
    )
    session.add(report)
    session.flush()
    return report


def _create_rejected_generated_news_placeholder(
    session: Session,
    workspace: Workspace,
    recommendation_item: RecommendationItem,
) -> GeneratedNews:
    news_item = recommendation_item.news_item
    title = news_item.normalized_title or news_item.source_title
    generated = GeneratedNews(
        recommendation_item=recommendation_item,
        news_item=news_item,
        workspace_code=workspace.code,
        domain_code=news_item.domain_code,
        visibility_scope=news_item.visibility_scope,
        sync_policy=news_item.sync_policy,
        category="基础竞争力",
        title=title,
        summary=news_item.summary or "候选池剔除占位记录，不进入标准公司 SQL。",
        key_points="",
        content_json={
            "background": "",
            "effects": "",
            "eventSummary": news_item.summary or title,
            "technologyAndInnovation": "",
            "valueAndImpact": "",
        },
        source_url=news_item.source_url,
        generated_by="bulk_reject_placeholder_v1",
        generation_status="rejected_candidate",
    )
    session.add(generated)
    return generated


def _next_daily_report_sort_order(report: DailyReport) -> int:
    if not report.items:
        return 1
    return max(item.sort_order for item in report.items) + 1


def _load_workspace_dedupe_group(
    session: Session,
    workspace_code: str,
    group_id: str,
) -> DedupeGroup | None:
    return session.scalar(
        select(DedupeGroup).where(
            DedupeGroup.id == group_id,
            DedupeGroup.workspace_code == workspace_code,
            DedupeGroup.status == "active",
        ),
    )


def _latest_recommendation_item_for_news(
    session: Session,
    *,
    workspace_code: str,
    news_item_id: str,
) -> RecommendationItem | None:
    return session.scalar(
        select(RecommendationItem)
        .join(RecommendationRun)
        .options(selectinload(RecommendationItem.news_item))
        .where(
            RecommendationItem.workspace_code == workspace_code,
            RecommendationItem.news_item_id == news_item_id,
        )
        .order_by(desc(RecommendationRun.created_at), RecommendationItem.rank)
        .limit(1),
    )


def _latest_generated_news_for_recommendation(
    session: Session,
    recommendation_item_id: str,
) -> GeneratedNews | None:
    return session.scalar(
        select(GeneratedNews)
        .where(GeneratedNews.recommendation_item_id == recommendation_item_id)
        .order_by(desc(GeneratedNews.created_at), GeneratedNews.id)
        .limit(1),
    )


def _daily_report_item_for_generated_news(
    session: Session,
    report_id: str,
    generated_news_id: str,
) -> DailyReportItem | None:
    return session.scalar(
        select(DailyReportItem).where(
            DailyReportItem.daily_report_id == report_id,
            DailyReportItem.generated_news_id == generated_news_id,
        ),
    )


def _assert_feedback_allowed(
    session: Session,
    current_user: User,
    workspace_code: str,
    action: str,
) -> None:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    policy = _feedback_policy_from_workspace(workspace)
    policy_key = {
        "react": "viewer_can_react",
        "rate": "viewer_can_rate",
        "comment": "viewer_can_comment",
    }[action]
    assert_workspace_member(
        session,
        current_user,
        workspace_code,
        min_role="viewer" if policy.get(policy_key) else "member",
    )


def _workspace_feedback_policy(session: Session, workspace_code: str) -> dict[str, bool]:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return _feedback_policy_from_workspace(workspace)


def _feedback_policy_from_workspace(workspace: Workspace) -> dict[str, bool]:
    return {
        "viewer_can_react": True,
        "viewer_can_rate": True,
        "viewer_can_comment": True,
        "viewer_can_edit": False,
        "notify_on_comment": True,
        "notify_on_publish": False,
        **dict((workspace.config_json or {}).get("feedback_policy") or {}),
    }


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
    scores = weekly_item_score(item.generated_news)
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
        weekly_score=scores.weekly_score,
        final_score=scores.final_score,
        heat_score=scores.heat_score,
        feedback_score=scores.feedback_score,
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
        "is_headline": bool(item.is_headline),
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
