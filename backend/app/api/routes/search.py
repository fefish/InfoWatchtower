from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.routes.auth import assert_workspace_member, get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.models.content import DataSource, GeneratedNews, NewsItem
from app.models.export import ExportJob, ExportJobItem
from app.models.feedback import Comment
from app.models.identity import User
from app.models.legacy import EntityMilestone, HistoricalReport, TrackedEntity
from app.models.reports import DailyReport, DailyReportItem, ReportRendition, WeeklyReport, WeeklyReportItem
from app.models.strategy import Requirement, TopicTask
from app.models.sync import SyncConflict, SyncRun
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.schemas.search import SearchRead, SearchResultRead

router = APIRouter(prefix="/api", tags=["search"])

SEARCH_TYPES: set[str] = {
    "daily_report",
    "daily_report_item",
    "weekly_report",
    "weekly_report_item",
    "news_item",
    "generated_news",
    "data_source",
    "tracked_entity",
    "entity_milestone",
    "historical_report",
    "requirement",
    "topic_task",
    "comment",
    "export_job",
    "export_job_item",
    "report_rendition",
    "sync_run",
    "sync_conflict",
}

SUPER_ADMIN_SEARCH_TYPES = {"sync_conflict", "sync_run"}


@dataclass
class SearchCandidate:
    object_type: str
    object_id: str
    title: str
    summary: str
    matched_fields: list[str]
    route: str
    score: float
    updated_at: datetime | None


@router.get("/search", response_model=SearchRead)
def search_workspace(
    q: str = Query(...),
    workspace_code: str = Query(...),
    types: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SearchRead:
    del cursor
    query = q.strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="q is required")
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")

    selected_types = _selected_types(types)
    if not settings.capability_ingestion:
        selected_types.discard("data_source")
    admin_only_types = selected_types & SUPER_ADMIN_SEARCH_TYPES
    if admin_only_types and not _is_super_admin(current_user):
        if types:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires super_admin")
        selected_types -= SUPER_ADMIN_SEARCH_TYPES

    per_type_limit = max(limit, 20)
    candidates: list[SearchCandidate] = []
    collectors: dict[str, Callable[[], list[SearchCandidate]]] = {
        "daily_report": lambda: _search_daily_reports(session, workspace_code, query, per_type_limit),
        "daily_report_item": lambda: _search_daily_report_items(session, workspace_code, query, per_type_limit),
        "weekly_report": lambda: _search_weekly_reports(session, workspace_code, query, per_type_limit),
        "weekly_report_item": lambda: _search_weekly_report_items(session, workspace_code, query, per_type_limit),
        "news_item": lambda: _search_news_items(session, workspace_code, query, per_type_limit),
        "generated_news": lambda: _search_generated_news(session, workspace_code, query, per_type_limit),
        "data_source": lambda: _search_data_sources(session, workspace_code, query, per_type_limit),
        "tracked_entity": lambda: _search_tracked_entities(session, workspace_code, query, per_type_limit),
        "entity_milestone": lambda: _search_entity_milestones(session, workspace_code, query, per_type_limit),
        "historical_report": lambda: _search_historical_reports(session, workspace_code, query, per_type_limit),
        "requirement": lambda: _search_requirements(session, workspace_code, query, per_type_limit),
        "topic_task": lambda: _search_topic_tasks(session, workspace_code, query, per_type_limit),
        "comment": lambda: _search_comments(session, workspace_code, query, per_type_limit),
        "export_job": lambda: _search_export_jobs(session, workspace_code, query, per_type_limit),
        "export_job_item": lambda: _search_export_job_items(session, workspace_code, query, per_type_limit),
        "report_rendition": lambda: _search_report_renditions(session, workspace_code, query, per_type_limit),
        "sync_run": lambda: _search_sync_runs(session, query, per_type_limit),
        "sync_conflict": lambda: _search_sync_conflicts(session, query, per_type_limit),
    }
    for search_type in selected_types:
        candidates.extend(collectors[search_type]())

    candidates.sort(
        key=lambda item: (
            -item.score,
            -(item.updated_at.timestamp() if item.updated_at else 0),
            item.object_type,
            item.object_id,
        ),
    )
    return SearchRead(
        query=query,
        workspace_code=workspace_code,
        results=[
            SearchResultRead(
                object_type=item.object_type,
                object_id=item.object_id,
                title=item.title,
                summary=item.summary,
                matched_fields=item.matched_fields,
                highlight=_highlight(item, query),
                route=item.route,
                score=item.score,
                updated_at=item.updated_at,
            )
            for item in candidates[:limit]
        ],
        next_cursor=None,
    )


