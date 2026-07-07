from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.content import GeneratedNews, NewsItem, RawItem, RecommendationItem, RecommendationRun
from app.models.feedback import EditorialAction
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.service import (
    RecommendationRunRequest,
    _key_points,
    run_daily_recommendation,
)
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_recommendation_run_creates_scores_generated_news_and_daily_draft():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Example Official RSS")
    add_raw_item(
        session,
        source,
        "rss:1",
        "New agent model release",
        "https://example.com/agent",
        "Agent model release with enough body to score well.",
    )
    add_raw_item(
        session,
        source,
        "rss:2",
        "Training technology update",
        "https://example.com/training",
        "Training technology update body.",
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )

    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=15,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    assert result.run.status == "completed"
    assert result.candidates_total == 2
    assert result.selected_total == 2
    assert result.generated_total == 2
    assert session.scalar(select(func.count(RecommendationItem.id))) == 2
    recommendation_item = session.scalar(select(RecommendationItem).order_by(RecommendationItem.rank))
    assert recommendation_item is not None
    assert recommendation_item.admission_level in {"P0", "P1", "P2", "P3", "R"}
    assert recommendation_item.admission_score >= 0
    assert recommendation_item.admission_pool
    assert isinstance(recommendation_item.noise_types_json, list)
    assert isinstance(recommendation_item.reject_reasons_json, list)
    assert isinstance(recommendation_item.scorer_breakdown_json, dict)
    assert "config_loaded" in recommendation_item.scorer_breakdown_json
    assert isinstance(recommendation_item.expert_routes_json, list)
    assert session.scalar(select(func.count(GeneratedNews.id))) == 2
    assert session.scalar(select(func.count(DailyReportItem.id))) == 2
    generated = session.scalars(select(GeneratedNews)).all()
    required_content_fields = {
        "background",
        "effects",
        "eventSummary",
        "technologyAndInnovation",
        "valueAndImpact",
        "source",
    }
    assert all(required_content_fields.issubset(item.content_json) for item in generated)

    report = session.scalar(select(DailyReport))
    assert report is not None
    assert report.workspace_code == "planning_intel"
    assert report.day_key == "2026-05-05"
    assert report.status == "draft"
    assert {item.adoption_status for item in report.items} == {2}
    assert (
        report.items[0].generated_news.news_item.raw_item.raw_payload_json["author"]
        == "Example Team"
    )


def test_technical_recommendation_prefers_research_over_commercial_ai_news():
    session = make_session()
    workspace = seed_workspace(session)
    paper_source = seed_source(
        session,
        workspace,
        source_type="paper_rss",
        name="Apple Machine Learning Research",
    )
    commercial_source = seed_source(
        session,
        workspace,
        source_type="rss",
        name="Mobile World Live",
    )
    add_raw_item(
        session,
        paper_source,
        "paper:technical",
        "Research paper introduces an inference benchmark for agent memory",
        "https://machinelearning.apple.com/research/agent-memory-benchmark",
        (
            "This research paper studies LLM agent memory architecture, inference latency, "
            "benchmark evaluation, retrieval quality, and deployment tradeoffs for AI "
            "engineering teams."
        ),
    )
    add_raw_item(
        session,
        commercial_source,
        "rss:commercial",
        "AI startup raises funding as revenue growth accelerates",
        "https://example.com/ai-startup-funding",
        (
            "The company announced a funding round, valuation growth, sales momentum, "
            "commercial partnerships, and revenue expansion for its AI product business."
        ),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )

    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=1,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    selected_item = session.scalar(
        select(RecommendationItem).where(RecommendationItem.selected.is_(True)),
    )
    assert result.selected_total == 1
    assert selected_item is not None
    assert selected_item.news_item.source_type == "paper_rss"
    assert "benchmark" in selected_item.news_item.source_title.lower()
    assert "admission=" in selected_item.recommendation_reason
    assert selected_item.admission_level in {"P0", "P1", "P2"}
    assert selected_item.scorer_breakdown_json["config_loaded"] is True


def test_rule_generated_key_points_use_content_keywords_not_source_metadata():
    keywords = _key_points(
        SimpleNamespace(
            source_title="Apple发布STARFlow-V：基于归一化流的端到端视频生成模型",
            summary="STARFlow-V 是 Apple 机器学习团队发布的视频生成研究。",
            content="该模型讨论归一化流、扩散模型、原生似然估计和因果预测。",
        ),
        "模型",
    )

    assert "STARFlow-V" in keywords
    assert "归一化流" in keywords
    assert "视频生成" in keywords
    assert "rss" not in keywords
    assert "canonical_url" not in keywords


