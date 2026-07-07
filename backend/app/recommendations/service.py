from __future__ import annotations

import html
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
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
from app.models.export import ExportJobItem
from app.models.feedback import Comment, EditorialAction, Rating, Reaction
from app.models.reports import DailyReport, DailyReportItem, WeeklyReportItem
from app.models.strategy import RequirementSourceLink
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.news_keywords import fallback_key_points
from app.scoring.content_scorer import load_content_scorer
from app.workspaces.policy import (
    WorkspaceContentPolicy,
    ensure_workspace_label_set,
    policy_for_workspace,
)

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_RECOMMENDATION_LIMIT = 15
DEFAULT_SOURCE_DAILY_LIMIT = 2
DEFAULT_GENERATION_TIMEOUT_SECONDS = 45.0
# 日报 draft 条目由推荐链路创建时的初始采信状态；偏离该值即视为编辑层决策。
DAILY_ITEM_INITIAL_ADOPTION_STATUS = 2
TECHNICAL_SOURCE_HINTS = (
    "machine learning",
    "ml blog",
    "research",
    "science",
    "aws ml",
    "google research",
    "deepmind",
    "microsoft research",
    "ibm research",
    "apple machine learning",
    "langchain",
    "llamaindex",
    "anthropic",
    "openai",
    "qwen",
    "kimi",
    "智东西",
)
VENDOR_TECH_SOURCE_HINTS = (
    "amd",
    "arm",
    "broadcom",
    "cisco",
    "cloudflare",
    "ericsson",
    "huawei",
    "intel",
    "mediatek",
    "meta engineering",
    "microsoft research",
    "nokia",
    "nvidia",
    "qualcomm",
    "samsung",
    "tsmc",
    "xilinx",
    "华为",
    "中兴",
    "英伟达",
    "高通",
    "英特尔",
)
COMMERCIAL_SOURCE_HINTS = (
    "mobile world live",
    "telecoms",
    "light reading",
    "venturebeat",
    "businesswire",
    "pr newswire",
    "gsmarena",
    "36kr",
    "36氪",
    "weixin.sogou",
    "c114",
    "钛媒体",
    "新智元",
)
HARDWARE_TEXT_HINTS = (
    "accelerator",
    "ai factory",
    "asic",
    "cpo",
    "cuda",
    "cxl",
    "dpu",
    "fp8",
    "gpu",
    "hbm",
    "infiniband",
    "liquid cooling",
    "3nm",
    "nvlink",
    "npu",
    "rack",
    "smartnic",
    "tpu",
    "芯片",
    "集群",
    "液冷",
    "智算",
    "算力",
    "服务器",
    "加速卡",
    "数据中心",
    "晶片",
    "3纳米",
    "3奈米",
)
TELECOM_TECH_TEXT_HINTS = (
    "3gpp",
    "5g-a",
    "5gc",
    "6g",
    "ai-ran",
    "network api",
    "o-ran",
    "oran",
    "upf",
    "核心网",
    "无线接入网",
    "自治网络",
    "网络切片",
    "标准",
)
TECHNICAL_TEXT_HINTS = (
    "agent",
    "agents",
    "architecture",
    "arxiv",
    "benchmark",
    "dataset",
    "deployment",
    "evaluation",
    "fine-tuning",
    "framework",
    "inference",
    "latency",
    "llm",
    "memory",
    "model",
    "multi-agent",
    "paper",
    "privacy",
    "rag",
    "reasoning",
    "research",
    "retrieval",
    "training",
    "workflow",
    "工程",
    "架构",
    "大模型",
    "训练",
    "推理",
    "模型",
    "智能体",
    "多智能体",
    "多模态",
    "新模态",
    "记忆",
    "评测",
    "基准",
    "论文",
    "研究",
    "技术",
    "开源",
    "框架",
    "部署",
)
NOVELTY_TEXT_HINTS = (
    "announce",
    "benchmark",
    "introduce",
    "launch",
    "open source",
    "release",
    "ship",
    "update",
    "发布",
    "推出",
    "开源",
    "首个",
    "升级",
)
MATURITY_TEXT_HINTS = (
    "architecture",
    "benchmark",
    "deployment",
    "framework",
    "open source",
    "performance",
    "production",
    "serving",
    "throughput",
    "架构",
    "部署",
    "开源",
    "性能",
    "吞吐",
    "延迟",
    "落地",
)
COMMERCIAL_TEXT_HINTS = (
    "acquisition",
    "earnings",
    "funding",
    "growth",
    "investment",
    "profit",
    "quarter",
    "pre-order",
    "revenue",
    "round",
    "sales",
    "shares",
    "stock",
    "valuation",
    "banking",
    "citi",
    "gotrade",
    "gartner",
    "hedge fund",
    "highest use case score",
    "lifts",
    "market size",
    "trillion",
    "并购",
    "财报",
    "财季",
    "融资",
    "估值",
    "对冲基金",
    "花旗",
    "银行",
    "基金",
    "加码",
    "上看",
    "市场规模",
    "增资",
    "价格",
    "价格带",
    "亿美元",
    "万亿美元",
    "众筹",
    "股价",
    "营收",
    "净利",
    "订单",
    "bid",
    "procurement",
    "投资",
    "收购",
    "商业化",
    "发布手机",
    "发手机",
    "联合创始人",
    "扫地机",
    "充电宝",
    "庭审",
    "吸金",
    "采购",
    "中标",
    "集采",
    "市值",
    "业绩",
)
MACRO_BUSINESS_TEXT_HINTS = (
    "industrial revenue",
    "macroeconomic",
    "quarterly data",
    "同比增长",
    "利润总额",
    "产业数据",
    "经济运行",
    "工信部公布",
    "万亿元",
)
RUMOR_OR_UNVERIFIED_HINTS = (
    "leak",
    "leaked",
    "rumor",
    "unconfirmed",
    "曝光",
    "代码曝光",
    "内部测试代码",
    "传闻",
    "疑似",
    "宣战",
)
GENERIC_MARKETING_TEXT_HINTS = (
    "empower",
    "partnership",
    "strategic cooperation",
    "unlock value",
    "赋能",
    "携手",
    "战略合作",
    "签约",
    "生态合作",
    "千行百业",
)
EVENT_PROMO_TEXT_HINTS = (
    "agenda",
    "open house",
    "register",
    "webinar",
    "workshop",
    "报名",
    "议程",
    "预告",
    "直播",
    "峰会",
    "宣传推广会",
    "提质行动",
)
LEGAL_OR_META_NOISE_HINTS = (
    "copyright",
    "lawsuit",
    "publisher sues",
    "scraped research papers",
    "sues over",
    "legal",
    "postdoc salary",
    "bill is as big",
    "research integrity",
    "诉讼",
    "起诉",
    "版权",
    "法律",
)
BIOMEDICAL_NOISE_HINTS = (
    "antibody",
    "cancer",
    "clinical trial",
    "hematopoietic",
    "metastatic",
    "molecule",
    "neuron",
    "oncology",
    "pembrolizumab",
    "protein",
    "transcriptomic",
    "tumor",
    "antibiotic",
    "antibiotics",
    "autism",
    "autism spectrum",
    "细胞",
    "肿瘤",
    "临床",
    "基因",
    "蛋白",
)
SOCIAL_OFF_SCOPE_HINTS = (
    "behavior",
    "behaviour",
    "campus",
    "cheat",
    "political",
    "social science",
    "state media",
    "students",
    "university",
    "coding assignments",
    "aerospace",
    "rocket",
    "作弊",
    "高校",
    "媒体控制",
    "社会科学",
    "学生",
    "政治",
    "航天",
    "火箭",
    "运载火箭",
    "飞行试验",
)
AEROSPACE_OFF_SCOPE_HINTS = (
    "aerospace",
    "rocket",
    "spacecraft",
    "satellite launch",
    "航天",
    "火箭",
    "运载火箭",
    "飞行试验",
    "卫星发射",
)
CONSUMER_NOISE_HINTS = (
    "phone",
    "smartphone",
    "wearable",
    "appliance",
    "appliances",
    "smart appliance",
    "smart appliances",
    "kids' toys",
    "toy",
    "toys",
    "手机",
    "耳机",
    "汽车",
    "问界",
    "家电",
    "智能家电",
    "扫地机",
)
CLICKBAIT_TEXT_HINTS = (
    "dethroned",
    "evil",
    "just dethroned",
    "shocking",
    "won't snitch",
    "blames dystopian",
    "leaked",
    "rumor",
    "反超",
    "吊打",
    "震惊",
    "曝光",
    "宣战",
)
PURE_ACADEMIC_SOURCE_HINTS = (
    "nature",
    "science",
    "pnas",
    "pubmed",
    "mdpi",
    "springer",
)
CORE_TECH_POOLS = ("ai_engineering", "vendor_hardware", "telecom_system", "ai_research")
ADMISSION_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "R": 4}


