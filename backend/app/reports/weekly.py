from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.content import GeneratedNews
from app.models.reports import (
    DailyReport,
    DailyReportItem,
    WeeklyReport,
    WeeklyReportItem,
)
from app.models.strategy import RequirementSourceLink
from app.models.workspace import Workspace

DEFAULT_WEEKLY_ITEM_LIMIT = 50
MAX_WEEKLY_CANDIDATE_SCAN_LIMIT = 200
WEEKLY_HEAT_SCORE_WEIGHT = 0.15
WEEKLY_FEEDBACK_SCORE_WEIGHT = 0.25
# 周报候选条目创建时的初始采信状态；偏离该值即视为编辑层决策。
WEEKLY_ITEM_INITIAL_ADOPTION_STATUS = 1


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


@dataclass(frozen=True)
class WeeklyItemScore:
    weekly_score: float
    final_score: float
    heat_score: float
    feedback_score: float


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
    existing_items: list[WeeklyReportItem] = []
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
        # 候选重建对既有 draft 走增量合并：已采信/已编辑的周报条目不因重建被整表销毁。
        report.title = f"{request.week_key} {workspace.name} 周报"
        report.summary = "由日报采信条目生成的周报候选草稿。"
        existing_items = list(
            session.scalars(
                select(WeeklyReportItem)
                .where(WeeklyReportItem.weekly_report_id == report.id)
                .order_by(
                    WeeklyReportItem.sort_order,
                    WeeklyReportItem.created_at,
                    WeeklyReportItem.id,
                ),
            ).all(),
        )

    daily_items = _load_weekly_candidate_items(
        session=session,
        workspace=workspace,
        week_start=week_start,
        week_end=week_end,
        limit=request.limit,
        include_unpublished_daily=request.include_unpublished_daily,
    )
    by_daily_item_id: dict[str, WeeklyReportItem] = {}
    by_generated_news_id: dict[str, WeeklyReportItem] = {}
    for existing in existing_items:
        if existing.daily_report_item_id:
            by_daily_item_id.setdefault(existing.daily_report_item_id, existing)
        if existing.generated_news_id:
            by_generated_news_id.setdefault(existing.generated_news_id, existing)

    matched_item_ids: set[str] = set()
    for index, daily_item in enumerate(daily_items, start=1):
        existing = by_daily_item_id.get(daily_item.id)
        if existing is None and daily_item.generated_news_id:
            existing = by_generated_news_id.get(daily_item.generated_news_id)
        if existing is not None and existing.id not in matched_item_ids:
            matched_item_ids.add(existing.id)
            # 已编辑条目原样保留；未编辑条目跟随本次候选重建刷新指针和排序。
            if not _weekly_report_item_edited(existing):
                existing.daily_report_item = daily_item
                existing.generated_news = daily_item.generated_news
                existing.sort_order = index
            continue
        session.add(
            WeeklyReportItem(
                weekly_report=report,
                daily_report_item=daily_item,
                generated_news=daily_item.generated_news,
                workspace_code=workspace.code,
                domain_code=daily_item.domain_code,
                visibility_scope=daily_item.visibility_scope,
                sync_policy=daily_item.sync_policy,
                adoption_status=WEEKLY_ITEM_INITIAL_ADOPTION_STATUS,
                sort_order=index,
            ),
        )

    # 只移除"不在新候选集 + 无编辑痕迹 + 无外部引用"的条目，避免抹掉编辑决策或悬挂外键。
    removable = [
        existing
        for existing in existing_items
        if existing.id not in matched_item_ids and not _weekly_report_item_edited(existing)
    ]
    referenced_ids = _referenced_weekly_report_item_ids(
        session,
        [existing.id for existing in removable],
    )
    for existing in removable:
        if existing.id not in referenced_ids:
            session.delete(existing)
    session.flush()
    session.expire(report, ["items"])
    refresh_weekly_report_summary(report)
    session.flush()
    return report


def _weekly_report_item_edited(item: WeeklyReportItem) -> bool:
    """判断周报条目是否带有编辑层痕迹：采信状态偏离初始值或任一 editor 覆盖。"""
    return (
        item.adoption_status != WEEKLY_ITEM_INITIAL_ADOPTION_STATUS
        or item.editor_title is not None
        or item.editor_summary is not None
        or item.editor_content_json is not None
    )


def _referenced_weekly_report_item_ids(session: Session, item_ids: list[str]) -> set[str]:
    """查出仍被需求证据链引用的周报条目，删除这些条目会造成外键悬挂。"""
    if not item_ids:
        return set()
    return set(
        session.scalars(
            select(RequirementSourceLink.weekly_report_item_id).where(
                RequirementSourceLink.weekly_report_item_id.in_(item_ids),
            ),
        ).all(),
    )


