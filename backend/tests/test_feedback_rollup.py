"""WP4-G 反馈回哺周/月 rollup 验收（feedback-heat-scoring §12-§15/§17-§18、
config/contracts/recommendation_ranking.json `feedback_workflow`）。

覆盖契约断言（acceptance_assertions）：
- rollup_empty_ok（断言 1）：空反馈数据 weekly rollup 写 status=empty，
  空样本指标全 null（无 0.0），零 LLM 调用零提案；
- rollup_idempotent（断言 2 rollup 面）：同 (workspace, period_type, period_key)
  重跑覆盖同一行；
- exploration_bounded（断言 7）：epsilon 越界 PATCH 422；epsilon=0（默认）选择
  逐位一致（回归红线，先写先绿）；每 run ≤1 探索位、P1/P2 限定、reason 含
  exploration_slot；同 run_key 抽签可复现；
- metrics_correct（断言 8）：固定 fixture 下全部指标与手工计算一致，无已发布
  日报时 precision 为 null；
- position_bias_applied（断言 9）：同采信事实不同位次产生不同 normalized_adopt_rate；
- monthly_review_advisory（断言 10）：下滑序列 drift_flag=true、失效源建议、
  data_sources 逐字段不变；
- no_boundary_leak（断言 11）：两新表无 SyncMixin 不进 feed，公司 SQL 逐字节
  不变，rollup 前后历史快照表行不变；
- manual_run_gated（断言 12）：手动触发幂等 + 审计 + viewer 403；
- dispatch_idempotent_and_gated（断言 13）：周/月触发点跨实例只投递一次、
  intranet 零投递、单工作台失败不中断其余。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.llm.budget import (
    PURPOSE_FEEDBACK_ROLLUP,
    current_day_key,
    generation_calls_used,
)
from app.main import create_app
from app.models.content import (
    DataSource,
    DedupeGroup,
    DedupeGroupItem,
    FeedbackRollup,
    GeneratedNews,
    NewsItem,
    RecommendationItem,
    RecommendationRun,
    RubricRevisionProposal,
    RubricTopicPrior,
    SourceScoreSnapshot,
)
from app.models.feedback import AuditLog
from app.models.pipeline import SchedulerHeartbeat
from app.models.reports import DailyReport, DailyReportItem
from app.recommendations import rollup as rollup_module
from app.recommendations import service as service_module
from app.recommendations.rollup import (
    exploration_draw,
    monthly_window,
    rank_bucket_weight,
    rollup_workspace_month,
    rollup_workspace_week,
    run_feedback_monthly_review,
    run_feedback_weekly_rollup,
    run_feedback_weekly_rollup_job,
    run_feedback_monthly_review_job,
    weekly_window,
)
from app.recommendations.service import RecommendationRunRequest, run_daily_recommendation
from app.models.common import utc_now
from app.workers.scheduler import SchedulerState, scheduler_tick
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace
from tests.test_recommendation_policy import make_client
from tests.test_scheduler_policy import (
    FakeQueue,
    make_session_factory,
    make_settings,
    shanghai,
)

BEIJING = rollup_module.BEIJING_TZ


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def current_week_key() -> str:
    iso = utc_now().astimezone(BEIJING).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def current_month_key() -> str:
    today = utc_now().astimezone(BEIJING).date()
    return f"{today.year}-{today.month:02d}"


def today_day_key() -> str:
    return utc_now().astimezone(BEIJING).date().isoformat()


def seed_news(session, workspace, source, key: str, title: str = "") -> NewsItem:
    raw = add_raw_item(
        session,
        source,
        key,
        title or f"news {key}",
        f"https://example.com/{key}",
        f"body of {key}",
        published_at=utc_now(),
    )
    news = NewsItem(
        raw_item=raw,
        data_source=source,
        workspace_code=workspace.code,
        domain_code="ai",
        source_type=source.source_type,
        source_name=source.name,
        source_url=f"https://example.com/{key}",
        source_title=title or f"news {key}",
        summary=f"summary of {key}",
        dedupe_key=key,
    )
    session.add(news)
    session.flush()
    return news


def seed_rec_run(session, workspace) -> RecommendationRun:
    run = RecommendationRun(
        run_key=f"run-{utc_now().timestamp()}-{id(workspace)}",
        workspace_code=workspace.code,
        domain_code="ai",
        status="completed",
    )
    session.add(run)
    session.flush()
    return run


def seed_rec_item(
    session,
    run,
    news,
    *,
    rank: int,
    final: float,
    coarse: float | None = None,
    llm_status: str = "not_run",
    hits: tuple[str, ...] = (),
    rubric_version: int = 0,
    selected: bool = True,
) -> RecommendationItem:
    group = DedupeGroup(
        workspace_code=news.workspace_code,
        domain_code="ai",
        dedupe_key=f"{news.dedupe_key}:{run.id}",
        winner_news_item_id=news.id,
        item_count=1,
    )
    session.add(group)
    session.flush()
    group_item = DedupeGroupItem(dedupe_group=group, news_item=news, is_winner=True)
    session.add(group_item)
    session.flush()
    item = RecommendationItem(
        run=run,
        workspace_code=news.workspace_code,
        domain_code="ai",
        dedupe_group=group,
        dedupe_group_item=group_item,
        news_item=news,
        rank=rank,
        final_score=final,
        coarse_score=coarse if coarse is not None else final,
        llm_rerank_status=llm_status,
        rubric_hits_json=list(hits),
        rubric_version=rubric_version,
        selected=selected,
        admission_level="P1",
        admission_pool="ai_engineering",
    )
    session.add(item)
    session.flush()
    return item


def seed_daily_report(
    session,
    workspace,
    entries: list[tuple[NewsItem, int, int, bool]],
    *,
    day_key: str | None = None,
    status: str = "published",
) -> DailyReport:
    """entries: (news, sort_order, adoption_status, edited)。"""
    report = DailyReport(
        workspace_code=workspace.code,
        domain_code="ai",
        day_key=day_key or today_day_key(),
        title="fixture report",
        status=status,
    )
    session.add(report)
    session.flush()
    for news, sort_order, adoption_status, edited in entries:
        generated = GeneratedNews(
            news_item=news,
            workspace_code=workspace.code,
            domain_code="ai",
            category="AI Infra",
            title=news.source_title,
            summary=f"导出摘要 {news.dedupe_key}",
            key_points="要点一,要点二",
            content_json={
                "background": "背景",
                "effects": "影响",
                "eventSummary": "事件",
                "technologyAndInnovation": "技术",
                "valueAndImpact": "价值",
            },
            generated_by="minimax:test",
            generation_status="ready",
        )
        session.add(generated)
        session.flush()
        item = DailyReportItem(
            daily_report=report,
            generated_news=generated,
            workspace_code=workspace.code,
            domain_code="ai",
            adoption_status=adoption_status,
            sort_order=sort_order,
            editor_title="edited title" if edited else None,
        )
        session.add(item)
    session.flush()
    return report


def set_recommendation_policy(session, workspace, **overrides):
    config = dict(workspace.config_json or {})
    policy = dict(config.get("recommendation_policy") or {})
    policy.update(overrides)
    config["recommendation_policy"] = policy
    workspace.config_json = config
    session.flush()


FIXTURE_RUBRIC = {
    "schema_version": 1,
    "topics": [
        {"code": "topic_a", "label": "A", "weight": 2.0, "keywords_hint": []},
        {"code": "topic_b", "label": "B", "weight": 2.0, "keywords_hint": []},
        {"code": "topic_c", "label": "C", "weight": 2.0, "keywords_hint": []},
        {"code": "topic_d", "label": "D", "weight": 2.0, "keywords_hint": []},
    ],
    "exclusions": [],
    "boost_signals": [],
    "scoring_dimensions": [{"code": "relevance", "weight": 1.0}],
    "language": "zh",
    "source_guidance_fingerprint": "sha256:fixture",
}


# ---------------------------------------------------------------------------
# 断言 1：空跑不报错（rollup_empty_ok）
# ---------------------------------------------------------------------------


def test_weekly_rollup_empty_ok():
    session = make_session()
    workspace = seed_workspace(session)
    payload = run_feedback_weekly_rollup(session, period_key=current_week_key())
    assert payload["workspaces_total"] == 1
    rollup = session.scalar(select(FeedbackRollup))
    assert rollup is not None
    assert rollup.status == "empty"
    metrics = rollup.metrics_json
    # 空样本指标一律 null，不得写 0.0（契约 empty_sample_rule）。
    for key in (
        "precision_at_6",
        "precision_at_12",
        "rerank_uplift",
        "source_coverage",
        "topic_entropy",
        "normalized_adopt_rate",
        "edit_rate",
    ):
        assert metrics[key] is None, key
    assert metrics["signal_counts"]["daily_adopt"] == 0
    assert metrics["low_data_sources"] == []
    # 零 LLM 调用、零提案。
    assert (
        generation_calls_used(
            session, workspace.code, current_day_key(), purpose=PURPOSE_FEEDBACK_ROLLUP
        )
        == 0
    )
    assert session.scalar(select(RubricRevisionProposal)) is None
    assert rollup.proposal_status == "skipped_no_rubric"


def test_monthly_review_empty_ok():
    session = make_session()
    seed_workspace(session)
    run_feedback_monthly_review(session, period_key=current_month_key())
    rollup = session.scalar(
        select(FeedbackRollup).where(FeedbackRollup.period_type == "monthly"),
    )
    assert rollup is not None
    assert rollup.status == "empty"
    assert rollup.proposal_status == "none"
    assert rollup.metrics_json["precision_at_6"] is None
    assert rollup.metrics_json["drift_flag"] is False


# ---------------------------------------------------------------------------
# 断言 2（rollup 面）：幂等覆盖
# ---------------------------------------------------------------------------


def test_weekly_rollup_idempotent_overwrites_same_row():
    session = make_session()
    seed_workspace(session)
    key = current_week_key()
    run_feedback_weekly_rollup(session, period_key=key)
    first = session.scalar(select(FeedbackRollup))
    first_id = first.id
    run_feedback_weekly_rollup(session, period_key=key)
    rows = session.scalars(select(FeedbackRollup)).all()
    assert len(rows) == 1
    assert rows[0].id == first_id


# ---------------------------------------------------------------------------
# 断言 8：指标正确性（固定 fixture 手工对账）
# ---------------------------------------------------------------------------


def build_metrics_fixture(session):
    workspace = seed_workspace(session)
    set_recommendation_policy(
        session,
        workspace,
        active_rubric=FIXTURE_RUBRIC,
        rubric_status="active",
        rubric_version=1,
    )
    source_a = seed_source(session, workspace, name="Source A")
    source_b = seed_source(session, workspace, name="Source B")
    run = seed_rec_run(session, workspace)
    news = {}
    # n1/n2 来自 A，n3..n7 来自 B；全部 scored（llm 精排参与）。
    specs = [
        ("n1", source_a, 95.0, 60.0, ("topic_a",)),
        ("n2", source_a, 90.0, 90.0, ("topic_b",)),
        ("n3", source_b, 88.0, 88.0, ()),
        ("n4", source_b, 86.0, 86.0, ()),
        ("n5", source_b, 84.0, 84.0, ()),
        ("n6", source_b, 82.0, 82.0, ()),
        ("n7", source_b, 80.0, 85.0, ()),
    ]
    for rank, (key, source, final, coarse, hits) in enumerate(specs, start=1):
        item = seed_news(session, workspace, source, key)
        news[key] = item
        seed_rec_item(
            session,
            run,
            item,
            rank=rank,
            final=final,
            coarse=coarse,
            llm_status="scored",
            hits=hits,
            rubric_version=1,
        )
    # 已发布日报：n1/n2 采信（n1 带编辑覆盖）、n3 驳回、其余待处理。
    seed_daily_report(
        session,
        workspace,
        [
            (news["n1"], 1, 2, True),
            (news["n2"], 2, 2, False),
            (news["n3"], 3, 3, False),
            (news["n4"], 4, 1, False),
            (news["n5"], 5, 1, False),
            (news["n6"], 6, 1, False),
            (news["n7"], 7, 1, False),
        ],
    )
    return workspace, news


def test_weekly_rollup_metrics_match_hand_computed_values():
    session = make_session()
    workspace, _news = build_metrics_fixture(session)
    rollup = rollup_workspace_week(session, workspace, current_week_key())
    metrics = rollup.metrics_json
    assert rollup.status == "succeeded"
    # precision@6：top6(sort 1..6) 采信 2 条 / min(6,7)=6 -> 0.3333。
    assert metrics["precision_at_6"] == round(2 / 6, 4)
    # precision@12：全部 7 条中采信 2 -> 2/7。
    assert metrics["precision_at_12"] == round(2 / 7, 4)
    # uplift：final 序 top6 含 n1,n2（2/6）；coarse 序 top6 不含 n1（1/6）。
    assert metrics["rerank_uplift"] == round(2 / 6 - 1 / 6, 4)
    # 采信 2 条来自同一源 -> 1/2。
    assert metrics["source_coverage"] == 0.5
    # 采信命中 topic_a/topic_b 各 1，rubric 共 4 主题 -> ln2/ln4 = 0.5。
    assert metrics["topic_entropy"] == 0.5
    # 位次去偏：sort 1/2 均在 rank1-6 桶（权重 1.0）-> 2.0/7。
    assert metrics["normalized_adopt_rate"] == round(2 / 7, 4)
    # 采信 2 条中 1 条带 editor 覆盖 -> 0.5。
    assert metrics["edit_rate"] == 0.5
    counts = metrics["signal_counts"]
    assert counts["daily_adopt"] == 2
    assert counts["daily_reject"] == 1
    assert counts["editor_override"] == 1
    # 低数据源：A 2 条 <5 -> insufficient；B 5 条 -> keep。
    low_ids = {entry["name"] for entry in metrics["low_data_sources"]}
    assert low_ids == {"Source A"}
    suggestions = {
        entry["name"]: entry["suggestion"]
        for entry in rollup.source_breakdown_json["sources"]
    }
    assert suggestions["Source A"] == "insufficient_data"
    assert suggestions["Source B"] == "keep"


def test_precision_null_without_published_reports():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    run = seed_rec_run(session, workspace)
    news = seed_news(session, workspace, source, "only")
    seed_rec_item(session, run, news, rank=1, final=80.0)
    # 草稿日报不计入 precision（仅 published）。
    seed_daily_report(session, workspace, [(news, 1, 2, False)], status="draft")
    rollup = rollup_workspace_week(session, workspace, current_week_key())
    assert rollup.metrics_json["precision_at_6"] is None
    assert rollup.metrics_json["precision_at_12"] is None


# ---------------------------------------------------------------------------
# 断言 9：位次去偏生效（bucket 权重 1.0/1.2/1.4）
# ---------------------------------------------------------------------------


def test_position_bias_changes_normalized_adopt_rate():
    assert rank_bucket_weight(1) == 1.0
    assert rank_bucket_weight(6) == 1.0
    assert rank_bucket_weight(7) == 1.2
    assert rank_bucket_weight(15) == 1.2
    assert rank_bucket_weight(16) == 1.4

    session = make_session()
    rates = {}
    for code, adopted_ranks in (("ws_head", (1, 2)), ("ws_tail", (16, 20))):
        workspace = seed_workspace(session, code=code)
        source = seed_source(session, workspace, name=f"src-{code}")
        run = seed_rec_run(session, workspace)
        entries = []
        for index in range(1, 21):
            news = seed_news(session, workspace, source, f"{code}-n{index}")
            seed_rec_item(session, run, news, rank=index, final=100.0 - index)
            adoption = 2 if index in adopted_ranks else 1
            entries.append((news, index, adoption, False))
        seed_daily_report(session, workspace, entries)
        rollup = rollup_workspace_week(session, workspace, current_week_key())
        rates[code] = rollup.metrics_json["normalized_adopt_rate"]
    # 同样 2 条采信、20 条推荐：头部桶 1.0*2/20，长尾桶 1.4*2/20。
    assert rates["ws_head"] == round(2 * 1.0 / 20, 4)
    assert rates["ws_tail"] == round(2 * 1.4 / 20, 4)
    assert rates["ws_head"] != rates["ws_tail"]


# ---------------------------------------------------------------------------
# 断言 10：月度漂移与失效源（advisory，不自动禁用）
# ---------------------------------------------------------------------------


def test_monthly_review_drift_and_stale_sources_advisory_only():
    session = make_session()
    workspace = seed_workspace(session)
    month_key = current_month_key()
    prev_key = rollup_module._previous_month_key(month_key)
    # 上月 monthly rollup：precision 0.5；本月构造 0.2 -> 相对降 60% 绝对降 0.3。
    window_start, window_end = monthly_window(prev_key)
    session.add(
        FeedbackRollup(
            workspace_code=workspace.code,
            period_type="monthly",
            period_key=prev_key,
            window_start=window_start,
            window_end=window_end,
            status="succeeded",
            proposal_status="none",
            metrics_json={"precision_at_6": 0.5},
            source_breakdown_json={},
            topic_breakdown_json={},
            sample_refs_json={},
            computed_at=utc_now(),
        ),
    )
    # 失效源 (a)：连续 4 个周 rollup recommended_count=0。
    stale_source = seed_source(session, workspace, name="Stale Zero Source")
    hot_source = seed_source(session, workspace, name="High Reject Source")
    for week in ("2026-W01", "2026-W02", "2026-W03", "2026-W04"):
        w_start, w_end = weekly_window(week)
        session.add(
            FeedbackRollup(
                workspace_code=workspace.code,
                period_type="weekly",
                period_key=week,
                window_start=w_start,
                window_end=w_end,
                status="empty",
                proposal_status="none",
                metrics_json={},
                source_breakdown_json={
                    "sources": [
                        {"data_source_id": stale_source.id, "recommended_count": 0},
                        {"data_source_id": hot_source.id, "recommended_count": 3},
                    ],
                },
                topic_breakdown_json={},
                sample_refs_json={},
                computed_at=utc_now(),
            ),
        )
    session.flush()
    # 失效源 (b)：本月 8 推荐 0 采信 4 驳回（reject_rate 0.5）+ precision 0.2。
    run = seed_rec_run(session, workspace)
    entries = []
    for index in range(1, 9):
        news = seed_news(session, workspace, hot_source, f"hot-{index}")
        seed_rec_item(session, run, news, rank=index, final=90.0 - index)
        adoption = 3 if index <= 4 else 1
        entries.append((news, index, adoption, False))
    # 单独一条采信（来自第三个源，保证 hot_source adopted=0）保 precision=1/5。
    good_source = seed_source(session, workspace, name="Good Source")
    extra = seed_news(session, workspace, good_source, "hot-adopted")
    seed_rec_item(session, run, extra, rank=9, final=95.0)
    seed_daily_report(
        session,
        workspace,
        [
            (extra, 1, 2, False),
            (entries[0][0], 2, 3, False),
            (entries[1][0], 3, 3, False),
            (entries[2][0], 4, 3, False),
            (entries[3][0], 5, 3, False),
        ],
    )

    before = [
        (source.id, source.enabled, dict(source.metadata_json or {}))
        for source in session.scalars(select(DataSource).order_by(DataSource.id)).all()
    ]
    rollup = rollup_workspace_month(session, workspace, month_key)
    metrics = rollup.metrics_json
    assert metrics["precision_at_6"] == 0.2
    assert metrics["drift_flag"] is True
    stale = {
        entry["name"]: entry["suggestion"]
        for entry in rollup.source_breakdown_json["stale_source_suggestions"]
    }
    assert stale["Stale Zero Source"] == "suggest_disable"
    assert stale["High Reject Source"] == "suggest_review"
    # 不自动禁用：data_sources.enabled 与元数据逐字段不变。
    after = [
        (source.id, source.enabled, dict(source.metadata_json or {}))
        for source in session.scalars(select(DataSource).order_by(DataSource.id)).all()
    ]
    assert before == after


# ---------------------------------------------------------------------------
# 断言 7：ε 探索位（默认 0 关闭 = 回归红线；上限 0.1；P1/P2 限定；可复现）
# ---------------------------------------------------------------------------


def test_exploration_draw_reproducible_and_bounded():
    draw_one = exploration_draw("run-key-1")
    draw_two = exploration_draw("run-key-1")
    assert draw_one == draw_two
    assert 0.0 <= draw_one < 1.0
    assert exploration_draw("run-key-2") != draw_one


def test_exploration_epsilon_out_of_range_patch_422(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    url = "/api/workspaces/planning_intel/recommendation-policy"
    for bad in (-0.1, 0.11, 1.0, "0.05", True):
        response = client.patch(url, json={"feedback_workflow": {"exploration_epsilon": bad}})
        assert response.status_code == 422, bad
    ok = client.patch(url, json={"feedback_workflow": {"exploration_epsilon": 0.05}})
    assert ok.status_code == 200
    assert ok.json()["policy"]["feedback_workflow"]["exploration_epsilon"] == 0.05


def epsilon_zero_fixture(session):
    workspace = seed_workspace(session)
    vendor = seed_source(session, workspace, name="NVIDIA Technical Blog")
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
    from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items

    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    return workspace


def run_recommendation(session, limit: int = 2):
    return run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=limit,
            source_daily_limit=2,
            create_daily_draft=False,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )


def test_epsilon_zero_selection_identical_to_current_behavior():
    """回归红线（先写先绿）：epsilon=0（默认与显式）时选择逐位一致。"""
    baseline: list[tuple[str, int, bool]] = []
    for explicit_zero in (False, True):
        session = make_session()
        workspace = epsilon_zero_fixture(session)
        if explicit_zero:
            set_recommendation_policy(
                session,
                workspace,
                feedback_workflow={
                    "weekly_rollup_enabled": True,
                    "monthly_review_enabled": True,
                    "proposal_generation_enabled": True,
                    "exploration_epsilon": 0.0,
                },
            )
            # 低数据源 rollup 存在也不得影响 epsilon=0 的选择。
            rollup_workspace_week(session, workspace, current_week_key())
        result = run_recommendation(session)
        rows = sorted(
            (
                (item.news_item.source_url or "", item.rank, item.selected)
                for item in result.run.items
            ),
        )
        if not baseline:
            baseline = rows
        else:
            assert rows == baseline
        assert all("exploration_slot" not in item.recommendation_reason for item in result.run.items)
        session.close()


def make_exploration_candidate(news_id: str, source_id: str, level: str, pool: str, coarse: float):
    from types import SimpleNamespace

    return SimpleNamespace(
        news_item=SimpleNamespace(id=news_id, data_source_id=source_id),
        admission_level=level,
        admission_pool=pool,
        coarse_score=coarse,
    )


def test_apply_exploration_slot_unit_caps_and_admission(monkeypatch):
    """探索位选择层单元行为：P1/P2 限定、coarse 最高、三 caps 冲突放弃、≤1 条。"""
    # epsilon=0（默认）：session=None 也可通过——零查询零改动（回归红线）。
    assert (
        service_module._apply_exploration_slot(
            None,
            workspace_code="ws",
            run_key="rk",
            rec_policy={"feedback_workflow": {"exploration_epsilon": 0.0}},
            scored=[],
            selected_ids=set(),
            limit=5,
            source_daily_limit=2,
        )
        is None
    )

    policy = {"feedback_workflow": {"exploration_epsilon": 0.1}}
    monkeypatch.setattr(
        service_module, "latest_low_data_source_ids", lambda _s, _w: {"src-low"}
    )
    monkeypatch.setattr(service_module, "exploration_draw", lambda _rk: 0.0)
    selected_item = make_exploration_candidate("d", "src-hot", "P0", "vendor_hardware", 99.0)
    p3_low = make_exploration_candidate("a", "src-low", "P3", "general_tech", 99.0)
    p1_low = make_exploration_candidate("b", "src-low", "P1", "ai_engineering", 80.0)
    p2_low = make_exploration_candidate("c", "src-low", "P2", "general_tech", 70.0)
    scored = [selected_item, p3_low, p1_low, p2_low]

    # R/P3 永不入选；coarse 最高的 P1 胜出并加入选集。
    selected_ids = {"d"}
    picked = service_module._apply_exploration_slot(
        None,
        workspace_code="ws",
        run_key="rk",
        rec_policy=policy,
        scored=scored,
        selected_ids=selected_ids,
        limit=5,
        source_daily_limit=2,
    )
    assert picked == "b"
    assert selected_ids == {"d", "b"}

    # run limit 冲突：放弃探索位。
    assert (
        service_module._apply_exploration_slot(
            None,
            workspace_code="ws",
            run_key="rk",
            rec_policy=policy,
            scored=scored,
            selected_ids={"d"},
            limit=1,
            source_daily_limit=2,
        )
        is None
    )
    # source cap 冲突（同源已达上限）：放弃。
    low_selected = make_exploration_candidate("e", "src-low", "P1", "telecom_system", 90.0)
    assert (
        service_module._apply_exploration_slot(
            None,
            workspace_code="ws",
            run_key="rk",
            rec_policy=policy,
            scored=[low_selected, p1_low],
            selected_ids={"e"},
            limit=5,
            source_daily_limit=1,
        )
        is None
    )
    # pool cap 冲突（同池已满）：放弃。limit=3 -> pool_limit=2。
    pool_a = make_exploration_candidate("f", "src-hot", "P1", "ai_engineering", 95.0)
    pool_b = make_exploration_candidate("g", "src-hot2", "P1", "ai_engineering", 94.0)
    assert (
        service_module._apply_exploration_slot(
            None,
            workspace_code="ws",
            run_key="rk",
            rec_policy=policy,
            scored=[pool_a, pool_b, p1_low],
            selected_ids={"f", "g"},
            limit=3,
            source_daily_limit=2,
        )
        is None
    )
    # 抽签未命中（draw >= epsilon）：不生效。
    monkeypatch.setattr(service_module, "exploration_draw", lambda _rk: 0.99)
    assert (
        service_module._apply_exploration_slot(
            None,
            workspace_code="ws",
            run_key="rk",
            rec_policy=policy,
            scored=scored,
            selected_ids={"d"},
            limit=5,
            source_daily_limit=2,
        )
        is None
    )


def test_exploration_slot_appends_low_data_p1_candidate(monkeypatch):
    session = make_session()
    workspace = epsilon_zero_fixture(session)
    set_recommendation_policy(
        session,
        workspace,
        feedback_workflow={
            "weekly_rollup_enabled": True,
            "monthly_review_enabled": True,
            "proposal_generation_enabled": True,
            "exploration_epsilon": 0.1,
        },
    )
    # 手动 rollup 产出低数据源清单（本周期全部源都 <5 条 -> insufficient_data）。
    rollup = rollup_workspace_week(session, workspace, current_week_key())
    assert rollup.metrics_json["low_data_sources"]

    # 构造「现状选择留下一个 P1 低数据源候选未入选」的场景（探索位唯一入口）。
    original_select = service_module._selected_candidate_ids

    def leave_agent_unselected(scored, limit, source_daily_limit):
        ids = original_select(scored, limit, source_daily_limit)
        for score in scored:
            if (score.news_item.source_url or "") == "https://example.com/baseline-agent":
                ids.discard(score.news_item.id)
        return ids

    monkeypatch.setattr(service_module, "_selected_candidate_ids", leave_agent_unselected)
    # 确定性抽签强制命中（draw < epsilon）。
    monkeypatch.setattr(service_module, "exploration_draw", lambda _run_key: 0.0)
    result = run_recommendation(session, limit=3)
    exploration_items = [
        item for item in result.run.items if "exploration_slot" in item.recommendation_reason
    ]
    # 每 run ≤ 1 条，admission 限定 P1/P2，selected=True，reason 可解释。
    assert len(exploration_items) == 1
    slot = exploration_items[0]
    assert slot.news_item.source_url == "https://example.com/baseline-agent"
    assert slot.admission_level in {"P1", "P2"}
    assert slot.selected is True

    # 抽签未命中（draw >= epsilon）时零探索位。
    monkeypatch.setattr(service_module, "exploration_draw", lambda _run_key: 0.99)
    result_missed = run_recommendation(session, limit=3)
    assert all(
        "exploration_slot" not in item.recommendation_reason for item in result_missed.run.items
    )


# ---------------------------------------------------------------------------
# 断言 11：边界不越权（sync feed / 公司 SQL / 历史快照）
# ---------------------------------------------------------------------------


def test_new_tables_never_enter_sync_feed_or_company_sql():
    from app.sync.feed import _FEED_MODELS

    assert FeedbackRollup not in _FEED_MODELS.values()
    assert RubricRevisionProposal not in _FEED_MODELS.values()
    # 无 SyncMixin：没有 global_id/sync_policy 列，物理上进不了 feed envelope。
    for model in (FeedbackRollup, RubricRevisionProposal):
        assert not hasattr(model, "global_id")
        assert not hasattr(model, "sync_policy")


def _strip_generated_at(sql_text: str) -> str:
    return "\n".join(
        line for line in sql_text.splitlines() if not line.startswith("-- 生成时间:")
    )


def test_rollup_runs_leave_history_and_company_sql_untouched():
    from app.exports.company_sql import generate_company_sql_for_daily_report
    from app.recommendations.reaggregate import run_feedback_reaggregate

    session = make_session()
    workspace, news = build_metrics_fixture(session)
    report = session.scalar(select(DailyReport))
    # 每日层快照先落一轮，作为“历史行不变”的对照。
    run_feedback_reaggregate(session)
    session.flush()

    def snapshot():
        rec = [
            (row.id, row.rank, row.final_score, row.selected, row.recommendation_reason)
            for row in session.scalars(
                select(RecommendationItem).order_by(RecommendationItem.id),
            ).all()
        ]
        src = [
            (row.id, row.source_prior_delta, row.adopt_rate, row.day_key)
            for row in session.scalars(
                select(SourceScoreSnapshot).order_by(SourceScoreSnapshot.id),
            ).all()
        ]
        topics = [
            (row.id, row.topic_code, row.effective_weight, row.day_key)
            for row in session.scalars(
                select(RubricTopicPrior).order_by(RubricTopicPrior.id),
            ).all()
        ]
        return rec, src, topics

    before_rows = snapshot()
    sql_before = generate_company_sql_for_daily_report(
        session, report.id, requested_by_id=None
    ).sql_text
    run_feedback_weekly_rollup(session, period_key=current_week_key())
    run_feedback_monthly_review(session, period_key=current_month_key())
    after_rows = snapshot()
    assert before_rows == after_rows
    sql_after = generate_company_sql_for_daily_report(
        session, report.id, requested_by_id=None
    ).sql_text
    # 公司 SQL 逐字节不变（生成时间行除外——与 rollup 无关的导出时刻戳）。
    assert _strip_generated_at(sql_before) == _strip_generated_at(sql_after)
    for needle in ("feedback_rollups", "rubric_revision_proposals"):
        assert needle not in sql_after


# ---------------------------------------------------------------------------
# 断言 12：手动触发 API（幂等 + 审计 + viewer 403）
# ---------------------------------------------------------------------------


ROLLUP_RUN_URL = "/api/workspaces/planning_intel/feedback-rollups/run"


def test_manual_rollup_run_idempotent_audited_and_gated(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    first = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly"})
    assert first.status_code == 200
    body = first.json()
    assert body["period_type"] == "weekly"
    assert body["status"] in {"empty", "succeeded"}
    # 幂等：重复触发覆盖同一行。
    second = client.post(
        ROLLUP_RUN_URL,
        json={"period_type": "weekly", "period_key": body["period_key"]},
    )
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]
    listed = client.get(
        "/api/workspaces/planning_intel/feedback-rollups?period_type=weekly&limit=8",
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    detail = client.get(f"/api/workspaces/planning_intel/feedback-rollups/{body['id']}")
    assert detail.status_code == 200
    assert "source_breakdown" in detail.json()

    # 非法 period_type / period_key -> 422。
    assert client.post(ROLLUP_RUN_URL, json={"period_type": "daily"}).status_code == 422
    assert (
        client.post(
            ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": "2026-13"}
        ).status_code
        == 422
    )

    with session_factory() as session:
        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "workspace.feedback_rollup.manual_run"),
        ).all()
        assert len(audits) == 2
        assert audits[0].detail_json["trigger"] == "manual"

    # viewer 403（admin+ 门禁）。
    invite = client.post(
        "/api/auth/invites",
        json={
            "role_code": "viewer",
            "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
            "expires_in_days": 7,
        },
    )
    assert invite.status_code == 200
    viewer = TestClient(create_app())
    accepted = viewer.post(
        f"/api/auth/invites/{invite.json()['code']}/accept",
        json={"username": "ws-viewer", "display_name": "ws-viewer", "password": "strong-password"},
    )
    assert accepted.status_code == 200
    assert viewer.post(ROLLUP_RUN_URL, json={"period_type": "weekly"}).status_code == 403
    assert (
        viewer.get("/api/workspaces/planning_intel/feedback-rollups").status_code == 403
    )
    assert (
        viewer.get(
            "/api/workspaces/planning_intel/rubric-revision-proposals?status=pending_review",
        ).status_code
        == 403
    )


# ---------------------------------------------------------------------------
# 断言 13：调度幂等与能力门（周一 03:00 / 每月 1 日 03:30；intranet 不投递）
# ---------------------------------------------------------------------------


def test_weekly_rollup_dispatches_once_at_monday_trigger(tmp_path):
    session_factory = make_session_factory(tmp_path, "feedback_weekly_rollup.sqlite")
    settings = make_settings()
    queue = FakeQueue()
    state = SchedulerState()

    # 2026-07-06 是周一：02:59 只初始化节拍，不投递。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 6, 2, 59), session_factory=session_factory)
    assert all(call[0] is not run_feedback_weekly_rollup_job for call in queue.calls)

    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 6, 3, 5), session_factory=session_factory)
    weekly_calls = [call for call in queue.calls if call[0] is run_feedback_weekly_rollup_job]
    assert len(weekly_calls) == 1

    # 同触发点 tick 重放不重复投递。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 6, 3, 6), session_factory=session_factory)
    weekly_calls = [call for call in queue.calls if call[0] is run_feedback_weekly_rollup_job]
    assert len(weekly_calls) == 1

    # 第二个 scheduler 实例跨过同一触发点：心跳表判重（跨实例幂等）。
    second_state = SchedulerState()
    scheduler_tick(queue, settings, second_state, now=shanghai(2026, 7, 6, 2, 58), session_factory=session_factory)
    scheduler_tick(queue, settings, second_state, now=shanghai(2026, 7, 6, 3, 10), session_factory=session_factory)
    weekly_calls = [call for call in queue.calls if call[0] is run_feedback_weekly_rollup_job]
    assert len(weekly_calls) == 1

    with session_factory() as session:
        heartbeat = session.scalar(
            select(SchedulerHeartbeat).where(
                SchedulerHeartbeat.job_kind == "feedback_weekly_rollup",
                SchedulerHeartbeat.last_enqueued_at.is_not(None),
            ),
        )
        assert heartbeat is not None

    # 非周一冷启动：节拍指向下周一 03:00，不补跑。
    cold_state = SchedulerState()
    cold_queue = FakeQueue()
    scheduler_tick(cold_queue, settings, cold_state, now=shanghai(2026, 7, 8, 10, 0), session_factory=session_factory)
    assert cold_state.next_feedback_weekly_rollup_at == shanghai(2026, 7, 13, 3, 0)
    assert all(call[0] is not run_feedback_weekly_rollup_job for call in cold_queue.calls)


def test_monthly_review_dispatch_and_intranet_gate(tmp_path):
    session_factory = make_session_factory(tmp_path, "feedback_monthly_review.sqlite")
    settings = make_settings()
    queue = FakeQueue()
    state = SchedulerState()

    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 1, 3, 29), session_factory=session_factory)
    assert all(call[0] is not run_feedback_monthly_review_job for call in queue.calls)
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 1, 3, 35), session_factory=session_factory)
    monthly_calls = [call for call in queue.calls if call[0] is run_feedback_monthly_review_job]
    assert len(monthly_calls) == 1
    # 节拍推进到下月 1 日 03:30。
    assert state.next_feedback_monthly_review_at == shanghai(2026, 8, 1, 3, 30)

    # intranet pull-only（capability_ingestion=false）：周/月 job 均零投递。
    intranet_queue = FakeQueue()
    intranet_settings = make_settings(deploy_mode="intranet", capability_ingestion=False)
    for now in (shanghai(2026, 7, 6, 2, 59), shanghai(2026, 7, 6, 3, 5), shanghai(2026, 7, 1, 3, 35)):
        scheduler_tick(
            intranet_queue,
            intranet_settings,
            SchedulerState(),
            now=now,
            session_factory=session_factory,
        )
    assert all(
        call[0] not in (run_feedback_weekly_rollup_job, run_feedback_monthly_review_job)
        for call in intranet_queue.calls
    )


def test_single_workspace_failure_does_not_abort_others(monkeypatch):
    session = make_session()
    seed_workspace(session, code="ws_alpha")
    seed_workspace(session, code="ws_beta")
    original = rollup_module.rollup_workspace_week

    def flaky(session_arg, workspace, period_key, **kwargs):
        if workspace.code == "ws_alpha":
            raise RuntimeError("boom")
        return original(session_arg, workspace, period_key, **kwargs)

    monkeypatch.setattr(rollup_module, "rollup_workspace_week", flaky)
    payload = run_feedback_weekly_rollup(session, period_key=current_week_key())
    by_code = {entry["workspace_code"]: entry["status"] for entry in payload["results"]}
    assert by_code["ws_alpha"] == "failed"
    assert by_code["ws_beta"] == "empty"
    rows = {
        row.workspace_code: row.status
        for row in session.scalars(select(FeedbackRollup)).all()
    }
    assert rows["ws_alpha"] == "failed"
    assert rows["ws_beta"] == "empty"
