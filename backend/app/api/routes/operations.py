from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import get_current_user, require_super_admin
from app.auth.service import write_audit
from app.core.database import get_db_session
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
from app.models.feedback import AuditLog
from app.models.identity import User
from app.models.legacy import EntityMilestone, HistoricalFeedbackItem, HistoricalJobRun, HistoricalReport, TrackedEntity
from app.models.strategy import Requirement, TopicTask
from app.models.sync import SyncOutbox, SyncRun
from app.schemas.operations import (
    AuditLogRead,
    EntityMilestoneDetailRead,
    EntityMilestoneListItem,
    EntityTimelineSummaryRead,
    HistoricalFeedbackListItem,
    HistoricalJobRunListItem,
    HistoricalReportDetailRead,
    HistoricalReportListItem,
    HistoricalReportSummaryRead,
    LegacyImportGapItemRead,
    LegacyImportSummaryRead,
    QualityArchiveSummaryRead,
    RequirementCreate,
    RequirementRead,
    RequirementUpdate,
    SyncRunCreate,
    SyncRunRead,
    TopicTaskCreate,
    TopicTaskRead,
    TopicTaskUpdate,
    TrackedEntityListItem,
)

router = APIRouter(prefix="/api", tags=["operations"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)


@router.get("/requirements", response_model=list[RequirementRead])
def list_requirements(
    workspace_code: str = Query(default="planning_intel"),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[RequirementRead]:
    statement = (
        select(Requirement)
        .options(
            selectinload(Requirement.owner),
            selectinload(Requirement.source_links),
            selectinload(Requirement.topic_tasks),
        )
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
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> RequirementRead:
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
    write_audit(
        session,
        current_user,
        "requirement.create",
        "requirement",
        requirement.id,
        {"workspace_code": requirement.workspace_code, "title": requirement.title},
    )
    session.commit()
    return _requirement_to_read(_load_requirement(session, requirement.id))


@router.patch("/requirements/{requirement_id}", response_model=RequirementRead)
def update_requirement(
    requirement_id: str,
    payload: RequirementUpdate,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> RequirementRead:
    requirement = _load_requirement(session, requirement_id)
    for field in ("title", "description", "priority", "status", "due_at", "owner_user_id", "metadata_json"):
        value = getattr(payload, field)
        if value is not None:
            setattr(requirement, field, value)
    write_audit(
        session,
        current_user,
        "requirement.update",
        "requirement",
        requirement.id,
        {"status": requirement.status, "priority": requirement.priority},
    )
    session.commit()
    return _requirement_to_read(_load_requirement(session, requirement.id))


@router.get("/topic-tasks", response_model=list[TopicTaskRead])
def list_topic_tasks(
    workspace_code: str = Query(default="planning_intel"),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[TopicTaskRead]:
    statement = (
        select(TopicTask)
        .options(selectinload(TopicTask.assignee), selectinload(TopicTask.requirement))
        .where(TopicTask.workspace_code == workspace_code)
        .order_by(TopicTask.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        statement = statement.where(TopicTask.status == status_filter)
    return [_topic_task_to_read(item) for item in session.scalars(statement).all()]


@router.post("/topic-tasks", response_model=TopicTaskRead)
def create_topic_task(
    payload: TopicTaskCreate,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> TopicTaskRead:
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
    session.commit()
    return _topic_task_to_read(_load_topic_task(session, task.id))


@router.patch("/topic-tasks/{task_id}", response_model=TopicTaskRead)
def update_topic_task(
    task_id: str,
    payload: TopicTaskUpdate,
    current_user: User = SUPER_ADMIN,
    session: Session = DB_SESSION,
) -> TopicTaskRead:
    task = _load_topic_task(session, task_id)
    for field in ("requirement_id", "title", "description", "status", "due_at", "assignee_user_id", "metadata_json"):
        value = getattr(payload, field)
        if value is not None:
            setattr(task, field, value)
    write_audit(
        session,
        current_user,
        "topic_task.update",
        "topic_task",
        task.id,
        {"status": task.status},
    )
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
    pending_count = session.scalar(
        select(func.count()).select_from(SyncOutbox).where(SyncOutbox.status == "pending"),
    ) or 0
    now = utc_now()
    run = SyncRun(
        package_id=f"sync_{now.strftime('%Y%m%d%H%M%S%f')}",
        source_instance_id=payload.source_instance_id,
        target_instance_id=payload.target_instance_id,
        direction=payload.direction,
        status="completed",
        counts_json={"pending_outbox": int(pending_count), "exported": int(pending_count), "conflicts": 0},
        started_at=now,
        completed_at=now,
    )
    session.add(run)
    session.flush()
    write_audit(
        session,
        current_user,
        "sync_run.create",
        "sync_run",
        run.id,
        {"package_id": run.package_id, "direction": run.direction},
    )
    session.commit()
    return _sync_run_to_read(session.get(SyncRun, run.id) or run)


@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    action: str | None = Query(default=None),
    object_type: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[AuditLogRead]:
    statement = (
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if action:
        statement = statement.where(AuditLog.action == action)
    if object_type:
        statement = statement.where(AuditLog.object_type == object_type)
    return [_audit_log_to_read(item) for item in session.scalars(statement).all()]


@router.get("/legacy-import/summary", response_model=LegacyImportSummaryRead)
def get_legacy_import_summary(
    workspace_code: str = Query(default=LEGACY_WORKSPACE_CODE),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> LegacyImportSummaryRead:
    summary = build_legacy_import_summary(session, workspace_code=workspace_code)
    return LegacyImportSummaryRead.model_validate(summary.to_dict())


@router.get("/legacy-import/gaps", response_model=list[LegacyImportGapItemRead])
def list_legacy_import_gaps(
    workspace_code: str = Query(default=LEGACY_WORKSPACE_CODE),
    kind: str = Query(default="all", pattern="^(all|historical_reports|entity_milestones|historical_feedback)$"),
    limit: int = Query(default=50, ge=1, le=300),
    _: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[LegacyImportGapItemRead]:
    gaps = list_legacy_import_gap_items(session, workspace_code=workspace_code, kind=kind, limit=limit)
    return [LegacyImportGapItemRead.model_validate(item.to_dict()) for item in gaps]


@router.get("/quality-archive/summary", response_model=QualityArchiveSummaryRead)
def get_quality_archive_summary(
    workspace_code: str = Query(default=LEGACY_WORKSPACE_CODE),
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
    workspace_code: str = Query(default=LEGACY_WORKSPACE_CODE),
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
    workspace_code: str = Query(default=LEGACY_WORKSPACE_CODE),
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
    workspace_code: str = Query(default="legacy_tech_insight_loop"),
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
    workspace_code: str = Query(default="legacy_tech_insight_loop"),
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
    workspace_code: str = Query(default="legacy_tech_insight_loop"),
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
    workspace_code: str = Query(default="legacy_tech_insight_loop"),
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
    workspace_code: str = Query(default="legacy_tech_insight_loop"),
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


def _load_requirement(session: Session, requirement_id: str) -> Requirement:
    requirement = session.scalar(
        select(Requirement)
        .options(
            selectinload(Requirement.owner),
            selectinload(Requirement.source_links),
            selectinload(Requirement.topic_tasks),
        )
        .where(Requirement.id == requirement_id),
    )
    if requirement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")
    return requirement


def _load_topic_task(session: Session, task_id: str) -> TopicTask:
    task = session.scalar(
        select(TopicTask)
        .options(selectinload(TopicTask.assignee), selectinload(TopicTask.requirement))
        .where(TopicTask.id == task_id),
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic task not found")
    return task


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
        task_count=len(item.topic_tasks or []),
        metadata_json=item.metadata_json or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _topic_task_to_read(item: TopicTask) -> TopicTaskRead:
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
        assignee_user_id=item.assignee_user_id,
        assignee_name=item.assignee.display_name if item.assignee else None,
        metadata_json=item.metadata_json or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


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
        action=item.action,
        object_type=item.object_type,
        object_id=item.object_id,
        ip_address=item.ip_address,
        user_agent=item.user_agent,
        detail_json=item.detail_json or {},
        created_at=item.created_at,
    )


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
