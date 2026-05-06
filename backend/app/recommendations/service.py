from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.llm import generate_news_with_minimax
from app.models.common import utc_now
from app.models.content import (
    DedupeGroup,
    DedupeGroupItem,
    GeneratedNews,
    NewsItem,
    RecommendationItem,
    RecommendationRun,
)
from app.models.feedback import Comment, Rating, Reaction
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace, WorkspaceSourceLink

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_RECOMMENDATION_LIMIT = 15
DEFAULT_SOURCE_DAILY_LIMIT = 2


@dataclass(frozen=True)
class RecommendationRunRequest:
    workspace_code: str
    day_key: str | None = None
    limit: int = DEFAULT_RECOMMENDATION_LIMIT
    source_daily_limit: int = DEFAULT_SOURCE_DAILY_LIMIT
    create_daily_draft: bool = True


@dataclass(frozen=True)
class RecommendationRunResult:
    run: RecommendationRun
    daily_report: DailyReport | None
    candidates_total: int
    selected_total: int
    generated_total: int


class WorkspaceNotFoundError(ValueError):
    pass


class PublishedDailyReportError(ValueError):
    pass


def run_daily_recommendation(
    session: Session,
    request: RecommendationRunRequest,
    now: datetime | None = None,
) -> RecommendationRunResult:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == request.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {request.workspace_code}")

    now = now or _recommendation_now_for_day(request.day_key)
    day_key = request.day_key or now.astimezone(BEIJING_TZ).date().isoformat()
    limit = max(0, request.limit)
    source_daily_limit = max(1, request.source_daily_limit)
    candidates = _candidate_rows(session, workspace.code, day_key)
    scored = sorted(
        (_score_candidate(session, workspace, row, now) for row in candidates),
        key=lambda item: item.final_score,
        reverse=True,
    )
    selected_ids = _selected_candidate_ids(scored, limit, source_daily_limit)

    run = RecommendationRun(
        run_key=_run_key(workspace.code, day_key, now),
        workspace_code=workspace.code,
        domain_code=workspace.default_domain_code,
        status="running",
        started_at=now,
        params_json={
            "workspace_code": workspace.code,
            "day_key": day_key,
            "limit": limit,
            "source_daily_limit": source_daily_limit,
            "create_daily_draft": request.create_daily_draft,
        },
    )
    session.add(run)
    session.flush()

    recommendation_items: list[RecommendationItem] = []
    for rank, score in enumerate(scored, start=1):
        recommendation_item = RecommendationItem(
            run=run,
            workspace_code=workspace.code,
            domain_code=score.news_item.domain_code,
            visibility_scope=score.news_item.visibility_scope,
            sync_policy=score.news_item.sync_policy,
            dedupe_group=score.dedupe_group,
            dedupe_group_item=score.dedupe_group_item,
            news_item=score.news_item,
            rank=rank,
            quality_score=score.quality_score,
            topic_score=score.topic_score,
            freshness_score=score.freshness_score,
            feedback_score=score.feedback_score,
            diversity_score=score.diversity_score,
            source_score=score.source_score,
            heat_score=score.heat_score,
            final_score=score.final_score,
            selected=score.news_item.id in selected_ids,
            recommendation_reason=score.reason,
        )
        session.add(recommendation_item)
        recommendation_items.append(recommendation_item)

    session.flush()
    generated_news = [
        _create_generated_news(session, workspace, item)
        for item in recommendation_items
        if item.selected
    ]
    daily_report = None
    if request.create_daily_draft:
        daily_report = _create_or_replace_daily_draft(
            session=session,
            workspace=workspace,
            day_key=day_key,
            generated_news=generated_news,
        )

    run.status = "completed"
    run.completed_at = utc_now()
    run.summary_json = {
        "candidates_total": len(scored),
        "selected_total": len(selected_ids),
        "generated_total": len(generated_news),
        "daily_report_id": daily_report.id if daily_report else None,
    }
    session.flush()
    return RecommendationRunResult(
        run=run,
        daily_report=daily_report,
        candidates_total=len(scored),
        selected_total=len(selected_ids),
        generated_total=len(generated_news),
    )


@dataclass(frozen=True)
class CandidateRow:
    dedupe_group: DedupeGroup
    dedupe_group_item: DedupeGroupItem
    news_item: NewsItem