@dataclass(frozen=True)
class RecommendationRunRequest:
    workspace_code: str
    day_key: str | None = None
    limit: int = DEFAULT_RECOMMENDATION_LIMIT
    source_daily_limit: int = DEFAULT_SOURCE_DAILY_LIMIT
    create_daily_draft: bool = True
    generation_timeout_seconds: float = DEFAULT_GENERATION_TIMEOUT_SECONDS


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


class DailyReportNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class DailyReportGenerationRerunRequest:
    report_id: str
    item_ids: list[str] | None = None
    limit: int | None = None
    replace_ready: bool = False
    generation_timeout_seconds: float = DEFAULT_GENERATION_TIMEOUT_SECONDS


@dataclass(frozen=True)
class DailyReportGenerationRerunResult:
    report: DailyReport
    attempted_total: int
    ready_total: int
    fallback_total: int
    skipped_total: int


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

    scoring_now = now or _recommendation_now_for_day(request.day_key)
    run_started_at = utc_now()
    day_key = request.day_key or scoring_now.astimezone(BEIJING_TZ).date().isoformat()
    limit = max(0, request.limit)
    source_daily_limit = max(1, request.source_daily_limit)
    policy = policy_for_workspace(workspace)
    # 自定义 label_set_code 随推荐链路运行落 LabelSet 记录（幂等）。
    ensure_workspace_label_set(session, workspace, policy)
    candidates = _candidate_rows(session, workspace.code, day_key)
    scored = sorted(
        (_score_candidate(session, workspace, row, scoring_now, policy) for row in candidates),
        key=lambda item: (
            ADMISSION_ORDER.get(item.admission_level, 9),
            -item.final_score,
        ),
    )
    selected_ids = _selected_candidate_ids(scored, limit, source_daily_limit)

    run = RecommendationRun(
        run_key=_run_key(workspace.code, day_key, run_started_at),
        workspace_code=workspace.code,
        domain_code=workspace.default_domain_code,
        status="running",
        started_at=run_started_at,
        params_json={
            "workspace_code": workspace.code,
            "day_key": day_key,
            "limit": limit,
            "source_daily_limit": source_daily_limit,
            "create_daily_draft": request.create_daily_draft,
            "generation_timeout_seconds": _normalize_generation_timeout(
                request.generation_timeout_seconds,
            ),
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
            admission_level=score.admission_level,
            admission_score=score.admission_score,
            admission_pool=score.admission_pool,
            noise_types_json=list(score.noise_types),
            reject_reasons_json=list(score.reject_reasons),
            scorer_breakdown_json=score.scorer_breakdown,
            expert_routes_json=list(score.expert_routes),
        )
        session.add(recommendation_item)
        recommendation_items.append(recommendation_item)

    session.flush()
    generation_timeout_seconds = _normalize_generation_timeout(
        request.generation_timeout_seconds,
    )
    generated_news = [
        _create_generated_news(
            session,
            workspace,
            item,
            generation_timeout_seconds=generation_timeout_seconds,
        )
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
        "generation_status": dict(
            Counter(item.generation_status for item in generated_news),
        ),
        "daily_report_id": daily_report.id if daily_report else None,
        "admission": _admission_summary(scored),
    }
    session.flush()
    return RecommendationRunResult(
        run=run,
        daily_report=daily_report,
        candidates_total=len(scored),
        selected_total=len(selected_ids),
        generated_total=len(generated_news),
    )


def regenerate_daily_report_generated_news(
    session: Session,
    request: DailyReportGenerationRerunRequest,
) -> DailyReportGenerationRerunResult:
    report = session.scalar(
        select(DailyReport)
        .options(
            selectinload(DailyReport.items)
            .selectinload(DailyReportItem.generated_news)
            .selectinload(GeneratedNews.recommendation_item)
            .selectinload(RecommendationItem.news_item),
        )
        .where(DailyReport.id == request.report_id),
    )
    if report is None:
        raise DailyReportNotFoundError(f"Daily report not found: {request.report_id}")
    if report.status == "published":
        raise PublishedDailyReportError(f"Daily report is already published: {report.id}")

    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == report.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {report.workspace_code}")

    allowed_item_ids = set(request.item_ids or [])
    items = sorted(report.items, key=lambda item: (item.sort_order, item.created_at, item.id))
    if allowed_item_ids:
        items = [item for item in items if item.id in allowed_item_ids]
    if request.limit is not None:
        items = items[: max(0, request.limit)]

    attempted_total = 0
    ready_total = 0
    fallback_total = 0
    skipped_total = 0
    timeout_seconds = _normalize_generation_timeout(request.generation_timeout_seconds)
    for item in items:
        generated = item.generated_news
        if generated.generation_status == "ready" and not request.replace_ready:
            skipped_total += 1
            continue
        recommendation_item = generated.recommendation_item
        if recommendation_item is None:
            skipped_total += 1
            continue
        attempted_total += 1
        _refresh_generated_news(
            generated,
            workspace,
            recommendation_item,
            generation_timeout_seconds=timeout_seconds,
        )
        if generated.generation_status == "ready":
            ready_total += 1
        else:
            fallback_total += 1

    session.flush()
    return DailyReportGenerationRerunResult(
        report=report,
        attempted_total=attempted_total,
        ready_total=ready_total,
        fallback_total=fallback_total,
        skipped_total=skipped_total,
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
    admission_level: str
    admission_score: float
    admission_pool: str
    noise_types: tuple[str, ...]
    reject_reasons: tuple[str, ...]
    expert_routes: tuple[str, ...]
    scorer_breakdown: dict[str, object]
    quality_score: float
    topic_score: float
    freshness_score: float
    feedback_score: float
    diversity_score: float
    source_score: float
    heat_score: float
    final_score: float
    reason: str


@dataclass(frozen=True)
class ContentAdmission:
    level: str
    score: float
    pool: str
    noise_types: tuple[str, ...]
    positive_reasons: tuple[str, ...]
    reject_reasons: tuple[str, ...]
    expert_routes: tuple[str, ...]
    scorer_breakdown: dict[str, object]
    eligible_for_daily: bool


@dataclass(frozen=True)
class ContentAdmissionPreviewRequest:
    workspace_code: str
    source_title: str
    summary: str = ""
    content: str = ""
    source_type: str = "rss"
    source_name: str = ""
    source_url: str = ""
    source_tier: str = ""
    source_channel_type: str = ""
    source_score: float = 0.0
    source_tags: tuple[str, ...] = ()
    source_secondary_tags: tuple[str, ...] = ()
    board_relevance_json: dict[str, object] | None = None
    freshness_score: float = 80.0


@dataclass(frozen=True)
class ContentAdmissionPreviewResult:
    workspace_code: str
    source_title: str
    admission: ContentAdmission


def preview_content_admission(
    session: Session,
    request: ContentAdmissionPreviewRequest,
) -> ContentAdmissionPreviewResult:
    workspace = session.scalar(select(Workspace).where(Workspace.code == request.workspace_code, Workspace.enabled.is_(True)))
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {request.workspace_code}")
    metadata = {
        "source_tier": request.source_tier,
        "source_channel_type": request.source_channel_type,
        "source_score": request.source_score,
        "source_tags": list(request.source_tags),
        "source_secondary_tags": list(request.source_secondary_tags),
        "board_relevance_json": request.board_relevance_json or {},
    }
    data_source = SimpleNamespace(metadata_json=metadata, source_score=request.source_score)
    news_item = SimpleNamespace(
        source_title=request.source_title,
        summary=request.summary,
        content=request.content,
        source_type=request.source_type,
        source_name=request.source_name,
        source_url=request.source_url,
        canonical_url=request.source_url,
        data_source=data_source,
    )
    admission = _content_admission(news_item, workspace, request.freshness_score, policy_for_workspace(workspace))
    return ContentAdmissionPreviewResult(
        workspace_code=workspace.code,
        source_title=request.source_title,
        admission=admission,
    )


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
    policy: WorkspaceContentPolicy,
) -> ScoredCandidate:
    news_item = row.news_item
    quality_score = _quality_score(news_item)
    topic_score = _topic_score(news_item, workspace, policy)
    freshness_score = _freshness_score(news_item, now)
    source_score = _source_score(session, workspace, news_item)
    heat_score = _heat_score(session, news_item)
    feedback_score = _feedback_score(session, news_item)
    diversity_score = _diversity_score(news_item)
    admission = _content_admission(news_item, workspace, freshness_score, policy)
    final_score = (
        admission.score * 0.35
        + quality_score * 0.15
        + topic_score * 0.20
        + freshness_score * 0.10
        + source_score * 0.10
        + heat_score * 0.10
        + feedback_score * 0.05
        + diversity_score
    )
    if admission.level == "R":
        final_score = min(final_score, 25.0)
    elif admission.level == "P3":
        final_score = min(final_score, 44.0)
    return ScoredCandidate(
        dedupe_group=row.dedupe_group,
        dedupe_group_item=row.dedupe_group_item,
        news_item=news_item,
        admission_level=admission.level,
        admission_score=round(admission.score, 2),
        admission_pool=admission.pool,
        noise_types=admission.noise_types,
        reject_reasons=admission.reject_reasons,
        expert_routes=admission.expert_routes,
        scorer_breakdown=admission.scorer_breakdown,
        quality_score=round(quality_score, 2),
        topic_score=round(topic_score, 2),
        freshness_score=round(freshness_score, 2),
        feedback_score=round(feedback_score, 2),
        diversity_score=round(diversity_score, 2),
        source_score=round(source_score, 2),
        heat_score=round(heat_score, 2),
        final_score=round(final_score, 2),
        reason=_recommendation_reason(
            admission=admission,
            quality_score=quality_score,
            topic_score=topic_score,
            freshness_score=freshness_score,
            source_score=source_score,
            heat_score=heat_score,
            feedback_score=feedback_score,
        ),
    )


def _selected_candidate_ids(
    scored: list[ScoredCandidate],
    limit: int,
    source_daily_limit: int,
) -> set[str]:
    selected: set[str] = set()
    source_counts: dict[str, int] = {}
    pool_counts: dict[str, int] = {}
    paper_count = 0
    paper_limit = max(1, math.ceil(limit * 0.10)) if limit else 0
    pool_limit = max(2, math.ceil(limit * 0.40)) if limit > 1 else 1

    def try_select(score: ScoredCandidate, *, enforce_mix: bool) -> bool:
        nonlocal paper_count
        if len(selected) >= limit or not _eligible_level(score.admission_level):
            return False
        if score.admission_level == "P2" and score.noise_types:
            return False
        if score.admission_level == "P2" and not _has_daily_worthy_signal(score):
            return False
        if score.news_item.source_type == "paper_rss" and score.admission_level not in {"P0", "P1"}:
            return False
        source_id = score.news_item.data_source_id
        if source_counts.get(source_id, 0) >= source_daily_limit:
            return False
        if enforce_mix:
            if score.news_item.source_type == "paper_rss" and paper_count >= paper_limit:
                return False
            if pool_counts.get(score.admission_pool, 0) >= pool_limit:
                return False
        selected.add(score.news_item.id)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        pool_counts[score.admission_pool] = pool_counts.get(score.admission_pool, 0) + 1
        if score.news_item.source_type == "paper_rss":
            paper_count += 1
        return True

    for allowed_levels, enforce_mix in (
        ({"P0", "P1"}, True),
        ({"P2"}, True),
    ):
        for score in scored:
            if len(selected) >= limit:
                break
            if score.news_item.id in selected or score.admission_level not in allowed_levels:
                continue
            try_select(score, enforce_mix=enforce_mix)
    return selected


def _eligible_level(level: str) -> bool:
    return level in {"P0", "P1", "P2"}


def _has_daily_worthy_signal(score: ScoredCandidate) -> bool:
    reason = score.reason
    if score.admission_pool in {"vendor_hardware", "telecom_system", "ai_engineering", "workspace_prior"}:
        return True
    return any(
        marker in reason
        for marker in (
            "technical_detail",
            "vendor_or_hardware_signal",
            "telecom_system_signal",
            "inference_signal",
            "implementation_or_benchmark_detail",
            "architecture_cost_or_performance_impact",
        )
    )


def _content_admission(
    news_item: NewsItem,
    workspace: Workspace,
    freshness_score: float,
    policy: WorkspaceContentPolicy,
) -> ContentAdmission:
    # AI 情报口径（噪声降权、AI 池、全局 scorer 配置）只对声明 AI 口径的
    # 工作台生效；其余工作台走中性准入，先验关键词经 policy 获取。
    if policy.scoring_mode != "ai_default":
        return _neutral_content_admission(news_item, policy, freshness_score)
    text = _candidate_text(news_item)
    source_identity = _source_identity(news_item)
    source_tags = _source_tags(news_item)
    source_secondary_tags = _source_secondary_tags(news_item)
    tag_text = " ".join([*source_tags, *source_secondary_tags]).lower()

    technical_hits = _keyword_hit_count(text, TECHNICAL_TEXT_HINTS)
    hardware_hits = _keyword_hit_count(text, HARDWARE_TEXT_HINTS)
    telecom_hits = _keyword_hit_count(text, TELECOM_TECH_TEXT_HINTS)
    novelty_hits = _keyword_hit_count(text, NOVELTY_TEXT_HINTS)
    maturity_hits = _keyword_hit_count(text, MATURITY_TEXT_HINTS)
    commercial_hits = _keyword_hit_count(text, COMMERCIAL_TEXT_HINTS)
    macro_business_hits = _keyword_hit_count(text, MACRO_BUSINESS_TEXT_HINTS)
    rumor_hits = _keyword_hit_count(text, RUMOR_OR_UNVERIFIED_HINTS)
    marketing_hits = _keyword_hit_count(text, GENERIC_MARKETING_TEXT_HINTS)
    event_hits = _keyword_hit_count(text, EVENT_PROMO_TEXT_HINTS)
    legal_hits = _keyword_hit_count(text, LEGAL_OR_META_NOISE_HINTS)
    biomedical_hits = _keyword_hit_count(text, BIOMEDICAL_NOISE_HINTS)
    consumer_hits = _keyword_hit_count(text, CONSUMER_NOISE_HINTS)
    clickbait_hits = _keyword_hit_count(text, CLICKBAIT_TEXT_HINTS)
    social_hits = _keyword_hit_count(text, SOCIAL_OFF_SCOPE_HINTS)
    aerospace_hits = _keyword_hit_count(text, AEROSPACE_OFF_SCOPE_HINTS)

    source_is_vendor = _contains_any(source_identity, VENDOR_TECH_SOURCE_HINTS)
    source_is_technical = _contains_any(source_identity, TECHNICAL_SOURCE_HINTS)
    source_is_commercial = _contains_any(source_identity, COMMERCIAL_SOURCE_HINTS)
    source_is_pure_academic = _contains_any(source_identity, PURE_ACADEMIC_SOURCE_HINTS)
    source_is_paper = news_item.source_type == "paper_rss"
    core_ai_signal = _core_ai_signal(text)
    tag_ai_engineering = any(
        token in tag_text
        for token in [
            "ai工程能力",
            "ai基础设施",
            "硬件",
            "芯片",
            "数据中心",
            "核心网",
            "通信系统",
        ]
    )
    technical_depth = bool(
        technical_hits >= 3
        or hardware_hits >= 2
        or telecom_hits
        or _contains_any(
            text,
            (
                "3d integration",
                "3dfabric",
                "architecture",
                "benchmark",
                "cluster scheduling",
                "inference serving",
                "model serving",
                "nvlink",
                "nccl",
                "webrtc",
                "3d集成",
                "架构",
                "基准",
                "集群调度",
                "模型服务",
                "推理服务",
                "网络原生",
            ),
        )
    )

    positive: list[str] = []
    noise: list[str] = []
    pool = "general_tech"
    topic_score = 24.0

    if technical_hits:
        topic_score += min(22.0, technical_hits * 4.0)
        positive.append("technical_detail")
    source_tag_can_boost = tag_ai_engineering and (technical_hits or hardware_hits or telecom_hits or core_ai_signal)
    if source_tag_can_boost:
        topic_score += 5.0
        positive.append("source_tag_match")
    vendor_content_signal = technical_hits or hardware_hits or telecom_hits or core_ai_signal
    if hardware_hits or (source_is_vendor and vendor_content_signal):
        topic_score += 16.0
        positive.append("vendor_or_hardware_signal")
        pool = "vendor_hardware"
    if telecom_hits:
        topic_score += 12.0
        positive.append("telecom_system_signal")
        pool = "telecom_system"
    if _contains_any(text, ("agent", "agents", "智能体", "mcp", "a2a", "tool calling")):
        topic_score += 12.0
        positive.append("agent_signal")
        if pool == "general_tech":
            pool = "ai_engineering"
    if _contains_any(text, ("inference", "serving", "kv cache", "推理", "吞吐", "延迟")):
        topic_score += 12.0
        positive.append("inference_signal")
        if pool == "general_tech":
            pool = "ai_engineering"
    if source_is_paper:
        pool = "ai_research" if (core_ai_signal or hardware_hits or telecom_hits) else "pure_research"
        if core_ai_signal or hardware_hits or telecom_hits:
            topic_score += 6.0
            positive.append("research_source")

    expert_impact = 5.0
    if hardware_hits or telecom_hits:
        expert_impact += 10.0
    if _contains_any(text, ("cost", "latency", "throughput", "tco", "energy", "成本", "能耗", "性能")):
        expert_impact += 8.0
        positive.append("architecture_cost_or_performance_impact")
    if source_is_vendor and technical_hits:
        expert_impact += 6.0

    evidence = 7.0
    if source_is_vendor or source_is_technical:
        evidence += 5.0
    if source_is_paper and (core_ai_signal or hardware_hits or telecom_hits):
        evidence += 5.0
    if "official" in source_identity or "research" in source_identity:
        evidence += 4.0
    if source_is_commercial:
        evidence -= 4.0

    novelty = min(10.0, novelty_hits * 3.0)
    if novelty:
        positive.append("new_or_released")
    maturity = min(10.0, maturity_hits * 2.5)
    if maturity:
        positive.append("implementation_or_benchmark_detail")
    freshness = min(5.0, freshness_score / 20.0)

    noise_penalty = 0.0
    if commercial_hits:
        noise.append("commercial_finance")
        noise_penalty += min(24.0, commercial_hits * 8.0)
    if macro_business_hits and not (technical_hits >= 3 and maturity_hits >= 2):
        noise.append("macro_business_stats")
        noise_penalty += 28.0
    if rumor_hits and not (source_is_vendor or source_is_technical or source_is_paper):
        noise.append("rumor_or_unverified")
        noise_penalty += 30.0
    if marketing_hits and technical_hits < 2 and hardware_hits == 0 and telecom_hits == 0:
        noise.append("generic_marketing")
        noise_penalty += 18.0
    if event_hits and marketing_hits:
        noise.append("marketing_event")
        noise_penalty += 35.0
    if event_hits and (technical_hits < 3 or commercial_hits):
        noise.append("event_promo")
        noise_penalty += 22.0
    if source_is_commercial and commercial_hits >= 3:
        noise.append("commercial_source_finance")
        noise_penalty += 30.0
    if legal_hits:
        noise.append("legal_or_meta_discussion")
        noise_penalty += 22.0
    if biomedical_hits:
        noise.append("biomedical_off_scope")
        noise_penalty += 35.0
    if social_hits and not (hardware_hits or telecom_hits or _contains_any(text, ("architecture", "benchmark", "inference", "架构", "基准", "推理"))):
        noise.append("social_or_policy_off_scope")
        noise_penalty += 22.0
    if aerospace_hits:
        noise.append("aerospace_off_scope")
        noise_penalty += 40.0
    if clickbait_hits and not (technical_hits >= 3 or hardware_hits or telecom_hits):
        noise.append("clickbait_or_low_signal")
        noise_penalty += 18.0
    if consumer_hits or "gsmarena" in source_identity:
        noise.append("consumer_product")
        noise_penalty += 35.0 if not core_ai_signal and hardware_hits < 2 else 12.0
    if source_is_pure_academic and source_is_paper and not (core_ai_signal or hardware_hits or telecom_hits):
        noise.append("pure_academic_off_scope")
        noise_penalty += 35.0
    if source_is_commercial and technical_hits < 2 and hardware_hits == 0 and telecom_hits == 0:
        noise.append("commercial_source_weak_tech")
        noise_penalty += 12.0

    score = (
        min(topic_score, 40.0)
        + min(expert_impact, 20.0)
        + max(0.0, min(evidence, 15.0))
        + novelty
        + maturity
        + freshness
        - noise_penalty
    )
    score = max(0.0, min(100.0, score))
    if score >= 85:
        level = "P0"
    elif score >= 60:
        level = "P1"
    elif score >= 44:
        level = "P2"
    elif score >= 30:
        level = "P3"
    else:
        level = "R"

    if "commercial_finance" in noise and not technical_depth:
        level = "R"
    elif "consumer_product" in noise and not technical_depth:
        level = "R"
    elif "legal_or_meta_discussion" in noise and not technical_depth:
        level = "R"
    elif "social_or_policy_off_scope" in noise and not technical_depth:
        level = "R"
    elif any(item in noise for item in ["biomedical_off_scope", "consumer_product"]) and score < 60:
        level = "R"
    elif "commercial_finance" in noise and score < 65:
        level = "R"
    elif "commercial_source_finance" in noise:
        level = "P3" if score >= 75 and technical_depth else "R"
    elif "macro_business_stats" in noise:
        level = "P3" if score >= 65 and technical_depth else "R"
    elif "rumor_or_unverified" in noise:
        level = "P3" if score >= 70 and technical_depth else "R"
    elif "event_promo" in noise and score < 70:
        level = "R"
    elif "marketing_event" in noise:
        level = "P3" if score >= 75 and technical_depth else "R"
    elif "aerospace_off_scope" in noise:
        level = "R"
    elif "legal_or_meta_discussion" in noise and score < 75:
        level = "P3"
    elif "social_or_policy_off_scope" in noise and score < 70:
        level = "P3"
    elif "clickbait_or_low_signal" in noise and score < 70:
        level = "R"
    elif "pure_academic_off_scope" in noise and score < 55:
        level = "P3"

    if workspace.code != "planning_intel" and level == "R" and not noise:
        level = "P2"

    baseline_admission = ContentAdmission(
        level=level,
        score=round(score, 2),
        pool=pool,
        noise_types=tuple(dict.fromkeys(noise)),
        positive_reasons=tuple(dict.fromkeys(positive)),
        reject_reasons=(),
        expert_routes=(),
        scorer_breakdown={"mode": "baseline"},
        eligible_for_daily=_eligible_level(level),
    )
    scorer_result = _configured_content_scorer().score(
        news_item,
        baseline_level=baseline_admission.level,
        baseline_score=baseline_admission.score,
        baseline_pool=baseline_admission.pool,
        baseline_noise_types=baseline_admission.noise_types,
        baseline_positive_reasons=baseline_admission.positive_reasons,
        freshness_score=freshness_score,
    )
    return ContentAdmission(
        level=scorer_result.level,
        score=scorer_result.score,
        pool=scorer_result.pool,
        noise_types=scorer_result.noise_types,
        positive_reasons=scorer_result.positive_reasons,
        reject_reasons=scorer_result.reject_reasons,
        expert_routes=scorer_result.expert_routes,
        scorer_breakdown=scorer_result.breakdown,
        eligible_for_daily=scorer_result.eligible_for_daily,
    )


def _neutral_content_admission(
    news_item: NewsItem,
    policy: WorkspaceContentPolicy,
    freshness_score: float,
) -> ContentAdmission:
    """非 AI 口径工作台的中性准入：不套 AI 噪声降权，
    先验关键词来自 domain pack scoring 或工作台标签策略。"""
    text = _candidate_text(news_item)
    prior_hits = _keyword_hit_count(text, policy.scoring_prior_keywords)
    novelty_hits = _keyword_hit_count(text, NOVELTY_TEXT_HINTS)
    positive: list[str] = []
    score = 45.0
    if prior_hits:
        score += min(24.0, prior_hits * 8.0)
        positive.append("workspace_prior_keyword")
    if novelty_hits:
        score += min(9.0, novelty_hits * 3.0)
        positive.append("new_or_released")
    if len(news_item.content or "") >= 200:
        score += 4.0
    if news_item.canonical_url:
        score += 2.0
    score += min(5.0, freshness_score / 20.0)
    score = max(0.0, min(100.0, score))
    if score >= 85:
        level = "P0"
    elif score >= 60:
        level = "P1"
    elif score >= 44:
        level = "P2"
    elif score >= 30:
        level = "P3"
    else:
        level = "R"
    return ContentAdmission(
        level=level,
        score=round(score, 2),
        pool="workspace_prior" if prior_hits else "general_tech",
        noise_types=(),
        positive_reasons=tuple(dict.fromkeys(positive)),
        reject_reasons=(),
        expert_routes=(),
        scorer_breakdown={
            "mode": "workspace_neutral",
            "config_loaded": False,
            "policy_source": policy.policy_source,
            "prior_keyword_hits": prior_hits,
        },
        eligible_for_daily=_eligible_level(level),
    )


def _admission_summary(scored: list[ScoredCandidate]) -> dict[str, object]:
    return {
        "levels": dict(Counter(item.admission_level for item in scored)),
        "pools": dict(Counter(item.admission_pool for item in scored)),
        "noise_types": dict(
            Counter(noise for item in scored for noise in item.noise_types),
        ),
        "reject_reasons": dict(
            Counter(reason for item in scored for reason in item.reject_reasons),
        ),
        "expert_routes": dict(
            Counter(route for item in scored for route in item.expert_routes),
        ),
        "eligible_for_daily": sum(1 for item in scored if _eligible_level(item.admission_level)),
    }


def _configured_content_scorer():
    settings = get_settings()
    return load_content_scorer(settings.content_scorer_config_path)


def _quality_score(news_item: NewsItem) -> float:
    content_length = len(news_item.content or "")
    title_bonus = 8.0 if len(news_item.source_title or "") >= 8 else 0.0
    url_bonus = 10.0 if news_item.canonical_url else 0.0
    return min(100.0, 30.0 + title_bonus + url_bonus + math.log1p(content_length) * 8.0)


def _topic_score(news_item: NewsItem, workspace: Workspace, policy: WorkspaceContentPolicy) -> float:
    text = _candidate_text(news_item)
    allowed = set(policy.allowed_primary_categories)
    score = 55.0
    for category, keywords in policy.category_keyword_rules:
        if category in allowed and any(keyword in text for keyword in keywords):
            score += 20.0
            break
    if policy.scoring_mode != "ai_default":
        # 中性口径：主题分只看策略先验与领域归属，不叠加 AI 文本信号。
        score += min(25.0, _keyword_hit_count(text, policy.scoring_prior_keywords) * 5.0)
        if news_item.domain_code == workspace.default_domain_code:
            score += 15.0
        return max(0.0, min(100.0, score))
    technical_hits = _keyword_hit_count(text, TECHNICAL_TEXT_HINTS)
    commercial_hits = _keyword_hit_count(text, COMMERCIAL_TEXT_HINTS)
    hardware_hits = _keyword_hit_count(text, HARDWARE_TEXT_HINTS)
    telecom_hits = _keyword_hit_count(text, TELECOM_TECH_TEXT_HINTS)
    score += min(25.0, technical_hits * 5.0)
    score += min(20.0, hardware_hits * 6.0 + telecom_hits * 5.0)
    score -= min(30.0, commercial_hits * 8.0)
    if news_item.source_type == "paper_rss" and (technical_hits or _source_tags(news_item)):
        score += 6.0
    if _contains_any(_source_identity(news_item), TECHNICAL_SOURCE_HINTS):
        score += 10.0
    if _contains_any(_source_identity(news_item), VENDOR_TECH_SOURCE_HINTS):
        score += 10.0
    if _contains_any(_source_identity(news_item), COMMERCIAL_SOURCE_HINTS):
        score -= 12.0
    if news_item.domain_code == workspace.default_domain_code:
        score += 15.0
    return max(0.0, min(100.0, score))


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
    source_identity = _source_identity(news_item)
    data_source = news_item.data_source
    if data_source and data_source.source_score:
        base += min(12.0, max(0.0, data_source.source_score) / 10.0)
    if "official" in source_identity:
        base += 10.0
    if news_item.source_type == "paper_rss":
        base += 6.0
    if _contains_any(source_identity, TECHNICAL_SOURCE_HINTS):
        base += 12.0
    if _contains_any(source_identity, VENDOR_TECH_SOURCE_HINTS):
        base += 10.0
    if _contains_any(source_identity, COMMERCIAL_SOURCE_HINTS):
        base -= 15.0
    return max(0.0, min(100.0, base))


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
    rating_score = (sum(ratings) / len(ratings)) * 20.0 if ratings else 0.0
    requirement_feedback = 0.0
    actions = session.scalars(
        select(EditorialAction).where(
            EditorialAction.object_type == "news_item",
            EditorialAction.object_id == news_item.id,
            EditorialAction.action_type == "requirement.feedback_to_recommendation",
        ),
    ).all()
    for action in actions:
        after_json = action.after_json or {}
        try:
            requirement_feedback += float(after_json.get("score_delta") or 0.0)
        except (TypeError, ValueError):
            continue
    return max(-50.0, min(100.0, rating_score + requirement_feedback))


def _diversity_score(news_item: NewsItem) -> float:
    if news_item.source_type == "paper_rss":
        return 2.0
    if news_item.source_type == "wiseflow":
        return 3.0
    source_identity = _source_identity(news_item)
    text = _candidate_text(news_item)
    if _contains_any(source_identity, COMMERCIAL_SOURCE_HINTS):
        return -6.0
    if _contains_any(source_identity, VENDOR_TECH_SOURCE_HINTS) or _keyword_hit_count(text, HARDWARE_TEXT_HINTS) > 0:
        return 8.0
    if _keyword_hit_count(text, TELECOM_TECH_TEXT_HINTS) > 0:
        return 6.0
    if _contains_any(source_identity, TECHNICAL_SOURCE_HINTS):
        return 5.0
    if _keyword_hit_count(text, TECHNICAL_TEXT_HINTS) >= 3:
        return 4.0
    return 0.0


def _source_identity(news_item: NewsItem) -> str:
    return (
        f"{news_item.source_name or ''} "
        f"{news_item.source_url or ''} "
        f"{news_item.canonical_url or ''}"
    ).lower()


def _candidate_text(news_item: NewsItem) -> str:
    return f"{news_item.source_title} {news_item.summary} {news_item.content}".lower()


def _source_tags(news_item: NewsItem) -> list[str]:
    metadata = (news_item.data_source.metadata_json if news_item.data_source else {}) or {}
    tags = metadata.get("source_tags") or []
    return [str(item) for item in tags] if isinstance(tags, list) else []


def _source_secondary_tags(news_item: NewsItem) -> list[str]:
    metadata = (news_item.data_source.metadata_json if news_item.data_source else {}) or {}
    tags = metadata.get("source_secondary_tags") or []
    return [str(item) for item in tags] if isinstance(tags, list) else []


def _core_ai_signal(text: str) -> bool:
    if re.search(r"\b(ai|llm|vlm|vla|agent|agents|rag|mcp|a2a|gpu|hbm|cxl|tpu|npu)\b", text):
        return True
    return _contains_any(
        text,
        (
            "大模型",
            "模型",
            "智能体",
            "推理",
            "训练",
            "评测",
            "多模态",
            "数据中心",
            "芯片",
            "算力",
        ),
    )


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(_keyword_in_text(text, keyword) for keyword in keywords)


def _keyword_hit_count(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if _keyword_in_text(text, keyword))


def _keyword_in_text(text: str, keyword: str) -> bool:
    normalized = keyword.lower()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9+._-]*", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None
    return normalized in text