def test_requirement_feedback_enters_recommendation_feedback_score():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Requirement Feedback Source")
    add_raw_item(
        session,
        source,
        "rss:requirement-feedback",
        "Agent memory benchmark informs internal platform roadmap",
        "https://example.com/requirement-feedback",
        (
            "The article describes agent memory architecture, retrieval quality, inference "
            "latency, benchmark methodology, deployment constraints, and product roadmap impact."
        ),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    news_item = session.scalar(select(NewsItem))
    assert news_item is not None
    session.add(
        EditorialAction(
            object_type="news_item",
            object_id=news_item.id,
            action_type="requirement.feedback_to_recommendation",
            after_json={
                "requirement_id": "req-feedback-1",
                "outcome": "positive",
                "score_delta": 80,
                "source": "requirement_conclusion",
            },
            reason="已形成内部建设建议",
        ),
    )

    run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=15,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    item = session.scalar(select(RecommendationItem).where(RecommendationItem.news_item_id == news_item.id))
    assert item is not None
    assert item.feedback_score == 80.0
    assert "requirement_feedback_positive" in item.recommendation_reason


def test_source_daily_limit_selects_at_most_configured_items_per_source():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    for index in range(3):
        add_raw_item(
            session,
            source,
            f"rss:{index}",
            f"Model update {index}",
            f"https://example.com/model-{index}",
            "A useful model update body.",
        )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )

    run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=15,
            source_daily_limit=1,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    assert session.scalar(select(func.count(RecommendationItem.id))) == 3
    assert session.scalar(
        select(func.count(RecommendationItem.id)).where(RecommendationItem.selected.is_(True)),
    ) == 1
    assert session.scalar(select(func.count(DailyReportItem.id))) == 1


def test_admission_prefers_hardware_vendor_tech_over_finance_news():
    session = make_session()
    workspace = seed_workspace(session)
    hardware_source = seed_source(session, workspace, name="NVIDIA Technical Blog")
    finance_source = seed_source(session, workspace, name="VentureBeat")
    add_raw_item(
        session,
        hardware_source,
        "rss:hardware",
        "NVIDIA introduces NVLink architecture for AI factory inference clusters",
        "https://developer.nvidia.com/blog/nvlink-ai-factory",
        (
            "The technical post explains GPU cluster architecture, NVLink, inference serving, "
            "throughput, latency, HBM bandwidth, rack-scale deployment, and data center cost."
        ),
    )
    add_raw_item(
        session,
        finance_source,
        "rss:finance",
        "AI chip startup raises funding as valuation and revenue grow",
        "https://example.com/funding",
        (
            "The article focuses on a funding round, valuation, revenue growth, investors, "
            "sales expansion, and market momentum without architecture or benchmark details."
        ),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )

    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=1,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    selected_item = session.scalar(
        select(RecommendationItem).where(RecommendationItem.selected.is_(True)),
    )
    assert result.selected_total == 1
    assert selected_item is not None
    assert selected_item.news_item.source_name == "NVIDIA Technical Blog"
    assert "pool=vendor_hardware" in selected_item.recommendation_reason
    finance_item = session.scalar(
        select(RecommendationItem).where(RecommendationItem.news_item.has(source_name="VentureBeat")),
    )
    assert finance_item is not None
    assert "commercial_finance" in finance_item.recommendation_reason


def test_selection_caps_pure_paper_concentration_when_vendor_items_exist():
    session = make_session()
    workspace = seed_workspace(session)
    paper_source = seed_source(session, workspace, source_type="paper_rss", name="Nature RSS")
    vendor_source = seed_source(session, workspace, name="Huawei Technical Blog")
    for index in range(4):
        add_raw_item(
            session,
            paper_source,
            f"paper:{index}",
            f"Research paper on LLM benchmark and agent memory {index}",
            f"https://example.com/paper-{index}",
            "Research paper with LLM benchmark, agent memory, evaluation and model architecture.",
        )
    for index in range(2):
        add_raw_item(
            session,
            vendor_source,
            f"vendor:{index}",
            f"Huawei releases AI inference cluster architecture update {index}",
            f"https://example.com/vendor-{index}",
            "Technical architecture for AI infrastructure, GPUs, inference serving, latency and data center deployment.",
        )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )

    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=3,
            source_daily_limit=4,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    selected_items = session.scalars(
        select(RecommendationItem).where(RecommendationItem.selected.is_(True)),
    ).all()
    selected_papers = [item for item in selected_items if item.news_item.source_type == "paper_rss"]
    selected_vendor = [item for item in selected_items if item.news_item.source_name == "Huawei Technical Blog"]
    assert result.selected_total == 3
    assert len(selected_papers) <= 1
    assert len(selected_vendor) == 2


