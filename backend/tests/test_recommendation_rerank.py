"""WP4-A L3 LLM 精排验收（recommendation-scoring-design §4/§6/§8/§9/§18、
config/contracts/recommendation_ranking.json acceptance_assertions）。

回归红线（断言 1）先行：`llm_rerank_enabled=false`（默认）时固定 fixture 下
rank 序列与 final_score 与纯粗排现状实现逐位一致——本文件第一批用例在动排序
代码之前先写先绿。LLM 调用全部走 app.llm.provider.TRANSPORT 的 MockTransport，
不出进程。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.llm.provider as provider
from app.core.config import get_settings
from app.core.database import Base
from app.llm.budget import (
    PURPOSE_GENERATION,
    PURPOSE_RERANK,
    current_day_key,
    generation_calls_used,
    record_generation_call,
)
from app.models.content import (
    GenerationUsage,
    RecommendationItem,
    RubricTopicPrior,
    SourceScoreSnapshot,
)
from app.models.reports import DailyReport
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.reaggregate import (
    effective_topic_weight,
    run_feedback_reaggregate,
    source_prior_delta,
)
from app.recommendations.rerank import rerank_window_partition, window_shuffle
from app.recommendations.service import (
    RecommendationRunRequest,
    run_daily_recommendation,
)
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUBRIC_PATH = REPO_ROOT / "config" / "scoring" / "rubrics" / "planning_intel_default.json"

FIXTURE_KEY = "fixture-secret-key-0123456789"
FIXED_NOW = datetime(2026, 5, 5, 10, tzinfo=UTC)

# 现状纯粗排基线（2026-07-08 在未改动排序代码的提交上采集）：
# (rank, source_url, admission_level, final_score, selected)
PURE_COARSE_BASELINE = [
    (1, "https://example.com/baseline-hw", "P0", 90.12, True),
    (2, "https://example.com/baseline-agent", "P1", 84.17, True),
    (3, "https://example.com/baseline-paper", "P1", 83.75, True),
    (4, "https://example.com/baseline-train", "P2", 66.96, False),
    (5, "https://example.com/baseline-fin", "R", 25.0, False),
]


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_baseline_fixture(session):
    """固定 fixture：P0 硬件 / P1 智能体 / P1 论文 / P2 弱信号 / R 商业噪声。"""
    workspace = seed_workspace(session)
    vendor = seed_source(session, workspace, name="NVIDIA Technical Blog")
    paper = seed_source(
        session,
        workspace,
        source_type="paper_rss",
        name="Apple Machine Learning Research",
    )
    commercial = seed_source(session, workspace, name="Mobile World Live")
    neutral = seed_source(session, workspace, name="Example Official RSS")
    add_raw_item(
        session,
        vendor,
        "rss:hw",
        "NVIDIA introduces NVLink architecture for AI factory inference clusters",
        "https://example.com/baseline-hw",
        (
            "The technical post explains GPU cluster architecture, NVLink, inference serving, "
            "throughput, latency, HBM bandwidth, rack-scale deployment, and data center cost."
        ),
    )
    add_raw_item(
        session,
        paper,
        "paper:1",
        "Research paper introduces an inference benchmark for agent memory",
        "https://example.com/baseline-paper",
        (
            "This research paper studies LLM agent memory architecture, inference latency, "
            "benchmark evaluation, retrieval quality, and deployment tradeoffs for AI "
            "engineering teams."
        ),
    )
    add_raw_item(
        session,
        commercial,
        "rss:fin",
        "AI startup raises funding as revenue growth accelerates",
        "https://example.com/baseline-fin",
        (
            "The company announced a funding round, valuation growth, sales momentum, "
            "commercial partnerships, and revenue expansion for its AI product business."
        ),
    )
    add_raw_item(
        session,
        neutral,
        "rss:agent",
        "New agent model release improves tool orchestration",
        "https://example.com/baseline-agent",
        (
            "Agent platform release with detailed architecture, benchmark results, "
            "inference latency and deployment tradeoffs body."
        ),
    )
    add_raw_item(
        session,
        neutral,
        "rss:train",
        "Training technology update",
        "https://example.com/baseline-train",
        "Training technology update body.",
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    return workspace


def run_fixture(session, limit: int = 3):
    return run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=limit,
            source_daily_limit=2,
            create_daily_draft=False,
        ),
        now=FIXED_NOW,
    )


def ordered_items(session):
    return session.scalars(
        select(RecommendationItem).order_by(RecommendationItem.rank),
    ).all()


@pytest.fixture()
def forbid_llm_calls(monkeypatch):
    """provider 层任何外呼都会失败：断言零调用路径。"""

    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected provider call: {request.url}")

    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(_explode))


# ---------------------------------------------------------------------------
# 断言 1（回归红线，先写先绿）：无导向时 rank 序列与 final_score 逐位一致
# ---------------------------------------------------------------------------


def test_baseline_no_guidance_rank_sequence_matches_pure_coarse(forbid_llm_calls):
    session = make_session()
    seed_baseline_fixture(session)
    run_fixture(session)
    session.commit()

    observed = [
        (item.rank, item.news_item.source_url, item.admission_level, item.final_score, item.selected)
        for item in ordered_items(session)
    ]
    assert observed == PURE_COARSE_BASELINE


def test_baseline_policy_disabled_explicitly_matches_pure_coarse(forbid_llm_calls):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    workspace.config_json = {
        **(workspace.config_json or {}),
        "recommendation_policy": {"llm_rerank_enabled": False},
    }
    session.flush()
    run_fixture(session)
    session.commit()

    observed = [
        (item.rank, item.news_item.source_url, item.admission_level, item.final_score, item.selected)
        for item in ordered_items(session)
    ]
    assert observed == PURE_COARSE_BASELINE


def test_baseline_disabled_run_marks_llm_fields_and_summary(forbid_llm_calls):
    """断言 1 补充：禁用路径 final==coarse、item/summary 标 disabled、零调用。"""
    session = make_session()
    seed_baseline_fixture(session)
    result = run_fixture(session)
    session.commit()

    for item in ordered_items(session):
        assert item.final_score == item.coarse_score
        assert item.llm_relevance_score is None
        assert item.llm_rerank_status == "disabled"
        assert item.rubric_hits_json == []
        assert item.recommendation_reason.endswith("llm_rerank=disabled")
    block = result.run.summary_json["llm_rerank"]
    assert block["status"] == "disabled"
    assert block["calls_used"] == 0
    assert generation_calls_used(session, "planning_intel", current_day_key(), PURPOSE_RERANK) == 0


# ---------------------------------------------------------------------------
# L3 精排 fixture 设施：provider env + MockTransport + 启用导向的 policy
# ---------------------------------------------------------------------------

FIXTURE_KEY_ENV = {
    "GENERATION_ENABLED": "true",
    "GENERATION_API_KEY": FIXTURE_KEY,
    "GENERATION_BASE_URL": "https://provider.fixture.test/v1",
}


def load_default_rubric() -> dict:
    return json.loads(DEFAULT_RUBRIC_PATH.read_text(encoding="utf-8"))


def enable_rerank_policy(session, workspace, **overrides):
    policy = {
        "llm_rerank_enabled": True,
        "rubric_status": "active",
        "rubric_version": 1,
        "active_rubric": load_default_rubric(),
        **overrides,
    }
    workspace.config_json = {
        **(workspace.config_json or {}),
        "recommendation_policy": policy,
    }
    session.flush()
    return policy


class RerankHandler:
    """按窗口请求回打分响应；记录每次请求载荷（契约断言用）。"""

    def __init__(self, score_fn=None, respond=None):
        self.windows: list[dict] = []
        self.score_fn = score_fn or (lambda candidate: 80)
        self.respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        window = json.loads(payload["messages"][1]["content"])
        self.windows.append(window)
        if self.respond is not None:
            return self.respond(window)
        entries = [
            {
                "id": candidate["id"],
                "relevance_score": int(self.score_fn(candidate)),
                "rubric_hits": ["inference_serving"],
                "reason": "契合工作台内容导向",
            }
            for candidate in window["candidates"]
        ]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(entries, ensure_ascii=False)}}]},
        )


@pytest.fixture()
def rerank_provider(monkeypatch):
    def _install(handler):
        monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
        for key, value in FIXTURE_KEY_ENV.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return handler

    yield _install
    get_settings.cache_clear()


def run_rerank_fixture(session, limit: int = 0):
    """limit=0：不选中不成稿——生成链零调用，transport 只承载 rerank 窗口。"""
    return run_fixture(session, limit=limit)


# ---------------------------------------------------------------------------
# 断言 6：分窗/洗牌确定性可复现（unit）
# ---------------------------------------------------------------------------


def test_window_partition_matches_design_defaults():
    # M=60 / W=12 / A=2 / 步长 10 -> 6 窗，相邻窗共享 2 条锚点（§4.4）。
    windows = rerank_window_partition(60, 12)
    assert windows == [(0, 12), (10, 22), (20, 32), (30, 42), (40, 52), (50, 60)]
    # 末窗允许不满。
    assert rerank_window_partition(15, 12) == [(0, 12), (10, 15)]
    assert rerank_window_partition(8, 12) == [(0, 8)]
    assert rerank_window_partition(0, 12) == []


def test_window_shuffle_is_deterministic_per_run_key_and_window():
    ids = [f"c{i}" for i in range(1, 13)]
    first = window_shuffle("ws:recommendation:2026-07-08:x", 0, ids)
    second = window_shuffle("ws:recommendation:2026-07-08:x", 0, ids)
    assert first == second
    assert sorted(first) == sorted(ids)
    # 不同窗口/不同 run_key 的洗牌序不同（种子 = sha256(run_key + ":" + index)）。
    assert window_shuffle("ws:recommendation:2026-07-08:x", 1, ids) != first
    assert window_shuffle("ws:recommendation:2026-07-08:y", 0, ids) != first


# ---------------------------------------------------------------------------
# 断言 8/11/13 + §6 融合：scored run 的融合公式、准入不变、预算分桶
# ---------------------------------------------------------------------------


def test_rerank_scored_run_fuses_scores_and_keeps_admission(rerank_provider):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    enable_rerank_policy(session, workspace)
    scores = {
        "https://example.com/baseline-paper": 95,
        "https://example.com/baseline-hw": 70,
        "https://example.com/baseline-agent": 60,
        "https://example.com/baseline-train": 40,
    }
    handler = rerank_provider(
        RerankHandler(score_fn=lambda c: scores.get(_url_for(c), 50)),
    )
    # 预置 generation 桶计数：断言 rerank 不挤占（断言 13）。
    record_generation_call(session, "planning_intel", current_day_key(), PURPOSE_GENERATION)

    result = run_rerank_fixture(session)
    session.commit()

    items = {item.news_item.source_url: item for item in ordered_items(session)}
    baseline = {url: (level, final) for _, url, level, final, _ in PURE_COARSE_BASELINE}

    # 准入结论与粗排分不被精排改变（断言 11）；R 不进精排且封顶保持。
    for url, (level, coarse) in baseline.items():
        assert items[url].admission_level == level
        assert items[url].coarse_score == coarse
    assert items["https://example.com/baseline-fin"].llm_rerank_status == "not_run"
    assert items["https://example.com/baseline-fin"].final_score == 25.0

    # 融合公式（断言 8）：final = round(0.6*llm + 0.4*coarse, 2)。
    for url, llm_score in scores.items():
        item = items[url]
        assert item.llm_rerank_status == "scored"
        assert item.llm_relevance_score == float(llm_score)
        assert item.final_score == round(0.6 * llm_score + 0.4 * item.coarse_score, 2)
        assert item.rubric_hits_json == ["inference_serving"]
        assert item.rubric_version == 1
        assert item.llm_rerank_reason == "契合工作台内容导向"
        assert item.recommendation_reason.endswith("llm_rerank=scored")

    # 展示序：final_score 降序（§7）。
    ranked = [item.final_score for item in ordered_items(session)]
    assert ranked == sorted(ranked, reverse=True)

    # 单窗（4 条 ≤ W=12）恰 1 次调用；预算分桶互不挤占（断言 13）。
    assert len(handler.windows) == 1
    day = current_day_key()
    assert generation_calls_used(session, "planning_intel", day, PURPOSE_RERANK) == 1
    assert generation_calls_used(session, "planning_intel", day, PURPOSE_GENERATION) == 1

    block = result.run.summary_json["llm_rerank"]
    assert block["status"] == "scored"
    assert block["windows_total"] == 1
    assert block["windows_failed"] == 0
    assert block["calls_used"] == 1
    assert block["rubric_version"] == 1
    assert block["llm_score_mean"] is not None


def _url_for(candidate: dict) -> str:
    """handler 侧通过标题反查 fixture URL（prompt 不含 URL）。"""
    title = candidate["title"]
    mapping = {
        "NVIDIA introduces": "https://example.com/baseline-hw",
        "Research paper introduces": "https://example.com/baseline-paper",
        "AI startup raises": "https://example.com/baseline-fin",
        "New agent model": "https://example.com/baseline-agent",
        "Training technology": "https://example.com/baseline-train",
    }
    for prefix, url in mapping.items():
        if title.startswith(prefix):
            return url
    return title


# ---------------------------------------------------------------------------
# 断言 2：预算耗尽降级（run 前耗尽 -> skipped；运行中耗尽 -> partial）
# ---------------------------------------------------------------------------


def test_budget_exhausted_before_run_skips_with_zero_calls(rerank_provider, monkeypatch):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    enable_rerank_policy(session, workspace, daily_rerank_call_budget=60)

    def _explode(request):
        raise AssertionError("no calls expected when budget is exhausted")

    rerank_provider(_explode)
    session.add(
        GenerationUsage(
            workspace_code="planning_intel",
            day_key=current_day_key(),
            purpose=PURPOSE_RERANK,
            calls_total=60,
        ),
    )
    session.flush()

    result = run_rerank_fixture(session)
    session.commit()

    block = result.run.summary_json["llm_rerank"]
    assert block["status"] == "skipped"
    assert block["skip_reason"] == "budget_exhausted"
    for item in ordered_items(session):
        assert item.final_score == item.coarse_score
        assert item.llm_rerank_status == "skipped"


def seed_multiwindow_fixture(session, count: int = 8):
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Example Official RSS")
    for index in range(count):
        add_raw_item(
            session,
            source,
            f"rss:multi-{index}",
            f"Agent model release {index} improves inference benchmark orchestration",
            f"https://example.com/multi-{index}",
            (
                "Agent platform release with detailed architecture, benchmark results, "
                f"inference latency and deployment tradeoffs body {index}."
            ),
        )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    return workspace


def test_budget_exhausted_mid_run_keeps_scored_windows(rerank_provider):
    session = make_session()
    workspace = seed_multiwindow_fixture(session, count=8)
    # W=6 / A=2 / 步长 4：8 条 -> 2 窗；预算 1 -> 第 2 窗申请被拒。
    enable_rerank_policy(
        session,
        workspace,
        rerank_window_size=6,
        daily_rerank_call_budget=1,
    )
    handler = rerank_provider(RerankHandler())

    result = run_rerank_fixture(session)
    session.commit()

    block = result.run.summary_json["llm_rerank"]
    assert block["status"] == "partial"
    assert block["skip_reason"] == "budget_exhausted"
    assert block["windows_total"] == 2
    assert block["calls_used"] == 1
    assert len(handler.windows) == 1

    statuses = [item.llm_rerank_status for item in ordered_items(session)]
    assert statuses.count("scored") == 6
    assert statuses.count("skipped") == 2
    for item in ordered_items(session):
        if item.llm_rerank_status == "skipped":
            assert item.final_score == item.coarse_score


# ---------------------------------------------------------------------------
# 断言 3：provider 不可用降级（零外呼）
# ---------------------------------------------------------------------------


def test_provider_unavailable_skips_with_zero_calls(forbid_llm_calls):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    enable_rerank_policy(session, workspace)
    # conftest 置 MINIMAX_GENERATION_ENABLED=false 且无 GENERATION_*：provider 不可用。
    result = run_fixture(session)
    session.commit()

    block = result.run.summary_json["llm_rerank"]
    assert block["status"] == "skipped"
    assert block["skip_reason"] == "provider_unavailable"
    for item in ordered_items(session):
        assert item.final_score == item.coarse_score
        assert item.llm_rerank_status == "skipped"
    assert generation_calls_used(session, "planning_intel", current_day_key(), PURPOSE_RERANK) == 0


# ---------------------------------------------------------------------------
# 断言 7：窗口失败降级（重试 1 次；失败窗 >1/2 -> 整 run failed 全量退回）
# ---------------------------------------------------------------------------


def test_window_failed_after_retry_falls_back_to_coarse(rerank_provider):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    enable_rerank_policy(session, workspace)
    handler = rerank_provider(
        RerankHandler(
            respond=lambda window: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not a json array"}}]},
            ),
        ),
    )

    result = run_rerank_fixture(session)
    session.commit()

    # 单窗：1 次 + 重试 1 次 = 2 次调用（重试计预算）；1/1 失败 > 1/2 -> failed。
    assert len(handler.windows) == 2
    assert generation_calls_used(session, "planning_intel", current_day_key(), PURPOSE_RERANK) == 2
    block = result.run.summary_json["llm_rerank"]
    assert block["status"] == "failed"
    assert block["windows_failed"] == 1

    observed = [
        (item.rank, item.news_item.source_url, item.admission_level, item.final_score, item.selected)
        for item in ordered_items(session)
    ]
    # 全量退回 coarse：序列与纯粗排基线一致（selected 差异只来自 limit=0）。
    assert [(rank, url, level, final) for rank, url, level, final, _ in observed] == [
        (rank, url, level, final) for rank, url, level, final, _ in PURE_COARSE_BASELINE
    ]
    for item in ordered_items(session):
        assert item.final_score == item.coarse_score
        assert item.llm_relevance_score is None
        if item.admission_level in {"P0", "P1", "P2"}:
            assert item.llm_rerank_status == "window_failed"


# ---------------------------------------------------------------------------
# §4.4 结果缓存：7 天内同 rubric 版本 scored 分复用，零调用
# ---------------------------------------------------------------------------


def test_rerank_result_cache_reuses_scores_with_zero_calls(rerank_provider):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    enable_rerank_policy(session, workspace)
    handler = rerank_provider(RerankHandler())

    run_rerank_fixture(session)
    session.commit()
    day = current_day_key()
    assert generation_calls_used(session, "planning_intel", day, PURPOSE_RERANK) == 1

    second = run_rerank_fixture(session)
    session.commit()

    assert len(handler.windows) == 1  # 第二次 run 零新调用
    assert generation_calls_used(session, "planning_intel", day, PURPOSE_RERANK) == 1
    second_items = session.scalars(
        select(RecommendationItem)
        .where(RecommendationItem.run_id == second.run.id)
        .order_by(RecommendationItem.rank),
    ).all()
    cached = [item for item in second_items if item.llm_rerank_status == "cached"]
    assert len(cached) == 4
    for item in cached:
        assert item.llm_relevance_score is not None
        assert item.final_score == round(0.6 * item.llm_relevance_score + 0.4 * item.coarse_score, 2)


# ---------------------------------------------------------------------------
# 硬排除封顶：severity=hard 命中 -> llm 分封顶 20（准入不动）
# ---------------------------------------------------------------------------


def test_hard_exclusion_hit_caps_llm_score_at_20(rerank_provider):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    enable_rerank_policy(session, workspace)

    def respond(window):
        entries = [
            {
                "id": candidate["id"],
                "relevance_score": 90,
                "rubric_hits": ["no_pure_finance"],  # 默认 rubric 的 hard 排除
                "reason": "纯商业新闻",
            }
            for candidate in window["candidates"]
        ]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(entries, ensure_ascii=False)}}]},
        )

    rerank_provider(RerankHandler(respond=respond))
    run_rerank_fixture(session)
    session.commit()

    scored = [item for item in ordered_items(session) if item.llm_rerank_status == "scored"]
    assert scored
    for item in scored:
        assert item.llm_relevance_score == 20.0
        # 准入结论不因硬排除改变（断言 11）。
        assert item.admission_level in {"P0", "P1", "P2"}


# ---------------------------------------------------------------------------
# 断言 12：反馈再估计有界、全量重估非累加、authored 权重不被改写
# ---------------------------------------------------------------------------


def test_source_prior_delta_formula_and_bounds():
    assert source_prior_delta(1.0, 0.0, 1.0) == 6.0  # 8+2=10 -> clamp +6
    assert source_prior_delta(0.0, 1.0, 0.0) == -6.0  # -6 -> clamp -6
    assert source_prior_delta(0.5, 0.25, 0.1) == 8 * 0.5 - 6 * 0.25 + 2 * 0.1


def test_effective_topic_weight_clamped_to_half_and_one_half():
    # 单次幅度 <= ±10%，累计钳制 [0.5w, 1.5w]。
    assert effective_topic_weight(4.0, 0, 0) == 4.0
    assert effective_topic_weight(4.0, 100, 0) == pytest.approx(4.0 * 1.1)
    assert effective_topic_weight(4.0, 0, 100) == pytest.approx(4.0 * 0.9)
    assert effective_topic_weight(4.0, 100, 0) <= 1.5 * 4.0
    assert effective_topic_weight(4.0, 0, 100) >= 0.5 * 4.0


def test_feedback_reaggregate_writes_bounded_snapshots_idempotently(forbid_llm_calls):
    session = make_session()
    seed_baseline_fixture(session)
    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=3,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=FIXED_NOW,
    )
    session.commit()

    # 采信 + 发布日报：被选中的 3 条 adoption_status 初始即 2。
    report = session.scalar(select(DailyReport))
    assert report is not None
    report.status = "published"
    session.flush()

    now = FIXED_NOW + timedelta(days=1)
    first = run_feedback_reaggregate(session, now=now)
    session.commit()
    assert first["status"] == "succeeded"
    snapshots = session.scalars(select(SourceScoreSnapshot)).all()
    assert snapshots
    for snapshot in snapshots:
        assert -6.0 <= snapshot.source_prior_delta <= 6.0
        assert snapshot.window == "14d"

    # 幂等：同 day_key 重跑覆盖当日快照（非累加、行数不增）。
    second = run_feedback_reaggregate(session, now=now)
    session.commit()
    assert second["source_snapshots_total"] == first["source_snapshots_total"]
    assert len(session.scalars(select(SourceScoreSnapshot)).all()) == len(snapshots)

    # 旧 run 分数快照不被再估计改写（断言 15）。
    old_items = session.scalars(
        select(RecommendationItem).where(RecommendationItem.run_id == result.run.id),
    ).all()
    baseline_by_url = {url: final for _, url, _, final, _ in PURE_COARSE_BASELINE}
    for item in old_items:
        assert item.final_score == baseline_by_url[item.news_item.source_url]

    # 新 run 消费 delta：采信过的源 delta > 0 -> source_score 上移（clamp 100 内）。
    vendor_snapshot = next(
        s for s in snapshots if s.adopted_count > 0 and s.source_prior_delta > 0
    )
    assert vendor_snapshot.adopt_rate > 0


def test_feedback_reaggregate_topic_priors_only_for_active_rubric(forbid_llm_calls):
    session = make_session()
    workspace = seed_baseline_fixture(session)
    rubric = load_default_rubric()
    enable_rerank_policy(session, workspace, llm_rerank_enabled=False, active_rubric=rubric)
    run_fixture(session, limit=3)
    session.commit()

    summary = run_feedback_reaggregate(session, now=FIXED_NOW + timedelta(days=1))
    session.commit()
    priors = session.scalars(select(RubricTopicPrior)).all()
    assert summary["topic_priors_total"] == len(rubric["topics"])
    assert {p.topic_code for p in priors} == {t["code"] for t in rubric["topics"]}
    authored = {t["code"]: t["weight"] for t in rubric["topics"]}
    for prior in priors:
        weight = authored[prior.topic_code]
        assert 0.5 * weight <= prior.effective_weight <= 1.5 * weight

    # authored rubric 权重永不被改写。
    from app.recommendations.policy import workspace_recommendation_policy

    stored = workspace_recommendation_policy(workspace)
    assert {t["code"]: t["weight"] for t in stored["active_rubric"]["topics"]} == authored
