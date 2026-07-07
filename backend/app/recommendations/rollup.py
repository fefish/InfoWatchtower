"""反馈回哺周/月 rollup（feedback_weekly_rollup / feedback_monthly_review）。

事实源：docs/backend/feedback-heat-scoring.md §11-§18；契约：
config/contracts/recommendation_ranking.json `feedback_workflow`。

一票否决级核心规则（§11.1）：周/月层零直接改分——本模块只读推荐/日报/反馈
事实表，产出评估快照（feedback_rollups）、advisory 建议与 rubric 修订提案
（人审硬门）；永不写 source_score_snapshots / rubric_topic_priors /
recommendation_items，永不改 data_sources tier/enabled 与 authored rubric。
空样本指标一律 null（不写 0）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import (
    FEEDBACK_ROLLUP_DAILY_CAP,
    PURPOSE_FEEDBACK_ROLLUP,
    current_day_key,
    generation_calls_used,
    try_acquire_feedback_rollup_call,
)
from app.llm.provider import request_chat_completion, resolve_generation_config
from app.models.common import utc_now
from app.models.content import (
    FeedbackRollup,
    GeneratedNews,
    NewsItem,
    RecommendationItem,
    RecommendationRun,
    RubricRevisionProposal,
    RubricTopicPrior,
)
from app.models.feedback import EditorialAction, Rating, Reaction
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.recommendations.policy import workspace_recommendation_policy
from app.recommendations.rubric import (
    RUBRIC_SCHEMA_VERSION,
    RubricValidationError,
    validate_rubric,
)

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

PERIOD_WEEKLY = "weekly"
PERIOD_MONTHLY = "monthly"
WEEKLY_PERIOD_KEY_PATTERN = re.compile(r"^(\d{4})-W(\d{2})$")
MONTHLY_PERIOD_KEY_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")

ADOPTED_STATUS = 2
REJECTED_STATUS = 3

# §12.1 信号清单与评估聚合权重（只用于指标/样本选择/建议排序，不进任何分数）。
SIGNAL_WEIGHTS: dict[str, float] = {
    "requirement_conversion_positive": 10.0,
    "daily_adopt": 8.0,
    "weekly_adopt": 4.0,
    "like": 2.0,
    "rating": 1.0,
    "daily_reject": -6.0,
    "weekly_reject": -2.0,
    "requirement_conversion_negative": -4.0,
    "editor_override": 0.0,
}

# §12.3 位次去偏 bucket 权重（写死）。
RANK_BUCKET_WEIGHTS: tuple[tuple[int, float], ...] = ((6, 1.0), (15, 1.2), (10**9, 1.4))

# §13.2 源分层建议阈值（advisory，写死）。
SOURCE_LOOKBACK_DAYS = 28
LOW_DATA_RECOMMENDED_THRESHOLD = 5
PROMOTE_MIN_RECOMMENDED = 8
PROMOTE_MIN_NORMALIZED_ADOPT_RATE = 0.25
PROMOTE_MAX_REJECT_RATE = 0.1
DEMOTE_MIN_REJECT_RATE = 0.5

# §13.3 topic 贴边判定（每日乘子 clamp [0.5, 1.5] 的观测边界）。
TOPIC_PIN_HIGH_RATIO = 1.45
TOPIC_PIN_LOW_RATIO = 0.55
TOPIC_PIN_CONSECUTIVE_DAYS = 7

# §13.5 提案生成（RLHF-lite，人审硬门）。
REVISION_PROMPT_VERSION = "revision_prompt_v1"
PROPOSAL_COMPILE_PROMPT_VERSION = "revision_proposal_v1"
PROPOSAL_MIN_STRONG_SIGNALS = 10
PROPOSAL_EXEMPLAR_LIMIT = 8
PROPOSAL_EXEMPLAR_SUMMARY_MAX = 200
PROPOSAL_EXPIRY_DAYS = 30
PROPOSAL_RATIONALE_MAX = 60
CHANGE_SUMMARY_OPS = (
    "add_topic",
    "remove_topic",
    "adjust_topic_weight",
    "add_exclusion",
    "remove_exclusion",
    "adjust_boost",
    "edit_keywords_hint",
)

# §14 月度漂移判定（相对下降 >20% 且绝对下降 >=0.05）。
DRIFT_RELATIVE_DROP = 0.20
DRIFT_ABSOLUTE_DROP = 0.05
STALE_ZERO_RECOMMENDED_WEEKS = 4
STALE_MIN_RECOMMENDED = 8
STALE_MIN_REJECT_RATE = 0.5

REVISION_SYSTEM_PROMPT = """你是情报工作台的「内容导向修订顾问」。基于当前 active rubric、
每日反馈再估计的 effective weights、本周评估指标与采信/驳回代表样本，产出一份 rubric
修订提案。要求：
1. proposed_rubric 必须是完整 rubric JSON，严格符合原 schema
   （topics 3-12 个、scoring_dimensions 含 relevance 且权重和 = 1.0、language zh|en）。
2. change_summary 逐条列出与当前 rubric 的差异：op 取
   add_topic|remove_topic|adjust_topic_weight|add_exclusion|remove_exclusion|adjust_boost|edit_keywords_hint，
   带 target_code、from、to 与一句话 rationale（<=60 字）。
