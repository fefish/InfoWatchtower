from datetime import UTC, datetime

from app.models.reports import ReportFormat
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.service import RecommendationRunRequest, run_daily_recommendation
from app.reports.rendition_html import render_html
from app.reports.renditions import (
    build_daily_rendition,
    ensure_report_formats,
    render_markdown,
)
from sqlalchemy import select

from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace
from tests.test_recommendations import make_session


def _daily_report_session():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Example Official RSS")
    add_raw_item(
        session,
        source,
        "rss:rendition-1",
        "New agent model release improves tool orchestration",
        "https://example.com/agent-release",
        "Agent platform release with detailed architecture and benchmark results body.",
        published_at=datetime(2026, 4, 30, 8, tzinfo=UTC),
    )
    add_raw_item(
        session,
        source,
        "rss:rendition-2",
        "Inference serving stack cuts token cost",
        "https://example.com/inference-stack",
        "Inference acceleration stack detail with throughput improvements body.",
        published_at=datetime(2026, 4, 30, 9, tzinfo=UTC),
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
            source_daily_limit=5,
            create_daily_draft=True,
        ),
        now=datetime(2026, 4, 30, 10, tzinfo=UTC),
    )
    assert result.daily_report is not None
    return session, result.daily_report


def test_builtin_formats_seeded_and_rendition_builds_markdown():
    session, report = _daily_report_session()
    formats = {fmt.format_code: fmt for fmt in ensure_report_formats(session, "planning_intel")}
    assert set(formats) >= {"company_sql_v1", "tech_insight_v1"}
    assert formats["company_sql_v1"].locked is True

    tech_format = formats["tech_insight_v1"]
    rendition = build_daily_rendition(session, report, tech_format, workspace_name="规划部情报工作台")
    session.commit()

    body = rendition.body_json
    assert body["group_by"] == "board"
    assert body["groups"], "board groups should not be empty"
    assert body["headlines"], "headline auto top-n should initialize"
    adopted = [item for item in report.items if item.adoption_status == 2]
    assert any(item.is_headline for item in adopted)

    snapshots = list(body["items"].values())
    for snapshot in snapshots:
        assert snapshot["board"], "each item must resolve a business board"
        assert snapshot["bullet_points"], "rule fallback must produce bullet points"
        assert snapshot["takeaway"], "rule fallback must produce takeaway"

    markdown = render_markdown(rendition)
    assert "## 今日头条" in markdown
    assert "📋 **要点**" in markdown
    assert "📌 **总结**" in markdown
    assert ":::summary" in markdown

    html = render_html(rendition)
    assert html.startswith("<!DOCTYPE html>")
    assert "今日头条" in html

    # 重生成幂等：同键 rendition 被覆盖而不是新增
    rendition_again = build_daily_rendition(session, report, tech_format, workspace_name="规划部情报工作台")
    session.commit()
    assert rendition_again.id == rendition.id


def test_rendition_does_not_touch_generated_news_or_adoption():
    session, report = _daily_report_session()
    formats = {fmt.format_code: fmt for fmt in ensure_report_formats(session, "planning_intel")}
    before = [
        (item.adoption_status, item.generated_news.category, dict(item.generated_news.content_json or {}))
        for item in report.items
    ]
    build_daily_rendition(session, report, formats["tech_insight_v1"])
    session.commit()
    after = [
        (item.adoption_status, item.generated_news.category, dict(item.generated_news.content_json or {}))
        for item in report.items
    ]
    assert before == after


def test_company_sql_rendition_groups_by_category():
    session, report = _daily_report_session()
    formats = {fmt.format_code: fmt for fmt in ensure_report_formats(session, "planning_intel")}
    rendition = build_daily_rendition(session, report, formats["company_sql_v1"])
    session.commit()
    assert rendition.body_json["group_by"] == "category"
    assert rendition.body_json["headlines"] == []
    markdown = render_markdown(rendition)
    assert "**事件总结**" in markdown or "**背景**" in markdown


def test_weekly_rendition_builds_from_adopted_items():
    from app.models.reports import WeeklyReport, WeeklyReportItem
    from app.reports.renditions import build_weekly_rendition

    session, report = _daily_report_session()
    formats = {fmt.format_code: fmt for fmt in ensure_report_formats(session, "planning_intel")}

    weekly = WeeklyReport(
        workspace_code="planning_intel",
        domain_code="ai",
        week_key="2026-W18",
        title="2026-W18 周报",
    )
    session.add(weekly)
    session.flush()
    for index, item in enumerate(report.items):
        session.add(
            WeeklyReportItem(
                weekly_report=weekly,
                workspace_code="planning_intel",
                domain_code="ai",
                daily_report_item_id=item.id,
                generated_news_id=item.generated_news_id,
                adoption_status=2,
                sort_order=index,
            ),
        )
    session.flush()
    session.refresh(weekly)

    rendition = build_weekly_rendition(session, weekly, formats["tech_insight_v1"], "规划部情报工作台")
    session.commit()
    assert rendition.report_type == "weekly"
    assert rendition.body_json["groups"]
    assert rendition.body_json["headlines"] == []
    assert rendition.summary_json["summary_generated_by"] == "rule_weekly_summary_v1"
    assert rendition.summary_json["summary_text"].startswith("本周共纳入")
    assert rendition.summary_json["key_highlights"]
    markdown = render_markdown(rendition)
    assert "技术洞察版" in rendition.title
    assert "- 摘要：" in markdown
    assert "- 关键亮点：" in markdown
    assert "📋 **要点**" in markdown
    html = render_html(rendition)
    assert "<strong>摘要：</strong>" in html
    assert "<strong>关键亮点：</strong>" in html