def _seed_hardware_workspace(session):
    """硬件工作台：关联 hardware domain pack + 自定义 label_set_code。"""
    workspace = Workspace(
        code="hardware_intel",
        name="硬件情报工作台",
        description="",
        default_domain_code="hardware",
        config_json={
            "label_policy": {
                "label_set_code": "hardware_intel_custom_categories",
                "news_format_code": "tech_insight_v1",
                "export_category_mode": "news_primary",
                "allowed_primary_categories": ["算力芯片", "端侧设备", "供应链与制造"],
                "secondary_labels_by_primary": {"算力芯片": ["GPU", "先进封装"]},
                "default_category": "算力芯片",
                "fallback_category": "算力芯片",
            },
        },
    )
    session.add(workspace)
    session.flush()
    return workspace


def test_hardware_workspace_neutral_scoring_not_killed_by_ai_noise_rules():
    """半导体/硬件工作台的核心内容（手机、可穿戴等端侧硬件）不被
    planning_intel 的 AI 噪声规则（consumer_product 等）误杀。"""
    session = make_session()
    workspace = _seed_hardware_workspace(session)
    source = seed_source(session, workspace, name="半导体产业观察")
    add_raw_item(
        session,
        source,
        "rss:hw-consumer",
        "手机与可穿戴端侧芯片出货带动先进封装产能",
        "https://example.com/hw-consumer",
        (
            "报道覆盖手机、可穿戴等端侧设备的 GPU 与 HBM 需求，"
            "以及晶圆代工与封测产能的排产变化。"
        ),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="hardware_intel", source_types=[], limit=None),
    )

    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="hardware_intel",
            day_key="2026-05-05",
            limit=15,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    item = session.scalar(select(RecommendationItem))
    assert item is not None
    # 中性口径：无 AI 噪声降权，pack 先验关键词命中后进入日报候选
    assert item.noise_types_json == []
    assert item.admission_level in {"P0", "P1", "P2"}
    assert item.selected is True
    assert item.scorer_breakdown_json["mode"] == "workspace_neutral"
    assert item.scorer_breakdown_json["policy_source"] == "domain_pack:hardware"
    assert result.selected_total == 1

    # 分类降级按 pack/policy 类目映射，不落 AI 十分类
    generated = session.scalar(select(GeneratedNews))
    assert generated is not None
    assert generated.category == "算力芯片"
    # 生成降级文案人称取自工作台，不再自称规划部
    assert "硬件情报工作台" in generated.content_json["effects"]
    assert "规划部" not in generated.content_json["effects"]

    # 自定义 label_set_code 随推荐链路运行 upsert 成 LabelSet 记录
    from app.models.labels import LabelSet

    stored = session.scalar(
        select(LabelSet).where(LabelSet.code == "hardware_intel_custom_categories"),
    )
    assert stored is not None
    assert stored.workspace_code == "hardware_intel"


def test_planning_workspace_keeps_ai_noise_rules_for_consumer_content():
    """planning_intel 的 AI 情报口径保持不变：消费电子内容仍被噪声规则拦截。"""
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Consumer Gadget News")
    add_raw_item(
        session,
        source,
        "rss:consumer",
        "新款手机与可穿戴设备发布",
        "https://example.com/consumer-phone",
        "新款手机和可穿戴设备上市，主打外观、价格与家电联动。",
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )

    run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=15,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    item = session.scalar(select(RecommendationItem))
    assert item is not None
    assert "consumer_product" in item.noise_types_json
    assert item.admission_level == "R"
    assert item.selected is False