@dataclass(frozen=True)
class ScoredCandidate:
    dedupe_group: DedupeGroup
    dedupe_group_item: DedupeGroupItem
    news_item: NewsItem
    quality_score: float
    topic_score: float
    freshness_score: float
    feedback_score: float
    diversity_score: float
    source_score: float
    heat_score: float
    final_score: float
    reason: str


def _candidate_rows(
    session: Session,
    workspace_code: str,
    day_key: str | None = None,
) -> list[CandidateRow]:
    rows = session.execute(
        select(DedupeGroup, DedupeGroupItem, NewsItem)
        .join(DedupeGroupItem, DedupeGroupItem.dedupe_group_id == DedupeGroup.id)
        .join(NewsItem, NewsItem.id == DedupeGroupItem.news_item_id)
        .where(
            DedupeGroup.workspace_code == workspace_code,
            DedupeGroup.status == "active",
            DedupeGroupItem.is_winner.is_(True),
            NewsItem.workspace_code == workspace_code,
            NewsItem.active.is_(True),
            NewsItem.normalization_status == "normalized",
        )
    ).all()
    candidates = [
        CandidateRow(dedupe_group=row[0], dedupe_group_item=row[1], news_item=row[2])
        for row in rows
    ]
    if not day_key:
        return candidates
    return [row for row in candidates if _matches_day_key(row.news_item, day_key)]


def _matches_day_key(news_item: NewsItem, day_key: str) -> bool:
    published_at = news_item.published_at or news_item.created_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return published_at.astimezone(BEIJING_TZ).date().isoformat() == day_key


def _score_candidate(
    session: Session,
    workspace: Workspace,
    row: CandidateRow,
    now: datetime,
) -> ScoredCandidate:
    news_item = row.news_item
    quality_score = _quality_score(news_item)
    topic_score = _topic_score(news_item, workspace)
    freshness_score = _freshness_score(news_item, now)
    source_score = _source_score(session, workspace, news_item)
    heat_score = _heat_score(session, news_item)
    feedback_score = _feedback_score(session, news_item)
    diversity_score = _diversity_score(news_item)
    final_score = (
        quality_score * 0.25
        + topic_score * 0.25
        + freshness_score * 0.15
        + source_score * 0.15
        + heat_score * 0.10
        + feedback_score * 0.10
        + diversity_score
    )
    return ScoredCandidate(
        dedupe_group=row.dedupe_group,
        dedupe_group_item=row.dedupe_group_item,
        news_item=news_item,
        quality_score=round(quality_score, 2),
        topic_score=round(topic_score, 2),
        freshness_score=round(freshness_score, 2),
        feedback_score=round(feedback_score, 2),
        diversity_score=round(diversity_score, 2),
        source_score=round(source_score, 2),
        heat_score=round(heat_score, 2),
        final_score=round(final_score, 2),
        reason=_recommendation_reason(
            quality_score=quality_score,
            topic_score=topic_score,
            freshness_score=freshness_score,
            source_score=source_score,
            heat_score=heat_score,
        ),
    )


def _selected_candidate_ids(
    scored: list[ScoredCandidate],
    limit: int,
    source_daily_limit: int,
) -> set[str]:
    selected: set[str] = set()
    source_counts: dict[str, int] = {}
    for score in scored:
        if len(selected) >= limit:
            break
        source_id = score.news_item.data_source_id
        if source_counts.get(source_id, 0) >= source_daily_limit:
            continue
        selected.add(score.news_item.id)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
    return selected


def _quality_score(news_item: NewsItem) -> float:
    content_length = len(news_item.content or "")
    title_bonus = 8.0 if len(news_item.source_title or "") >= 8 else 0.0
    url_bonus = 10.0 if news_item.canonical_url else 0.0
    return min(100.0, 30.0 + title_bonus + url_bonus + math.log1p(content_length) * 8.0)


def _topic_score(news_item: NewsItem, workspace: Workspace) -> float:
    policy = _label_policy(workspace)
    text = f"{news_item.source_title} {news_item.summary} {news_item.content}".lower()
    allowed = set(policy["allowed_primary_categories"])
    score = 55.0
    keyword_hits = {
        "智能体": ["agent", "智能体", "agents"],
        "模型": ["model", "模型", "llm"],
        "推理加速": ["inference", "推理", "加速"],
        "训练技术": ["training", "训练"],
        "工具新功能": ["release", "发布", "更新", "feature"],
        "工具新案例": ["case", "案例", "实践"],
        "工具新技术": ["技术", "architecture", "benchmark"],
    }
    for category, keywords in keyword_hits.items():
        if category in allowed and any(keyword in text for keyword in keywords):
            score += 20.0
            break
    if news_item.domain_code == workspace.default_domain_code:
        score += 15.0
    return min(100.0, score)