def refresh_weekly_report_summary(report: WeeklyReport) -> None:
    """Refresh the report-level summary from current weekly items.

    This is the backend-owned text shown by the weekly page. Richer markdown/html
    summaries are generated in report_renditions.summary_json from the same item facts.
    """
    items = [item for item in report.items if item.generated_news is not None]
    if not items:
        report.summary = "暂无周报候选条目。"
        return

    adopted = [item for item in items if item.adoption_status == 2]
    base_items = adopted or items
    status_label = "采信" if adopted else "候选"
    boards = _weekly_board_counts(base_items)
    top_boards = [name for name, _count in sorted(boards.items(), key=lambda pair: (-pair[1], pair[0]))[:3]]
    highlights = [_weekly_item_title(item) for item in _weekly_highlight_items(base_items, limit=3)]
    day_total = len({item.daily_report_item.daily_report.day_key for item in base_items if item.daily_report_item})

    board_text = "、".join(top_boards) if top_boards else "未分板块"
    highlight_text = "；".join(highlights) if highlights else "待编辑补充"
    day_clause = f"，覆盖 {day_total} 个日报日" if day_total else ""
    report.summary = (
        f"本周{status_label} {len(base_items)} 条{day_clause}，覆盖 {len(boards)} 个板块，"
        f"重点集中在 {board_text}。关键亮点：{highlight_text}。"
    )


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
            selectinload(DailyReportItem.generated_news).selectinload(
                GeneratedNews.recommendation_item,
            ),
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
        .limit(MAX_WEEKLY_CANDIDATE_SCAN_LIMIT)
    )
    if not include_unpublished_daily:
        statement = statement.where(DailyReport.status == "published")
    candidate_limit = max(1, min(int(limit or DEFAULT_WEEKLY_ITEM_LIMIT), MAX_WEEKLY_CANDIDATE_SCAN_LIMIT))
    candidates = list(session.scalars(statement).all())
    return sorted(candidates, key=_weekly_candidate_sort_key)[:candidate_limit]


def weekly_item_score(generated_news: GeneratedNews | None) -> WeeklyItemScore:
    recommendation = generated_news.recommendation_item if generated_news else None
    final_score = float(recommendation.final_score) if recommendation is not None else 0.0
    heat_score = float(recommendation.heat_score) if recommendation is not None else 0.0
    feedback_score = float(recommendation.feedback_score) if recommendation is not None else 0.0
    weekly_score = (
        final_score
        + heat_score * WEEKLY_HEAT_SCORE_WEIGHT
        + feedback_score * WEEKLY_FEEDBACK_SCORE_WEIGHT
    )
    return WeeklyItemScore(
        weekly_score=round(weekly_score, 2),
        final_score=round(final_score, 2),
        heat_score=round(heat_score, 2),
        feedback_score=round(feedback_score, 2),
    )


def _weekly_candidate_sort_key(item: DailyReportItem) -> tuple[float, float, float, float, int, int, str, str]:
    scores = weekly_item_score(item.generated_news)
    day_ordinal = _day_ordinal(item.daily_report.day_key if item.daily_report else "")
    return (
        -scores.weekly_score,
        -scores.final_score,
        -scores.heat_score,
        -scores.feedback_score,
        -day_ordinal,
        item.sort_order,
        item.created_at.isoformat() if item.created_at else "",
        item.id,
    )


def _day_ordinal(day_key: str) -> int:
    try:
        return date.fromisoformat(day_key).toordinal()
    except ValueError:
        return 0


def _weekly_board_counts(items: list[WeeklyReportItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        board = _weekly_item_board(item)
        counts[board] = counts.get(board, 0) + 1
    return counts


def _weekly_item_board(item: WeeklyReportItem) -> str:
    news = item.generated_news
    if news is None:
        return "未分板块"
    insight = news.insight_json or {}
    board = str(insight.get("board") or "").strip()
    return board or news.category or "未分板块"


def _weekly_highlight_items(items: list[WeeklyReportItem], *, limit: int) -> list[WeeklyReportItem]:
    return sorted(
        items,
        key=lambda item: (weekly_item_score(item.generated_news).weekly_score, -item.sort_order),
        reverse=True,
    )[: max(0, limit)]


def _weekly_item_title(item: WeeklyReportItem) -> str:
    news = item.generated_news
    if news is None:
        return "未命名条目"
    return (item.editor_title or news.title or "未命名条目").strip()
