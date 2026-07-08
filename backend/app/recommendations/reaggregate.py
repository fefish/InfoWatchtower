"""反馈周期再估计：源先验与主题权重每日 job（feedback_reaggregate_daily）。

事实源：docs/backend/recommendation-scoring-design.md §8、
docs/backend/feedback-heat-scoring.md §10；契约：
config/contracts/recommendation_ranking.json `feedback_reestimation`。

- trailing 14 天窗口，每日全量重估、非累加（delta/乘子硬界防振荡）；
- 幂等：同 day_key 重跑覆盖当日快照（unique 约束 + upsert）;
- 只读反馈聚合，禁止改写评论/通知/Strategy Loop 状态与 authored rubric；
- 历史 recommendation_items 快照不被修改——delta 只影响后续新 run 的
  `_source_score`，旧 run 分数保持原样。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.common import utc_now
from app.models.content import (
    GeneratedNews,
    NewsItem,
    RecommendationItem,
    RubricTopicPrior,
    SourceScoreSnapshot,
)
from app.models.feedback import Reaction
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace
from app.recommendations.policy import workspace_recommendation_policy

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
REAGGREGATE_WINDOW = "14d"
REAGGREGATE_WINDOW_DAYS = 14
SOURCE_PRIOR_DELTA_BOUND = 6.0
TOPIC_WEIGHT_CLAMP = (0.5, 1.5)
ADOPTED_STATUS = 2
REJECTED_STATUS = 3


def source_prior_delta(adopt_rate: float, reject_rate: float, like_rate: float) -> float:
    """clamp(8*adopt - 6*reject + 2*like, -6.0, +6.0)（公式写死，§8.1）。"""
    raw = 8.0 * adopt_rate - 6.0 * reject_rate + 2.0 * like_rate
    return max(-SOURCE_PRIOR_DELTA_BOUND, min(SOURCE_PRIOR_DELTA_BOUND, raw))


def effective_topic_weight(authored_weight: float, pos: int, neg: int) -> float:
    """clamp(w * (1 + 0.1*(pos-neg)/max(5, pos+neg)), 0.5w, 1.5w)（§8.2）。"""
    multiplier = 1.0 + 0.1 * (pos - neg) / max(5, pos + neg)
    low = TOPIC_WEIGHT_CLAMP[0] * authored_weight
    high = TOPIC_WEIGHT_CLAMP[1] * authored_weight
    return max(low, min(high, authored_weight * multiplier))


def run_feedback_reaggregate(
    session: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """全量重估所有 enabled 工作台的源先验与主题权重快照（幂等覆盖当日）。"""
    moment = now or utc_now()
    day_key = moment.astimezone(BEIJING_TZ).date().isoformat()
    window_start = moment - timedelta(days=REAGGREGATE_WINDOW_DAYS)
    computed_at = utc_now()

    workspaces = session.scalars(
        select(Workspace).where(Workspace.enabled.is_(True)).order_by(Workspace.code),
    ).all()
    source_snapshots_total = 0
    topic_priors_total = 0
    for workspace in workspaces:
        stats = _collect_window_stats(session, workspace.code, window_start)
        source_snapshots_total += _upsert_source_snapshots(
            session,
            workspace.code,
            stats,
            day_key=day_key,
            computed_at=computed_at,
        )
        topic_priors_total += _upsert_topic_priors(
            session,
            workspace,
            stats,
            day_key=day_key,
            computed_at=computed_at,
        )
    session.flush()
    return {
        "status": "succeeded",
        "day_key": day_key,
        "window": REAGGREGATE_WINDOW,
        "workspaces_total": len(workspaces),
        "source_snapshots_total": source_snapshots_total,
        "topic_priors_total": topic_priors_total,
    }


class _WindowStats:
    """窗口内 (news_item -> 采信/剔除/点赞/来源/rubric 命中) 聚合。"""

    def __init__(self) -> None:
        self.source_by_news: dict[str, str] = {}
        self.adopted: set[str] = set()
        self.rejected: set[str] = set()
        self.liked_counts: dict[str, int] = {}
        # news_item_id -> {(rubric_version, topic_code), ...}
        self.rubric_hits: dict[str, set[tuple[int, str]]] = {}


def _collect_window_stats(session: Session, workspace_code: str, window_start: datetime) -> _WindowStats:
    stats = _WindowStats()
    rows = session.execute(
        select(RecommendationItem, NewsItem.data_source_id)
        .join(NewsItem, NewsItem.id == RecommendationItem.news_item_id)
        .where(
            RecommendationItem.workspace_code == workspace_code,
            RecommendationItem.created_at >= window_start,
        ),
    ).all()
    if not rows:
        return stats
    item_ids: list[str] = []
    for item, data_source_id in rows:
        stats.source_by_news.setdefault(item.news_item_id, data_source_id)
        item_ids.append(item.id)
        hits = item.rubric_hits_json or []
        if hits:
            bucket = stats.rubric_hits.setdefault(item.news_item_id, set())
            for code in hits:
                bucket.add((int(item.rubric_version or 0), str(code)))

    news_ids = list(stats.source_by_news)

    # 采信/剔除：沿 recommendation_item -> generated_news -> daily_report_item 链。
    report_rows = session.execute(
        select(
            GeneratedNews.news_item_id,
            DailyReportItem.id,
            DailyReportItem.adoption_status,
            DailyReport.status,
        )
        .join(DailyReportItem, DailyReportItem.generated_news_id == GeneratedNews.id)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .where(
            GeneratedNews.workspace_code == workspace_code,
            GeneratedNews.news_item_id.in_(news_ids),
        ),
    ).all()
    report_item_to_news: dict[str, str] = {}
    for news_item_id, report_item_id, adoption_status, report_status in report_rows:
        report_item_to_news[report_item_id] = news_item_id
        if adoption_status == ADOPTED_STATUS and report_status == "published":
            stats.adopted.add(news_item_id)
        elif adoption_status == REJECTED_STATUS:
            stats.rejected.add(news_item_id)

    # 点赞：news_item 维度 + 日报条目维度（去重按 reaction 行）。
    like_rows = session.execute(
        select(Reaction.news_item_id, Reaction.daily_report_item_id).where(
            Reaction.active.is_(True),
            Reaction.reaction_type == "like",
        ),
    ).all()
    for news_item_id, daily_report_item_id in like_rows:
        target = None
        if news_item_id and news_item_id in stats.source_by_news:
            target = news_item_id
        elif daily_report_item_id and daily_report_item_id in report_item_to_news:
            target = report_item_to_news[daily_report_item_id]
        if target is not None:
            stats.liked_counts[target] = stats.liked_counts.get(target, 0) + 1
    return stats


def _upsert_source_snapshots(
    session: Session,
    workspace_code: str,
    stats: _WindowStats,
    *,
    day_key: str,
    computed_at: datetime,
) -> int:
    per_source: dict[str, dict[str, int]] = {}
    for news_item_id, data_source_id in stats.source_by_news.items():
        bucket = per_source.setdefault(
            data_source_id,
            {"recommended": 0, "adopted": 0, "rejected": 0, "likes": 0},
        )
        bucket["recommended"] += 1
        if news_item_id in stats.adopted:
            bucket["adopted"] += 1
        if news_item_id in stats.rejected:
            bucket["rejected"] += 1
        bucket["likes"] += stats.liked_counts.get(news_item_id, 0)

    written = 0
    for data_source_id, bucket in per_source.items():
        recommended = bucket["recommended"]
        adopt_rate = bucket["adopted"] / max(1, recommended)
        reject_rate = bucket["rejected"] / max(1, recommended)
        like_rate = min(1.0, bucket["likes"] / max(1, recommended))
        delta = source_prior_delta(adopt_rate, reject_rate, like_rate)
        snapshot = session.scalar(
            select(SourceScoreSnapshot).where(
                SourceScoreSnapshot.workspace_code == workspace_code,
                SourceScoreSnapshot.data_source_id == data_source_id,
                SourceScoreSnapshot.window == REAGGREGATE_WINDOW,
                SourceScoreSnapshot.day_key == day_key,
            ),
        )
        if snapshot is None:
            snapshot = SourceScoreSnapshot(
                workspace_code=workspace_code,
                data_source_id=data_source_id,
                window=REAGGREGATE_WINDOW,
                day_key=day_key,
            )
            session.add(snapshot)
        snapshot.recommended_count = recommended
        snapshot.adopted_count = bucket["adopted"]
        snapshot.rejected_count = bucket["rejected"]
        snapshot.like_count = bucket["likes"]
        snapshot.adopt_rate = round(adopt_rate, 4)
        snapshot.reject_rate = round(reject_rate, 4)
        snapshot.like_rate = round(like_rate, 4)
        snapshot.source_prior_delta = round(delta, 4)
        snapshot.computed_at = computed_at
        written += 1
    return written


def _upsert_topic_priors(
    session: Session,
    workspace: Workspace,
    stats: _WindowStats,
    *,
    day_key: str,
    computed_at: datetime,
) -> int:
    policy = workspace_recommendation_policy(workspace)
    rubric = policy.get("active_rubric")
    if policy.get("rubric_status") != "active" or not isinstance(rubric, dict):
        return 0
    rubric_version = int(policy.get("rubric_version") or 0)

    written = 0
    for topic in rubric.get("topics") or []:
        code = str(topic.get("code") or "")
        if not code:
            continue
        authored_weight = float(topic.get("weight") or 0.0)
        pos = 0
        neg = 0
        # rubric_version 变更后统计清零重来：只统计当前版本的命中快照。
        for news_item_id, hits in stats.rubric_hits.items():
            if (rubric_version, code) not in hits:
                continue
            if news_item_id in stats.adopted:
                pos += 1
            if news_item_id in stats.rejected:
                neg += 1
        weight = effective_topic_weight(authored_weight, pos, neg)
        prior = session.scalar(
            select(RubricTopicPrior).where(
                RubricTopicPrior.workspace_code == workspace.code,
                RubricTopicPrior.rubric_version == rubric_version,
                RubricTopicPrior.topic_code == code,
                RubricTopicPrior.day_key == day_key,
            ),
        )
        if prior is None:
            prior = RubricTopicPrior(
                workspace_code=workspace.code,
                rubric_version=rubric_version,
                topic_code=code,
                day_key=day_key,
            )
            session.add(prior)
        prior.pos_count = pos
        prior.neg_count = neg
        prior.effective_weight = round(weight, 4)
        prior.computed_at = computed_at
        written += 1
    return written


def latest_source_prior_deltas(session: Session, workspace_code: str) -> dict[str, float]:
    """L1 `_source_score` 消费的最新源先验增量（无快照 -> 空 dict，行为与现状一致）。"""
    rows = session.execute(
        select(
            SourceScoreSnapshot.data_source_id,
            SourceScoreSnapshot.source_prior_delta,
            SourceScoreSnapshot.day_key,
        )
        .where(
            SourceScoreSnapshot.workspace_code == workspace_code,
            SourceScoreSnapshot.window == REAGGREGATE_WINDOW,
        )
        .order_by(SourceScoreSnapshot.day_key.asc()),
    ).all()
    deltas: dict[str, float] = {}
    for data_source_id, delta, _day_key in rows:
        # 升序遍历：后写入（更大 day_key）覆盖，留下每源最新快照。
        deltas[data_source_id] = float(delta or 0.0)
    return deltas


def latest_effective_topic_weights(
    session: Session,
    workspace_code: str,
    rubric_version: int,
) -> dict[str, float]:
    """L3 rerank prompt 消费的最新 effective topic weights（无快照 -> 空 dict）。"""
    rows = session.execute(
        select(
            RubricTopicPrior.topic_code,
            RubricTopicPrior.effective_weight,
            RubricTopicPrior.day_key,
        )
        .where(
            RubricTopicPrior.workspace_code == workspace_code,
            RubricTopicPrior.rubric_version == rubric_version,
        )
        .order_by(RubricTopicPrior.day_key.asc()),
    ).all()
    weights: dict[str, float] = {}
    for topic_code, weight, _day_key in rows:
        weights[topic_code] = float(weight or 0.0)
    return weights


def run_feedback_reaggregate_daily_job() -> dict[str, Any]:
    """RQ job 入口（scheduler 每日 02:00 Asia/Shanghai 投递，幂等可重跑）。"""
    from app.core.database import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for feedback reaggregate jobs.")
    with session_factory() as session:
        payload = run_feedback_reaggregate(session)
        session.commit()
        return payload
