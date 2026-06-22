from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models.reports import (
    DailyReport,
    DailyReportItem,
    WeeklyReport,
    WeeklyReportItem,
)
from app.models.workspace import Workspace

DEFAULT_WEEKLY_ITEM_LIMIT = 50


@dataclass(frozen=True)
class WeeklyReportDraftRequest:
    workspace_code: str
    week_key: str
    limit: int = DEFAULT_WEEKLY_ITEM_LIMIT
    include_unpublished_daily: bool = False


class InvalidWeekKeyError(ValueError):
    pass


class PublishedWeeklyReportError(ValueError):
    pass


class WorkspaceNotFoundError(ValueError):
    pass


def create_weekly_report_draft(
    session: Session,
    request: WeeklyReportDraftRequest,
) -> WeeklyReport:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == request.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {request.workspace_code}")

    week_start, week_end = week_bounds(request.week_key)
    report = session.scalar(
        select(WeeklyReport).where(
            WeeklyReport.workspace_code == workspace.code,
            WeeklyReport.domain_code == workspace.default_domain_code,
            WeeklyReport.week_key == request.week_key,
        ),
    )
    if report and report.status == "published":
        raise PublishedWeeklyReportError(f"Weekly report is already published: {report.id}")
    if report is None:
        report = WeeklyReport(
            workspace_code=workspace.code,
            domain_code=workspace.default_domain_code,
            week_key=request.week_key,
            title=f"{request.week_key} {workspace.name} 周报",
            summary="由日报采信条目生成的周报候选草稿。",
            status="draft",
        )
        session.add(report)
        session.flush()
    else:
        report.title = f"{request.week_key} {workspace.name} 周报"
        report.summary = "由日报采信条目生成的周报候选草稿。"
        session.execute(
            delete(WeeklyReportItem).where(WeeklyReportItem.weekly_report_id == report.id),
        )
        session.flush()

    daily_items = _load_weekly_candidate_items(
        session=session,
        workspace=workspace,
        week_start=week_start,
        week_end=week_end,
        limit=request.limit,
        include_unpublished_daily=request.include_unpublished_daily,
    )
    for index, daily_item in enumerate(daily_items, start=1):
        generated_news = daily_item.generated_news
        session.add(
            WeeklyReportItem(
                weekly_report=report,
                daily_report_item=daily_item,
                generated_news=generated_news,
                workspace_code=workspace.code,
                domain_code=daily_item.domain_code,
                visibility_scope=daily_item.visibility_scope,
                sync_policy=daily_item.sync_policy,
                adoption_status=1,
                sort_order=index,
            ),
        )
    session.flush()
    return report


def week_bounds(week_key: str) -> tuple[date, date]:
    try:
        week_start = datetime.strptime(f"{week_key}-1", "%G-W%V-%u").date()
    except ValueError as exc:
        raise InvalidWeekKeyError(
            "week_key must use ISO format YYYY-Www, for example 2026-W19",
        ) from exc
    return week_start, date.fromordinal(week_start.toordinal() + 6)


def _load_weekly_candidate_items(
    *,
    session: Session,
    workspace: Workspace,
    week_start: date,
    week_end: date,
    limit: int,
    include_unpublished_daily: bool,
) -> list[DailyReportItem]:
    statement = (
        select(DailyReportItem)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .options(
            selectinload(DailyReportItem.daily_report),
            selectinload(DailyReportItem.generated_news),
        )
        .where(
            DailyReport.workspace_code == workspace.code,
            DailyReport.domain_code == workspace.default_domain_code,
            DailyReport.day_key >= week_start.isoformat(),
            DailyReport.day_key <= week_end.isoformat(),
            DailyReportItem.adoption_status == 2,
        )
        .order_by(
            DailyReport.day_key.desc(),
            DailyReportItem.sort_order,
            DailyReportItem.created_at,
        )
        .limit(max(1, min(int(limit or DEFAULT_WEEKLY_ITEM_LIMIT), 200)))
    )
    if not include_unpublished_daily:
        statement = statement.where(DailyReport.status == "published")
    return list(session.scalars(statement).all())