def test_recommendation_can_rerun_same_day_with_same_scoring_time():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    add_raw_item(
        session,
        source,
        "rss:rerun",
        "Model rerun update",
        "https://example.com/model-rerun",
        "A useful model update body.",
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    request = RecommendationRunRequest(
        workspace_code="planning_intel",
        day_key="2026-05-05",
        limit=15,
        source_daily_limit=2,
        create_daily_draft=True,
    )
    fixed_scoring_time = datetime(2026, 5, 5, 10, tzinfo=UTC)

    first = run_daily_recommendation(session, request, now=fixed_scoring_time)
    second = run_daily_recommendation(session, request, now=fixed_scoring_time)
    session.commit()

    assert first.run.run_key != second.run.run_key
    assert session.scalar(select(func.count(RecommendationRun.id))) == 2
    assert session.scalar(select(func.count(DailyReport.id))) == 1
    assert session.scalar(select(func.count(DailyReportItem.id))) == 1


def test_recommendation_day_key_only_selects_that_report_day():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    add_raw_item(
        session,
        source,
        "rss:april-30",
        "April 30 model release",
        "https://example.com/april-30",
        "April 30 body.",
        published_at=datetime(2026, 4, 30, 8, tzinfo=UTC),
    )
    add_raw_item(
        session,
        source,
        "rss:may-01",
        "May 1 model release",
        "https://example.com/may-01",
        "May 1 body.",
        published_at=datetime(2026, 5, 1, 8, tzinfo=UTC),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )

    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-04-30",
            limit=15,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
    )
    session.commit()

    assert result.candidates_total == 1
    assert result.daily_report is not None
    assert result.daily_report.day_key == "2026-04-30"
    assert result.daily_report.items[0].generated_news.news_item.source_url == (
        "https://example.com/april-30"
    )


def test_normalization_rebuild_preserves_historical_recommendation_links():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    raw_item = add_raw_item(
        session,
        source,
        "rss:historical",
        "Historical model release",
        "https://example.com/historical",
        "Historical body.",
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key="2026-05-05",
            limit=15,
            source_daily_limit=2,
            create_daily_draft=True,
        ),
        now=datetime(2026, 5, 5, 10, tzinfo=UTC),
    )

    raw_item.source_url = None
    raw_item.source_title = ""
    raw_item.published_at = None
    result = normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    session.commit()

    assert result.raw_skipped == 1
    assert session.scalar(select(func.count(RecommendationItem.id))) == 1
    historical_item = session.scalar(select(RecommendationItem))
    assert historical_item is not None
    assert historical_item.dedupe_group_item_id is not None
    assert historical_item.dedupe_group_item.is_winner is False
    assert historical_item.dedupe_group_item.duplicate_reason == "stale_after_rebuild"


def test_daily_reports_are_scoped_by_workspace_for_same_day_and_domain():
    session = make_session()
    planning = seed_workspace(session, "planning_intel")
    tools = seed_workspace(session, "ai_tools")
    source = seed_source(session, planning)
    session.add(
        WorkspaceSourceLink(
            workspace=tools,
            data_source=source,
            domain_code="ai",
            enabled=True,
        ),
    )
    add_raw_item(session, source, "rss:1", "Shared item", "https://example.com/shared", "Body")
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="ai_tools", source_types=[], limit=None),
    )

    for workspace_code in ("planning_intel", "ai_tools"):
        run_daily_recommendation(
            session,
            RecommendationRunRequest(
                workspace_code=workspace_code,
                day_key="2026-05-05",
                limit=15,
                source_daily_limit=2,
                create_daily_draft=True,
            ),
            now=datetime(2026, 5, 5, 10, tzinfo=UTC),
        )
    session.commit()

    assert session.scalar(select(func.count(DailyReport.id))) == 2
    assert {report.workspace_code for report in session.scalars(select(DailyReport)).all()} == {
        "planning_intel",
        "ai_tools",
    }


def make_client(monkeypatch, tmp_path):
    database_path = tmp_path / "recommendations_api.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_MODE", "public_password")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        assert workspace is not None
        source = seed_source(session, workspace)
        session.add(
            RawItem(
                data_source=source,
                workspace_code="shared",
                domain_code="ai",
                source_type="rss",
                source_name=source.name,
                entry_key="entry:1",
                source_title="API recommendation item introduces inference serving architecture",
                source_url="https://example.com/api-rec",
                raw_content=(
                    "The update explains model serving architecture, inference latency, "
                    "throughput, benchmark results, and deployment tradeoffs."
                ),
                fetched_at=datetime(2026, 5, 5, 9, tzinfo=UTC),
                published_at=datetime(2026, 5, 5, 8, tzinfo=UTC),
                raw_payload_json={"title": "API recommendation item introduces inference serving architecture"},
            ),
        )
        normalize_workspace_raw_items(
            session,
            NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
        )
        session.commit()

    return TestClient(create_app())