def _recommendation_reason(
    admission: ContentAdmission,
    quality_score: float,
    topic_score: float,
    freshness_score: float,
    source_score: float,
    heat_score: float,
    feedback_score: float,
) -> str:
    reasons: list[str] = [
        f"admission={admission.level}",
        f"pool={admission.pool}",
        f"content_value={admission.score:.1f}",
    ]
    reasons.extend(admission.positive_reasons[:4])
    if admission.noise_types:
        reasons.append(f"noise={','.join(admission.noise_types)}")
    if admission.reject_reasons:
        reasons.append(f"reject={','.join(admission.reject_reasons[:3])}")
    if admission.expert_routes:
        reasons.append(f"expert={','.join(admission.expert_routes[:2])}")
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
    if feedback_score > 0:
        reasons.append("requirement_feedback_positive")
    elif feedback_score < 0:
        reasons.append("requirement_feedback_negative")
    return "; ".join(reasons) or "baseline_score"


def _create_generated_news(
    session: Session,
    workspace: Workspace,
    recommendation_item: RecommendationItem,
    *,
    generation_timeout_seconds: float,
) -> GeneratedNews:
    news_item = recommendation_item.news_item
    generated_fields = _generated_news_fields(
        workspace,
        recommendation_item,
        generation_timeout_seconds=generation_timeout_seconds,
    )
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
        generation_status=str(generated_fields["generation_status"]),
    )
    session.add(generated)
    return generated


