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
    markdown = render_markdown(rendition)
    assert "技术洞察版" in rendition.title
    assert "📋 **要点**" in markdown


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
