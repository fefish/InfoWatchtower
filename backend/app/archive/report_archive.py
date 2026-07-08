"""统一报告归档的 SQL 聚合降级路径（archive-knowledge-design §5.1 后续增量 2）。

`/api/report-archive` 与 `/api/report-archive/summary` 默认走全量内存聚合
（operations.py `_report_archive_entries`）。工作台报告总量超过
``SQL_AGGREGATION_THRESHOLD`` 时切换到本模块：先用轻量列查询构建归档索引
（不加载条目链），月桶/过滤/分页在索引上完成，仅对当前页命中的报告做完整
ORM 聚合；条目级统计（累计条目/采信、来源 Top）始终由 SQL GROUP BY 给出。
API 形状不变，前端无感。

边界（archive-knowledge-design §8/§11）：本模块只读，不新增写端点，
不收录草稿（daily/weekly 仅 status=published），legacy 报告不因此进入
报告页时间轴语义。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.content import GeneratedNews, NewsItem
from app.models.legacy import HistoricalReport
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.reports.weekly import InvalidWeekKeyError, week_bounds

# 约 1000 份报告以内内存聚合延迟可接受（§5.1 增量 2 的判定阈值）。
SQL_AGGREGATION_THRESHOLD = 1000

_LIKE_ESCAPE = "\\"


@dataclass(frozen=True)
class ArchiveIndexRow:
    """归档索引行：只含排序/过滤/月桶所需的轻量字段。"""

    kind: str  # daily_report | weekly_report | historical_report
    id: str
    origin: str  # published | legacy
    report_type: str  # daily | weekly（legacy 未知类型归一为 daily，与内存路径一致）
    month: str
    sort_time: datetime
    published_at: datetime | None


def count_archive_reports(session: Session, *, workspace_code: str) -> int:
    daily = session.scalar(
        select(func.count())
        .select_from(DailyReport)
        .where(DailyReport.workspace_code == workspace_code, DailyReport.status == "published"),
    ) or 0
    weekly = session.scalar(
        select(func.count())
        .select_from(WeeklyReport)
        .where(WeeklyReport.workspace_code == workspace_code, WeeklyReport.status == "published"),
    ) or 0
    legacy = session.scalar(
        select(func.count())
        .select_from(HistoricalReport)
        .where(HistoricalReport.workspace_code == workspace_code),
    ) or 0
    return int(daily) + int(weekly) + int(legacy)


def should_use_sql_aggregation(session: Session, *, workspace_code: str) -> bool:
    return count_archive_reports(session, workspace_code=workspace_code) > SQL_AGGREGATION_THRESHOLD


def _sort_value(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _weekly_month(week_key: str, created_at: datetime) -> str:
    try:
        return week_bounds(week_key)[0].strftime("%Y-%m")
    except InvalidWeekKeyError:
        return created_at.strftime("%Y-%m")


def _like_pattern(needle: str) -> str:
    escaped = (
        needle.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )
    return f"%{escaped}%"


def fetch_archive_index(
    session: Session,
    *,
    workspace_code: str,
    report_type: str | None = None,
    origin: str | None = None,
    q: str | None = None,
) -> list[ArchiveIndexRow]:
    """轻量归档索引：SQL 侧完成来源/类型/关键词过滤，按时间倒序返回。

    关键词匹配下推为 ``lower(title/summary/content) LIKE``；与内存路径的差异
    仅在于内存路径只匹配截断后的摘要（约 180 字），SQL 路径匹配全文，属可
    接受的降级近似（只多不少）。
    """

    needle = (q or "").strip().lower()
    pattern = _like_pattern(needle) if needle else None
    rows: list[ArchiveIndexRow] = []

    if origin in (None, "published") and report_type in (None, "daily"):
        stmt = select(
            DailyReport.id,
            DailyReport.day_key,
            DailyReport.published_at,
            DailyReport.created_at,
        ).where(DailyReport.workspace_code == workspace_code, DailyReport.status == "published")
        if pattern:
            stmt = stmt.where(
                func.lower(DailyReport.title).like(pattern, escape=_LIKE_ESCAPE)
                | func.lower(DailyReport.summary).like(pattern, escape=_LIKE_ESCAPE),
            )
        for report_id, day_key, published_at, created_at in session.execute(stmt):
            rows.append(
                ArchiveIndexRow(
                    kind="daily_report",
                    id=report_id,
                    origin="published",
                    report_type="daily",
                    month=(day_key or "")[:7],
                    sort_time=_sort_value(published_at or created_at),
                    published_at=published_at,
                ),
            )

    if origin in (None, "published") and report_type in (None, "weekly"):
        stmt = select(
            WeeklyReport.id,
            WeeklyReport.week_key,
            WeeklyReport.published_at,
            WeeklyReport.created_at,
        ).where(WeeklyReport.workspace_code == workspace_code, WeeklyReport.status == "published")
        if pattern:
            stmt = stmt.where(
                func.lower(WeeklyReport.title).like(pattern, escape=_LIKE_ESCAPE)
                | func.lower(WeeklyReport.summary).like(pattern, escape=_LIKE_ESCAPE),
            )
        for report_id, week_key, published_at, created_at in session.execute(stmt):
            rows.append(
                ArchiveIndexRow(
                    kind="weekly_report",
                    id=report_id,
                    origin="published",
                    report_type="weekly",
                    month=_weekly_month(week_key, created_at),
                    sort_time=_sort_value(published_at or created_at),
                    published_at=published_at,
                ),
            )

    if origin in (None, "legacy"):
        stmt = select(
            HistoricalReport.id,
            HistoricalReport.report_type,
            HistoricalReport.period_start_at,
            HistoricalReport.created_at,
        ).where(HistoricalReport.workspace_code == workspace_code)
        if pattern:
            stmt = stmt.where(
                func.lower(HistoricalReport.title).like(pattern, escape=_LIKE_ESCAPE)
                | func.lower(HistoricalReport.content).like(pattern, escape=_LIKE_ESCAPE),
            )
        for report_id, legacy_type, period_start_at, created_at in session.execute(stmt):
            normalized_type = legacy_type if legacy_type in {"daily", "weekly"} else "daily"
            if report_type and normalized_type != report_type:
                continue
            rows.append(
                ArchiveIndexRow(
                    kind="historical_report",
                    id=report_id,
                    origin="legacy",
                    report_type=normalized_type,
                    month=period_start_at.strftime("%Y-%m") if period_start_at else "",
                    sort_time=_sort_value(period_start_at or created_at),
                    published_at=period_start_at,
                ),
            )

    rows.sort(key=lambda row: row.sort_time, reverse=True)
    return rows


_PUBLISHED_ITEM_SPECS = (
    ("daily", DailyReportItem, DailyReportItem.daily_report_id, DailyReport),
    ("weekly", WeeklyReportItem, WeeklyReportItem.weekly_report_id, WeeklyReport),
)


def published_item_stats(
    session: Session,
    *,
    workspace_code: str,
    report_type: str | None = None,
) -> tuple[int, int, list[float]]:
    """已发布报告条目统计（SQL GROUP BY）：累计条目数、累计采信数、逐报告采信率。"""

    per_report: list[tuple[int, int]] = []
    for kind, item_model, report_fk, report_model in _PUBLISHED_ITEM_SPECS:
        if report_type and kind != report_type:
            continue
        stmt = (
            select(
                func.count(item_model.id),
                func.sum(case((item_model.adoption_status == 2, 1), else_=0)),
            )
            .join(report_model, report_fk == report_model.id)
            .where(report_model.workspace_code == workspace_code, report_model.status == "published")
            .group_by(report_fk)
        )
        for item_count, adopted_count in session.execute(stmt):
            per_report.append((int(item_count or 0), int(adopted_count or 0)))
    total_items = sum(count for count, _ in per_report)
    total_adopted = sum(adopted for _, adopted in per_report)
    rates = [round(adopted / count, 4) for count, adopted in per_report if count > 0]
    return total_items, total_adopted, rates


_PUBLISHED_SOURCE_SPECS = (
    ("daily", DailyReportItem, DailyReportItem.daily_report_id, DailyReport, DailyReportItem.generated_news_id),
    ("weekly", WeeklyReportItem, WeeklyReportItem.weekly_report_id, WeeklyReport, WeeklyReportItem.generated_news_id),
)


def published_top_sources(
    session: Session,
    *,
    workspace_code: str,
    report_type: str | None = None,
    limit: int = 5,
) -> list[tuple[str, int]]:
    """已发布报告采信条目的来源 Top（SQL GROUP BY，legacy 无来源数据不参与）。"""

    counts: dict[str, int] = {}
    for kind, item_model, report_fk, report_model, generated_fk in _PUBLISHED_SOURCE_SPECS:
        if report_type and kind != report_type:
            continue
        stmt = (
            select(NewsItem.source_name, func.count(item_model.id))
            .select_from(item_model)
            .join(report_model, report_fk == report_model.id)
            .join(GeneratedNews, generated_fk == GeneratedNews.id)
            .join(NewsItem, GeneratedNews.news_item_id == NewsItem.id)
            .where(
                report_model.workspace_code == workspace_code,
                report_model.status == "published",
                item_model.adoption_status == 2,
            )
            .group_by(NewsItem.source_name)
        )
        for source_name, count in session.execute(stmt):
            cleaned = (source_name or "").strip()
            if cleaned:
                counts[cleaned] = counts.get(cleaned, 0) + int(count or 0)
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:limit]