def _refresh_generated_news(
    generated: GeneratedNews,
    workspace: Workspace,
    recommendation_item: RecommendationItem,
    *,
    generation_timeout_seconds: float,
) -> None:
    generated_fields = _generated_news_fields(
        workspace,
        recommendation_item,
        generation_timeout_seconds=generation_timeout_seconds,
    )
    generated.category = str(generated_fields["category"])
    generated.title = str(generated_fields["title"])
    generated.summary = str(generated_fields["summary"])
    generated.key_points = str(generated_fields["key_points"])
    generated.content_json = generated_fields["content_json"]
    generated.insight_json = generated_fields.get("insight_json") or {}
    generated.source_url = recommendation_item.news_item.source_url
    generated.generated_by = str(generated_fields["generated_by"])
    generated.generation_status = str(generated_fields["generation_status"])


def _generated_news_fields(
    workspace: Workspace,
    recommendation_item: RecommendationItem,
    *,
    generation_timeout_seconds: float,
) -> dict[str, object]:
    news_item = recommendation_item.news_item
    policy = policy_for_workspace(workspace)
    category = _category_for_news(workspace, news_item, policy)
    llm_draft = generate_news_with_minimax(
        news_item,
        fallback_category=category,
        allowed_categories=list(policy.allowed_primary_categories),
        recommendation_reason=recommendation_item.recommendation_reason,
        timeout_seconds=generation_timeout_seconds,
    )
    if llm_draft is None:
        content_json = {
            "background": f"来源：{news_item.source_name}；类型：{news_item.source_type}",
            "effects": policy.effects_fallback_text,
            "eventSummary": news_item.summary or news_item.source_title,
            "technologyAndInnovation": _content_excerpt(news_item.content),
            "valueAndImpact": "该信号进入日报候选，后续由管理员结合业务场景判断采信和改写。",
        }
        generated_fields = {
            "category": category,
            "title": _generated_title(news_item),
            "summary": news_item.summary or news_item.content[:220],
            "key_points": _key_points(news_item, category),
            "content_json": content_json,
            "insight_json": {},
            "generated_by": "rule_v1:fallback",
            "generation_status": "fallback_needs_review",
        }
    else:
        generated_fields = {
            "category": llm_draft.category,
            "title": llm_draft.title,
            "summary": llm_draft.summary,
            "key_points": llm_draft.key_points,
            "content_json": llm_draft.content_json,
            "insight_json": llm_draft.insight_json,
            "generated_by": llm_draft.generated_by,
            "generation_status": "ready",
        }
    generated_fields["content_json"] = {
        **generated_fields["content_json"],
        "source": {
            "news_item_id": news_item.id,
            "raw_item_id": news_item.raw_item_id,
            "data_source_id": news_item.data_source_id,
            "generation_timeout_seconds": generation_timeout_seconds,
        },
    }
    return generated_fields