def _hardware_report_session():
    """硬件工作台日报：看板 taxonomy 应来自 hardware domain pack。"""
    from app.models.workspace import Workspace

    session = make_session()
    workspace = Workspace(
        code="hardware_intel",
        name="硬件情报工作台",
        description="",
        default_domain_code="hardware",
        config_json={
            "label_policy": {
                "label_set_code": "hardware_categories",
                "news_format_code": "tech_insight_v1",
                "allowed_primary_categories": ["算力芯片", "端侧设备", "供应链与制造"],
                "default_category": "算力芯片",
                "fallback_category": "算力芯片",
            },
        },
    )
    session.add(workspace)
    session.flush()
    source = seed_source(session, workspace, name="半导体产业观察")
    add_raw_item(
        session,
        source,
        "rss:hw-gpu",
        "NVIDIA 发布新一代 GPU 与 HBM 先进封装方案",
        "https://example.com/hw-gpu",
        "GPU、HBM 与先进封装产能提升，晶圆代工与封测排产同步调整。",
        published_at=datetime(2026, 4, 30, 8, tzinfo=UTC),
    )
    add_raw_item(
        session,
        source,
        "rss:hw-edge",
        "Edge AI 手机与可穿戴设备发布",
        "https://example.com/hw-edge",
        "edge ai 能力下放到手机与可穿戴设备，本地体验升级。",
        published_at=datetime(2026, 4, 30, 9, tzinfo=UTC),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="hardware_intel", source_types=[], limit=None),
    )
    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="hardware_intel",
            day_key="2026-04-30",
            limit=15,
            source_daily_limit=5,
            create_daily_draft=True,
        ),
        now=datetime(2026, 4, 30, 10, tzinfo=UTC),
    )
    assert result.daily_report is not None
    return session, result.daily_report


def test_hardware_workspace_rendition_groups_by_domain_pack_boards():
    session, report = _hardware_report_session()
    formats = {fmt.format_code: fmt for fmt in ensure_report_formats(session, "hardware_intel")}

    rendition = build_daily_rendition(session, report, formats["tech_insight_v1"], "硬件情报工作台")
    session.commit()

    body = rendition.body_json
    assert body["board_taxonomy_source"] == "domain_pack:hardware"
    pack_boards = {"算力芯片", "端侧设备", "供应链与制造"}
    group_titles = [group["title"] for group in body["groups"]]
    assert group_titles == ["算力芯片", "端侧设备"]
    for snapshot in body["items"].values():
        assert snapshot["board"] in pack_boards

    # pack 二级标签被看板归组消费：category 命中二级标签时归入其一级看板
    item = next(iter(report.items))
    item.generated_news.category = "GPU"
    session.flush()
    rendition = build_daily_rendition(session, report, formats["tech_insight_v1"], "硬件情报工作台")
    session.commit()
    snapshot = rendition.body_json["items"][item.id]
    assert snapshot["board"] == "算力芯片"


def test_custom_policy_workspace_rendition_groups_by_label_policy_boards():
    from app.models.workspace import Workspace

    session = make_session()
    workspace = Workspace(
        code="policy_intel",
        name="政策情报工作台",
        description="",
        default_domain_code="policy",
        config_json={
            "label_policy": {
                "label_set_code": "policy_intel_custom_categories",
                "news_format_code": "tech_insight_v1",
                "allowed_primary_categories": ["合规监管", "行业动态"],
                "secondary_labels_by_primary": {"合规监管": ["数据出境"]},
                "default_category": "行业动态",
                "fallback_category": "行业动态",
            },
        },
    )
    session.add(workspace)
    session.flush()
    source = seed_source(session, workspace, name="政策观察")
    add_raw_item(
        session,
        source,
        "rss:policy-1",
        "数据出境新规发布并公开征求意见",
        "https://example.com/policy-1",
        "监管部门发布数据出境合规监管新规，行业需评估牌照与流程调整。",
        published_at=datetime(2026, 4, 30, 8, tzinfo=UTC),
    )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="policy_intel", source_types=[], limit=None),
    )
    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="policy_intel",
            day_key="2026-04-30",
            limit=15,
            source_daily_limit=5,
            create_daily_draft=True,
        ),
        now=datetime(2026, 4, 30, 10, tzinfo=UTC),
    )
    assert result.daily_report is not None
    formats = {fmt.format_code: fmt for fmt in ensure_report_formats(session, "policy_intel")}

    rendition = build_daily_rendition(session, result.daily_report, formats["tech_insight_v1"], "政策情报工作台")
    session.commit()

    body = rendition.body_json
    assert body["board_taxonomy_source"] == "label_policy"
    assert [group["title"] for group in body["groups"]] == ["合规监管"]
    for snapshot in body["items"].values():
        assert snapshot["board"] == "合规监管"
        # AI 全局 14 板块不再泄漏到非 AI 工作台
        assert snapshot["board"] not in {"基础竞争力", "AI模型"}


def test_locked_format_cannot_change_structure():
    session, _ = _daily_report_session()
    ensure_report_formats(session, "planning_intel")
    locked = session.scalar(
        select(ReportFormat).where(
            ReportFormat.workspace_code == "planning_intel",
            ReportFormat.format_code == "company_sql_v1",
        ),
    )
    assert locked is not None and locked.locked is True