3. 只做反馈证据支持的最小修订，不推翻用户原始导向。
只输出一个合法 JSON 对象 {"proposed_rubric": ..., "change_summary": [...]}，
不要输出 Markdown 代码块或解释文字。"""


class RollupPeriodError(ValueError):
    """period_key 非法（API 层映射 422）。"""


# ---------------------------------------------------------------------------
# 周期窗口（§12.2：周=上一个完整 ISO 周，月=上一个自然月，Asia/Shanghai）
# ---------------------------------------------------------------------------


def previous_weekly_period(now: datetime | None = None) -> str:
    moment = (now or utc_now()).astimezone(BEIJING_TZ)
    this_monday = moment.date() - timedelta(days=moment.isoweekday() - 1)
    prev_monday = this_monday - timedelta(days=7)
    iso = prev_monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def previous_monthly_period(now: datetime | None = None) -> str:
    moment = (now or utc_now()).astimezone(BEIJING_TZ)
    first_of_month = moment.date().replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    return f"{last_month_end.year}-{last_month_end.month:02d}"


def weekly_window(period_key: str) -> tuple[datetime, datetime]:
    match = WEEKLY_PERIOD_KEY_PATTERN.fullmatch(period_key or "")
    if match is None:
        raise RollupPeriodError(f"invalid weekly period_key: {period_key!r} (expected YYYY-Www)")
    year, week = int(match.group(1)), int(match.group(2))
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise RollupPeriodError(f"invalid weekly period_key: {period_key!r}") from exc
    start = datetime(monday.year, monday.month, monday.day, tzinfo=BEIJING_TZ)
    # 统一转 UTC：与库内 utc_now() 存量时间戳同一时区口径（SQLite 字符串比较安全）。
    return start.astimezone(UTC), (start + timedelta(days=7)).astimezone(UTC)


def monthly_window(period_key: str) -> tuple[datetime, datetime]:
    match = MONTHLY_PERIOD_KEY_PATTERN.fullmatch(period_key or "")
    if match is None:
        raise RollupPeriodError(f"invalid monthly period_key: {period_key!r} (expected YYYY-MM)")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise RollupPeriodError(f"invalid monthly period_key: {period_key!r}")
    start = datetime(year, month, 1, tzinfo=BEIJING_TZ)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=BEIJING_TZ)
    else:
        end = datetime(year, month + 1, 1, tzinfo=BEIJING_TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


def rank_bucket_weight(rank: int) -> float:
    for upper, weight in RANK_BUCKET_WEIGHTS:
        if rank <= upper:
            return weight
    return RANK_BUCKET_WEIGHTS[-1][1]


# ---------------------------------------------------------------------------
# 窗口事实聚合（只读；事件归属时间 = 反馈动作发生时间，§12.2）
# ---------------------------------------------------------------------------


class _WindowFacts:
    def __init__(self) -> None:
        # 窗口内进入推荐的条目：news_item_id -> 最新 RecommendationItem 快照。
        self.rec_by_news: dict[str, RecommendationItem] = {}
        self.source_by_news: dict[str, str] = {}
        self.source_names: dict[str, str] = {}
        self.news_titles: dict[str, str] = {}
        self.news_summaries: dict[str, str] = {}
        # 展示位次（§12.3）：日报 sort_order 优先，否则推荐 run rank。
        self.display_rank: dict[str, int] = {}
        # 窗口内反馈事件（按信号去重后的集合/计数）。
        self.daily_adopt_events: set[tuple[str, str]] = set()  # (news, report)
        self.daily_reject_events: set[tuple[str, str]] = set()
        self.weekly_adopt_events: set[tuple[str, str]] = set()
        self.weekly_reject_events: set[tuple[str, str]] = set()
        self.adopted: set[str] = set()  # 日报采信（published）
        self.rejected: set[str] = set()  # 日报驳回
        self.adopted_edited_items = 0  # 被采信且带 editor_* 覆盖的日报条目数
        self.adopted_report_items = 0
        self.like_count = 0
        self.rating_count = 0
        self.requirement_positive: set[tuple[str, str]] = set()  # (requirement, news)
        self.requirement_negative: set[tuple[str, str]] = set()
        self.editor_override_count = 0

    def signal_counts(self) -> dict[str, int]:
        return {
            "requirement_conversion_positive": len(self.requirement_positive),
            "daily_adopt": len(self.daily_adopt_events),
            "weekly_adopt": len(self.weekly_adopt_events),
            "like": self.like_count,
            "rating": self.rating_count,
            "daily_reject": len(self.daily_reject_events),
            "weekly_reject": len(self.weekly_reject_events),
            "requirement_conversion_negative": len(self.requirement_negative),
            "editor_override": self.editor_override_count,
        }

    def total_feedback_events(self) -> int:
        return sum(self.signal_counts().values())


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _in_window(value: datetime | None, window_start: datetime, window_end: datetime) -> bool:
    moment = _ensure_aware(value)
    return moment is not None and window_start <= moment < window_end


def _recommended_news_ids(session: Session, workspace_code: str) -> set[str]:
    """曾进入本工作台推荐的 news（存在 recommendation_items 行，任意时间）。"""
    return set(
        session.scalars(
            select(RecommendationItem.news_item_id).where(
                RecommendationItem.workspace_code == workspace_code,
            ),
        ).all(),
    )


def _collect_window_facts(
    session: Session,
    workspace_code: str,
    window_start: datetime,
    window_end: datetime,
) -> _WindowFacts:
    facts = _WindowFacts()

    rows = session.execute(
        select(RecommendationItem, NewsItem)
        .join(NewsItem, NewsItem.id == RecommendationItem.news_item_id)
        .where(
            RecommendationItem.workspace_code == workspace_code,
            RecommendationItem.created_at >= window_start,
            RecommendationItem.created_at < window_end,
        )
        .order_by(RecommendationItem.created_at.asc()),
    ).all()
    for item, news in rows:
        facts.rec_by_news[news.id] = item  # 升序遍历：最新 run 的快照胜出
        facts.source_by_news[news.id] = news.data_source_id
        facts.source_names.setdefault(news.data_source_id, news.source_name)
        facts.news_titles[news.id] = news.source_title
        facts.news_summaries[news.id] = news.summary or ""
        existing = facts.display_rank.get(news.id)
        if existing is None or item.rank < existing:
            facts.display_rank[news.id] = item.rank

    ever_recommended = _recommended_news_ids(session, workspace_code)

    # 日报采信/驳回（事件时间 = 条目 updated_at；展示位次 = sort_order）。
    report_rows = session.execute(
        select(DailyReportItem, DailyReport, GeneratedNews.news_item_id)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .join(GeneratedNews, GeneratedNews.id == DailyReportItem.generated_news_id)
        .where(DailyReport.workspace_code == workspace_code)
        .order_by(DailyReport.day_key.asc()),
    ).all()
    report_item_to_news: dict[str, str] = {}
    for item, report, news_item_id in report_rows:
        report_item_to_news[item.id] = news_item_id
        if news_item_id not in ever_recommended:
            continue
        if not _in_window(item.updated_at, window_start, window_end):
            continue
        if item.adoption_status == ADOPTED_STATUS and report.status == "published":
            facts.daily_adopt_events.add((news_item_id, report.id))
            # day_key 升序遍历：最新日报的状态胜出（§12.1 去重规则）。
            facts.adopted.add(news_item_id)
            facts.rejected.discard(news_item_id)
            facts.adopted_report_items += 1
            if _daily_item_edited(item):
                facts.adopted_edited_items += 1
                facts.editor_override_count += 1
            facts.display_rank[news_item_id] = item.sort_order or facts.display_rank.get(
                news_item_id,
                10**6,
            )
        elif item.adoption_status == REJECTED_STATUS:
            facts.daily_reject_events.add((news_item_id, report.id))
            facts.rejected.add(news_item_id)
            facts.adopted.discard(news_item_id)

    # 周报采信/驳回：沿 daily_report_item / generated_news 回溯 news_item。
    weekly_rows = session.execute(
        select(WeeklyReportItem, WeeklyReport)
        .join(WeeklyReport, WeeklyReport.id == WeeklyReportItem.weekly_report_id)
        .where(
            WeeklyReport.workspace_code == workspace_code,
            WeeklyReportItem.adoption_status.in_([ADOPTED_STATUS, REJECTED_STATUS]),
        ),
    ).all()
    generated_ids = [
        row[0].generated_news_id for row in weekly_rows if row[0].generated_news_id
    ]
    generated_to_news: dict[str, str] = {}
    if generated_ids:
        generated_to_news = dict(
            session.execute(
                select(GeneratedNews.id, GeneratedNews.news_item_id).where(
                    GeneratedNews.id.in_(generated_ids),
                ),
            ).all(),
        )
    for item, report in weekly_rows:
        if not _in_window(item.updated_at, window_start, window_end):
            continue
        news_item_id = None
        if item.daily_report_item_id and item.daily_report_item_id in report_item_to_news:
            news_item_id = report_item_to_news[item.daily_report_item_id]
        elif item.generated_news_id:
            news_item_id = generated_to_news.get(item.generated_news_id)
        if news_item_id is None or news_item_id not in ever_recommended:
            continue
        if item.adoption_status == ADOPTED_STATUS and report.status == "published":
            facts.weekly_adopt_events.add((news_item_id, report.id))
        elif item.adoption_status == REJECTED_STATUS:
            facts.weekly_reject_events.add((news_item_id, report.id))

    # 点赞（news_item / daily_report_item 双维度合并；每 user × target 一行）。
    like_rows = session.execute(
        select(Reaction).where(
            Reaction.active.is_(True),
            Reaction.reaction_type == "like",
        ),
    ).all()
    for (reaction,) in like_rows:
        if not _in_window(reaction.created_at, window_start, window_end):
            continue
        target = None
        if reaction.news_item_id and reaction.news_item_id in ever_recommended:
            target = reaction.news_item_id
        elif reaction.daily_report_item_id in report_item_to_news:
            target = report_item_to_news[reaction.daily_report_item_id]
        if target is not None:
            facts.like_count += 1

    # 评分（dimension=overall，每 user × target 取最新一条）。
    rating_rows = session.execute(
        select(Rating)
        .where(Rating.dimension == "overall")
        .order_by(Rating.created_at.asc()),
    ).all()
    latest_ratings: dict[tuple[str, str], Rating] = {}
    for (rating,) in rating_rows:
        if not _in_window(rating.created_at, window_start, window_end):
            continue
        target = None
        if rating.news_item_id and rating.news_item_id in ever_recommended:
            target = rating.news_item_id
        elif rating.daily_report_item_id in report_item_to_news:
            target = report_item_to_news[rating.daily_report_item_id]
        if target is None:
            continue
        latest_ratings[(rating.user_id, target)] = rating  # 升序遍历：最新胜出
    facts.rating_count = len(latest_ratings)

    # requirement 转化（editorial_actions 写入侧已按 (requirement, news, outcome) 幂等）。
    action_rows = session.scalars(
        select(EditorialAction).where(
            EditorialAction.object_type == "news_item",
            EditorialAction.action_type == "requirement.feedback_to_recommendation",
        ),
    ).all()
    for action in action_rows:
        if not _in_window(action.created_at, window_start, window_end):
            continue
        if action.object_id not in ever_recommended:
            continue
        after = action.after_json or {}
        requirement_id = str(after.get("requirement_id") or "")
        outcome = str(after.get("outcome") or "")
        if outcome == "positive":
            facts.requirement_positive.add((requirement_id, action.object_id))
        elif outcome == "negative":
            facts.requirement_negative.add((requirement_id, action.object_id))
    return facts


def _daily_item_edited(item: DailyReportItem) -> bool:
    return bool(
        (item.editor_title or "").strip()
        or (item.editor_summary or "").strip()
        or item.editor_content_json,
    )


# ---------------------------------------------------------------------------
# 评估指标（§13.4，定义写死；空样本一律 null）
# ---------------------------------------------------------------------------


def _published_reports_in_window(
    session: Session,
    workspace_code: str,
    window_start: datetime,
    window_end: datetime,
) -> list[DailyReport]:
    day_keys: list[str] = []
    cursor = window_start.astimezone(BEIJING_TZ).date()
    end_date = window_end.astimezone(BEIJING_TZ).date()
    while cursor < end_date:
        day_keys.append(cursor.isoformat())
        cursor += timedelta(days=1)
    if not day_keys:
        return []
    return list(
        session.scalars(
            select(DailyReport).where(
                DailyReport.workspace_code == workspace_code,
                DailyReport.status == "published",
                DailyReport.day_key.in_(day_keys),
            ),
        ).all(),
    )


def _precision_at_k(session: Session, reports: list[DailyReport], k: int) -> float | None:
    if not reports:
        return None
    precisions: list[float] = []
    for report in reports:
        items = list(
            session.scalars(
                select(DailyReportItem)
                .where(DailyReportItem.daily_report_id == report.id)
                .order_by(DailyReportItem.sort_order.asc(), DailyReportItem.id.asc()),
            ).all(),
        )
        if not items:
            continue
        top = items[:k]
        adopted = sum(1 for item in top if item.adoption_status == ADOPTED_STATUS)
        precisions.append(adopted / min(k, len(items)))
    if not precisions:
        return None
    return round(sum(precisions) / len(precisions), 4)


def _rerank_uplift(facts: _WindowFacts) -> float | None:
    scored_items = [
        (news_id, item)
        for news_id, item in facts.rec_by_news.items()
        if (item.llm_rerank_status or "") in {"scored", "cached"}
    ]
    if not scored_items:
        return None

    def precision(sort_key) -> float:
        ordered = sorted(scored_items, key=sort_key)
        top = ordered[:6]
        adopted = sum(1 for news_id, _item in top if news_id in facts.adopted)
        return adopted / min(6, len(scored_items))

    by_final = precision(lambda pair: (-float(pair[1].final_score or 0.0), pair[0]))
    by_coarse = precision(lambda pair: (-float(pair[1].coarse_score or 0.0), pair[0]))
    return round(by_final - by_coarse, 4)


def _source_coverage(facts: _WindowFacts) -> float | None:
    if not facts.adopted:
        return None
    sources = {
        facts.source_by_news[news_id]
        for news_id in facts.adopted
        if news_id in facts.source_by_news
    }
    if not sources:
        return None
    return round(len(sources) / len(facts.adopted), 4)


def _topic_entropy(facts: _WindowFacts, rubric: dict[str, Any] | None) -> float | None:
    if not isinstance(rubric, dict):
        return None
    topic_count = len(rubric.get("topics") or [])
    if topic_count <= 1:
        return None
    counts: dict[str, int] = {}
    for news_id in facts.adopted:
        item = facts.rec_by_news.get(news_id)
        if item is None:
            continue
        for code in item.rubric_hits_json or []:
            counts[str(code)] = counts.get(str(code), 0) + 1
    total = sum(counts.values())
    if total == 0:
        return None
    entropy = -sum(
        (count / total) * math.log(count / total) for count in counts.values() if count > 0
    )
    return round(entropy / math.log(topic_count), 4)


def _normalized_adopt_rate(facts: _WindowFacts) -> float | None:
    recommended = len(facts.rec_by_news)
    if recommended == 0:
        return None
    weighted = 0.0
    for news_id in facts.adopted:
        if news_id not in facts.rec_by_news:
            continue
        rank = facts.display_rank.get(news_id, 10**6)
        weighted += rank_bucket_weight(rank)
    return round(min(1.0, weighted / max(1, recommended)), 4)


def _edit_rate(facts: _WindowFacts) -> float | None:
    if facts.adopted_report_items == 0:
        return None
    return round(facts.adopted_edited_items / facts.adopted_report_items, 4)


# ---------------------------------------------------------------------------
# 源分层建议（§13.2，advisory；28 天回看补样本量）
# ---------------------------------------------------------------------------


def _workspace_sources(session: Session, workspace: Workspace) -> dict[str, str]:
    """enabled 源清单（id -> name）：工作台 source links 中 enabled 的源。"""
    from app.models.content import DataSource

    rows = session.execute(
        select(DataSource.id, DataSource.name)
        .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
        .where(
            WorkspaceSourceLink.workspace_id == workspace.id,
            WorkspaceSourceLink.enabled.is_(True),
            DataSource.enabled.is_(True),
        ),
    ).all()
    return {source_id: name for source_id, name in rows}


def _source_breakdown(
    session: Session,
    workspace: Workspace,
    lookback_facts: _WindowFacts,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    sources = _workspace_sources(session, workspace)
    for source_id, name in lookback_facts.source_names.items():
        sources.setdefault(source_id, name)

    per_source: dict[str, dict[str, Any]] = {}
    for source_id, name in sources.items():
        per_source[source_id] = {
            "data_source_id": source_id,
            "name": name,
            "recommended_count": 0,
            "adopted_count": 0,
            "rejected_count": 0,
            "adopted_weighted": 0.0,
        }
    for news_id, source_id in lookback_facts.source_by_news.items():
        bucket = per_source.setdefault(
            source_id,
            {
                "data_source_id": source_id,
                "name": lookback_facts.source_names.get(source_id, source_id),
                "recommended_count": 0,
                "adopted_count": 0,
                "rejected_count": 0,
                "adopted_weighted": 0.0,
            },
        )
        bucket["recommended_count"] += 1
        if news_id in lookback_facts.adopted:
            bucket["adopted_count"] += 1
            rank = lookback_facts.display_rank.get(news_id, 10**6)
            bucket["adopted_weighted"] += rank_bucket_weight(rank)
        if news_id in lookback_facts.rejected:
            bucket["rejected_count"] += 1

    entries: list[dict[str, Any]] = []
    low_data: list[dict[str, str]] = []
    for source_id in sorted(per_source):
        bucket = per_source[source_id]
        recommended = bucket["recommended_count"]
        reject_rate = bucket["rejected_count"] / max(1, recommended)
        normalized = min(1.0, bucket["adopted_weighted"] / max(1, recommended))
        if (
            recommended >= PROMOTE_MIN_RECOMMENDED
            and normalized >= PROMOTE_MIN_NORMALIZED_ADOPT_RATE
            and reject_rate <= PROMOTE_MAX_REJECT_RATE
        ):
            suggestion = "suggest_promote"
        elif (
            recommended >= PROMOTE_MIN_RECOMMENDED
            and bucket["adopted_count"] == 0
            and reject_rate >= DEMOTE_MIN_REJECT_RATE
        ):
            suggestion = "suggest_demote"
        elif recommended < LOW_DATA_RECOMMENDED_THRESHOLD:
            suggestion = "insufficient_data"
            low_data.append({"id": source_id, "name": bucket["name"]})
        else:
            suggestion = "keep"
        entries.append(
            {
                "data_source_id": source_id,
                "name": bucket["name"],
                "recommended_count": recommended,
                "adopted_count": bucket["adopted_count"],
                "rejected_count": bucket["rejected_count"],
                "normalized_adopt_rate": round(normalized, 4),
                "reject_rate": round(reject_rate, 4),
                "suggestion": suggestion,
            },
        )
    breakdown = {
        "window": f"{SOURCE_LOOKBACK_DAYS}d",
        "sources": entries,
    }
    return breakdown, low_data


# ---------------------------------------------------------------------------
# topic 权重再平衡观测（§13.3；rubric_topic_priors 唯一写入方仍是每日 job）
# ---------------------------------------------------------------------------


def _topic_breakdown(
    session: Session,
    workspace: Workspace,
    facts: _WindowFacts,
    policy: dict[str, Any],
    window_end: datetime,
) -> dict[str, Any]:
    rubric = policy.get("active_rubric")
    if policy.get("rubric_status") != "active" or not isinstance(rubric, dict):
        return {}
    rubric_version = int(policy.get("rubric_version") or 0)
    end_date = window_end.astimezone(BEIJING_TZ).date()
    pin_day_keys = [
        (end_date - timedelta(days=offset)).isoformat()
        for offset in range(1, TOPIC_PIN_CONSECUTIVE_DAYS + 1)
    ]

    topics: list[dict[str, Any]] = []
    pinned: list[dict[str, Any]] = []
    for topic in rubric.get("topics") or []:
        code = str(topic.get("code") or "")
        if not code:
            continue
        authored_weight = float(topic.get("weight") or 0.0)
        pos = 0
        neg = 0
        for news_id, item in facts.rec_by_news.items():
            hits = [str(hit) for hit in item.rubric_hits_json or []]
            if code not in hits or int(item.rubric_version or 0) != rubric_version:
                continue
            if news_id in facts.adopted:
                pos += 1
            if news_id in facts.rejected:
                neg += 1
        prior_rows = session.execute(
            select(RubricTopicPrior.day_key, RubricTopicPrior.effective_weight).where(
                RubricTopicPrior.workspace_code == workspace.code,
                RubricTopicPrior.rubric_version == rubric_version,
                RubricTopicPrior.topic_code == code,
                RubricTopicPrior.day_key.in_(pin_day_keys),
            ),
        ).all()
        weights_by_day = {day_key: float(weight or 0.0) for day_key, weight in prior_rows}
        latest_weight = None
        for day_key in pin_day_keys:  # pin_day_keys[0] 是窗口末日，取最近存在值
            if day_key in weights_by_day:
                latest_weight = weights_by_day[day_key]
                break
        pinned_side = None
        if authored_weight > 0 and len(weights_by_day) == TOPIC_PIN_CONSECUTIVE_DAYS:
            if all(
                weight >= TOPIC_PIN_HIGH_RATIO * authored_weight
                for weight in weights_by_day.values()
            ):
                pinned_side = "high"
            elif all(
                weight <= TOPIC_PIN_LOW_RATIO * authored_weight
                for weight in weights_by_day.values()
            ):
                pinned_side = "low"
        entry = {
            "code": code,
            "authored_weight": authored_weight,
            "pos": pos,
            "neg": neg,
            "latest_effective_weight": latest_weight,
            "pinned": pinned_side,
        }
        topics.append(entry)
        if pinned_side is not None:
            pinned.append(
                {
                    "code": code,
                    "authored_weight": authored_weight,
                    "pinned": pinned_side,
                    "suggestion": "revise_authored_weight",
                },
            )
    return {
        "rubric_version": rubric_version,
        "topics": topics,
        "pinned_topics": pinned,
    }


# ---------------------------------------------------------------------------
# rubric 修订提案（§13.5；LLM 只在全部前置条件满足时调用，人审硬门）
# ---------------------------------------------------------------------------


class ProposalOutputError(ValueError):
    """模型输出不符合提案 schema 或 change_summary 与 diff 不一致。"""


def proposal_rubric_fingerprint(rubric: dict[str, Any]) -> str:
    """提案 rubric 的确定性 fingerprint（accept 时登记 compile 记录复用）。"""
    body = {key: value for key, value in rubric.items() if key != "source_guidance_fingerprint"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(
        f"{canonical}|{RUBRIC_SCHEMA_VERSION}|{PROPOSAL_COMPILE_PROMPT_VERSION}".encode(),
    ).hexdigest()
    return f"sha256:{digest}"


def _parse_model_json(content: str) -> Any:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _topic_weight_map(rubric: dict[str, Any]) -> dict[str, float]:
    return {
        str(topic.get("code")): float(topic.get("weight") or 0.0)
        for topic in rubric.get("topics") or []
        if isinstance(topic, dict) and topic.get("code")
    }


def _exclusion_codes(rubric: dict[str, Any]) -> set[str]:
    return {
        str(entry.get("code"))
        for entry in rubric.get("exclusions") or []
        if isinstance(entry, dict) and entry.get("code")
    }


def validate_change_summary(
    change_summary: Any,
    current_rubric: dict[str, Any],
    proposed_rubric: dict[str, Any],
) -> list[dict[str, Any]]:
    """change_summary 必须逐条合法且与前后 rubric 的 topic/exclusion diff 一致。"""
    if not isinstance(change_summary, list) or not change_summary:
        raise ProposalOutputError("change_summary must be a non-empty list")
    entries: list[dict[str, Any]] = []
    declared: dict[str, set[str]] = {op: set() for op in CHANGE_SUMMARY_OPS}
    for raw in change_summary:
        if not isinstance(raw, dict):
            raise ProposalOutputError("change_summary entries must be objects")
        op = raw.get("op")
        if op not in CHANGE_SUMMARY_OPS:
            raise ProposalOutputError(f"invalid change_summary op: {op!r}")
        target = str(raw.get("target_code") or "")
        if not target:
            raise ProposalOutputError(f"change_summary op {op} requires target_code")
        declared[op].add(target)
        entries.append(
            {
                "op": op,
                "target_code": target,
                "from": raw.get("from"),
                "to": raw.get("to"),
                "rationale": str(raw.get("rationale") or "")[:PROPOSAL_RATIONALE_MAX],
            },
        )

    current_topics = _topic_weight_map(current_rubric)
    proposed_topics = _topic_weight_map(proposed_rubric)
    added_topics = set(proposed_topics) - set(current_topics)
    removed_topics = set(current_topics) - set(proposed_topics)
    weight_changed = {
        code
        for code in set(current_topics) & set(proposed_topics)
        if abs(current_topics[code] - proposed_topics[code]) > 1e-9
    }
    if added_topics != declared["add_topic"]:
        raise ProposalOutputError("change_summary add_topic entries do not match rubric diff")
    if removed_topics != declared["remove_topic"]:
        raise ProposalOutputError("change_summary remove_topic entries do not match rubric diff")
    if not weight_changed <= declared["adjust_topic_weight"]:
        raise ProposalOutputError(
            "change_summary adjust_topic_weight entries do not cover rubric weight diff",
        )
    current_exclusions = _exclusion_codes(current_rubric)
    proposed_exclusions = _exclusion_codes(proposed_rubric)
    if (proposed_exclusions - current_exclusions) != declared["add_exclusion"]:
        raise ProposalOutputError("change_summary add_exclusion entries do not match rubric diff")
    if (current_exclusions - proposed_exclusions) != declared["remove_exclusion"]:
        raise ProposalOutputError(
            "change_summary remove_exclusion entries do not match rubric diff",
        )
    return entries


def _select_exemplars(facts: _WindowFacts) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """确定性代表样本（§13.5）：采信/驳回各按 final_score 降序 top 8。"""

    def build(news_ids: set[str]) -> list[dict[str, Any]]:
        candidates = [
            (news_id, facts.rec_by_news[news_id])
            for news_id in news_ids
            if news_id in facts.rec_by_news
        ]
        candidates.sort(key=lambda pair: (-float(pair[1].final_score or 0.0), pair[0]))
        exemplars = []
        for news_id, item in candidates[:PROPOSAL_EXEMPLAR_LIMIT]:
            exemplars.append(
                {
                    "news_item_id": news_id,
                    "title": facts.news_titles.get(news_id, ""),
                    "summary": (facts.news_summaries.get(news_id, ""))[
                        :PROPOSAL_EXEMPLAR_SUMMARY_MAX
                    ],
                    "source_name": facts.source_names.get(
                        facts.source_by_news.get(news_id, ""),
                        "",
                    ),
                    "rubric_hits": [str(hit) for hit in item.rubric_hits_json or []],
                },
            )
        return exemplars

    return build(facts.adopted), build(facts.rejected)


def expire_stale_proposals(session: Session, workspace_code: str, now: datetime) -> int:
    """把超 30 天仍 pending_review 的提案置 expired（§16.1 提案过期治理）。"""
    cutoff = now - timedelta(days=PROPOSAL_EXPIRY_DAYS)
    stale_rows = session.scalars(
        select(RubricRevisionProposal).where(
            RubricRevisionProposal.workspace_code == workspace_code,
            RubricRevisionProposal.status == "pending_review",
        ),
    ).all()
    expired = 0
    for proposal in stale_rows:
        created_at = _ensure_aware(proposal.created_at)
        if created_at is not None and created_at < cutoff:
            proposal.status = "expired"
            expired += 1
    return expired


def _generate_revision_proposal(
    session: Session,
    workspace: Workspace,
    rollup: FeedbackRollup,
    policy: dict[str, Any],
    facts: _WindowFacts,
    metrics: dict[str, Any],
    topic_breakdown: dict[str, Any],
) -> str:
    """返回 proposal_status（generated | failed | skipped_*，rollup 本身照常成功）。"""
    existing = session.scalar(
        select(RubricRevisionProposal).where(RubricRevisionProposal.rollup_id == rollup.id),
    )
    if existing is not None:
        # 幂等：本窗口已有提案（任意状态）不重复生成（§18 断言 2）。
        return "generated"

    rubric = policy.get("active_rubric")
    if policy.get("rubric_status") != "active" or not isinstance(rubric, dict):
        return "skipped_no_rubric"
    workflow = policy.get("feedback_workflow") or {}
    if not workflow.get("proposal_generation_enabled", True):
        return "skipped_disabled"
    strong_signals = len(facts.daily_adopt_events) + len(facts.daily_reject_events)
    if strong_signals < PROPOSAL_MIN_STRONG_SIGNALS:
        return "skipped_low_data"
    pending = session.scalar(
        select(RubricRevisionProposal).where(
            RubricRevisionProposal.workspace_code == workspace.code,
            RubricRevisionProposal.status == "pending_review",
        ),
    )
    if pending is not None:
        return "skipped_pending_exists"
    config = resolve_generation_config(workspace=workspace)
    if not (config.enabled and config.key_configured):
        return "skipped_provider"
    day_key = current_day_key()
    if (
        generation_calls_used(session, workspace.code, day_key, purpose=PURPOSE_FEEDBACK_ROLLUP)
        >= FEEDBACK_ROLLUP_DAILY_CAP
    ):
        return "skipped_budget"

    adopted_exemplars, rejected_exemplars = _select_exemplars(facts)
    from app.recommendations.reaggregate import latest_effective_topic_weights

    effective_weights = latest_effective_topic_weights(
        session,
        workspace.code,
        int(policy.get("rubric_version") or 0),
    )
    user_prompt = json.dumps(
        {
            "prompt_version": REVISION_PROMPT_VERSION,
            "current_rubric": rubric,
            "effective_topic_weights": effective_weights,
            "weekly_metrics": metrics,
            "adopted_exemplars": adopted_exemplars,
            "rejected_exemplars": rejected_exemplars,
            "pinned_topics": topic_breakdown.get("pinned_topics") or [],
        },
        ensure_ascii=False,
    )

    proposed_rubric: dict[str, Any] | None = None
    change_summary: list[dict[str, Any]] = []
    attempted = False
    for _attempt in (1, 2):
        if not try_acquire_feedback_rollup_call(session, workspace.code, day_key):
            if not attempted:
                return "skipped_budget"
            break
        attempted = True
        try:
            content = request_chat_completion(config, REVISION_SYSTEM_PROMPT, user_prompt)
            parsed = _parse_model_json(content)
            if not isinstance(parsed, dict):
                raise ProposalOutputError("proposal output must be a JSON object")
            candidate = validate_rubric(parsed.get("proposed_rubric"), fingerprint="")
            candidate["source_guidance_fingerprint"] = proposal_rubric_fingerprint(candidate)
            change_summary = validate_change_summary(
                parsed.get("change_summary"),
                rubric,
                candidate,
            )
            proposed_rubric = candidate
            break
        except (
            ProposalOutputError,
            RubricValidationError,
            ValueError,
            KeyError,
            TypeError,
        ):
            proposed_rubric = None
    if proposed_rubric is None:
        return "failed"

    proposal = RubricRevisionProposal(
        workspace_code=workspace.code,
        rollup_id=rollup.id,
        base_rubric_version=int(policy.get("rubric_version") or 0),
        prompt_version=REVISION_PROMPT_VERSION,
        proposed_rubric_json=proposed_rubric,
        change_summary_json=change_summary,
        sample_refs_json={
            "adopted": [entry["news_item_id"] for entry in adopted_exemplars],
            "rejected": [entry["news_item_id"] for entry in rejected_exemplars],
        },
        status="pending_review",
    )
    session.add(proposal)
    session.flush()
    # 兜底手动触发竞态：新提案入库后，同工作台其余 pending 一律 superseded。
    supersede_other_pending_proposals(session, workspace.code, keep_id=proposal.id)
    return "generated"


def supersede_other_pending_proposals(
    session: Session,
    workspace_code: str,
    *,
    keep_id: str,
) -> int:
    """新提案入库后把同工作台其余 pending_review 提案置 superseded（§13.5 兜底）。"""
    leftovers = session.scalars(
        select(RubricRevisionProposal).where(
            RubricRevisionProposal.workspace_code == workspace_code,
            RubricRevisionProposal.status == "pending_review",
            RubricRevisionProposal.id != keep_id,
        ),
    ).all()
    for leftover in leftovers:
        leftover.status = "superseded"
    return len(leftovers)


# ---------------------------------------------------------------------------
# 周 rollup（§13）
# ---------------------------------------------------------------------------


def _upsert_rollup(
    session: Session,
    workspace_code: str,
    period_type: str,
    period_key: str,
) -> FeedbackRollup:
    rollup = session.scalar(
        select(FeedbackRollup).where(
            FeedbackRollup.workspace_code == workspace_code,
            FeedbackRollup.period_type == period_type,
            FeedbackRollup.period_key == period_key,
        ),
    )
    if rollup is None:
        rollup = FeedbackRollup(
            workspace_code=workspace_code,
            period_type=period_type,
            period_key=period_key,
        )
        session.add(rollup)
    return rollup


def rollup_workspace_week(
    session: Session,
    workspace: Workspace,
    period_key: str,
    *,
    now: datetime | None = None,
) -> FeedbackRollup:
    moment = now or utc_now()
    window_start, window_end = weekly_window(period_key)
    policy = workspace_recommendation_policy(workspace)

    expire_stale_proposals(session, workspace.code, moment)

    facts = _collect_window_facts(session, workspace.code, window_start, window_end)
    lookback_facts = _collect_window_facts(
        session,
        workspace.code,
        window_end - timedelta(days=SOURCE_LOOKBACK_DAYS),
        window_end,
    )
    reports = _published_reports_in_window(session, workspace.code, window_start, window_end)
    source_breakdown, low_data = _source_breakdown(session, workspace, lookback_facts)
    topic_breakdown = _topic_breakdown(session, workspace, facts, policy, window_end)

    metrics: dict[str, Any] = {
        "precision_at_6": _precision_at_k(session, reports, 6),
        "precision_at_12": _precision_at_k(session, reports, 12),
        "rerank_uplift": _rerank_uplift(facts),
        "source_coverage": _source_coverage(facts),
        "topic_entropy": _topic_entropy(facts, policy.get("active_rubric")),
        "normalized_adopt_rate": _normalized_adopt_rate(facts),
        "edit_rate": _edit_rate(facts),
        "signal_counts": facts.signal_counts(),
        "low_data_sources": low_data,
    }

    rollup = _upsert_rollup(session, workspace.code, PERIOD_WEEKLY, period_key)
    rollup.window_start = window_start
    rollup.window_end = window_end
    rollup.status = "succeeded" if facts.total_feedback_events() > 0 else "empty"
    rollup.metrics_json = metrics
    rollup.source_breakdown_json = source_breakdown
    rollup.topic_breakdown_json = topic_breakdown
    adopted_refs, rejected_refs = _select_exemplars(facts)
    rollup.sample_refs_json = {
        "adopted": [entry["news_item_id"] for entry in adopted_refs],
        "rejected": [entry["news_item_id"] for entry in rejected_refs],
    }
    rollup.computed_at = moment
    session.flush()

    rollup.proposal_status = _generate_revision_proposal(
        session,
        workspace,
        rollup,
        policy,
        facts,
        metrics,
        topic_breakdown,
    )
    session.flush()
    return rollup


def run_feedback_weekly_rollup(
    session: Session,
    *,
    workspace_code: str | None = None,
    period_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """遍历 enabled 工作台逐个 rollup；单工作台失败不中断其余（§13.1）。"""
    moment = now or utc_now()
    key = period_key or previous_weekly_period(moment)
    weekly_window(key)  # 先校验 period_key 合法
    statement = select(Workspace).where(Workspace.enabled.is_(True)).order_by(Workspace.code)
    if workspace_code:
        statement = statement.where(Workspace.code == workspace_code)
    workspaces = session.scalars(statement).all()
    results: list[dict[str, Any]] = []
    for workspace in workspaces:
        workflow = workspace_recommendation_policy(workspace).get("feedback_workflow") or {}
        if not workspace_code and not workflow.get("weekly_rollup_enabled", True):
            results.append(
                {"workspace_code": workspace.code, "status": "skipped_disabled"},
            )
            continue
        try:
            # SAVEPOINT 隔离：单工作台失败只回滚自身，不吞掉已完成工作台的 rollup。
            with session.begin_nested():
                rollup = rollup_workspace_week(session, workspace, key, now=moment)
            results.append(
                {
                    "workspace_code": workspace.code,
                    "status": rollup.status,
                    "proposal_status": rollup.proposal_status,
                    "rollup_id": rollup.id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 单工作台失败不阻塞其余
            failed = _upsert_rollup(session, workspace.code, PERIOD_WEEKLY, key)
            window_start, window_end = weekly_window(key)
            failed.window_start = window_start
            failed.window_end = window_end
            failed.status = "failed"
            failed.metrics_json = {"error": str(exc)[:200]}
            failed.computed_at = moment
            session.flush()
            results.append({"workspace_code": workspace.code, "status": "failed"})
    session.flush()
    return {
        "job": "feedback_weekly_rollup",
        "period_key": key,
        "workspaces_total": len(workspaces),
        "results": results,
    }


# ---------------------------------------------------------------------------
# 月 review（§14；v1 纯聚合零 LLM）
# ---------------------------------------------------------------------------


def _previous_month_key(period_key: str) -> str:
    year, month = int(period_key[:4]), int(period_key[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _run_summary_flag_counts(
    session: Session,
    workspace_code: str,
    window_start: datetime,
    window_end: datetime,
) -> tuple[int, int]:
    runs = session.scalars(
        select(RecommendationRun).where(
            RecommendationRun.workspace_code == workspace_code,
            RecommendationRun.created_at >= window_start,
            RecommendationRun.created_at < window_end,
        ),
    ).all()
    drift = 0
    low_variance = 0
    for run in runs:
        block = (run.summary_json or {}).get("llm_rerank") or {}
        if block.get("drift_alert"):
            drift += 1
        if block.get("low_variance"):
            low_variance += 1
    return drift, low_variance


def _weekly_rollups_for_month(
    session: Session,
    workspace_code: str,
    window_start: datetime,
    window_end: datetime,
) -> list[FeedbackRollup]:
    rows = session.scalars(
        select(FeedbackRollup)
        .where(
            FeedbackRollup.workspace_code == workspace_code,
            FeedbackRollup.period_type == PERIOD_WEEKLY,
        )
        .order_by(FeedbackRollup.period_key.asc()),
    ).all()
    selected = []
    for rollup in rows:
        rollup_end = _ensure_aware(rollup.window_end)
        if rollup_end is None:
            continue
        if window_start < rollup_end <= window_end:
            selected.append(rollup)
    return selected


def _stale_source_suggestions(
    session: Session,
    workspace: Workspace,
    month_entries: list[dict[str, Any]],
    window_end: datetime,
) -> list[dict[str, Any]]:
    enabled_sources = _workspace_sources(session, workspace)
    suggestions: dict[str, dict[str, Any]] = {}

    # (a) 连续 4 个周 rollup recommended_count=0 → suggest_disable。
    recent_weeklies = [
        rollup
        for rollup in session.scalars(
            select(FeedbackRollup)
            .where(
                FeedbackRollup.workspace_code == workspace.code,
                FeedbackRollup.period_type == PERIOD_WEEKLY,
            )
            .order_by(FeedbackRollup.period_key.desc()),
        ).all()
        if _ensure_aware(rollup.window_end) is not None
        and _ensure_aware(rollup.window_end) <= window_end
    ][:STALE_ZERO_RECOMMENDED_WEEKS]
    if len(recent_weeklies) == STALE_ZERO_RECOMMENDED_WEEKS:
        for source_id, name in enabled_sources.items():
            zero_everywhere = True
            for rollup in recent_weeklies:
                entries = (rollup.source_breakdown_json or {}).get("sources") or []
                counts = {
                    entry.get("data_source_id"): int(entry.get("recommended_count") or 0)
                    for entry in entries
                }
                if counts.get(source_id, 0) != 0:
                    zero_everywhere = False
                    break
            if zero_everywhere:
                suggestions[source_id] = {
                    "id": source_id,
                    "name": name,
                    "suggestion": "suggest_disable",
                    "reason": f"连续 {STALE_ZERO_RECOMMENDED_WEEKS} 周零推荐",
                }

    # (b) 当月 recommended >= 8 且 adopted = 0 且 reject_rate >= 0.5 → suggest_review。
    for entry in month_entries:
        source_id = entry["data_source_id"]
        if source_id not in enabled_sources:
            continue
        if (
            entry["recommended_count"] >= STALE_MIN_RECOMMENDED
            and entry["adopted_count"] == 0
            and entry["reject_rate"] >= STALE_MIN_REJECT_RATE
        ):
            suggestions.setdefault(
                source_id,
                {
                    "id": source_id,
                    "name": entry["name"],
                    "suggestion": "suggest_review",
                    "reason": "当月高驳回零采信",
                },
            )
    return [suggestions[source_id] for source_id in sorted(suggestions)]


def rollup_workspace_month(
    session: Session,
    workspace: Workspace,
    period_key: str,
    *,
    now: datetime | None = None,
) -> FeedbackRollup:
    moment = now or utc_now()
    window_start, window_end = monthly_window(period_key)
    facts = _collect_window_facts(session, workspace.code, window_start, window_end)
    reports = _published_reports_in_window(session, workspace.code, window_start, window_end)
    precision_at_6 = _precision_at_k(session, reports, 6)
    precision_at_12 = _precision_at_k(session, reports, 12)

    # 长期漂移：优先读上月 monthly rollup 指标，缺失时按原始数据重算。
    previous_key = _previous_month_key(period_key)
    previous_rollup = session.scalar(
        select(FeedbackRollup).where(
            FeedbackRollup.workspace_code == workspace.code,
            FeedbackRollup.period_type == PERIOD_MONTHLY,
            FeedbackRollup.period_key == previous_key,
        ),
    )
    previous_precision: float | None = None
    if previous_rollup is not None:
        raw = (previous_rollup.metrics_json or {}).get("precision_at_6")
        previous_precision = float(raw) if isinstance(raw, (int, float)) else None
    else:
        prev_start, prev_end = monthly_window(previous_key)
        prev_reports = _published_reports_in_window(session, workspace.code, prev_start, prev_end)
        previous_precision = _precision_at_k(session, prev_reports, 6)
    drift_flag = False
    if previous_precision is not None and precision_at_6 is not None and previous_precision > 0:
        drop = previous_precision - precision_at_6
        drift_flag = drop >= DRIFT_ABSOLUTE_DROP and drop / previous_precision > DRIFT_RELATIVE_DROP

    drift_runs, low_variance_runs = _run_summary_flag_counts(
        session,
        workspace.code,
        window_start,
        window_end,
    )

    # 当月各周 rollup 指标均值/序列 + 提案审阅计数。
    weeklies = _weekly_rollups_for_month(session, workspace.code, window_start, window_end)
    weekly_series: dict[str, list[Any]] = {}
    weekly_means: dict[str, float | None] = {}
    for metric in ("precision_at_6", "precision_at_12", "rerank_uplift", "normalized_adopt_rate"):
        series = [
            (rollup.period_key, (rollup.metrics_json or {}).get(metric)) for rollup in weeklies
        ]
        weekly_series[metric] = [
            {"period_key": period, "value": value} for period, value in series
        ]
        values = [value for _period, value in series if isinstance(value, (int, float))]
        weekly_means[metric] = round(sum(values) / len(values), 4) if values else None

    proposals = session.scalars(
        select(RubricRevisionProposal).where(
            RubricRevisionProposal.workspace_code == workspace.code,
        ),
    ).all()
    generated = sum(
        1 for proposal in proposals if _in_window(proposal.created_at, window_start, window_end)
    )
    accepted = sum(
        1
        for proposal in proposals
        if proposal.status == "accepted"
        and _in_window(proposal.reviewed_at, window_start, window_end)
    )
    rejected = sum(
        1
        for proposal in proposals
        if proposal.status == "rejected"
        and _in_window(proposal.reviewed_at, window_start, window_end)
    )

    month_breakdown, _low_data = _source_breakdown(session, workspace, facts)
    month_breakdown["window"] = "month"
    stale = _stale_source_suggestions(
        session,
        workspace,
        month_breakdown["sources"],
        window_end,
    )
    month_breakdown["stale_source_suggestions"] = stale

    metrics: dict[str, Any] = {
        "precision_at_6": precision_at_6,
        "precision_at_12": precision_at_12,
        "previous_precision_at_6": previous_precision,
        "drift_flag": drift_flag,
        "run_drift_alert_count": drift_runs,
        "run_low_variance_count": low_variance_runs,
        "weekly_metric_means": weekly_means,
        "weekly_metric_series": weekly_series,
        "proposal_counts": {
            "generated": generated,
            "accepted": accepted,
            "rejected": rejected,
        },
        "signal_counts": facts.signal_counts(),
    }

    rollup = _upsert_rollup(session, workspace.code, PERIOD_MONTHLY, period_key)
    rollup.window_start = window_start
    rollup.window_end = window_end
    rollup.status = "succeeded" if facts.total_feedback_events() > 0 else "empty"
    rollup.proposal_status = "none"  # 月节拍 v1 零 LLM 调用（§14 写死）
    rollup.metrics_json = metrics
    rollup.source_breakdown_json = month_breakdown
    rollup.topic_breakdown_json = {}
    rollup.sample_refs_json = {}
    rollup.computed_at = moment
    session.flush()
    return rollup


def run_feedback_monthly_review(
    session: Session,
    *,
    workspace_code: str | None = None,
    period_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or utc_now()
    key = period_key or previous_monthly_period(moment)
    monthly_window(key)
    statement = select(Workspace).where(Workspace.enabled.is_(True)).order_by(Workspace.code)
    if workspace_code:
        statement = statement.where(Workspace.code == workspace_code)
    workspaces = session.scalars(statement).all()
    results: list[dict[str, Any]] = []
    for workspace in workspaces:
        workflow = workspace_recommendation_policy(workspace).get("feedback_workflow") or {}
        if not workspace_code and not workflow.get("monthly_review_enabled", True):
            results.append({"workspace_code": workspace.code, "status": "skipped_disabled"})
            continue
        try:
            with session.begin_nested():
                rollup = rollup_workspace_month(session, workspace, key, now=moment)
            results.append(
                {
                    "workspace_code": workspace.code,
                    "status": rollup.status,
                    "rollup_id": rollup.id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 单工作台失败不阻塞其余
            failed = _upsert_rollup(session, workspace.code, PERIOD_MONTHLY, key)
            window_start, window_end = monthly_window(key)
            failed.window_start = window_start
            failed.window_end = window_end
            failed.status = "failed"
            failed.metrics_json = {"error": str(exc)[:200]}
            failed.computed_at = moment
            session.flush()
            results.append({"workspace_code": workspace.code, "status": "failed"})
    session.flush()
    return {
        "job": "feedback_monthly_review",
        "period_key": key,
        "workspaces_total": len(workspaces),
        "results": results,
    }


# ---------------------------------------------------------------------------
# ε 探索位（§15；epsilon=0 缺省关闭，选择行为与现状逐位一致）
# ---------------------------------------------------------------------------


def exploration_draw(run_key: str) -> float:
    """确定性抽签：sha256(run_key + ':exploration') 归一到 0..1（同 run_key 可复现）。"""
    digest = hashlib.sha256(f"{run_key}:exploration".encode()).hexdigest()
    return int(digest, 16) / float(2**256)


def latest_low_data_source_ids(session: Session, workspace_code: str) -> set[str]:
    """最新 weekly rollup 的低数据源清单（无 rollup → 空集，探索位不生效）。"""
    rollup = session.scalar(
        select(FeedbackRollup)
        .where(
            FeedbackRollup.workspace_code == workspace_code,
            FeedbackRollup.period_type == PERIOD_WEEKLY,
        )
        .order_by(FeedbackRollup.period_key.desc())
        .limit(1),
    )
    if rollup is None:
        return set()
    entries = (rollup.metrics_json or {}).get("low_data_sources") or []
    return {
        str(entry.get("id"))
        for entry in entries
        if isinstance(entry, dict) and entry.get("id")
    }


# ---------------------------------------------------------------------------
# RQ job 入口（scheduler 投递；幂等可重跑）
# ---------------------------------------------------------------------------


def run_feedback_weekly_rollup_job() -> dict[str, Any]:
    from app.core.database import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for feedback rollup jobs.")
    with session_factory() as session:
        payload = run_feedback_weekly_rollup(session)
        session.commit()
        return payload


def run_feedback_monthly_review_job() -> dict[str, Any]:
    from app.core.database import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for feedback rollup jobs.")
    with session_factory() as session:
        payload = run_feedback_monthly_review(session)
        session.commit()
        return payload