def _freshness_score(news_item: NewsItem, now: datetime) -> float:
    published_at = news_item.published_at or news_item.created_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
    return max(15.0, 100.0 * math.exp(-hours / 168.0))


def _source_score(session: Session, workspace: Workspace, news_item: NewsItem) -> float:
    link = session.scalar(
        select(WorkspaceSourceLink).where(
            WorkspaceSourceLink.workspace_id == workspace.id,
            WorkspaceSourceLink.data_source_id == news_item.data_source_id,
        ),
    )
    weight = link.source_weight if link else 1.0
    base = 60.0 + min(weight, 2.0) * 15.0
    if "official" in (news_item.source_name or "").lower():
        base += 10.0
    return min(100.0, base)


def _heat_score(session: Session, news_item: NewsItem) -> float:
    likes = session.scalar(
        select(func.count(Reaction.id)).where(
            Reaction.news_item_id == news_item.id,
            Reaction.active.is_(True),
            Reaction.reaction_type == "like",
        ),
    ) or 0
    comments = session.scalar(
        select(func.count(Comment.id)).where(
            Comment.news_item_id == news_item.id,
            Comment.status == "visible",
        ),
    ) or 0
    ratings = session.scalars(
        select(Rating.score).where(Rating.news_item_id == news_item.id),
    ).all()
    rating_avg = sum(ratings) / len(ratings) if ratings else 0.0
    return min(100.0, likes * 8.0 + comments * 12.0 + len(ratings) * rating_avg * 3.0)


def _feedback_score(session: Session, news_item: NewsItem) -> float:
    ratings = session.scalars(select(Rating.score).where(Rating.news_item_id == news_item.id)).all()
    if not ratings:
        return 0.0
    return min(100.0, (sum(ratings) / len(ratings)) * 20.0)


def _diversity_score(news_item: NewsItem) -> float:
    if news_item.source_type == "paper_rss":
        return 4.0
    if news_item.source_type == "wiseflow":
        return 3.0
    return 0.0


def _recommendation_reason(
    quality_score: float,
    topic_score: float,
    freshness_score: float,
    source_score: float,
    heat_score: float,
) -> str:
    reasons: list[str] = []
    if quality_score >= 75:
        reasons.append("content_quality")
    if topic_score >= 75:
        reasons.append("topic_match")
    if freshness_score >= 60:
        reasons.append("fresh")
    if source_score >= 80:
        reasons.append("trusted_source")
    if heat_score > 0:
        reasons.append("user_feedback")
    return "; ".join(reasons) or "baseline_score"


def _create_generated_news(
    session: Session,
    workspace: Workspace,
    recommendation_item: RecommendationItem,
) -> GeneratedNews:
    news_item = recommendation_item.news_item
    category = _category_for_news(workspace, news_item)
    policy = _label_policy(workspace)
    llm_draft = generate_news_with_minimax(
        news_item,
        fallback_category=category,
        allowed_categories=list(policy["allowed_primary_categories"]),
        recommendation_reason=recommendation_item.recommendation_reason,
    )
    if llm_draft is None:
        content_json = {
            "eventSummary": news_item.summary or news_item.source_title,
            "technologyAndInnovation": _content_excerpt(news_item.content),
            "valueAndImpact": "该信号进入日报候选，后续由管理员结合业务场景判断采信和改写。",
            "background": f"来源：{news_item.source_name}；类型：{news_item.source_type}",
        }
        generated_fields = {
            "category": category,
            "title": _generated_title(news_item),
            "summary": news_item.summary or news_item.content[:220],
            "key_points": _key_points(news_item, category),
            "content_json": content_json,
            "generated_by": "rule_v1",
        }
    else:
        generated_fields = {
            "category": llm_draft.category,
            "title": llm_draft.title,
            "summary": llm_draft.summary,
            "key_points": llm_draft.key_points,
            "content_json": llm_draft.content_json,
            "generated_by": llm_draft.generated_by,
        }
    generated_fields["content_json"] = {
        **generated_fields["content_json"],
        "source": {
            "news_item_id": news_item.id,
            "raw_item_id": news_item.raw_item_id,
            "data_source_id": news_item.data_source_id,
        },
    }
    generated = GeneratedNews(
        recommendation_item=recommendation_item,
        news_item=news_item,
        workspace_code=workspace.code,
        domain_code=news_item.domain_code,
        visibility_scope=news_item.visibility_scope,
        sync_policy=news_item.sync_policy,
        category=str(generated_fields["category"]),
        title=str(generated_fields["title"]),
        summary=str(generated_fields["summary"]),
        key_points=str(generated_fields["key_points"]),
        content_json=generated_fields["content_json"],
        source_url=news_item.source_url,
        generated_by=str(generated_fields["generated_by"]),
        generation_status="ready",
    )
    session.add(generated)
    return generated


