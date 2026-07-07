from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date, datetime, time, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.auth.service import write_audit
from app.collaboration.notifications import (
    record_requirement_status_changed_activity,
    record_topic_task_assigned_activity,
)
from app.core.database import get_db_session
from app.core.privacy import contains_secret_like_key
from app.ingestion.tech_insight_loop_import_audit import (
    build_legacy_import_summary,
    feedback_ref_flag,
    feedback_unresolved_ref_count,
    list_legacy_import_gap_items,
    milestone_ref_flags,
    milestone_unresolved_ref_count,
    report_ref_counts,
)
from app.ingestion.tech_insight_loop_legacy import LEGACY_WORKSPACE_CODE
from app.models.common import utc_now
from app.models.content import GeneratedNews, NewsItem, RawItem
from app.models.feedback import AuditLog, EditorialAction
from app.models.identity import User
from app.models.legacy import (
    EntityMilestone,
    HistoricalFeedbackItem,
    HistoricalJobRun,
    HistoricalReport,
    TrackedEntity,
)
from app.models.reports import DailyReportItem, WeeklyReportItem
from app.models.strategy import Insight, Requirement, RequirementSourceLink, StrategicImplication, TopicTask
from app.models.sync import SyncOutbox, SyncRun
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.operations import (
    AuditLogRead,
    EntityMilestoneDetailRead,
    EntityMilestoneListItem,
    EntityMilestoneUpdate,
    EntityTimelineSummaryRead,
    HistoricalFeedbackListItem,
    HistoricalJobRunListItem,
    HistoricalReportDetailRead,
    HistoricalReportListItem,
    HistoricalReportSummaryRead,
    InsightCreate,
    InsightRead,
    InsightUpdate,
    LegacyImportGapItemRead,
    LegacyImportSummaryRead,
    QualityArchiveSummaryRead,
    ReportItemEntityMilestoneCreate,
    ReportItemStrategyLoopCreate,
    ReportItemStrategyLoopRead,
    RequirementCreate,
    RequirementRead,
    RequirementSourceLinkCreate,
    RequirementSourceLinkRead,
    RequirementUpdate,
    SyncPackageExportCreate,
    SyncPackageExportRead,
    SyncPackageImportCreate,
    SyncPackageImportRead,
    SyncRunCreate,
    SyncRunRead,
    StrategicImplicationCreate,
    StrategicImplicationRead,
    StrategicImplicationUpdate,
    TopicTaskBatchUpdate,
    TopicTaskBatchUpdateRead,
    TopicTaskCreate,
    TopicTaskRead,
    TopicTaskUpdate,
    TrackedEntityListItem,
)
from app.sync.apply import apply_sync_records
from app.sync.records import sort_records_by_dependency