def _normalize_generation_timeout(value: float) -> float:
    return min(max(float(value or DEFAULT_GENERATION_TIMEOUT_SECONDS), 5.0), 180.0)


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
    existing_items: list[DailyReportItem] = []
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
        # 重跑对既有 draft 走增量合并：报告层是唯一可编辑层，
        # adoption_status/is_headline/editor 覆盖不因 pipeline 重跑被整表重建。
        report.title = f"{day_key} {workspace.name} 日报"
        report.summary = "由阶段 5 推荐链路生成的日报草稿。"
        existing_items = list(
            session.scalars(
                select(DailyReportItem)
                .options(selectinload(DailyReportItem.generated_news))
                .where(DailyReportItem.daily_report_id == report.id)
                .order_by(
                    DailyReportItem.sort_order,
                    DailyReportItem.created_at,
                    DailyReportItem.id,
                ),
            ).all(),
        )

    by_generated_news_id: dict[str, DailyReportItem] = {}
    by_news_item_id: dict[str, DailyReportItem] = {}
    for existing in existing_items:
        by_generated_news_id.setdefault(existing.generated_news_id, existing)
        if existing.generated_news is not None:
            by_news_item_id.setdefault(existing.generated_news.news_item_id, existing)

    matched_item_ids: set[str] = set()
    for index, item in enumerate(generated_news, start=1):
        news_item_id = item.news_item.id if item.news_item is not None else item.news_item_id
        existing = by_generated_news_id.get(item.id) or by_news_item_id.get(news_item_id)
        if existing is not None and existing.id not in matched_item_ids:
            matched_item_ids.add(existing.id)
            # 已编辑条目原样保留（含其成稿指针）；未编辑条目跟随本次重跑刷新成稿和排序。
            if not _daily_report_item_edited(existing):
                existing.generated_news = item
                existing.sort_order = index
            continue
        session.add(
            DailyReportItem(
                daily_report=report,
                generated_news=item,
                workspace_code=workspace.code,
                domain_code=item.domain_code,
                visibility_scope=item.visibility_scope,
                sync_policy=item.sync_policy,
                adoption_status=DAILY_ITEM_INITIAL_ADOPTION_STATUS,
                sort_order=index,
            ),
        )

    # 只移除"不在新候选集 + 无编辑痕迹 + 无外部引用"的条目，避免抹掉编辑决策或悬挂外键。
    removable = [
        existing
        for existing in existing_items
        if existing.id not in matched_item_ids and not _daily_report_item_edited(existing)
    ]
    referenced_ids = _referenced_daily_report_item_ids(
        session,
        [existing.id for existing in removable],
    )
    for existing in removable:
        if existing.id not in referenced_ids:
            session.delete(existing)
    session.flush()
    session.expire(report, ["items"])
    return report