def _create_or_replace_daily_draft(
    session: Session,
    workspace: Workspace,
    day_key: str,
    generated_news: list[GeneratedNews],
) -> DailyReport:
    report = session.scalar(
        select(DailyReport).where(
            DailyReport.workspace_code == workspace.code,
            DailyReport.domain_code == workspace.default_domain_code,
            DailyReport.day_key == day_key,
        ),
    )
    if report is None:
        report = DailyReport(
            workspace_code=workspace.code,
            domain_code=workspace.default_domain_code,
            day_key=day_key,
            title=f"{day_key} {workspace.name} 日报",
            summary="由阶段 5 推荐链路生成的日报草稿。",
            status="draft",
        )
        session.add(report)
        session.flush()
    elif report.status == "published":
        raise PublishedDailyReportError(f"Daily report is already published: {report.id}")
    else:
        report.title = f"{day_key} {workspace.name} 日报"
        report.summary = "由阶段 5 推荐链路生成的日报草稿。"
        session.execute(delete(DailyReportItem).where(DailyReportItem.daily_report_id == report.id))
        session.flush()

    for index, item in enumerate(generated_news, start=1):
        session.add(
            DailyReportItem(
                daily_report=report,
                generated_news=item,
                workspace_code=workspace.code,
                domain_code=item.domain_code,
                visibility_scope=item.visibility_scope,
                sync_policy=item.sync_policy,
                adoption_status=2,
                sort_order=index,
            ),
        )
    return report


def _label_policy(workspace: Workspace) -> dict[str, object]:
    config = workspace.config_json or {}
    policy = config.get("label_policy") or {}
    allowed = list(policy.get("allowed_primary_categories") or [])
    if not allowed:
        allowed = ["AI 应用"]
    return {
        "allowed_primary_categories": allowed,
        "default_category": str(policy.get("default_category") or allowed[0]),
        "fallback_category": str(policy.get("fallback_category") or allowed[0]),
    }


def _category_for_news(workspace: Workspace, news_item: NewsItem) -> str:
    policy = _label_policy(workspace)
    allowed = list(policy["allowed_primary_categories"])
    text = f"{news_item.source_title} {news_item.summary} {news_item.content}".lower()
    ordered_rules = [
        ("智能体", ["agent", "agents", "智能体"]),
        ("模型", ["model", "模型", "llm"]),
        ("推理加速", ["inference", "推理", "加速"]),
        ("训练技术", ["training", "训练"]),
        ("工具新案例", ["case", "案例"]),
        ("工具新技术", ["技术", "benchmark", "architecture"]),
        ("工具新功能", ["release", "发布", "更新", "feature"]),
    ]
    for category, keywords in ordered_rules:
        if category in allowed and any(keyword in text for keyword in keywords):
            return category
    default_category = str(policy["default_category"])
    return default_category if default_category in allowed else allowed[0]


def _generated_title(news_item: NewsItem) -> str:
    title = (news_item.source_title or "未命名情报").strip()
    if len(title) <= 80:
        return title
    return f"{title[:77].rstrip()}..."


def _key_points(news_item: NewsItem, category: str) -> str:
    parts = [
        category,
        news_item.source_type,
        news_item.source_name,
    ]
    if news_item.canonical_url:
        parts.append("canonical_url")
    return ", ".join(parts)


def _content_excerpt(content: str) -> str:
    if len(content) <= 500:
        return content
    return f"{content[:497].rstrip()}..."


def _recommendation_now_for_day(day_key: str | None) -> datetime:
    if not day_key:
        return utc_now()
    try:
        target_date = date.fromisoformat(day_key)
    except ValueError:
        return utc_now()
    return datetime.combine(target_date, time(23, 59, 59), tzinfo=BEIJING_TZ).astimezone(UTC)


def _run_key(workspace_code: str, day_key: str, now: datetime) -> str:
    compact_time = now.strftime("%Y%m%d%H%M%S%f")
    return f"{workspace_code}:recommendation:{day_key}:{compact_time}"