router = APIRouter(prefix="/api", tags=["operations"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)
EXPORTABLE_SYNC_POLICIES = {"public_to_intranet", "manual_only", "two_way_config"}


@router.get("/insights", response_model=list[InsightRead])
def list_insights(
    workspace_code: str = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    query: str | None = Query(default=None, alias="q"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[InsightRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    statement = (
        select(Insight)
        .options(*_insight_query_options())
        .where(Insight.workspace_code == workspace_code)
        .order_by(Insight.updated_at.desc(), Insight.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        statement = statement.where(Insight.status == status_filter)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(Insight.title.ilike(pattern), Insight.summary.ilike(pattern)))
    return [_insight_to_read(item) for item in session.scalars(statement).all()]


@router.post("/insights", response_model=InsightRead)
def create_insight(
    payload: InsightCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> InsightRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="member")
    news_item = _load_news_item_for_insight(session, payload.news_item_id, payload.workspace_code)
    raw_item_id = _resolve_insight_raw_item_id(news_item, payload.raw_item_id)
    insight = Insight(
        workspace_code=payload.workspace_code,
        domain_code=payload.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        news_item_id=news_item.id,
        raw_item_id=raw_item_id,
        title=payload.title.strip(),
        summary=payload.summary,
        insight_type=payload.insight_type,
        status=payload.status,
        source_report_type=payload.source_report_type,
        source_report_id=payload.source_report_id,
        source_report_item_id=payload.source_report_item_id,
        confidence_score=payload.confidence_score,
        metadata_json=payload.metadata_json,
    )
    session.add(insight)
    session.flush()
    write_audit(
        session,
        current_user,
        "insight.create",
        "insight",
        insight.id,
        {"workspace_code": insight.workspace_code, "news_item_id": insight.news_item_id, "status": insight.status},
    )
    session.commit()
    return _insight_to_read(_load_insight(session, insight.id))


@router.get("/insights/{insight_id}", response_model=InsightRead)
def get_insight(
    insight_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> InsightRead:
    insight = _load_insight(session, insight_id)
    assert_workspace_member(session, current_user, insight.workspace_code, min_role="viewer")
    return _insight_to_read(insight)


@router.patch("/insights/{insight_id}", response_model=InsightRead)
def update_insight(
    insight_id: str,
    payload: InsightUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> InsightRead:
    insight = _load_insight(session, insight_id)
    assert_workspace_member(session, current_user, insight.workspace_code, min_role="member")
    for field in ("title", "summary", "insight_type", "status", "confidence_score", "metadata_json"):
        value = getattr(payload, field)
        if value is not None:
            setattr(insight, field, value.strip() if field == "title" and isinstance(value, str) else value)
    write_audit(
        session,
        current_user,
        "insight.update",
        "insight",
        insight.id,
        {"status": insight.status, "insight_type": insight.insight_type},
    )
    session.commit()
    return _insight_to_read(_load_insight(session, insight.id))


@router.get("/strategic-implications", response_model=list[StrategicImplicationRead])
def list_strategic_implications(
    workspace_code: str = Query(...),
    insight_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[StrategicImplicationRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    statement = (
        select(StrategicImplication)
        .options(*_strategic_implication_query_options())
        .where(StrategicImplication.workspace_code == workspace_code)
        .order_by(StrategicImplication.updated_at.desc(), StrategicImplication.created_at.desc())
        .limit(limit)
    )
    if insight_id:
        statement = statement.where(StrategicImplication.insight_id == insight_id)
    return [_strategic_implication_to_read(item) for item in session.scalars(statement).all()]


@router.post("/strategic-implications", response_model=StrategicImplicationRead)
def create_strategic_implication(
    payload: StrategicImplicationCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> StrategicImplicationRead:
    insight = _load_insight(session, payload.insight_id)
    assert_workspace_member(session, current_user, insight.workspace_code, min_role="member")
    implication = StrategicImplication(
        workspace_code=insight.workspace_code,
        domain_code=insight.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        insight_id=insight.id,
        title=payload.title.strip(),
        description=payload.description,
        implication_type=payload.implication_type,
        metadata_json=payload.metadata_json,
    )
    session.add(implication)
    session.flush()
    write_audit(
        session,
        current_user,
        "strategic_implication.create",
        "strategic_implication",
        implication.id,
        {"workspace_code": implication.workspace_code, "insight_id": implication.insight_id},
    )
    session.commit()
    return _strategic_implication_to_read(_load_strategic_implication(session, implication.id))


@router.get("/strategic-implications/{implication_id}", response_model=StrategicImplicationRead)
def get_strategic_implication(
    implication_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> StrategicImplicationRead:
    implication = _load_strategic_implication(session, implication_id)
    assert_workspace_member(session, current_user, implication.workspace_code, min_role="viewer")
    return _strategic_implication_to_read(implication)


@router.patch("/strategic-implications/{implication_id}", response_model=StrategicImplicationRead)
def update_strategic_implication(
    implication_id: str,
    payload: StrategicImplicationUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> StrategicImplicationRead:
    implication = _load_strategic_implication(session, implication_id)
    assert_workspace_member(session, current_user, implication.workspace_code, min_role="member")
    for field in ("title", "description", "implication_type", "metadata_json"):
        value = getattr(payload, field)
        if value is not None:
            setattr(implication, field, value.strip() if field == "title" and isinstance(value, str) else value)
    write_audit(
        session,
        current_user,
        "strategic_implication.update",
        "strategic_implication",
        implication.id,
        {"implication_type": implication.implication_type},
    )
    session.commit()
    return _strategic_implication_to_read(_load_strategic_implication(session, implication.id))


@router.get("/requirements", response_model=list[RequirementRead])
def list_requirements(
    workspace_code: str = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[RequirementRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    statement = (
        select(Requirement)
        .options(*_requirement_query_options())
        .where(Requirement.workspace_code == workspace_code)
        .order_by(Requirement.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        statement = statement.where(Requirement.status == status_filter)
    return [_requirement_to_read(item) for item in session.scalars(statement).all()]


@router.post("/requirements", response_model=RequirementRead)
def create_requirement(
    payload: RequirementCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RequirementRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    _validate_workspace_member_user(
        session,
        workspace_code=payload.workspace_code,
        user_id=payload.owner_user_id,
        detail="owner must be an active workspace member",
    )
    requirement = Requirement(
        workspace_code=payload.workspace_code,
        domain_code=payload.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        owner_user_id=payload.owner_user_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        status=payload.status,
        due_at=payload.due_at,
        metadata_json=payload.metadata_json,
    )
    session.add(requirement)
    session.flush()
    if _requirement_create_has_source(payload):
        session.add(
            _build_requirement_source_link(
                session,
                requirement=requirement,
                payload=RequirementSourceLinkCreate(
                    insight_id=payload.source_insight_id,
                    daily_report_item_id=payload.source_daily_report_item_id,
                    weekly_report_item_id=payload.source_weekly_report_item_id,
                    entity_milestone_id=payload.source_entity_milestone_id,
                    historical_report_id=payload.source_historical_report_id,
                    historical_feedback_item_id=payload.source_historical_feedback_item_id,
                    news_item_id=payload.source_news_item_id,
                    raw_item_id=payload.source_raw_item_id,
                    note=payload.source_note,
                ),
            ),
        )
    write_audit(
        session,
        current_user,
        "requirement.create",
        "requirement",
        requirement.id,
        {
            "workspace_code": requirement.workspace_code,
            "title": requirement.title,
            "source_link": _requirement_create_has_source(payload),
        },
    )
    session.commit()
    return _requirement_to_read(_load_requirement(session, requirement.id))


@router.patch("/requirements/{requirement_id}", response_model=RequirementRead)
def update_requirement(
    requirement_id: str,
    payload: RequirementUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RequirementRead:
    requirement = _load_requirement(session, requirement_id)
    assert_workspace_member(session, current_user, requirement.workspace_code, min_role="admin")
    previous_status = requirement.status
    if payload.owner_user_id is not None:
        _validate_workspace_member_user(
            session,
            workspace_code=requirement.workspace_code,
            user_id=payload.owner_user_id,
            detail="owner must be an active workspace member",
        )
    for field in ("title", "description", "priority", "status", "due_at", "owner_user_id", "metadata_json"):
        value = getattr(payload, field)
        if value is not None:
            if field == "metadata_json":
                requirement.metadata_json = {**(requirement.metadata_json or {}), **value}
            else:
                setattr(requirement, field, value)
    write_audit(
        session,
        current_user,
        "requirement.update",
        "requirement",
        requirement.id,
        {"status": requirement.status, "priority": requirement.priority},
    )
    if requirement.status != previous_status:
        record_requirement_status_changed_activity(
            session,
            actor=current_user,
            requirement=requirement,
            previous_status=previous_status,
        )
    _record_requirement_recommendation_feedback(session, current_user, requirement)
    session.commit()
    return _requirement_to_read(_load_requirement(session, requirement.id))


@router.post("/requirements/{requirement_id}/source-links", response_model=RequirementRead)
def create_requirement_source_link(
    requirement_id: str,
    payload: RequirementSourceLinkCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RequirementRead:
    requirement = _load_requirement(session, requirement_id)
    assert_workspace_member(session, current_user, requirement.workspace_code, min_role="admin")
    source_link = _build_requirement_source_link(session, requirement=requirement, payload=payload)
    session.add(source_link)
    session.flush()
    write_audit(
        session,
        current_user,
        "requirement.source_link.create",
        "requirement",
        requirement.id,
        {
            "source_link_id": source_link.id,
            "daily_report_item_id": source_link.daily_report_item_id,
            "weekly_report_item_id": source_link.weekly_report_item_id,
            "news_item_id": source_link.news_item_id,
            "raw_item_id": source_link.raw_item_id,
        },
    )
    session.commit()
    return _requirement_to_read(_load_requirement(session, requirement.id))


@router.post("/daily-report-items/{item_id}/insights", response_model=ReportItemStrategyLoopRead)
def create_daily_report_item_strategy_loop(
    item_id: str,
    payload: ReportItemStrategyLoopCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ReportItemStrategyLoopRead:
    item = _load_daily_report_item_source(session, item_id)
    assert_workspace_member(session, current_user, item.workspace_code, min_role="admin")
    return _create_strategy_loop_from_report_item(
        session,
        current_user=current_user,
        payload=payload,
        daily_item=item,
        weekly_item=None,
    )


@router.post("/weekly-report-items/{item_id}/insights", response_model=ReportItemStrategyLoopRead)
def create_weekly_report_item_strategy_loop(
    item_id: str,
    payload: ReportItemStrategyLoopCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ReportItemStrategyLoopRead:
    item = _load_weekly_report_item_source(session, item_id)
    assert_workspace_member(session, current_user, item.workspace_code, min_role="admin")
    return _create_strategy_loop_from_report_item(
        session,
        current_user=current_user,
        payload=payload,
        daily_item=item.daily_report_item,
        weekly_item=item,
    )


@router.post("/daily-report-items/{item_id}/entity-milestones", response_model=EntityMilestoneDetailRead)
def create_daily_report_item_entity_milestone(
    item_id: str,
    payload: ReportItemEntityMilestoneCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> EntityMilestoneDetailRead:
    item = _load_daily_report_item_source(session, item_id)
    assert_workspace_member(session, current_user, item.workspace_code, min_role="member")
    return _create_entity_milestone_from_report_item(
        session,
        current_user=current_user,
        payload=payload,
        daily_item=item,
        weekly_item=None,
    )


@router.post("/weekly-report-items/{item_id}/entity-milestones", response_model=EntityMilestoneDetailRead)
def create_weekly_report_item_entity_milestone(
    item_id: str,
    payload: ReportItemEntityMilestoneCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> EntityMilestoneDetailRead:
    item = _load_weekly_report_item_source(session, item_id)
    assert_workspace_member(session, current_user, item.workspace_code, min_role="member")
    return _create_entity_milestone_from_report_item(
        session,
        current_user=current_user,
        payload=payload,
        daily_item=item.daily_report_item,
        weekly_item=item,
    )


@router.get("/topic-tasks", response_model=list[TopicTaskRead])
def list_topic_tasks(
    workspace_code: str = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    assignee_user_id: str | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    due_filter: str | None = Query(default=None, alias="due", pattern="^(overdue|due_today)$"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[TopicTaskRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    now = utc_now()
    statement = (
        select(TopicTask)
        .options(*_topic_task_query_options())
        .where(TopicTask.workspace_code == workspace_code)
        .order_by(TopicTask.created_at.desc())
    )
    if status_filter:
        statement = statement.where(TopicTask.status == status_filter)
    if assigned_to_me:
        statement = statement.where(TopicTask.assignee_user_id == current_user.id)
    if assignee_user_id:
        statement = statement.where(TopicTask.assignee_user_id == assignee_user_id)
    if due_filter == "overdue":
        statement = statement.where(
            TopicTask.due_at.is_not(None),
            TopicTask.due_at < now,
            TopicTask.status.notin_(("done", "canceled")),
        )
    elif due_filter == "due_today":
        day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(now.date(), time.max, tzinfo=timezone.utc)
        statement = statement.where(
            TopicTask.due_at.is_not(None),
            TopicTask.due_at >= day_start,
            TopicTask.due_at <= day_end,
            TopicTask.status.notin_(("done", "canceled")),
        )
    statement = statement.limit(limit)
    return [_topic_task_to_read(item) for item in session.scalars(statement).all()]


@router.post("/topic-tasks", response_model=TopicTaskRead)
def create_topic_task(
    payload: TopicTaskCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> TopicTaskRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    _validate_topic_task_assignee(
        session,
        workspace_code=payload.workspace_code,
        assignee_user_id=payload.assignee_user_id,
    )
    task = TopicTask(
        workspace_code=payload.workspace_code,
        domain_code=payload.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        requirement_id=payload.requirement_id,
        assignee_user_id=payload.assignee_user_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        due_at=payload.due_at,
        metadata_json=payload.metadata_json,
    )
    session.add(task)
    session.flush()
    write_audit(
        session,
        current_user,
        "topic_task.create",
        "topic_task",
        task.id,
        {"workspace_code": task.workspace_code, "title": task.title},
    )
    if task.assignee_user_id:
        record_topic_task_assigned_activity(session, actor=current_user, task=task)
    session.commit()
    return _topic_task_to_read(_load_topic_task(session, task.id))


@router.get("/topic-tasks/{task_id}", response_model=TopicTaskRead)
def get_topic_task(
    task_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> TopicTaskRead:
    task = _load_topic_task(session, task_id)
    assert_workspace_member(session, current_user, task.workspace_code, min_role="viewer")
    return _topic_task_to_read(task)


@router.post("/topic-tasks/batch", response_model=TopicTaskBatchUpdateRead)
def batch_update_topic_tasks(
    payload: TopicTaskBatchUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> TopicTaskBatchUpdateRead:
    if payload.status is None and payload.blocked_reason is None:
        raise HTTPException(
            status_code=422,
            detail="status or blocked_reason is required",
        )
    blocked_reason = payload.blocked_reason.strip() if payload.blocked_reason is not None else None
    if payload.status == "blocked" and not blocked_reason:
        raise HTTPException(
            status_code=422,
            detail="blocked_reason is required when status is blocked",
        )

    task_ids = list(dict.fromkeys(payload.task_ids))
    statement = (
        select(TopicTask)
        .options(*_topic_task_query_options())
        .where(TopicTask.workspace_code == payload.workspace_code, TopicTask.id.in_(task_ids))
    )
    tasks = session.scalars(statement).all()
    tasks_by_id = {task.id: task for task in tasks}
    missing_ids = [task_id for task_id in task_ids if task_id not in tasks_by_id]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"missing_task_ids": missing_ids})

    _ensure_topic_task_batch_update_permission(session, current_user, tasks)
    for task in tasks:
        if payload.status is not None:
            task.status = payload.status
        if blocked_reason is not None:
            task.metadata_json = {**(task.metadata_json or {}), "blocked_reason": blocked_reason}

    write_audit(
        session,
        current_user,
        "topic_task.batch_update",
        "topic_task",
        payload.workspace_code,
        {
            "workspace_code": payload.workspace_code,
            "task_ids": task_ids,
            "status": payload.status,
            "blocked_reason": blocked_reason,
            "updated_count": len(tasks),
        },
    )
    session.commit()
    reloaded = _load_topic_tasks_by_ids(session, task_ids)
    return TopicTaskBatchUpdateRead(updated_count=len(reloaded), tasks=[_topic_task_to_read(task) for task in reloaded])


@router.patch("/topic-tasks/{task_id}", response_model=TopicTaskRead)
def update_topic_task(
    task_id: str,
    payload: TopicTaskUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> TopicTaskRead:
    task = _load_topic_task(session, task_id)
    _ensure_topic_task_update_permission(session, current_user, task, payload)
    previous_assignee_user_id = task.assignee_user_id
    if payload.assignee_user_id is not None:
        _validate_topic_task_assignee(
            session,
            workspace_code=task.workspace_code,
            assignee_user_id=payload.assignee_user_id,
        )
    for field in ("requirement_id", "title", "description", "status", "due_at", "assignee_user_id", "metadata_json"):
        value = getattr(payload, field)
        if value is not None:
            if field == "metadata_json":
                task.metadata_json = {**(task.metadata_json or {}), **value}
            else:
                setattr(task, field, value)
    write_audit(
        session,
        current_user,
        "topic_task.update",
        "topic_task",
        task.id,
        {"status": task.status},
    )
    if task.assignee_user_id and task.assignee_user_id != previous_assignee_user_id:
        record_topic_task_assigned_activity(session, actor=current_user, task=task)
    session.commit()
    return _topic_task_to_read(_load_topic_task(session, task.id))


@router.get("/sync-runs", response_model=list[SyncRunRead])
def list_sync_runs(
    limit: int = Query(default=50, ge=1, le=200),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[SyncRunRead]:
    runs = session.scalars(select(SyncRun).order_by(SyncRun.created_at.desc()).limit(limit)).all()
    return [_sync_run_to_read(run) for run in runs]


@router.post("/sync-runs", response_model=SyncRunRead)
def create_sync_run(
    payload: SyncRunCreate,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> SyncRunRead:
    export = _create_sync_export_package(
        session,
        payload=SyncPackageExportCreate(
            source_instance_id=payload.source_instance_id,
            target_instance_id=payload.target_instance_id,
            direction=payload.direction,
            limit=payload.limit,
        ),
        current_user=current_user,
    )
    run = session.get(SyncRun, export.sync_run.id) or _load_sync_run_by_package(
        session,
        export.sync_run.package_id,
    )
    return _sync_run_to_read(run)


@router.post("/sync/packages/export", response_model=SyncPackageExportRead)
def export_sync_package(
    payload: SyncPackageExportCreate,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> SyncPackageExportRead:
    return _create_sync_export_package(session, payload=payload, current_user=current_user)


@router.get("/sync/packages/{package_id}/download")
def download_sync_package(
    package_id: str,
    _: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> StreamingResponse:
    run = _load_sync_run_by_package(session, package_id)
    package_manifest = (run.counts_json or {}).get("package_manifest")
    records = (run.counts_json or {}).get("package_records")
    if not isinstance(package_manifest, dict) or not isinstance(records, list):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync package payload not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(package_manifest, ensure_ascii=False, indent=2))
        archive.writestr(
            "records.jsonl",
            "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n",
        )
    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{package_id}.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


@router.post("/sync/packages/import", response_model=SyncPackageImportRead)
def import_sync_package(
    payload: SyncPackageImportCreate,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> SyncPackageImportRead:
    package_id = str(payload.package_manifest.get("package_id") or "")
    if not package_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="package_manifest.package_id is required")
    expected_hash = str(payload.package_manifest.get("records_sha256") or "")
    if expected_hash and expected_hash != _hash_json(payload.records):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="records_sha256 does not match records")

    now = utc_now()
    run = SyncRun(
        package_id=f"{package_id}_import_{now.strftime('%Y%m%d%H%M%S%f')}",
        source_instance_id=str(payload.package_manifest.get("source_instance_id") or ""),
        target_instance_id=str(payload.package_manifest.get("target_instance_id") or ""),
        direction="import",
        status="running",
        counts_json={},
        started_at=now,
    )
    session.add(run)
    session.flush()

    # 手工包不保证 records.jsonl 的对象顺序（可能出自第三方或人工拼包），
    # 先按外键依赖序稳定排序，让一轮 apply 即净，而不是 failed 后等 retry 收敛。
    # records_sha256 校验在上面用原始顺序完成，排序不影响包完整性校验。
    outcome = apply_sync_records(
        session,
        run,
        sort_records_by_dependency(payload.records),
        source_instance_id=str(payload.package_manifest.get("source_instance_id") or ""),
    )
    applied = outcome.applied
    skipped = outcome.skipped
    failed = outcome.failed
    conflicts = outcome.conflicts
    errors = outcome.errors

    if failed:
        run.status = "completed_with_errors"
    elif conflicts:
        run.status = "completed_with_conflicts"
    else:
        run.status = "completed"
    run.counts_json = {
        "source_package_id": package_id,
        "received": len(payload.records),
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "conflicts": conflicts,
        "errors": errors,
    }
    run.completed_at = utc_now()
    write_audit(
        session,
        current_user,
        "sync_package.import",
        "sync_run",
        run.id,
        {
            "source_package_id": package_id,
            "applied": applied,
            "skipped": skipped,
            "failed": failed,
            "conflicts": conflicts,
        },
    )
    session.commit()
    return SyncPackageImportRead(
        package_id=package_id,
        status=run.status,
        received=len(payload.records),
        applied=applied,
        skipped=skipped,
        failed=failed,
        conflicts=conflicts,
        errors=errors,
    )


@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    workspace_code: str | None = Query(default=None),
    action: str | None = Query(default=None),
    object_type: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=300),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[AuditLogRead]:
    if workspace_code:
        if not _is_super_admin(current_user):
            assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    else:
        require_super_admin(current_user)
    statement = (
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if workspace_code:
        statement = statement.where(AuditLog.workspace_code == workspace_code)
    if action:
        statement = statement.where(AuditLog.action == action)
    if object_type:
        statement = statement.where(AuditLog.object_type == object_type)
    return [_audit_log_to_read(item) for item in session.scalars(statement).all()]


@router.get("/legacy-import/summary", response_model=LegacyImportSummaryRead)
def get_legacy_import_summary(
    workspace_code: str = Query(...),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> LegacyImportSummaryRead:
    summary = build_legacy_import_summary(session, workspace_code=workspace_code)
    return LegacyImportSummaryRead.model_validate(summary.to_dict())


@router.get("/legacy-import/gaps", response_model=list[LegacyImportGapItemRead])
def list_legacy_import_gaps(
    workspace_code: str = Query(...),
    kind: str = Query(default="all", pattern="^(all|historical_reports|entity_milestones|historical_feedback)$"),
    limit: int = Query(default=50, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[LegacyImportGapItemRead]:
    gaps = list_legacy_import_gap_items(session, workspace_code=workspace_code, kind=kind, limit=limit)
    return [LegacyImportGapItemRead.model_validate(item.to_dict()) for item in gaps]


@router.get("/quality-archive/summary", response_model=QualityArchiveSummaryRead)
def get_quality_archive_summary(
    workspace_code: str = Query(...),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> QualityArchiveSummaryRead:
    feedback_items = session.scalars(
        select(HistoricalFeedbackItem).where(HistoricalFeedbackItem.workspace_code == workspace_code),
    ).all()
    job_runs = session.scalars(
        select(HistoricalJobRun).where(HistoricalJobRun.workspace_code == workspace_code),
    ).all()

    by_feedback_type: dict[str, int] = {}
    by_quality_reason: dict[str, int] = {}
    latest_feedback_values = []
    unresolved_feedback_count = 0
    unresolved_feedback_ref_count = 0
    total_feedback = 0
    total_quality_feedback = 0
    for item in feedback_items:
        if item.feedback_kind == "quality_feedback":
            total_quality_feedback += 1
            reason_key = item.reason or item.feedback_type or "未标注"
            by_quality_reason[reason_key] = by_quality_reason.get(reason_key, 0) + 1
        else:
            total_feedback += 1
        type_key = item.feedback_type or item.feedback_kind or "未标注"
        by_feedback_type[type_key] = by_feedback_type.get(type_key, 0) + 1
        unresolved_count = feedback_unresolved_ref_count(item)
        if unresolved_count:
            unresolved_feedback_count += 1
            unresolved_feedback_ref_count += unresolved_count
        if item.feedback_at:
            latest_feedback_values.append(item.feedback_at)

    by_job_type: dict[str, int] = {}
    by_job_status: dict[str, int] = {}
    latest_job_values = []
    total_job_failures = 0
    for run in job_runs:
        type_key = run.job_type or "未标注"
        status_key = run.status or "unknown"
        by_job_type[type_key] = by_job_type.get(type_key, 0) + 1
        by_job_status[status_key] = by_job_status.get(status_key, 0) + 1
        total_job_failures += run.failed_count or 0
        if run.started_at:
            latest_job_values.append(run.started_at)

    return QualityArchiveSummaryRead(
        workspace_code=workspace_code,
        total_feedback=total_feedback,
        total_quality_feedback=total_quality_feedback,
        total_job_runs=len(job_runs),
        unresolved_feedback_count=unresolved_feedback_count,
        unresolved_feedback_ref_count=unresolved_feedback_ref_count,
        total_job_failures=total_job_failures,
        by_feedback_type=by_feedback_type,
        by_quality_reason=by_quality_reason,
        by_job_type=by_job_type,
        by_job_status=by_job_status,
        latest_feedback_at=max(latest_feedback_values) if latest_feedback_values else None,
        latest_job_started_at=max(latest_job_values) if latest_job_values else None,
    )


@router.get("/historical-feedback-items", response_model=list[HistoricalFeedbackListItem])
def list_historical_feedback_items(
    workspace_code: str = Query(...),
    feedback_kind: str | None = Query(default=None),
    feedback_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    has_unresolved_refs: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=80, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[HistoricalFeedbackListItem]:
    statement = select(HistoricalFeedbackItem).where(HistoricalFeedbackItem.workspace_code == workspace_code)
    if feedback_kind:
        statement = statement.where(HistoricalFeedbackItem.feedback_kind == feedback_kind)
    if feedback_type:
        statement = statement.where(HistoricalFeedbackItem.feedback_type == feedback_type)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                HistoricalFeedbackItem.user_name.ilike(pattern),
                HistoricalFeedbackItem.feedback_type.ilike(pattern),
                HistoricalFeedbackItem.reason.ilike(pattern),
                HistoricalFeedbackItem.comment.ilike(pattern),
                HistoricalFeedbackItem.legacy_article_id.ilike(pattern),
            ),
        )
    feedback_items = session.scalars(
        statement.order_by(HistoricalFeedbackItem.feedback_at.desc().nullslast(), HistoricalFeedbackItem.created_at.desc()),
    ).all()
    if has_unresolved_refs is not None:
        feedback_items = [
            item
            for item in feedback_items
            if (feedback_unresolved_ref_count(item) > 0) == has_unresolved_refs
        ]
    page = feedback_items[offset: offset + limit]
    return [_historical_feedback_to_list_item(item) for item in page]


@router.get("/historical-job-runs", response_model=list[HistoricalJobRunListItem])
def list_historical_job_runs(
    workspace_code: str = Query(...),
    job_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=80, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[HistoricalJobRunListItem]:
    statement = select(HistoricalJobRun).where(HistoricalJobRun.workspace_code == workspace_code)
    if job_type:
        statement = statement.where(HistoricalJobRun.job_type == job_type)
    if status_filter:
        statement = statement.where(HistoricalJobRun.status == status_filter)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                HistoricalJobRun.job_type.ilike(pattern),
                HistoricalJobRun.status.ilike(pattern),
                HistoricalJobRun.message.ilike(pattern),
            ),
        )
    runs = session.scalars(
        statement.order_by(HistoricalJobRun.started_at.desc().nullslast(), HistoricalJobRun.created_at.desc())
        .offset(offset)
        .limit(limit),
    ).all()
    return [_historical_job_run_to_list_item(run) for run in runs]


@router.get("/historical-reports/summary", response_model=HistoricalReportSummaryRead)
def get_historical_reports_summary(
    workspace_code: str = Query(...),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> HistoricalReportSummaryRead:
    reports = session.scalars(
        select(HistoricalReport).where(HistoricalReport.workspace_code == workspace_code),
    ).all()
    by_report_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    unresolved_report_count = 0
    unresolved_ref_count = 0
    period_starts = []
    for report in reports:
        by_report_type[report.report_type] = by_report_type.get(report.report_type, 0) + 1
        by_status[report.status] = by_status.get(report.status, 0) + 1
        unresolved_count = report_ref_counts(report)[1]
        if unresolved_count:
            unresolved_report_count += 1
            unresolved_ref_count += unresolved_count
        if report.period_start_at:
            period_starts.append(report.period_start_at)
    return HistoricalReportSummaryRead(
        workspace_code=workspace_code,
        total=len(reports),
        by_report_type=by_report_type,
        by_status=by_status,
        unresolved_report_count=unresolved_report_count,
        unresolved_ref_count=unresolved_ref_count,
        earliest_period_start_at=min(period_starts) if period_starts else None,
        latest_period_start_at=max(period_starts) if period_starts else None,
    )


@router.get("/historical-reports", response_model=list[HistoricalReportListItem])
def list_historical_reports(
    workspace_code: str = Query(...),
    report_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    q: str | None = Query(default=None),
    has_unresolved_refs: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[HistoricalReportListItem]:
    statement = _historical_reports_statement(
        workspace_code=workspace_code,
        report_type=report_type,
        status_filter=status_filter,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    reports = session.scalars(statement).all()
    if has_unresolved_refs is not None:
        reports = [
            report
            for report in reports
            if (report_ref_counts(report)[1] > 0) == has_unresolved_refs
        ]
    page = reports[offset: offset + limit]
    return [_historical_report_to_list_item(report) for report in page]


@router.get("/historical-reports/{report_id}", response_model=HistoricalReportDetailRead)
def get_historical_report(
    report_id: str,
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> HistoricalReportDetailRead:
    report = session.get(HistoricalReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Historical report not found")
    return _historical_report_to_detail(report)


@router.get("/entity-timeline/summary", response_model=EntityTimelineSummaryRead)
def get_entity_timeline_summary(
    workspace_code: str = Query(...),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> EntityTimelineSummaryRead:
    entities = session.scalars(
        select(TrackedEntity).where(TrackedEntity.workspace_code == workspace_code),
    ).all()
    milestones = session.scalars(
        select(EntityMilestone)
        .options(selectinload(EntityMilestone.tracked_entity))
        .where(EntityMilestone.workspace_code == workspace_code),
    ).all()

    by_entity_type: dict[str, int] = {}
    by_event_type: dict[str, int] = {}
    by_importance_level: dict[str, int] = {}
    event_times = []
    unresolved_milestone_count = 0
    unresolved_ref_count = 0
    selected_milestones = 0

    for entity in entities:
        key = entity.entity_type or "未分类"
        by_entity_type[key] = by_entity_type.get(key, 0) + 1
    for milestone in milestones:
        event_key = milestone.event_type or "未分类"
        level_key = milestone.importance_level or "unknown"
        by_event_type[event_key] = by_event_type.get(event_key, 0) + 1
        by_importance_level[level_key] = by_importance_level.get(level_key, 0) + 1
        if milestone.event_time:
            event_times.append(milestone.event_time)
        if milestone.selected_for_timeline:
            selected_milestones += 1
        unresolved_refs = milestone_unresolved_ref_count(milestone)
        if unresolved_refs:
            unresolved_milestone_count += 1
            unresolved_ref_count += unresolved_refs

    return EntityTimelineSummaryRead(
        workspace_code=workspace_code,
        total_entities=len(entities),
        total_milestones=len(milestones),
        selected_milestones=selected_milestones,
        unresolved_milestone_count=unresolved_milestone_count,
        unresolved_ref_count=unresolved_ref_count,
        by_entity_type=by_entity_type,
        by_event_type=by_event_type,
        by_importance_level=by_importance_level,
        earliest_event_time=min(event_times) if event_times else None,
        latest_event_time=max(event_times) if event_times else None,
    )


@router.get("/tracked-entities", response_model=list[TrackedEntityListItem])
def list_tracked_entities(
    workspace_code: str = Query(...),
    entity_type: str | None = Query(default=None),
    rank: str | None = Query(default=None),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=80, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[TrackedEntityListItem]:
    statement = select(TrackedEntity).where(TrackedEntity.workspace_code == workspace_code)
    if entity_type:
        statement = statement.where(TrackedEntity.entity_type == entity_type)
    if rank:
        statement = statement.where(TrackedEntity.rank == rank)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                TrackedEntity.name.ilike(pattern),
                TrackedEntity.entity_type.ilike(pattern),
                TrackedEntity.notes.ilike(pattern),
            ),
        )
    entities = session.scalars(
        statement.order_by(TrackedEntity.influence_score.desc(), TrackedEntity.name).offset(offset).limit(limit),
    ).all()
    return [_tracked_entity_to_list_item(session, entity) for entity in entities]


@router.get("/entity-milestones", response_model=list[EntityMilestoneListItem])
def list_entity_milestones(
    workspace_code: str = Query(...),
    tracked_entity_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    importance_level: str | None = Query(default=None),
    board: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    q: str | None = Query(default=None),
    has_unresolved_refs: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=80, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[EntityMilestoneListItem]:
    statement = _entity_milestones_statement(
        workspace_code=workspace_code,
        tracked_entity_id=tracked_entity_id,
        entity_type=entity_type,
        event_type=event_type,
        importance_level=importance_level,
        board=board,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    milestones = session.scalars(statement).all()
    if has_unresolved_refs is not None:
        milestones = [
            item
            for item in milestones
            if (milestone_unresolved_ref_count(item) > 0) == has_unresolved_refs
        ]
    page = milestones[offset: offset + limit]
    return [_entity_milestone_to_list_item(item) for item in page]


@router.get("/entity-milestones/{milestone_id}", response_model=EntityMilestoneDetailRead)
def get_entity_milestone(
    milestone_id: str,
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> EntityMilestoneDetailRead:
    milestone = session.scalar(
        select(EntityMilestone)
        .options(selectinload(EntityMilestone.tracked_entity))
        .where(EntityMilestone.id == milestone_id),
    )
    if milestone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity milestone not found")
    return _entity_milestone_to_detail(milestone)


@router.patch("/entity-milestones/{milestone_id}", response_model=EntityMilestoneDetailRead)
def update_entity_milestone(
    milestone_id: str,
    payload: EntityMilestoneUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> EntityMilestoneDetailRead:
    milestone = _load_entity_milestone_source(session, milestone_id)
    assert_workspace_member(session, current_user, milestone.workspace_code, min_role="admin")
    if milestone.legacy_system != "current":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imported legacy milestone is immutable")
    _apply_entity_milestone_update(milestone, payload, current_user)
    write_audit(
        session,
        current_user,
        "entity_milestone.update",
        "entity_milestone",
        milestone.id,
        {
            "curation_status": _milestone_curation_status(milestone),
            "selected_for_timeline": milestone.selected_for_timeline,
            "fields": sorted(_schema_fields_set(payload)),
        },
    )
    session.commit()
    loaded = _load_entity_milestone_source(session, milestone.id)
    return _entity_milestone_to_detail(loaded)


def _create_sync_export_package(
    session: Session,
    *,
    payload: SyncPackageExportCreate,
    current_user: User,
) -> SyncPackageExportRead:
    now = utc_now()
    statement = (
        select(SyncOutbox)
        .where(
            SyncOutbox.status == "pending",
            SyncOutbox.visibility_scope != "restricted",
            SyncOutbox.sync_policy.in_(EXPORTABLE_SYNC_POLICIES),
        )
        .order_by(SyncOutbox.created_at, SyncOutbox.id)
        .limit(payload.limit)
    )
    outbox_items = list(session.scalars(statement).all())
    records: list[dict[str, object]] = []
    secret_blocked_event_ids: list[str] = []
    for item in outbox_items:
        if contains_secret_like_key(item.payload_json or {}):
            item.status = "failed"
            secret_blocked_event_ids.append(item.event_id)
            continue
        records.append(_sync_outbox_to_record(item))
    package_manifest = {
        "format_version": "sync_package_v1",
        "package_id": f"sync_{now.strftime('%Y%m%d%H%M%S%f')}",
        "source_instance_id": payload.source_instance_id,
        "target_instance_id": payload.target_instance_id,
        "direction": payload.direction,
        "created_at": now.isoformat(),
        "record_count": len(records),
        "records_sha256": _hash_json(records),
        "safety": {
            "excluded_visibility_scope": "restricted",
            "allowed_sync_policies": sorted(EXPORTABLE_SYNC_POLICIES),
            "secrets_policy": "payloads must reference credential_ref and must not include tokens",
            "secret_blocked_count": len(secret_blocked_event_ids),
        },
    }
    pending_total = session.scalar(select(func.count()).select_from(SyncOutbox).where(SyncOutbox.status == "pending")) or 0
    counts_json = {
        "pending_outbox": int(pending_total),
        "exported": len(records),
        "secret_blocked": len(secret_blocked_event_ids),
        "secret_blocked_event_ids": secret_blocked_event_ids,
        "conflicts": 0,
        "package_manifest": package_manifest,
        "package_records": records,
    }
    run = SyncRun(
        package_id=package_manifest["package_id"],
        source_instance_id=payload.source_instance_id,
        target_instance_id=payload.target_instance_id,
        direction=payload.direction,
        status="completed",
        counts_json=counts_json,
        started_at=now,
        completed_at=now,
    )
    session.add(run)
    for item in outbox_items:
        if item.event_id in secret_blocked_event_ids:
            continue
        item.status = "exported"
    session.flush()
    write_audit(
        session,
        current_user,
        "sync_package.export",
        "sync_run",
        run.id,
        {
            "package_id": run.package_id,
            "direction": run.direction,
            "exported": len(records),
            "secret_blocked": len(secret_blocked_event_ids),
        },
    )
    session.commit()
    session.refresh(run)
    return SyncPackageExportRead(
        sync_run=_sync_run_to_read(run),
        package_manifest=package_manifest,
        records=records,
    )


def _sync_outbox_to_record(item: SyncOutbox) -> dict[str, object]:
    payload = item.payload_json or {}
    content_hash = item.payload_hash or _hash_json(payload)
    return {
        "event_id": item.event_id,
        "object_type": item.object_type,
        "object_id": item.object_id,
        "object_global_id": str(payload.get("global_id") or item.object_id),
        "operation": item.operation,
        "revision": int(payload.get("revision") or 1),
        "content_hash": content_hash,
        "visibility_scope": item.visibility_scope,
        "sync_policy": item.sync_policy,
        "workspace_code": item.workspace_code,
        "domain_code": item.domain_code,
        "payload": payload,
    }


def _hash_json(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _load_sync_run_by_package(session: Session, package_id: str) -> SyncRun:
    run = session.scalar(select(SyncRun).where(SyncRun.package_id == package_id))
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync package not found")
    return run


def _load_requirement(session: Session, requirement_id: str) -> Requirement:
    requirement = session.scalar(
        select(Requirement)
        .options(*_requirement_query_options())
        .where(Requirement.id == requirement_id),
    )
    if requirement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    return requirement


def _load_insight(session: Session, insight_id: str) -> Insight:
    insight = session.scalar(
        select(Insight)
        .options(*_insight_query_options())
        .where(Insight.id == insight_id),
    )
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    return insight


def _insight_query_options() -> list[Any]:
    return [
        selectinload(Insight.implications),
        selectinload(Insight.news_item).selectinload(NewsItem.data_source),
        selectinload(Insight.news_item).selectinload(NewsItem.raw_item).selectinload(RawItem.data_source),
        selectinload(Insight.raw_item).selectinload(RawItem.data_source),
    ]


def _load_strategic_implication(session: Session, implication_id: str) -> StrategicImplication:
    implication = session.scalar(
        select(StrategicImplication)
        .options(*_strategic_implication_query_options())
        .where(StrategicImplication.id == implication_id),
    )
    if implication is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategic implication not found")
    return implication


def _strategic_implication_query_options() -> list[Any]:
    return [selectinload(StrategicImplication.insight)]


def _requirement_query_options() -> list[Any]:
    return [
        selectinload(Requirement.owner),
        selectinload(Requirement.topic_tasks),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.insight)
        .selectinload(Insight.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.news_item)
        .selectinload(NewsItem.data_source),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.daily_report_item)
        .selectinload(DailyReportItem.generated_news)
        .selectinload(GeneratedNews.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.weekly_report_item)
        .selectinload(WeeklyReportItem.generated_news)
        .selectinload(GeneratedNews.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.weekly_report_item)
        .selectinload(WeeklyReportItem.daily_report_item)
        .selectinload(DailyReportItem.generated_news)
        .selectinload(GeneratedNews.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.entity_milestone)
        .selectinload(EntityMilestone.tracked_entity),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.entity_milestone)
        .selectinload(EntityMilestone.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(Requirement.source_links).selectinload(RequirementSourceLink.historical_report),
        selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.historical_feedback_item)
        .selectinload(HistoricalFeedbackItem.raw_item)
        .selectinload(RawItem.data_source),
    ]


def _load_topic_task(session: Session, task_id: str) -> TopicTask:
    task = session.scalar(
        select(TopicTask)
        .options(*_topic_task_query_options())
        .where(TopicTask.id == task_id),
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic task not found")
    return task


def _load_topic_tasks_by_ids(session: Session, task_ids: list[str]) -> list[TopicTask]:
    if not task_ids:
        return []
    tasks = session.scalars(
        select(TopicTask)
        .options(*_topic_task_query_options())
        .where(TopicTask.id.in_(task_ids)),
    ).all()
    tasks_by_id = {task.id: task for task in tasks}
    return [tasks_by_id[task_id] for task_id in task_ids if task_id in tasks_by_id]


def _topic_task_query_options() -> list[Any]:
    return [
        selectinload(TopicTask.assignee),
        selectinload(TopicTask.requirement),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.insight)
        .selectinload(Insight.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.news_item)
        .selectinload(NewsItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.daily_report_item)
        .selectinload(DailyReportItem.generated_news)
        .selectinload(GeneratedNews.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.weekly_report_item)
        .selectinload(WeeklyReportItem.generated_news)
        .selectinload(GeneratedNews.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.weekly_report_item)
        .selectinload(WeeklyReportItem.daily_report_item)
        .selectinload(DailyReportItem.generated_news)
        .selectinload(GeneratedNews.news_item)
        .selectinload(NewsItem.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.entity_milestone)
        .selectinload(EntityMilestone.tracked_entity),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.entity_milestone)
        .selectinload(EntityMilestone.raw_item)
        .selectinload(RawItem.data_source),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.historical_report),
        selectinload(TopicTask.requirement)
        .selectinload(Requirement.source_links)
        .selectinload(RequirementSourceLink.historical_feedback_item)
        .selectinload(HistoricalFeedbackItem.raw_item)
        .selectinload(RawItem.data_source),
    ]


def _validate_topic_task_assignee(session: Session, *, workspace_code: str, assignee_user_id: str | None) -> None:
    _validate_workspace_member_user(
        session,
        workspace_code=workspace_code,
        user_id=assignee_user_id,
        detail="assignee must be an active workspace member",
    )


def _validate_workspace_member_user(
    session: Session,
    *,
    workspace_code: str,
    user_id: str | None,
    detail: str,
) -> None:
    if not user_id:
        return
    membership = session.scalar(
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.enabled.is_(True),
            User.is_active.is_(True),
            User.status == "active",
        ),
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


def _ensure_topic_task_update_permission(
    session: Session,
    user: User,
    task: TopicTask,
    payload: TopicTaskUpdate,
) -> None:
    try:
        assert_workspace_member(session, user, task.workspace_code, min_role="admin")
        return
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise

    if task.assignee_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient workspace role")

    assert_workspace_member(session, user, task.workspace_code, min_role="viewer")
    if _assignee_task_update_allowed(payload):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="assignees may only update task status or blocked reason",
    )


def _assignee_task_update_allowed(payload: TopicTaskUpdate) -> bool:
    fields = _schema_fields_set(payload)
    if not fields <= {"status", "metadata_json"}:
        return False
    if "metadata_json" not in fields or payload.metadata_json is None:
        return True
    return set(payload.metadata_json.keys()) <= {"blocked_reason"}


def _ensure_topic_task_batch_update_permission(
    session: Session,
    user: User,
    tasks: list[TopicTask],
) -> None:
    if not tasks:
        return
    workspace_code = tasks[0].workspace_code
    try:
        assert_workspace_member(session, user, workspace_code, min_role="admin")
        return
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise

    assert_workspace_member(session, user, workspace_code, min_role="viewer")
    if all(task.assignee_user_id == user.id for task in tasks):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="assignees may only batch update their own tasks",
    )


def _schema_fields_set(payload: object) -> set[str]:
    fields = getattr(payload, "model_fields_set", None)
    if fields is None:
        fields = getattr(payload, "__fields_set__", set())
    return set(fields)


def _create_strategy_loop_from_report_item(
    session: Session,
    *,
    current_user: User,
    payload: ReportItemStrategyLoopCreate,
    daily_item: DailyReportItem | None,
    weekly_item: WeeklyReportItem | None,
) -> ReportItemStrategyLoopRead:
    source_item = weekly_item or daily_item
    if source_item is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="report item source is required")
    generated_news = _report_item_generated_news(daily_item=daily_item, weekly_item=weekly_item)
    if generated_news is None or generated_news.news_item is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="report item has no generated news source",
        )
    news_item = generated_news.news_item
    raw_item = news_item.raw_item
    workspace_code = source_item.workspace_code
    _validate_workspace_member_user(
        session,
        workspace_code=workspace_code,
        user_id=payload.owner_user_id,
        detail="owner must be an active workspace member",
    )
    if payload.create_task:
        _validate_topic_task_assignee(
            session,
            workspace_code=workspace_code,
            assignee_user_id=payload.task_assignee_user_id,
        )

    source_title = _report_item_title(daily_item=daily_item, weekly_item=weekly_item)
    source_summary = _report_item_summary(daily_item=daily_item, weekly_item=weekly_item)
    source_report_type = "weekly" if weekly_item else "daily"
    source_report_id = weekly_item.weekly_report_id if weekly_item else daily_item.daily_report_id if daily_item else None
    source_report_item_id = weekly_item.id if weekly_item else daily_item.id if daily_item else None

    insight = Insight(
        workspace_code=workspace_code,
        domain_code=source_item.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        news_item_id=news_item.id,
        raw_item_id=raw_item.id if raw_item else None,
        title=(payload.insight_title or source_title).strip(),
        summary=(payload.insight_summary or source_summary).strip(),
        insight_type=payload.insight_type,
        status="linked_to_requirement",
        source_report_type=source_report_type,
        source_report_id=source_report_id,
        source_report_item_id=source_report_item_id,
        confidence_score=payload.confidence_score,
        metadata_json={
            **(payload.metadata_json or {}),
            "created_from": f"{source_report_type}_report_item",
            "generated_news_id": generated_news.id,
        },
    )
    session.add(insight)
    session.flush()

    implication = StrategicImplication(
        workspace_code=workspace_code,
        domain_code=source_item.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        insight_id=insight.id,
        title=(payload.implication_title or f"研判：{insight.title}").strip(),
        description=(payload.implication_description or insight.summary).strip(),
        implication_type=payload.implication_type,
        metadata_json={
            "created_from": f"{source_report_type}_report_item",
            "source_report_item_id": source_report_item_id,
        },
    )
    session.add(implication)
    session.flush()

    requirement = Requirement(
        workspace_code=workspace_code,
        domain_code=source_item.domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        strategic_implication_id=implication.id,
        owner_user_id=payload.owner_user_id,
        title=(payload.requirement_title or f"跟进：{insight.title}").strip(),
        description=(payload.requirement_description or implication.description or insight.summary).strip(),
        priority=payload.requirement_priority,
        status=payload.requirement_status,
        due_at=payload.requirement_due_at,
        metadata_json={
            "created_from": f"{source_report_type}_report_item",
            "insight_id": insight.id,
            "strategic_implication_id": implication.id,
        },
    )
    session.add(requirement)
    session.flush()

    source_link = _build_requirement_source_link(
        session,
        requirement=requirement,
        payload=RequirementSourceLinkCreate(
            insight_id=insight.id,
            daily_report_item_id=daily_item.id if daily_item else None,
            weekly_report_item_id=weekly_item.id if weekly_item else None,
            note=payload.source_note or f"由{source_report_type} report item 沉淀",
        ),
    )
    session.add(source_link)
    session.flush()

    task: TopicTask | None = None
    if payload.create_task:
        task = TopicTask(
            workspace_code=workspace_code,
            domain_code=source_item.domain_code,
            visibility_scope="workspace",
            sync_policy="outbox",
            requirement_id=requirement.id,
            assignee_user_id=payload.task_assignee_user_id,
            title=(payload.task_title or f"跟进需求：{requirement.title}").strip(),
            description=(payload.task_description or requirement.description).strip(),
            status=payload.task_status,
            due_at=payload.task_due_at,
            metadata_json={
                "created_from": f"{source_report_type}_report_item",
                "requirement_id": requirement.id,
            },
        )
        session.add(task)
        session.flush()
        if task.assignee_user_id:
            record_topic_task_assigned_activity(session, actor=current_user, task=task)

    write_audit(
        session,
        current_user,
        f"{source_report_type}_report_item.strategy_loop.create",
        f"{source_report_type}_report_item",
        source_report_item_id or "",
        {
            "insight_id": insight.id,
            "strategic_implication_id": implication.id,
            "requirement_id": requirement.id,
            "topic_task_id": task.id if task else None,
        },
    )
    session.commit()
    return ReportItemStrategyLoopRead(
        insight=_insight_to_read(session.get(Insight, insight.id) or insight),
        implication=_strategic_implication_to_read(session.get(StrategicImplication, implication.id) or implication),
        requirement=_requirement_to_read(_load_requirement(session, requirement.id)),
        task=_topic_task_to_read(_load_topic_task(session, task.id)) if task else None,
    )


def _create_entity_milestone_from_report_item(
    session: Session,
    *,
    current_user: User,
    payload: ReportItemEntityMilestoneCreate,
    daily_item: DailyReportItem | None,
    weekly_item: WeeklyReportItem | None,
) -> EntityMilestoneDetailRead:
    source_item = weekly_item or daily_item
    if source_item is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="report item source is required")
    generated_news = _report_item_generated_news(daily_item=daily_item, weekly_item=weekly_item)
    if generated_news is None or generated_news.news_item is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="report item has no generated news source",
        )
    news_item = generated_news.news_item
    raw_item = news_item.raw_item
    workspace_code = source_item.workspace_code
    entity = _upsert_report_item_tracked_entity(
        session,
        payload=payload,
        workspace_code=workspace_code,
        domain_code=source_item.domain_code,
    )

    source_title = _report_item_title(daily_item=daily_item, weekly_item=weekly_item)
    source_summary = _report_item_summary(daily_item=daily_item, weekly_item=weekly_item)
    source_report_type = "weekly" if weekly_item else "daily"
    source_report_id = weekly_item.weekly_report_id if weekly_item else daily_item.daily_report_id if daily_item else None
    source_report_item_id = weekly_item.id if weekly_item else daily_item.id if daily_item else None
    milestone_legacy_id = f"{source_report_type}:{source_report_item_id}:{entity.id}"
    milestone = session.scalar(
        select(EntityMilestone).where(
            EntityMilestone.legacy_system == "current",
            EntityMilestone.legacy_table == "report_item_entity_milestones",
            EntityMilestone.legacy_id == milestone_legacy_id,
        ),
    )
    created = milestone is None
    if milestone is None:
        milestone = EntityMilestone(
            workspace_code=workspace_code,
            domain_code=source_item.domain_code,
            visibility_scope="workspace",
            sync_policy="outbox",
            legacy_system="current",
            legacy_table="report_item_entity_milestones",
            legacy_id=milestone_legacy_id,
            tracked_entity_id=entity.id,
            legacy_entity_id=entity.legacy_id,
        )
        session.add(milestone)

    board = payload.board or _generated_news_board(generated_news)
    source_url = generated_news.source_url or news_item.source_url or (raw_item.source_url if raw_item else None)
    source_name = news_item.source_name or (raw_item.source_name if raw_item else "")
    if not source_name and raw_item and raw_item.data_source:
        source_name = raw_item.data_source.name
    event_brief = (payload.event_brief or source_summary or source_title).strip()
    impact_brief = (payload.impact_brief or source_summary).strip()
    event_time = payload.event_time or news_item.published_at or (raw_item.published_at if raw_item else None) or source_item.created_at
    current_refs = {
        "source_report_type": source_report_type,
        "source_report_id": source_report_id,
        "source_report_item_id": source_report_item_id,
        "daily_report_item_id": daily_item.id if daily_item else None,
        "weekly_report_item_id": weekly_item.id if weekly_item else None,
        "generated_news_id": generated_news.id,
        "news_item_id": news_item.id,
        "raw_item_id": raw_item.id if raw_item else None,
        "data_source_id": raw_item.data_source_id if raw_item else news_item.data_source_id,
    }

    milestone.workspace_code = workspace_code
    milestone.domain_code = source_item.domain_code
    milestone.visibility_scope = "workspace"
    milestone.sync_policy = "outbox"
    milestone.tracked_entity_id = entity.id
    milestone.legacy_entity_id = entity.legacy_id
    milestone.legacy_article_id = None
    milestone.legacy_report_id = None
    milestone.raw_item_id = raw_item.id if raw_item else None
    milestone.historical_report_id = None
    milestone.event_time = event_time
    milestone.event_type = payload.event_type
    milestone.title = (payload.event_title or source_title).strip()
    milestone.event_content = event_brief
    milestone.impact = impact_brief
    milestone.event_brief = event_brief
    milestone.impact_brief = impact_brief
    milestone.timeline_brief = event_brief
    milestone.source_url = source_url
    milestone.source_name = source_name
    milestone.board = board
    milestone.selected_for_timeline = True
    milestone.confidence_score = payload.confidence_score
    milestone.importance_score = payload.importance_score
    milestone.importance_level = payload.importance_level
    milestone.event_dedupe_key = f"{entity.id}:{source_report_type}:{source_report_item_id}"
    milestone.metadata_json = {
        **(milestone.metadata_json or {}),
        **(payload.metadata_json or {}),
        "created_from": f"{source_report_type}_report_item",
        "curation_status": (milestone.metadata_json or {}).get("curation_status") or "draft",
        "source_note": payload.source_note,
        "created_by_user_id": (milestone.metadata_json or {}).get("created_by_user_id") or current_user.id,
        "updated_by_user_id": current_user.id,
        "current_refs": current_refs,
    }
    session.flush()

    write_audit(
        session,
        current_user,
        f"{source_report_type}_report_item.entity_milestone.{ 'create' if created else 'update' }",
        "entity_milestone",
        milestone.id,
        {
            "tracked_entity_id": entity.id,
            "source_report_item_id": source_report_item_id,
            "daily_report_item_id": daily_item.id if daily_item else None,
            "weekly_report_item_id": weekly_item.id if weekly_item else None,
            "news_item_id": news_item.id,
            "raw_item_id": raw_item.id if raw_item else None,
        },
    )
    session.commit()
    loaded = session.scalar(
        select(EntityMilestone)
        .options(selectinload(EntityMilestone.tracked_entity))
        .where(EntityMilestone.id == milestone.id),
    )
    return _entity_milestone_to_detail(loaded or milestone)


def _upsert_report_item_tracked_entity(
    session: Session,
    *,
    payload: ReportItemEntityMilestoneCreate,
    workspace_code: str,
    domain_code: str,
) -> TrackedEntity:
    entity_name = payload.entity_name.strip()
    if not entity_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="entity_name is required")
    if payload.tracked_entity_id:
        entity = session.scalar(
            select(TrackedEntity).where(
                TrackedEntity.id == payload.tracked_entity_id,
                TrackedEntity.workspace_code == workspace_code,
            ),
        )
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracked entity not found")
        return entity

    existing = session.scalar(
        select(TrackedEntity).where(
            TrackedEntity.workspace_code == workspace_code,
            func.lower(TrackedEntity.name) == entity_name.lower(),
        ),
    )
    if existing:
        if payload.entity_type:
            existing.entity_type = existing.entity_type or payload.entity_type
        if payload.entity_rank:
            existing.rank = existing.rank or payload.entity_rank
        return existing

    legacy_id = f"{workspace_code}:{hashlib.sha1(entity_name.lower().encode('utf-8')).hexdigest()[:16]}"
    entity = TrackedEntity(
        workspace_code=workspace_code,
        domain_code=domain_code,
        visibility_scope="workspace",
        sync_policy="outbox",
        legacy_system="current",
        legacy_table="tracked_entities",
        legacy_id=legacy_id,
        name=entity_name,
        entity_type=payload.entity_type,
        rank=payload.entity_rank,
        aliases_json=[],
        influence_score=0,
        notes="",
        metadata_json={"created_from": "report_item_entity_milestone"},
    )
    session.add(entity)
    session.flush()
    return entity


def _generated_news_board(generated_news: GeneratedNews) -> str:
    insight_json = generated_news.insight_json or {}
    board = insight_json.get("board") if isinstance(insight_json, dict) else None
    return str(board or generated_news.category or "")


def _apply_entity_milestone_update(
    milestone: EntityMilestone,
    payload: EntityMilestoneUpdate,
    current_user: User,
) -> None:
    fields = _schema_fields_set(payload)
    text_fields = {
        "event_type": "event_type",
        "event_brief": "event_brief",
        "event_content": "event_content",
        "impact_brief": "impact_brief",
        "impact": "impact",
        "timeline_brief": "timeline_brief",
        "source_url": "source_url",
        "source_name": "source_name",
        "board": "board",
        "importance_level": "importance_level",
    }
    if "event_title" in fields and payload.event_title is not None:
        title = payload.event_title.strip()
        if not title:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="event_title is required")
        milestone.title = title
    for payload_field, model_field in text_fields.items():
        if payload_field in fields:
            value = getattr(payload, payload_field)
            if value is not None:
                setattr(milestone, model_field, value.strip() if isinstance(value, str) else value)
    for field in ("event_time", "selected_for_timeline", "importance_score", "confidence_score"):
        if field in fields:
            value = getattr(payload, field)
            if value is not None:
                setattr(milestone, field, value)

    metadata = {**(milestone.metadata_json or {})}
    if payload.metadata_json is not None:
        metadata.update(payload.metadata_json)
    if payload.curation_status is not None:
        curation_status = payload.curation_status.strip()
        if curation_status not in {"draft", "confirmed", "revoked"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid curation_status")
        metadata["curation_status"] = curation_status
        if curation_status == "confirmed":
            milestone.selected_for_timeline = True
        if curation_status == "revoked":
            milestone.selected_for_timeline = False
    if payload.curation_note is not None:
        metadata["curation_note"] = payload.curation_note.strip()
    metadata["updated_by_user_id"] = current_user.id
    metadata["updated_at"] = utc_now().isoformat()
    milestone.metadata_json = metadata


def _milestone_curation_status(milestone: EntityMilestone) -> str:
    metadata = milestone.metadata_json or {}
    status_value = metadata.get("curation_status")
    if isinstance(status_value, str) and status_value:
        return status_value
    if milestone.legacy_system == "current":
        return "draft"
    return "imported"


def _report_item_generated_news(
    *,
    daily_item: DailyReportItem | None,
    weekly_item: WeeklyReportItem | None,
) -> GeneratedNews | None:
    if weekly_item and weekly_item.generated_news:
        return weekly_item.generated_news
    if weekly_item and weekly_item.daily_report_item:
        return weekly_item.daily_report_item.generated_news
    if daily_item:
        return daily_item.generated_news
    return None


def _report_item_title(
    *,
    daily_item: DailyReportItem | None,
    weekly_item: WeeklyReportItem | None,
) -> str:
    generated_news = _report_item_generated_news(daily_item=daily_item, weekly_item=weekly_item)
    return (
        (weekly_item.editor_title if weekly_item else None)
        or (daily_item.editor_title if daily_item else None)
        or (generated_news.title if generated_news else None)
        or "未命名情报"
    )


def _report_item_summary(
    *,
    daily_item: DailyReportItem | None,
    weekly_item: WeeklyReportItem | None,
) -> str:
    generated_news = _report_item_generated_news(daily_item=daily_item, weekly_item=weekly_item)
    return (
        (weekly_item.editor_summary if weekly_item else None)
        or (daily_item.editor_summary if daily_item else None)
        or (generated_news.summary if generated_news else None)
        or ""
    )


def _record_requirement_recommendation_feedback(
    session: Session,
    current_user: User,
    requirement: Requirement,
) -> None:
    feedback = _requirement_recommendation_feedback(requirement)
    if feedback is None:
        return
    news_item_ids = _requirement_feedback_news_item_ids(session, requirement)
    if not news_item_ids:
        return
    for news_item_id in news_item_ids:
        if _requirement_feedback_action_exists(
            session,
            requirement_id=requirement.id,
            news_item_id=news_item_id,
            outcome=feedback["outcome"],
        ):
            continue
        session.add(
            EditorialAction(
                user_id=current_user.id,
                object_type="news_item",
                object_id=news_item_id,
                action_type="requirement.feedback_to_recommendation",
                before_json={},
                after_json={
                    "requirement_id": requirement.id,
                    "requirement_status": requirement.status,
                    "outcome": feedback["outcome"],
                    "score_delta": feedback["score_delta"],
                    "source": "requirement_conclusion",
                },
                reason=feedback["reason"],
            ),
        )
    write_audit(
        session,
        current_user,
        "requirement.feedback_to_recommendation",
        "requirement",
        requirement.id,
        {
            "outcome": feedback["outcome"],
            "score_delta": feedback["score_delta"],
            "news_item_ids": news_item_ids,
        },
    )


def _requirement_recommendation_feedback(requirement: Requirement) -> dict[str, object] | None:
    metadata = requirement.metadata_json or {}
    configured = metadata.get("recommendation_feedback")
    if isinstance(configured, dict):
        outcome = str(configured.get("outcome") or "").strip().lower()
        if outcome in {"positive", "negative", "neutral"}:
            return {
                "outcome": outcome,
                "score_delta": _recommendation_feedback_score_delta(outcome, configured.get("score_delta")),
                "reason": str(configured.get("reason") or f"requirement {requirement.status}"),
            }
    if requirement.status in {"done", "resolved", "closed"}:
        return {"outcome": "positive", "score_delta": 80.0, "reason": f"requirement {requirement.status}"}
    if requirement.status in {"rejected", "canceled"}:
        return {"outcome": "negative", "score_delta": -40.0, "reason": f"requirement {requirement.status}"}
    return None


def _recommendation_feedback_score_delta(outcome: str, configured_delta: object) -> float:
    if configured_delta is not None:
        try:
            return max(-50.0, min(100.0, float(configured_delta)))
        except (TypeError, ValueError):
            pass
    if outcome == "positive":
        return 80.0
    if outcome == "negative":
        return -40.0
    return 0.0


def _requirement_feedback_news_item_ids(session: Session, requirement: Requirement) -> list[str]:
    news_item_ids: set[str] = set()
    for link in requirement.source_links or []:
        if link.news_item_id:
            news_item_ids.add(link.news_item_id)
        if link.insight and link.insight.news_item_id:
            news_item_ids.add(link.insight.news_item_id)
        if link.daily_report_item and link.daily_report_item.generated_news_id:
            generated = link.daily_report_item.generated_news
            if generated and generated.news_item_id:
                news_item_ids.add(generated.news_item_id)
        if link.weekly_report_item and link.weekly_report_item.generated_news_id:
            generated = link.weekly_report_item.generated_news
            if generated and generated.news_item_id:
                news_item_ids.add(generated.news_item_id)
        if link.raw_item_id:
            derived_news_ids = session.scalars(
                select(NewsItem.id).where(
                    NewsItem.raw_item_id == link.raw_item_id,
                    NewsItem.workspace_code == requirement.workspace_code,
                ),
            ).all()
            news_item_ids.update(derived_news_ids)
    return sorted(news_item_ids)


def _requirement_feedback_action_exists(
    session: Session,
    *,
    requirement_id: str,
    news_item_id: str,
    outcome: object,
) -> bool:
    actions = session.scalars(
        select(EditorialAction).where(
            EditorialAction.object_type == "news_item",
            EditorialAction.object_id == news_item_id,
            EditorialAction.action_type == "requirement.feedback_to_recommendation",
        ),
    ).all()
    for action in actions:
        after_json = action.after_json or {}
        if after_json.get("requirement_id") == requirement_id and after_json.get("outcome") == outcome:
            return True
    return False


def _requirement_create_has_source(payload: RequirementCreate) -> bool:
    return any(
        (
            payload.source_insight_id,
            payload.source_daily_report_item_id,
            payload.source_weekly_report_item_id,
            payload.source_entity_milestone_id,
            payload.source_historical_report_id,
            payload.source_historical_feedback_item_id,
            payload.source_news_item_id,
            payload.source_raw_item_id,
        ),
    )


def _build_requirement_source_link(
    session: Session,
    *,
    requirement: Requirement,
    payload: RequirementSourceLinkCreate,
) -> RequirementSourceLink:
    if not any(
        (
            payload.insight_id,
            payload.daily_report_item_id,
            payload.weekly_report_item_id,
            payload.entity_milestone_id,
            payload.historical_report_id,
            payload.historical_feedback_item_id,
            payload.news_item_id,
            payload.raw_item_id,
        ),
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="source reference is required")

    source_link = RequirementSourceLink(
        requirement_id=requirement.id,
        link_type=payload.link_type or "evidence",
        note=payload.note or "",
    )
    if payload.insight_id:
        insight = _load_insight_source(session, payload.insight_id)
        _assert_same_workspace(requirement, insight.workspace_code, "insight belongs to another workspace")
        source_link.insight_id = insight.id
        _merge_source_ids(source_link, news_item=insight.news_item)

    if payload.daily_report_item_id:
        daily_item = _load_daily_report_item_source(session, payload.daily_report_item_id)
        _assert_same_workspace(requirement, daily_item.workspace_code, "daily report item belongs to another workspace")
        source_link.daily_report_item_id = daily_item.id
        _merge_source_ids(source_link, generated_news=daily_item.generated_news)

    if payload.weekly_report_item_id:
        weekly_item = _load_weekly_report_item_source(session, payload.weekly_report_item_id)
        _assert_same_workspace(requirement, weekly_item.workspace_code, "weekly report item belongs to another workspace")
        source_link.weekly_report_item_id = weekly_item.id
        if weekly_item.daily_report_item_id:
            _set_source_id(source_link, "daily_report_item_id", weekly_item.daily_report_item_id)
        _merge_source_ids(source_link, generated_news=weekly_item.generated_news)
        if weekly_item.daily_report_item:
            _merge_source_ids(source_link, generated_news=weekly_item.daily_report_item.generated_news)

    if payload.entity_milestone_id:
        milestone = _load_entity_milestone_source(session, payload.entity_milestone_id)
        _assert_same_workspace(requirement, milestone.workspace_code, "entity milestone belongs to another workspace")
        source_link.entity_milestone_id = milestone.id
        if milestone.raw_item:
            _merge_source_ids(source_link, raw_item=milestone.raw_item)
        elif milestone.raw_item_id:
            _set_source_id(source_link, "raw_item_id", milestone.raw_item_id)

    if payload.historical_report_id:
        historical_report = _load_historical_report_source(session, payload.historical_report_id)
        _assert_same_workspace(requirement, historical_report.workspace_code, "historical report belongs to another workspace")
        source_link.historical_report_id = historical_report.id

    if payload.historical_feedback_item_id:
        feedback = _load_historical_feedback_source(session, payload.historical_feedback_item_id)
        _assert_same_workspace(requirement, feedback.workspace_code, "historical feedback belongs to another workspace")
        source_link.historical_feedback_item_id = feedback.id
        if feedback.raw_item:
            _merge_source_ids(source_link, raw_item=feedback.raw_item)
        elif feedback.raw_item_id:
            _set_source_id(source_link, "raw_item_id", feedback.raw_item_id)

    if payload.news_item_id:
        news_item = _load_news_item_source(session, payload.news_item_id)
        _assert_same_workspace(requirement, news_item.workspace_code, "news item belongs to another workspace")
        _merge_source_ids(source_link, news_item=news_item)

    if payload.raw_item_id:
        raw_item = _load_raw_item_source(session, payload.raw_item_id)
        _assert_same_workspace(requirement, raw_item.workspace_code, "raw item belongs to another workspace")
        _merge_source_ids(source_link, raw_item=raw_item)

    return source_link


def _load_news_item_for_insight(session: Session, news_item_id: str, workspace_code: str) -> NewsItem:
    news_item = _load_news_item_source(session, news_item_id)
    if news_item.workspace_code != workspace_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="news item belongs to another workspace")
    return news_item


def _resolve_insight_raw_item_id(news_item: NewsItem, raw_item_id: str | None) -> str | None:
    derived_raw_item_id = news_item.raw_item_id or (news_item.raw_item.id if news_item.raw_item else None)
    if raw_item_id and derived_raw_item_id and raw_item_id != derived_raw_item_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="raw item conflicts with news item")
    return raw_item_id or derived_raw_item_id


def _load_insight_source(session: Session, insight_id: str) -> Insight:
    insight = session.scalar(
        select(Insight)
        .options(
            selectinload(Insight.news_item).selectinload(NewsItem.raw_item).selectinload(RawItem.data_source),
        )
        .where(Insight.id == insight_id),
    )
    if insight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight source not found")
    return insight


def _load_daily_report_item_source(session: Session, daily_report_item_id: str) -> DailyReportItem:
    daily_item = session.scalar(
        select(DailyReportItem)
        .options(
            selectinload(DailyReportItem.generated_news)
            .selectinload(GeneratedNews.news_item)
            .selectinload(NewsItem.raw_item)
            .selectinload(RawItem.data_source),
        )
        .where(DailyReportItem.id == daily_report_item_id),
    )
    if daily_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report item source not found")
    return daily_item


def _load_weekly_report_item_source(session: Session, weekly_report_item_id: str) -> WeeklyReportItem:
    weekly_item = session.scalar(
        select(WeeklyReportItem)
        .options(
            selectinload(WeeklyReportItem.generated_news)
            .selectinload(GeneratedNews.news_item)
            .selectinload(NewsItem.raw_item)
            .selectinload(RawItem.data_source),
            selectinload(WeeklyReportItem.daily_report_item)
            .selectinload(DailyReportItem.generated_news)
            .selectinload(GeneratedNews.news_item)
            .selectinload(NewsItem.raw_item)
            .selectinload(RawItem.data_source),
        )
        .where(WeeklyReportItem.id == weekly_report_item_id),
    )
    if weekly_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly report item source not found")
    return weekly_item


def _load_news_item_source(session: Session, news_item_id: str) -> NewsItem:
    news_item = session.scalar(
        select(NewsItem)
        .options(
            selectinload(NewsItem.data_source),
            selectinload(NewsItem.raw_item).selectinload(RawItem.data_source),
        )
        .where(NewsItem.id == news_item_id),
    )
    if news_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News item source not found")
    return news_item


def _load_raw_item_source(session: Session, raw_item_id: str) -> RawItem:
    raw_item = session.scalar(
        select(RawItem).options(selectinload(RawItem.data_source)).where(RawItem.id == raw_item_id),
    )
    if raw_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw item source not found")
    return raw_item


def _load_entity_milestone_source(session: Session, milestone_id: str) -> EntityMilestone:
    milestone = session.scalar(
        select(EntityMilestone)
        .options(
            selectinload(EntityMilestone.tracked_entity),
            selectinload(EntityMilestone.raw_item).selectinload(RawItem.data_source),
        )
        .where(EntityMilestone.id == milestone_id),
    )
    if milestone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity milestone source not found")
    return milestone


def _load_historical_report_source(session: Session, report_id: str) -> HistoricalReport:
    report = session.get(HistoricalReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Historical report source not found")
    return report


def _load_historical_feedback_source(session: Session, feedback_id: str) -> HistoricalFeedbackItem:
    feedback = session.scalar(
        select(HistoricalFeedbackItem)
        .options(selectinload(HistoricalFeedbackItem.raw_item).selectinload(RawItem.data_source))
        .where(HistoricalFeedbackItem.id == feedback_id),
    )
    if feedback is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Historical feedback source not found")
    return feedback


def _assert_same_workspace(requirement: Requirement, workspace_code: str, detail: str) -> None:
    if workspace_code != requirement.workspace_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _merge_source_ids(
    source_link: RequirementSourceLink,
    *,
    generated_news: GeneratedNews | None = None,
    news_item: NewsItem | None = None,
    raw_item: RawItem | None = None,
) -> None:
    if generated_news is not None:
        _set_source_id(source_link, "news_item_id", generated_news.news_item_id)
        if generated_news.news_item is not None:
            news_item = generated_news.news_item
    if news_item is not None:
        _set_source_id(source_link, "news_item_id", news_item.id)
        if news_item.raw_item is not None:
            raw_item = news_item.raw_item
        elif news_item.raw_item_id:
            _set_source_id(source_link, "raw_item_id", news_item.raw_item_id)
    if raw_item is not None:
        _set_source_id(source_link, "raw_item_id", raw_item.id)


def _set_source_id(source_link: RequirementSourceLink, field: str, value: str | None) -> None:
    if not value:
        return
    existing = getattr(source_link, field)
    if existing and existing != value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"conflicting {field}")
    setattr(source_link, field, value)


def _insight_to_read(item: Insight) -> InsightRead:
    source_title, source_url, data_source_name = _insight_source_summary(item)
    return InsightRead(
        id=item.id,
        workspace_code=item.workspace_code,
        domain_code=item.domain_code,
        news_item_id=item.news_item_id,
        raw_item_id=item.raw_item_id,
        title=item.title,
        summary=item.summary,
        insight_type=item.insight_type,
        status=item.status,
        source_report_type=item.source_report_type,
        source_report_id=item.source_report_id,
        source_report_item_id=item.source_report_item_id,
        source_title=source_title,
        source_url=source_url,
        data_source_name=data_source_name,
        implication_count=len(item.implications or []),
        confidence_score=item.confidence_score,
        metadata_json=item.metadata_json or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _insight_source_summary(item: Insight) -> tuple[str, str | None, str | None]:
    news_item = item.news_item
    raw_item = item.raw_item or (news_item.raw_item if news_item is not None else None)
    data_source = None
    if news_item is not None and news_item.data_source is not None:
        data_source = news_item.data_source
    elif raw_item is not None:
        data_source = raw_item.data_source
    title = (
        (news_item.source_title if news_item is not None else None)
        or (raw_item.source_title if raw_item is not None else None)
        or item.title
    )
    url = (
        (news_item.source_url if news_item is not None else None)
        or (raw_item.source_url if raw_item is not None else None)
    )
    data_source_name = data_source.name if data_source is not None else None
    return title, url, data_source_name


def _strategic_implication_to_read(item: StrategicImplication) -> StrategicImplicationRead:
    return StrategicImplicationRead(
        id=item.id,
        workspace_code=item.workspace_code,
        domain_code=item.domain_code,
        insight_id=item.insight_id,
        insight_title=item.insight.title if item.insight else None,
        title=item.title,
        description=item.description,
        implication_type=item.implication_type,
        metadata_json=item.metadata_json or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _requirement_to_read(item: Requirement) -> RequirementRead:
    return RequirementRead(
        id=item.id,
        workspace_code=item.workspace_code,
        domain_code=item.domain_code,
        title=item.title,
        description=item.description,
        priority=item.priority,
        status=item.status,
        due_at=item.due_at,
        owner_user_id=item.owner_user_id,
        owner_name=item.owner.display_name if item.owner else None,
        source_count=len(item.source_links or []),
        source_links=[_requirement_source_link_to_read(link) for link in item.source_links or []],
        task_count=len(item.topic_tasks or []),
        metadata_json=item.metadata_json or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _requirement_source_link_to_read(link: RequirementSourceLink) -> RequirementSourceLinkRead:
    daily_item = link.daily_report_item
    weekly_item = link.weekly_report_item
    entity_milestone = link.entity_milestone
    historical_report = link.historical_report
    historical_feedback = link.historical_feedback_item
    generated_news = _source_generated_news(link)
    news_item = link.news_item or (generated_news.news_item if generated_news else None)
    raw_item = link.raw_item or (news_item.raw_item if news_item else None) or (
        entity_milestone.raw_item if entity_milestone else None
    ) or (
        historical_feedback.raw_item if historical_feedback else None
    )
    source_title = (
        (weekly_item.editor_title if weekly_item else None)
        or (daily_item.editor_title if daily_item else None)
        or (entity_milestone.title if entity_milestone else None)
        or (historical_report.title if historical_report else None)
        or (_historical_feedback_title(historical_feedback) if historical_feedback else None)
        or (generated_news.title if generated_news else None)
        or (link.insight.title if link.insight else None)
        or (news_item.source_title if news_item else None)
        or (raw_item.source_title if raw_item else None)
        or ""
    )
    source_url = (
        (entity_milestone.source_url if entity_milestone else None)
        or (generated_news.source_url if generated_news else None)
        or (news_item.source_url if news_item else None)
        or (raw_item.source_url if raw_item else None)
    )
    data_source = (
        raw_item.data_source
        if raw_item and raw_item.data_source
        else news_item.data_source
        if news_item and news_item.data_source
        else None
    )
    return RequirementSourceLinkRead(
        id=link.id,
        link_type=link.link_type,
        note=link.note,
        insight_id=link.insight_id,
        daily_report_item_id=link.daily_report_item_id,
        weekly_report_item_id=link.weekly_report_item_id,
        entity_milestone_id=link.entity_milestone_id,
        historical_report_id=link.historical_report_id,
        historical_feedback_item_id=link.historical_feedback_item_id,
        news_item_id=link.news_item_id,
        raw_item_id=link.raw_item_id,
        source_object_type=_source_object_type(link),
        source_title=source_title,
        source_url=source_url,
        data_source_name=data_source.name if data_source else None,
        created_at=link.created_at,
    )


def _historical_feedback_title(item: HistoricalFeedbackItem | None) -> str:
    if item is None:
        return ""
    text = item.reason or item.comment or item.feedback_type or item.legacy_id
    return f"{_feedback_kind_label(item.feedback_kind)}：{text}"


def _feedback_kind_label(value: str) -> str:
    if value == "quality_feedback":
        return "历史质量反馈"
    if value == "feedback":
        return "历史反馈"
    return value or "历史反馈"


def _source_generated_news(link: RequirementSourceLink) -> GeneratedNews | None:
    if link.weekly_report_item and link.weekly_report_item.generated_news:
        return link.weekly_report_item.generated_news
    if link.weekly_report_item and link.weekly_report_item.daily_report_item:
        return link.weekly_report_item.daily_report_item.generated_news
    if link.daily_report_item:
        return link.daily_report_item.generated_news
    return None


def _source_object_type(link: RequirementSourceLink) -> str:
    if link.historical_feedback_item_id:
        return "historical_feedback"
    if link.historical_report_id:
        return "historical_report"
    if link.entity_milestone_id:
        return "entity_milestone"
    if link.weekly_report_item_id:
        return "weekly_report_item"
    if link.daily_report_item_id:
        return "daily_report_item"
    if link.insight_id:
        return "insight"
    if link.news_item_id:
        return "news_item"
    if link.raw_item_id:
        return "raw_item"
    return "unknown"


def _topic_task_to_read(item: TopicTask) -> TopicTaskRead:
    metadata = item.metadata_json or {}
    return TopicTaskRead(
        id=item.id,
        workspace_code=item.workspace_code,
        domain_code=item.domain_code,
        requirement_id=item.requirement_id,
        requirement_title=item.requirement.title if item.requirement else None,
        title=item.title,
        description=item.description,
        status=item.status,
        due_at=item.due_at,
        is_overdue=_topic_task_is_overdue(item),
        blocked_reason=str(metadata.get("blocked_reason") or ""),
        assignee_user_id=item.assignee_user_id,
        assignee_name=item.assignee.display_name if item.assignee else None,
        requirement_source_count=len(item.requirement.source_links or []) if item.requirement else 0,
        requirement_source_links=[
            _requirement_source_link_to_read(link)
            for link in (item.requirement.source_links if item.requirement else [])
        ],
        metadata_json=metadata,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _topic_task_is_overdue(item: TopicTask) -> bool:
    if item.due_at is None or item.status in {"done", "canceled"}:
        return False
    due_at = item.due_at
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return due_at < utc_now()


def _sync_run_to_read(run: SyncRun) -> SyncRunRead:
    return SyncRunRead(
        id=run.id,
        package_id=run.package_id,
        source_instance_id=run.source_instance_id,
        target_instance_id=run.target_instance_id,
        direction=run.direction,
        status=run.status,
        counts_json=run.counts_json or {},
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


def _audit_log_to_read(item: AuditLog) -> AuditLogRead:
    return AuditLogRead(
        id=item.id,
        user_id=item.user_id,
        user_name=item.user.display_name if item.user else None,
        workspace_code=item.workspace_code,
        action=item.action,
        object_type=item.object_type,
        object_id=item.object_id,
        ip_address=item.ip_address,
        user_agent=item.user_agent,
        detail_json=item.detail_json or {},
        created_at=item.created_at,
    )


def _is_super_admin(user: User) -> bool:
    return "super_admin" in {role.code for role in user.roles}


def _historical_reports_statement(
    *,
    workspace_code: str,
    report_type: str | None,
    status_filter: str | None,
    start_date: date | None,
    end_date: date | None,
    q: str | None,
):
    statement = select(HistoricalReport).where(HistoricalReport.workspace_code == workspace_code)
    if report_type:
        statement = statement.where(HistoricalReport.report_type == report_type)
    if status_filter:
        statement = statement.where(HistoricalReport.status == status_filter)
    if start_date:
        statement = statement.where(
            HistoricalReport.period_start_at >= datetime.combine(start_date, time.min, tzinfo=timezone.utc),
        )
    if end_date:
        statement = statement.where(
            HistoricalReport.period_start_at <= datetime.combine(end_date, time.max, tzinfo=timezone.utc),
        )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                HistoricalReport.title.ilike(pattern),
                HistoricalReport.content.ilike(pattern),
            ),
        )
    return statement.order_by(
        HistoricalReport.period_start_at.desc().nullslast(),
        HistoricalReport.created_at.desc(),
    )


def _historical_report_to_list_item(report: HistoricalReport) -> HistoricalReportListItem:
    resolved_count, unresolved_count = report_ref_counts(report)
    return HistoricalReportListItem(
        id=report.id,
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        legacy_system=report.legacy_system,
        legacy_id=report.legacy_id,
        report_type=report.report_type,
        title=report.title,
        status=report.status,
        period_start_at=report.period_start_at,
        period_end_at=report.period_end_at,
        resolved_ref_count=resolved_count,
        unresolved_ref_count=unresolved_count,
        content_excerpt=_content_excerpt(report.content),
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def _historical_report_to_detail(report: HistoricalReport) -> HistoricalReportDetailRead:
    base = _historical_report_to_list_item(report).model_dump()
    return HistoricalReportDetailRead(
        **base,
        content=report.content,
        source_refs_json=report.source_refs_json or {},
        metadata_json=report.metadata_json or {},
    )


def _tracked_entity_to_list_item(session: Session, entity: TrackedEntity) -> TrackedEntityListItem:
    milestone_count = session.scalar(
        select(func.count()).select_from(EntityMilestone).where(EntityMilestone.tracked_entity_id == entity.id),
    ) or 0
    latest_event_time = session.scalar(
        select(func.max(EntityMilestone.event_time)).where(EntityMilestone.tracked_entity_id == entity.id),
    )
    return TrackedEntityListItem(
        id=entity.id,
        workspace_code=entity.workspace_code,
        domain_code=entity.domain_code,
        legacy_system=entity.legacy_system,
        legacy_id=entity.legacy_id,
        name=entity.name,
        entity_type=entity.entity_type,
        rank=entity.rank,
        aliases_json=entity.aliases_json or [],
        influence_score=entity.influence_score,
        milestone_count=int(milestone_count),
        latest_event_time=latest_event_time,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _entity_milestones_statement(
    *,
    workspace_code: str,
    tracked_entity_id: str | None,
    entity_type: str | None,
    event_type: str | None,
    importance_level: str | None,
    board: str | None,
    start_date: date | None,
    end_date: date | None,
    q: str | None,
):
    statement = (
        select(EntityMilestone)
        .join(EntityMilestone.tracked_entity)
        .options(selectinload(EntityMilestone.tracked_entity))
        .where(EntityMilestone.workspace_code == workspace_code)
    )
    if tracked_entity_id:
        statement = statement.where(EntityMilestone.tracked_entity_id == tracked_entity_id)
    if entity_type:
        statement = statement.where(TrackedEntity.entity_type == entity_type)
    if event_type:
        statement = statement.where(EntityMilestone.event_type == event_type)
    if importance_level:
        statement = statement.where(EntityMilestone.importance_level == importance_level)
    if board:
        statement = statement.where(EntityMilestone.board == board)
    if start_date:
        statement = statement.where(
            EntityMilestone.event_time >= datetime.combine(start_date, time.min, tzinfo=timezone.utc),
        )
    if end_date:
        statement = statement.where(
            EntityMilestone.event_time <= datetime.combine(end_date, time.max, tzinfo=timezone.utc),
        )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                EntityMilestone.title.ilike(pattern),
                EntityMilestone.event_content.ilike(pattern),
                EntityMilestone.impact.ilike(pattern),
                EntityMilestone.timeline_brief.ilike(pattern),
                TrackedEntity.name.ilike(pattern),
            ),
        )
    return statement.order_by(
        EntityMilestone.event_time.desc().nullslast(),
        EntityMilestone.importance_score.desc(),
        EntityMilestone.created_at.desc(),
    )


def _entity_milestone_to_list_item(milestone: EntityMilestone) -> EntityMilestoneListItem:
    article_ref_resolved, report_ref_resolved = milestone_ref_flags(milestone)
    entity = milestone.tracked_entity
    return EntityMilestoneListItem(
        id=milestone.id,
        workspace_code=milestone.workspace_code,
        domain_code=milestone.domain_code,
        legacy_system=milestone.legacy_system,
        legacy_id=milestone.legacy_id,
        tracked_entity_id=milestone.tracked_entity_id,
        entity_name=entity.name if entity else "",
        entity_type=entity.entity_type if entity else "",
        legacy_article_id=milestone.legacy_article_id,
        legacy_report_id=milestone.legacy_report_id,
        raw_item_id=milestone.raw_item_id,
        historical_report_id=milestone.historical_report_id,
        event_time=milestone.event_time,
        event_type=milestone.event_type,
        title=milestone.title,
        timeline_brief=milestone.timeline_brief,
        source_url=milestone.source_url,
        source_name=milestone.source_name,
        board=milestone.board,
        selected_for_timeline=milestone.selected_for_timeline,
        curation_status=_milestone_curation_status(milestone),
        importance_score=milestone.importance_score,
        importance_level=milestone.importance_level,
        article_ref_resolved=article_ref_resolved,
        report_ref_resolved=report_ref_resolved,
        created_at=milestone.created_at,
        updated_at=milestone.updated_at,
    )


def _entity_milestone_to_detail(milestone: EntityMilestone) -> EntityMilestoneDetailRead:
    base = _entity_milestone_to_list_item(milestone).model_dump()
    legacy_refs = _milestone_legacy_refs(milestone)
    return EntityMilestoneDetailRead(
        **base,
        event_content=milestone.event_content,
        impact=milestone.impact,
        event_brief=milestone.event_brief,
        impact_brief=milestone.impact_brief,
        confidence_score=milestone.confidence_score,
        event_dedupe_key=milestone.event_dedupe_key,
        legacy_refs=legacy_refs,
        metadata_json=milestone.metadata_json or {},
    )


def _historical_feedback_to_list_item(item: HistoricalFeedbackItem) -> HistoricalFeedbackListItem:
    return HistoricalFeedbackListItem(
        id=item.id,
        workspace_code=item.workspace_code,
        domain_code=item.domain_code,
        legacy_system=item.legacy_system,
        legacy_table=item.legacy_table,
        legacy_id=item.legacy_id,
        legacy_article_id=item.legacy_article_id,
        raw_item_id=item.raw_item_id,
        feedback_kind=item.feedback_kind,
        user_name=item.user_name,
        feedback_type=item.feedback_type,
        reason=item.reason,
        comment=item.comment,
        feedback_at=item.feedback_at,
        article_ref_resolved=feedback_ref_flag(item),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _historical_job_run_to_list_item(run: HistoricalJobRun) -> HistoricalJobRunListItem:
    return HistoricalJobRunListItem(
        id=run.id,
        workspace_code=run.workspace_code,
        domain_code=run.domain_code,
        legacy_system=run.legacy_system,
        legacy_table=run.legacy_table,
        legacy_id=run.legacy_id,
        job_type=run.job_type,
        status=run.status,
        message=run.message,
        started_at=run.started_at,
        ended_at=run.ended_at,
        total_sources=run.total_sources,
        processed_sources=run.processed_sources,
        inserted_count=run.inserted_count,
        failed_count=run.failed_count,
        details_json=run.details_json or {},
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _milestone_legacy_refs(milestone: EntityMilestone) -> dict:
    metadata = milestone.metadata_json or {}
    refs = metadata.get("legacy_refs")
    return refs if isinstance(refs, dict) else {}


def _content_excerpt(content: str, limit: int = 180) -> str:
    compact = " ".join((content or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."