def test_recommendation_api_creates_daily_report_and_accepts_feedback(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/recommendation/runs",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "limit": 15,
            "source_daily_limit": 2,
            "create_daily_draft": True,
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["selected_total"] == 1
    report_id = created_payload["daily_report_id"]
    assert report_id

    report = client.get(f"/api/daily-reports/{report_id}")
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["status"] == "draft"
    item_id = report_payload["items"][0]["id"]

    patched = client.patch(
        f"/api/daily-report-items/{item_id}",
        json={"editor_title": "编辑后的标题", "adoption_status": 2},
    )
    assert patched.status_code == 200
    assert patched.json()["editor_title"] == "编辑后的标题"

    reaction = client.post(
        f"/api/daily-report-items/{item_id}/reactions",
        json={"reaction_type": "like"},
    )
    assert reaction.status_code == 200
    rating = client.post(f"/api/daily-report-items/{item_id}/ratings", json={"score": 5})
    assert rating.status_code == 200
    comment = client.post(
        f"/api/daily-report-items/{item_id}/comments",
        json={"body": "值得进入周报"},
    )
    assert comment.status_code == 200

    published = client.post(f"/api/daily-reports/{report_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    groups = client.get("/api/dedupe-groups", params={"workspace_code": "planning_intel"})
    assert groups.status_code == 200
    group_payload = groups.json()[0]
    assert group_payload["recommendation"]["selected"] is True
    assert group_payload["recommendation"]["day_key"] == "2026-05-05"
    assert group_payload["recommendation"]["admission_level"]
    assert isinstance(group_payload["recommendation"]["noise_types"], list)
    assert group_payload["daily_report"]["daily_report_id"] == report_id
    assert group_payload["daily_report"]["adoption_status"] == 2


def test_recommendation_run_detail_exposes_daily_report_review_trace(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/recommendation/runs",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "limit": 5,
            "source_daily_limit": 2,
            "create_daily_draft": False,
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["id"]

    run_before = client.get(f"/api/recommendation/runs/{run_id}")
    assert run_before.status_code == 200
    item_before = run_before.json()["items"][0]
    assert item_before["daily_report"] is None

    groups = client.get("/api/dedupe-groups", params={"workspace_code": "planning_intel"})
    assert groups.status_code == 200
    group_id = groups.json()[0]["id"]
    adopted = client.post(
        "/api/daily-reports/bulk-adopt-from-candidates",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "dedupe_group_ids": [group_id],
        },
    )
    assert adopted.status_code == 200
    assert adopted.json()["created_total"] == 1

    run_after = client.get(f"/api/recommendation/runs/{run_id}")
    assert run_after.status_code == 200
    item_after = run_after.json()["items"][0]
    assert item_after["daily_report"]["day_key"] == "2026-05-05"
    assert item_after["daily_report"]["report_status"] == "draft"
    assert item_after["daily_report"]["adoption_status"] == 2
    assert item_after["daily_report"]["daily_report_item_id"]


def test_scorer_policy_api_exposes_operational_summary(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    response = client.get(
        "/api/recommendation/scorer-policy",
        params={"workspace_code": "planning_intel"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_code"] == "planning_intel"
    assert payload["config_loaded"] is True
    assert payload["enabled"] is True
    assert payload["config_version"].startswith("content-scorer")
    assert payload["thresholds"]["P1"] == 84
    assert "P1" in payload["daily_levels"]
    assert "P2" in payload["weekly_levels"]
    assert payload["noise_rule_count"] > 0
    assert payload["weights"]
    assert payload["top_topics"]
    assert "topic_fields" not in payload


def test_scorer_preview_api_scores_without_creating_recommendation_run(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    before_runs = client.get("/api/recommendation/runs", params={"workspace_code": "planning_intel"})
    assert before_runs.status_code == 200
    assert before_runs.json() == []

    response = client.post(
        "/api/recommendation/scorer-preview",
        json={
            "workspace_code": "planning_intel",
            "source_title": "New inference serving architecture improves agent latency benchmark",
            "summary": "The release explains inference serving, KV cache, throughput and benchmark tradeoffs.",
            "content": "Architecture details include model serving, latency, throughput, benchmark and deployment cost.",
            "source_type": "rss",
            "source_name": "Example Official RSS",
            "source_url": "https://example.com/inference-serving",
            "source_tier": "P0",
            "source_channel_type": "官方技术规范/标准/RFC/Release",
            "source_score": 92,
            "source_tags": ["AI基础设施"],
            "source_secondary_tags": ["推理服务"],
            "board_relevance_json": {"AI Infra": "强相关"},
            "freshness_score": 90,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_code"] == "planning_intel"
    assert payload["source_title"].startswith("New inference serving")
    assert payload["admission_level"] in {"P0", "P1", "P2", "P3", "R"}
    assert payload["admission_score"] >= 0
    assert payload["admission_pool"]
    assert payload["persistence"] == "not_persisted"
    assert isinstance(payload["scorer_breakdown"], dict)

    after_runs = client.get("/api/recommendation/runs", params={"workspace_code": "planning_intel"})
    assert after_runs.status_code == 200
    assert after_runs.json() == []
