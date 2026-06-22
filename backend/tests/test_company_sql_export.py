import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.exports.company_sql import (
    COMPANY_SQL_CONTENT_FIELDS,
    DailyReportGenerationNotReadyError,
    DailyReportNotPublishedError,
    generate_company_sql_for_daily_report,
)
from app.models.export import ExportJob, ExportJobItem
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.service import RecommendationRunRequest, run_daily_recommendation
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace
from tests.test_recommendations import make_client, make_session


def _published_report_session():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Example Official RSS")
    add_raw_item(
        session,
        source,
        "rss:company-sql",
        "Apple发布STARFlow-V：基于归一化流的端到端视频生成模型",
        "https://example.com/starflow",
        (
            "<p>STARFlow-V 讨论<span class=\"x\">归一化流</span>、扩散模型、"
            "端到端视频生成和原生似然估计。</p><script>bad()</script>"
        ),
        published_at=datetime(2026, 4, 30, 8, tzinfo=UTC),
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
        now=datetime(2026, 4, 30, 10, tzinfo=UTC),
    )
    assert result.daily_report is not None
    report = result.daily_report
    report.status = "published"
    report.items[0].generated_news.generated_by = "minimax:test"
    report.items[0].generated_news.generation_status = "ready"
    report.items[0].editor_title = "Apple发布STARFlow-V：O'Hara 兼容性验证"
    report.items[0].editor_key_points = "STARFlow-V,归一化流,端到端视频生成"
    report.items[0].editor_content_json = {"valueAndImpact": "编辑后的价值判断"}
    session.flush()
    return session, report


def test_company_sql_export_matches_legacy_table_order_and_content_shape():
    session, report = _published_report_session()

    result = generate_company_sql_for_daily_report(session, report.id, requested_by_id=None)
    session.commit()

    sql_text = result.sql_text
    assert result.item_count == 1
    assert result.statement_count == 4
    assert sql_text.startswith("-- InfoWatchtower Company SQL Preview\n")
    assert "-- 工作台: planning_intel" in sql_text
    assert "-- 日期范围: 2026-04-30" in sql_text
    assert "-- 汇总: 1 条新闻，4 条 SQL 语句。" in sql_text
    assert "-- [写入数据 Focus_ID: 1]" in sql_text
    assert (
        "INSERT IGNORE INTO ai_journal (source_url, source_title, content, created_at) VALUES"
        in sql_text
    )
    assert "INSERT IGNORE INTO ai_journal_focus (journal_id, focus_id) SELECT id, 1" in sql_text
    assert "INSERT INTO ai_journal_analysis" in sql_text
    assert (
        "INSERT INTO ai_journal_analysis "
        "(journal_id, category, title, summary, key_points, content_json, source_url, created_at) "
        in sql_text
    )
    assert "INSERT INTO t_news_data_info" in sql_text
    assert "SELECT NULL, id, NULL, 2," in sql_text
    assert "'2026-04-30 16:00:00'" in sql_text
    assert "STR_TO_DATE(" not in sql_text
    assert "O''Hara" in sql_text
    assert "STARFlow-V,归一化流,端到端视频生成" in sql_text
    assert "<span" not in sql_text
    assert "<script" not in sql_text
    assert "bad()" not in sql_text
    assert "STARFlow-V 讨论 归一化流" in sql_text
    assert "编辑后的价值判断" in sql_text
    assert '"recommendationReason"' not in sql_text
    assert '"source"' not in sql_text
    for field in COMPANY_SQL_CONTENT_FIELDS:
        assert f'"{field}"' in sql_text

    assert session.scalar(select(func.count(ExportJob.id))) == 1
    assert session.scalar(select(func.count(ExportJobItem.id))) == 4


def test_company_sql_export_rejects_unpublished_reports():
    session, report = _published_report_session()
    report.status = "draft"
    session.flush()

    with pytest.raises(DailyReportNotPublishedError):
        generate_company_sql_for_daily_report(session, report.id)


def test_company_sql_export_falls_back_to_report_day_when_published_at_missing():
    session, report = _published_report_session()
    item = report.items[0]
    news_item = item.generated_news.news_item
    raw_item = news_item.raw_item
    raw_item.published_at = None
    news_item.published_at = None
    session.flush()

    result = generate_company_sql_for_daily_report(session, report.id, requested_by_id=None)
    sql_text = result.sql_text

    assert len(re.findall(r"created_at\) VALUES \([^\n]*, '2026-04-30 09:00:00'\);", sql_text)) == 1
    assert ", '2026-04-30 09:00:00' FROM ai_journal" in sql_text
    assert "source_url, created_at)" in sql_text
    assert ", NULL FROM ai_journal" not in sql_text


def test_company_sql_export_rejects_non_llm_generated_items():
    session, report = _published_report_session()
    report.items[0].generated_news.generated_by = "rule_v1:fallback"
    report.items[0].generated_news.generation_status = "fallback_needs_review"
    session.flush()

    with pytest.raises(DailyReportGenerationNotReadyError):
        generate_company_sql_for_daily_report(session, report.id)


def test_company_sql_export_api_requires_published_report(monkeypatch, tmp_path):
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
    report_id = created.json()["daily_report_id"]
    blocked = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert blocked.status_code == 409

    published = client.post(f"/api/daily-reports/{report_id}/publish")
    assert published.status_code == 200
    exported = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert exported.status_code == 409
    assert "generated by the LLM" in exported.json()["detail"]

    jobs = client.get("/api/exports")
    assert jobs.status_code == 200
    assert jobs.json() == []