def _daily_report_item_edited(item: DailyReportItem) -> bool:
    """判断 draft 条目是否带有编辑层痕迹：采信状态偏离初始值、头条标记或任一 editor 覆盖。"""
    return (
        item.adoption_status != DAILY_ITEM_INITIAL_ADOPTION_STATUS
        or item.is_headline
        or item.editor_title is not None
        or item.editor_summary is not None
        or item.editor_key_points is not None
        or item.editor_content_json is not None
        or bool((item.editor_notes or "").strip())
    )


def _referenced_daily_report_item_ids(session: Session, item_ids: list[str]) -> set[str]:
    """查出仍被反馈/周报/导出/需求证据链引用的日报条目，删除这些条目会造成外键悬挂。"""
    if not item_ids:
        return set()
    referencing_columns = (
        Reaction.daily_report_item_id,
        Rating.daily_report_item_id,
        Comment.daily_report_item_id,
        WeeklyReportItem.daily_report_item_id,
        ExportJobItem.daily_report_item_id,
        RequirementSourceLink.daily_report_item_id,
    )
    referenced: set[str] = set()
    for column in referencing_columns:
        referenced.update(session.scalars(select(column).where(column.in_(item_ids))).all())
    return referenced


def _category_for_news(
    workspace: Workspace,
    news_item: NewsItem,
    policy: WorkspaceContentPolicy | None = None,
) -> str:
    # 分类降级（LLM 不可用时）：关键词规则经工作台策略解析，
    # AI/AI 工具关键词表只是内置默认，不再对自定义类目隐含生效。
    policy = policy or policy_for_workspace(workspace)
    allowed = list(policy.allowed_primary_categories)
    text = f"{news_item.source_title} {news_item.summary} {news_item.content}".lower()
    for category, keywords in policy.category_keyword_rules:
        if category in allowed and any(keyword in text for keyword in keywords):
            return category
    default_category = policy.default_category
    return default_category if default_category in allowed else allowed[0]


def _generated_title(news_item: NewsItem) -> str:
    title = _plain_text(news_item.source_title or "未命名情报")
    if len(title) <= 80:
        return title
    return f"{title[:77].rstrip()}..."


def _key_points(news_item: NewsItem, category: str) -> str:
    return fallback_key_points(news_item, category)


def _content_excerpt(content: str) -> str:
    clean = _plain_text(content)
    if len(clean) <= 500:
        return clean
    return f"{clean[:497].rstrip()}..."


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(without_tags).split()).strip()


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
    return f"{workspace_code}:recommendation:{day_key}:{compact_time}:{uuid4().hex[:8]}"