def _selected_types(types: str | None) -> set[str]:
    if not types:
        return set(SEARCH_TYPES)
    selected = {item.strip() for item in types.split(",") if item.strip()}
    unknown = selected - SEARCH_TYPES
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported search types: {', '.join(sorted(unknown))}",
        )
    return selected


def _is_super_admin(user: User) -> bool:
    return "super_admin" in {role.code for role in user.roles}


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches(query: str, fields: dict[str, str | None]) -> list[str]:
    needle = query.casefold()
    return [name for name, value in fields.items() if needle in _text(value).casefold()]


def _score(query: str, fields: dict[str, str | None], matched_fields: list[str]) -> float:
    if not matched_fields:
        return 0.0
    needle = query.casefold()
    score = 0.35 + 0.08 * len(matched_fields)
    title = fields.get("title") or fields.get("name") or ""
    if needle in title.casefold():
        score += 0.45
        if title.casefold().startswith(needle):
            score += 0.12
    return round(min(score, 0.99), 4)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _compact(value: str | None, limit: int = 140) -> str:
    text = " ".join(_text(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}..."


def _candidate(
    *,
    object_type: str,
    object_id: str,
    title: str | None,
    summary: str | None,
    fields: dict[str, str | None],
    route: str,
    updated_at: datetime | None,
    query: str,
) -> SearchCandidate:
    matched_fields = _matches(query, fields)
    return SearchCandidate(
        object_type=object_type,
        object_id=object_id,
        title=_text(title).strip() or "未命名对象",
        summary=_compact(summary),
        matched_fields=matched_fields,
        route=route,
        score=_score(query, fields, matched_fields),
        updated_at=updated_at,
    )


def _where_text(query: str, *columns):
    pattern = _like(query)
    return or_(*(column.ilike(pattern, escape="\\") for column in columns))


def _search_daily_reports(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(DailyReport)
        .where(
            DailyReport.workspace_code == workspace_code,
            _where_text(query, DailyReport.title, DailyReport.summary, DailyReport.day_key),
        )
        .order_by(DailyReport.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="daily_report",
            object_id=item.id,
            title=item.title,
            summary=item.summary,
            fields={"title": item.title, "summary": item.summary, "day_key": item.day_key},
            route=f"/daily-reports?report_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_daily_report_items(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.execute(
        select(DailyReportItem, DailyReport, GeneratedNews)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .join(GeneratedNews, GeneratedNews.id == DailyReportItem.generated_news_id)
        .where(
            DailyReport.workspace_code == workspace_code,
            _where_text(
                query,
                DailyReportItem.editor_title,
                DailyReportItem.editor_summary,
                DailyReportItem.editor_key_points,
                GeneratedNews.title,
                GeneratedNews.summary,
                GeneratedNews.key_points,
            ),
        )
        .order_by(DailyReportItem.updated_at.desc())
        .limit(limit),
    ).all()
    results: list[SearchCandidate] = []
    for item, report, generated in rows:
        title = item.editor_title or generated.title
        summary = item.editor_summary or generated.summary
        results.append(
            _candidate(
                object_type="daily_report_item",
                object_id=item.id,
                title=title,
                summary=summary,
                fields={
                    "title": title,
                    "summary": summary,
                    "key_points": item.editor_key_points or generated.key_points,
                    "day_key": report.day_key,
                },
                route=f"/daily-reports?item_id={item.id}",
                updated_at=item.updated_at,
                query=query,
            ),
        )
    return results


def _search_weekly_reports(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(WeeklyReport)
        .where(
            WeeklyReport.workspace_code == workspace_code,
            _where_text(query, WeeklyReport.title, WeeklyReport.summary, WeeklyReport.week_key),
        )
        .order_by(WeeklyReport.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="weekly_report",
            object_id=item.id,
            title=item.title,
            summary=item.summary,
            fields={"title": item.title, "summary": item.summary, "week_key": item.week_key},
            route=f"/weekly-reports?report_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_weekly_report_items(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.execute(
        select(WeeklyReportItem, WeeklyReport, GeneratedNews)
        .join(WeeklyReport, WeeklyReport.id == WeeklyReportItem.weekly_report_id)
        .outerjoin(GeneratedNews, GeneratedNews.id == WeeklyReportItem.generated_news_id)
        .where(
            WeeklyReport.workspace_code == workspace_code,
            _where_text(
                query,
                WeeklyReportItem.editor_title,
                WeeklyReportItem.editor_summary,
                GeneratedNews.title,
                GeneratedNews.summary,
                GeneratedNews.key_points,
                WeeklyReport.week_key,
            ),
        )
        .order_by(WeeklyReportItem.updated_at.desc())
        .limit(limit),
    ).all()
    results: list[SearchCandidate] = []
    for item, report, generated in rows:
        title = item.editor_title or (generated.title if generated else "")
        summary = item.editor_summary or (generated.summary if generated else "")
        key_points = generated.key_points if generated else ""
        results.append(
            _candidate(
                object_type="weekly_report_item",
                object_id=item.id,
                title=title,
                summary=summary,
                fields={
                    "title": title,
                    "summary": summary,
                    "key_points": key_points,
                    "week_key": report.week_key,
                },
                route=f"/weekly-reports?report_id={report.id}&item_id={item.id}",
                updated_at=item.updated_at,
                query=query,
            ),
        )
    return results


def _search_news_items(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(NewsItem)
        .where(
            NewsItem.workspace_code == workspace_code,
            NewsItem.active.is_(True),
            _where_text(query, NewsItem.source_title, NewsItem.normalized_title, NewsItem.summary, NewsItem.content),
        )
        .order_by(NewsItem.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="news_item",
            object_id=item.id,
            title=item.normalized_title or item.source_title,
            summary=item.summary,
            fields={"title": item.normalized_title or item.source_title, "summary": item.summary, "content": item.content},
            route=f"/news?news_item_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_generated_news(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.execute(
        select(GeneratedNews, DailyReportItem)
        .outerjoin(DailyReportItem, DailyReportItem.generated_news_id == GeneratedNews.id)
        .where(
            GeneratedNews.workspace_code == workspace_code,
            _where_text(query, GeneratedNews.title, GeneratedNews.summary, GeneratedNews.key_points),
        )
        .order_by(GeneratedNews.updated_at.desc())
        .limit(limit),
    ).all()
    results: list[SearchCandidate] = []
    for item, report_item in rows:
        route = f"/daily-reports?item_id={report_item.id}" if report_item else f"/news?news_item_id={item.news_item_id}"
        results.append(
            _candidate(
                object_type="generated_news",
                object_id=item.id,
                title=item.title,
                summary=item.summary,
                fields={"title": item.title, "summary": item.summary, "key_points": item.key_points},
                route=route,
                updated_at=item.updated_at,
                query=query,
            ),
        )
    return results


def _search_data_sources(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.execute(
        select(DataSource)
        .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
        .join(Workspace, Workspace.id == WorkspaceSourceLink.workspace_id)
        .where(
            Workspace.code == workspace_code,
            WorkspaceSourceLink.enabled.is_(True),
            DataSource.enabled.is_(True),
            _where_text(query, DataSource.name, DataSource.url, DataSource.source_type),
        )
        .order_by(DataSource.updated_at.desc())
        .limit(limit),
    ).scalars().all()
    return [
        _candidate(
            object_type="data_source",
            object_id=item.id,
            title=item.name,
            summary=item.url or item.source_type,
            fields={"name": item.name, "url": item.url, "source_type": item.source_type},
            route=f"/sources/{item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_tracked_entities(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(TrackedEntity)
        .where(
            TrackedEntity.workspace_code == workspace_code,
            _where_text(query, TrackedEntity.name, TrackedEntity.entity_type, TrackedEntity.notes),
        )
        .order_by(TrackedEntity.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="tracked_entity",
            object_id=item.id,
            title=item.name,
            summary=item.notes or item.entity_type,
            fields={"title": item.name, "summary": item.notes, "entity_type": item.entity_type},
            route=f"/entity-milestones?entity_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_entity_milestones(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(EntityMilestone)
        .where(
            EntityMilestone.workspace_code == workspace_code,
            _where_text(
                query,
                EntityMilestone.title,
                EntityMilestone.event_content,
                EntityMilestone.event_brief,
                EntityMilestone.impact,
            ),
        )
        .order_by(EntityMilestone.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="entity_milestone",
            object_id=item.id,
            title=item.title,
            summary=item.event_brief or item.event_content,
            fields={"title": item.title, "summary": item.event_brief or item.event_content, "impact": item.impact},
            route=f"/entity-milestones?milestone_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_historical_reports(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(HistoricalReport)
        .where(
            HistoricalReport.workspace_code == workspace_code,
            _where_text(query, HistoricalReport.title, HistoricalReport.content, HistoricalReport.report_type),
        )
        .order_by(HistoricalReport.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="historical_report",
            object_id=item.id,
            title=item.title,
            summary=item.content,
            fields={"title": item.title, "summary": item.content, "report_type": item.report_type},
            route=f"/historical-reports?id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_requirements(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(Requirement)
        .where(
            Requirement.workspace_code == workspace_code,
            _where_text(query, Requirement.title, Requirement.description, Requirement.status, Requirement.priority),
        )
        .order_by(Requirement.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="requirement",
            object_id=item.id,
            title=item.title,
            summary=item.description,
            fields={"title": item.title, "summary": item.description, "status": item.status, "priority": item.priority},
            route=f"/requirements?requirement_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_topic_tasks(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(TopicTask)
        .where(
            TopicTask.workspace_code == workspace_code,
            _where_text(query, TopicTask.title, TopicTask.description, TopicTask.status),
        )
        .order_by(TopicTask.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="topic_task",
            object_id=item.id,
            title=item.title,
            summary=item.description,
            fields={"title": item.title, "summary": item.description, "status": item.status},
            route=f"/tasks?task_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_comments(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.execute(
        select(Comment, DailyReportItem)
        .join(DailyReportItem, DailyReportItem.id == Comment.daily_report_item_id)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .where(
            DailyReport.workspace_code == workspace_code,
            Comment.status == "visible",
            _where_text(query, Comment.body),
        )
        .order_by(Comment.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="comment",
            object_id=comment.id,
            title=_compact(comment.body, limit=60),
            summary=comment.body,
            fields={"body": comment.body},
            route=f"/daily-reports?item_id={report_item.id}&comment_id={comment.id}",
            updated_at=comment.updated_at,
            query=query,
        )
        for comment, report_item in rows
    ]


def _search_export_jobs(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(ExportJob)
        .where(
            ExportJob.workspace_code == workspace_code,
            _where_text(query, ExportJob.id, ExportJob.export_type, ExportJob.status, ExportJob.file_path),
        )
        .order_by(ExportJob.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="export_job",
            object_id=item.id,
            title=f"{item.export_type} · {item.status}",
            summary=_export_job_summary(item),
            fields={
                "title": f"{item.export_type} {item.status}",
                "id": item.id,
                "file_path": item.file_path,
                "summary": _export_job_summary(item),
            },
            route=f"/exports?export_job_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_export_job_items(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.execute(
        select(ExportJobItem, ExportJob, GeneratedNews)
        .join(ExportJob, ExportJob.id == ExportJobItem.export_job_id)
        .join(GeneratedNews, GeneratedNews.id == ExportJobItem.generated_news_id)
        .where(
            ExportJob.workspace_code == workspace_code,
            _where_text(
                query,
                ExportJobItem.id,
                ExportJobItem.sql_table,
                ExportJobItem.sql_text,
                ExportJobItem.status,
                ExportJob.export_type,
                ExportJob.status,
                GeneratedNews.title,
                GeneratedNews.category,
            ),
        )
        .order_by(ExportJobItem.updated_at.desc())
        .limit(limit),
    ).all()
    results: list[SearchCandidate] = []
    for item, job, generated in rows:
        title = f"{job.export_type} #{item.sql_sequence} · {item.sql_table}"
        summary = generated.title or item.sql_text
        results.append(
            _candidate(
                object_type="export_job_item",
                object_id=item.id,
                title=title,
                summary=summary,
                fields={
                    "title": title,
                    "summary": summary,
                    "sql_table": item.sql_table,
                    "sql_text": item.sql_text,
                    "status": item.status,
                    "category": generated.category,
                },
                route=f"/exports?export_job_id={job.id}&export_job_item_id={item.id}",
                updated_at=item.updated_at,
                query=query,
            ),
        )
    return results


def _search_report_renditions(session: Session, workspace_code: str, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(ReportRendition)
        .where(
            ReportRendition.workspace_code == workspace_code,
            _where_text(
                query,
                ReportRendition.id,
                ReportRendition.title,
                ReportRendition.report_type,
                ReportRendition.format_code,
                ReportRendition.status,
                ReportRendition.generated_by,
            ),
        )
        .order_by(ReportRendition.updated_at.desc())
        .limit(limit),
    ).all()
    results: list[SearchCandidate] = []
    for item in rows:
        summary = _report_rendition_summary(item)
        results.append(
            _candidate(
                object_type="report_rendition",
                object_id=item.id,
                title=item.title,
                summary=summary,
                fields={
                    "id": item.id,
                    "title": item.title,
                    "report_type": item.report_type,
                    "format_code": item.format_code,
                    "status": item.status,
                    "generated_by": item.generated_by,
                    "summary": summary,
                },
                route=_report_rendition_route(item),
                updated_at=item.updated_at,
                query=query,
            ),
        )
    return results


def _report_rendition_route(item: ReportRendition) -> str:
    page = "/weekly-reports" if item.report_type == "weekly" else "/daily-reports"
    return f"{page}?report_id={item.report_id}&rendition_id={item.id}&format_code={item.format_code}"


def _report_rendition_summary(item: ReportRendition) -> str:
    summary = item.summary_json or {}
    period = summary.get("period_key") or item.report_type
    item_total = summary.get("item_total")
    source_total = summary.get("source_total")
    parts = [str(period), item.format_code, item.status]
    if item_total is not None:
        parts.append(f"{item_total} items")
    if source_total is not None:
        parts.append(f"{source_total} sources")
    return " · ".join(parts)


def _search_sync_runs(session: Session, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.scalars(
        select(SyncRun)
        .where(
            _where_text(
                query,
                SyncRun.id,
                SyncRun.package_id,
                SyncRun.source_instance_id,
                SyncRun.target_instance_id,
                SyncRun.direction,
                SyncRun.status,
            ),
        )
        .order_by(SyncRun.updated_at.desc())
        .limit(limit),
    ).all()
    return [
        _candidate(
            object_type="sync_run",
            object_id=item.id,
            title=item.package_id,
            summary=f"{item.source_instance_id} -> {item.target_instance_id} · {item.direction} · {item.status}",
            fields={
                "title": item.package_id,
                "source_instance_id": item.source_instance_id,
                "target_instance_id": item.target_instance_id,
                "direction": item.direction,
                "status": item.status,
            },
            route=f"/sync?sync_run_id={item.id}",
            updated_at=item.updated_at,
            query=query,
        )
        for item in rows
    ]


def _search_sync_conflicts(session: Session, query: str, limit: int) -> list[SearchCandidate]:
    rows = session.execute(
        select(SyncConflict, SyncRun)
        .join(SyncRun, SyncRun.id == SyncConflict.sync_run_id)
        .where(
            _where_text(
                query,
                SyncConflict.id,
                SyncConflict.object_type,
                SyncConflict.object_id,
                SyncConflict.field_name,
                SyncConflict.conflict_reason,
                SyncConflict.status,
                SyncRun.package_id,
            ),
        )
        .order_by(SyncConflict.updated_at.desc())
        .limit(limit),
    ).all()
    results: list[SearchCandidate] = []
    for conflict, run in rows:
        title = f"{conflict.object_type} · {conflict.object_id}"
        summary = conflict.conflict_reason or f"{run.package_id} · {conflict.status}"
        results.append(
            _candidate(
                object_type="sync_conflict",
                object_id=conflict.id,
                title=title,
                summary=summary,
                fields={
                    "title": title,
                    "summary": summary,
                    "field_name": conflict.field_name,
                    "status": conflict.status,
                    "package_id": run.package_id,
                },
                route=f"/sync?conflict_id={conflict.id}",
                updated_at=conflict.updated_at,
                query=query,
            ),
        )
    return results


def _export_job_summary(job: ExportJob) -> str:
    result = job.result_json or {}
    statement_count = result.get("statement_count")
    item_count = result.get("item_count")
    parts = [f"job {job.id}"]
    if item_count is not None:
        parts.append(f"{item_count} items")
    if statement_count is not None:
        parts.append(f"{statement_count} statements")
    return " · ".join(parts)


def _highlight(item: SearchCandidate, query: str) -> str:
    source = item.summary or item.title
    if not source:
        return ""
    needle = query.casefold()
    haystack = source.casefold()
    index = haystack.find(needle)
    if index < 0:
        return _compact(source, 100)
    start = max(0, index - 32)
    end = min(len(source), index + len(query) + 48)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(source) else ""
    return f"{prefix}{source[start:end]}{suffix}"
