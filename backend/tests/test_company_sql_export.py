import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.auth.passwords import hash_password
from app.core.database import get_engine
from app.exports.company_sql import (
    COMPANY_SQL_CONTENT_FIELDS,
    CompanySqlWorkspaceNotSupportedError,
    DailyReportGenerationNotReadyError,
    DailyReportNotPublishedError,
    _export_category,
    _export_category_mode,
    generate_company_sql_for_daily_report,
    run_company_sql_preflight,
)
from app.models.export import ExportImportReceipt, ExportJob, ExportJobItem
from app.models.identity import Role, User
from app.models.workspace import Workspace, WorkspaceMembership
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
    assert result.export_job.result_json["sql_size_bytes"] == len(sql_text.encode("utf-8"))
    assert result.export_job.result_json["download_strategy"] == "server_streaming"
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


def test_company_sql_preflight_reports_item_warnings_without_writing_jobs():
    session, report = _published_report_session()

    preflight = run_company_sql_preflight(session, report.id)

    assert preflight.status == "passed"
    assert preflight.eligible_count == 1
    assert preflight.blocked_count == 0
    assert preflight.skipped_count == 0
    assert preflight.warning_count >= 1
    assert preflight.items[0].status == "eligible"
    assert "raw_content_html_cleaned" in {warning.code for warning in preflight.items[0].warnings}
    assert session.scalar(select(func.count(ExportJob.id))) == 0
    assert session.scalar(select(func.count(ExportJobItem.id))) == 0


def test_company_sql_preflight_blocks_missing_content_fields_and_export():
    session, report = _published_report_session()
    report.items[0].generated_news.content_json = {"background": "only one field"}
    report.items[0].editor_content_json = None
    session.flush()

    preflight = run_company_sql_preflight(session, report.id)

    assert preflight.status == "failed"
    assert preflight.blocked_count == 1
    assert "content_field_missing" in {error.code for error in preflight.items[0].errors}
    with pytest.raises(DailyReportGenerationNotReadyError):
        generate_company_sql_for_daily_report(session, report.id)
    assert session.scalar(select(func.count(ExportJob.id))) == 0


def test_company_sql_export_trace_preserves_source_lineage(monkeypatch, tmp_path):
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
    report_id = created.json()["daily_report_id"]
    published = client.post(f"/api/daily-reports/{report_id}/publish")
    assert published.status_code == 200

    # The API path intentionally keeps the SQL contract unchanged: trace data is
    # exposed through export_job_items instead of being serialized into SQL.
    from app.core.database import get_session_factory
    from app.models.content import GeneratedNews
    from app.models.reports import DailyReport

    Session = get_session_factory()
    with Session() as session:
        generated_items = session.scalars(select(GeneratedNews)).all()
        for generated in generated_items:
            generated.generated_by = "minimax:test"
            generated.generation_status = "ready"
        report = session.get(DailyReport, report_id)
        assert report is not None
        report.items[0].editor_title = "编辑 trace 标题"
        report.items[0].editor_content_json = {"valueAndImpact": "编辑 trace 价值判断"}
        session.commit()

    exported = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert exported.status_code == 200
    exported_payload = exported.json()
    export_job_id = exported_payload["export_job_id"]
    assert exported_payload["sql_text_bytes"] == len(exported_payload["sql_text"].encode("utf-8"))
    assert exported_payload["sql_text_truncated"] is False
    assert exported_payload["download_url"] == f"/api/exports/{export_job_id}/download"

    trace = client.get(f"/api/exports/{export_job_id}/trace")
    assert trace.status_code == 200
    payload = trace.json()
    assert payload["statement_count"] == exported.json()["statement_count"]
    assert len(payload["trace_items"]) == exported.json()["statement_count"]
    first = payload["trace_items"][0]
    assert first["export_job_item_id"]
    assert first["daily_report_item_id"]
    assert first["generated_news_id"]
    assert first["news_item_id"]
    assert first["raw_item_id"]
    assert first["data_source_id"]
    assert first["data_source_name"]
    assert first["source_url"].startswith("https://example.com/")
    assert first["sql_table"] == "ai_journal"
    assert first["export_title"] == "编辑 trace 标题"
    assert first["title_source"] == "daily_report_items.editor_title"
    assert first["summary_source"] == "generated_news.summary"
    assert first["content_field_sources"]["valueAndImpact"] == "daily_report_items.editor_content_json"
    assert "content_json.valueAndImpact" in first["editor_override_fields"]
    field_diffs = {item["field"]: item for item in first["field_diffs"]}
    assert field_diffs["title"]["changed_by_editor"] is True
    assert field_diffs["title"]["editor_value_preview"] == "编辑 trace 标题"
    assert field_diffs["summary"]["export_source"] == "generated_news.summary"
    assert field_diffs["content_json.valueAndImpact"]["changed_by_editor"] is True
    assert field_diffs["content_json.valueAndImpact"]["export_value_preview"] == "编辑 trace 价值判断"
    assert field_diffs["raw_content"]["raw_value_preview"]
    assert "raw_payload_json" not in first


def test_company_sql_export_response_truncates_large_inline_preview(monkeypatch, tmp_path):
    from app.api.routes import exports as exports_route

    monkeypatch.setattr(exports_route, "COMPANY_SQL_INLINE_PREVIEW_MAX_BYTES", 128)
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
    report_id = created.json()["daily_report_id"]
    assert client.post(f"/api/daily-reports/{report_id}/publish").status_code == 200
    _mark_all_generated_news_ready(get_engine())

    exported = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["sql_text_truncated"] is True
    assert payload["sql_text_bytes"] > payload["sql_text_preview_bytes"]
    assert "SQL preview truncated by InfoWatchtower" in payload["sql_text"]
    assert payload["download_url"] == f"/api/exports/{payload['export_job_id']}/download"
    assert payload["download_filename"] == "planning_intel_2026-05-05_company_sql.sql"


def test_company_sql_batch_export_returns_manifest_and_per_day_results(monkeypatch, tmp_path):
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
    report_id = created.json()["daily_report_id"]
    assert client.post(f"/api/daily-reports/{report_id}/publish").status_code == 200
    _mark_all_generated_news_ready(get_engine())

    batch = client.post(
        "/api/exports/company-sql/daily-reports/batch",
        json={"daily_report_ids": [report_id, "missing-report"], "continue_on_error": True},
    )

    assert batch.status_code == 200
    payload = batch.json()
    assert payload["status"] == "partial_success"
    assert payload["succeeded_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["total_reports"] == 2
    assert payload["total_statement_count"] == 4
    assert payload["total_sql_text_bytes"] > 0
    assert payload["manifest_json"]["schema_version"] == 1
    assert payload["manifest_json"]["validation_summary"]["passed"] == 1
    success_item = payload["items"][0]
    failed_item = payload["items"][1]
    assert success_item["daily_report_id"] == report_id
    assert success_item["status"] == "succeeded"
    assert success_item["export_job_id"]
    assert success_item["download_url"] == f"/api/exports/{success_item['export_job_id']}/download"
    assert failed_item["daily_report_id"] == "missing-report"
    assert failed_item["status"] == "failed"
    assert "Daily report not found" in failed_item["errors"][0]

    jobs = client.get("/api/exports", params={"workspace_code": "planning_intel"})
    assert jobs.status_code == 200
    export_types = {item["export_type"] for item in jobs.json()}
    assert {"company_sql", "company_sql_batch"}.issubset(export_types)


def test_company_sql_export_download_requires_workspace_admin(monkeypatch, tmp_path):
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
    report_id = created.json()["daily_report_id"]
    published = client.post(f"/api/daily-reports/{report_id}/publish")
    assert published.status_code == 200

    engine = get_engine()
    _mark_all_generated_news_ready(engine)
    _create_workspace_user(engine, "export-viewer", "password-123", workspace_role="viewer")
    _create_workspace_user(engine, "export-admin", "password-123", workspace_role="admin")

    exported = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert exported.status_code == 200
    export_job_id = exported.json()["export_job_id"]

    viewer_login = client.post("/api/auth/login", json={"username": "export-viewer", "password": "password-123"})
    assert viewer_login.status_code == 200
    viewer_download = client.get(f"/api/exports/{export_job_id}/download")
    assert viewer_download.status_code == 403
    assert viewer_download.json()["detail"] == "insufficient workspace role"

    workspace_admin_login = client.post("/api/auth/login", json={"username": "export-admin", "password": "password-123"})
    assert workspace_admin_login.status_code == 200
    admin_download = client.get(f"/api/exports/{export_job_id}/download")
    assert admin_download.status_code == 200
    assert admin_download.headers["content-type"].startswith("text/sql")
    assert "attachment" in admin_download.headers["content-disposition"]
    assert "planning_intel_2026-05-05_company_sql.sql" in admin_download.headers["content-disposition"]
    assert admin_download.headers["x-infowatchtower-download-strategy"] == "server_streaming"
    assert int(admin_download.headers["x-infowatchtower-sql-bytes"]) == len(admin_download.content)
    assert int(admin_download.headers["content-length"]) == len(admin_download.content)
    assert admin_download.text.startswith("-- InfoWatchtower Company SQL Preview\n")
    assert "INSERT IGNORE INTO ai_journal" in admin_download.text


def test_company_sql_import_receipt_records_intranet_feedback_with_viewer_read_gate(monkeypatch, tmp_path):
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
    report_id = created.json()["daily_report_id"]
    assert client.post(f"/api/daily-reports/{report_id}/publish").status_code == 200
    engine = get_engine()
    _mark_all_generated_news_ready(engine)
    _create_workspace_user(engine, "receipt-viewer", "password-123", workspace_role="viewer")

    exported = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert exported.status_code == 200
    export_job_id = exported.json()["export_job_id"]
    statement_count = exported.json()["statement_count"]

    receipt = client.post(
        f"/api/exports/{export_job_id}/import-receipts",
        json={
            "target_system": "company_intranet_prod",
            "import_status": "partial",
            "imported_statement_count": statement_count - 1,
            "failed_statement_count": 1,
            "failure_items": [
                {
                    "sql_sequence": 1,
                    "sql_table": "ai_journal",
                    "error_code": "column_too_long",
                    "error_message": "source_title 超过内网字段长度",
                },
            ],
            "notes": "内网测试导入反馈",
        },
    )
    assert receipt.status_code == 200
    receipt_payload = receipt.json()
    assert receipt_payload["export_job_id"] == export_job_id
    assert receipt_payload["import_status"] == "partial"
    assert receipt_payload["target_system"] == "company_intranet_prod"
    assert receipt_payload["failed_statement_count"] == 1
    failure = receipt_payload["failure_items"][0]
    assert failure["export_job_item_id"]
    assert failure["sql_sequence"] == 1
    assert failure["sql_table"] == "ai_journal"
    assert failure["sql_excerpt"].startswith("INSERT IGNORE INTO ai_journal")
    assert "source_title" in failure["error_message"]

    history = client.get("/api/exports", params={"workspace_code": "planning_intel"})
    assert history.status_code == 200
    latest = next(item for item in history.json() if item["id"] == export_job_id)["latest_import_receipt"]
    assert latest["import_status"] == "partial"
    assert latest["failed_statement_count"] == 1

    viewer_login = client.post("/api/auth/login", json={"username": "receipt-viewer", "password": "password-123"})
    assert viewer_login.status_code == 200
    viewer_get = client.get(f"/api/exports/{export_job_id}/import-receipts")
    assert viewer_get.status_code == 200
    assert viewer_get.json()[0]["id"] == receipt_payload["id"]
    viewer_write = client.post(
        f"/api/exports/{export_job_id}/import-receipts",
        json={"target_system": "company_intranet_prod", "import_status": "imported", "imported_statement_count": 1},
    )
    assert viewer_write.status_code == 403

    Session = sessionmaker(bind=engine)
    with Session() as session:
        stored = session.get(ExportImportReceipt, receipt_payload["id"])
        assert stored is not None
        assert stored.sync_policy == "local_only"
        assert stored.workspace_code == "planning_intel"


def test_company_sql_import_receipt_callback_uses_service_token_without_cookie_or_csrf(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNC_SERVICE_TOKENS", "import-token")
    monkeypatch.setenv("AUTH_CSRF_ENABLED", "true")
    client = make_client(monkeypatch, tmp_path)
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        export_job = ExportJob(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="local_only",
            export_type="company_sql",
            status="completed",
            result_json={"statement_count": 4, "sql_text": "-- sql"},
        )
        session.add(export_job)
        session.commit()
        export_job_id = export_job.id

    no_token = client.post(
        f"/api/exports/{export_job_id}/import-receipts/callback",
        json={
            "target_system": "company_intranet_prod",
            "import_status": "imported",
            "imported_statement_count": 4,
        },
    )
    assert no_token.status_code == 401

    callback = client.post(
        f"/api/exports/{export_job_id}/import-receipts/callback",
        headers={"Authorization": "Bearer import-token"},
        json={
            "target_system": "company_intranet_prod",
            "import_status": "imported",
            "imported_statement_count": 4,
            "notes": "内网 importer 自动回调",
        },
    )
    assert callback.status_code == 200
    payload = callback.json()
    assert payload["recorded_by_id"] is None
    assert payload["recorded_by_name"] is None
    assert payload["import_status"] == "imported"
    assert payload["notes"] == "内网 importer 自动回调"

    with Session() as session:
        stored = session.get(ExportImportReceipt, payload["id"])
        assert stored is not None
        assert stored.sync_policy == "local_only"
        assert stored.recorded_by_id is None


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
    preflight = client.post(f"/api/exports/company-sql/daily-reports/{report_id}/preflight")
    assert preflight.status_code == 200
    assert preflight.json()["status"] == "failed"
    assert preflight.json()["errors"][0]["code"] == "report_not_published"

    blocked = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert blocked.status_code == 409

    published = client.post(f"/api/daily-reports/{report_id}/publish")
    assert published.status_code == 200
    ready_check = client.post(f"/api/exports/company-sql/daily-reports/{report_id}/preflight")
    assert ready_check.status_code == 200
    assert ready_check.json()["status"] == "failed"
    assert ready_check.json()["blocked_count"] > 0
    assert "rule_fallback_blocked" in {
        issue["code"]
        for item in ready_check.json()["items"]
        for issue in item["errors"]
    }
    exported = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert exported.status_code == 409
    # 文案违例 #8 已替换（frontend-product-design §14.2）：透传到界面的 preflight
    # 提示不再出现实现术语 rule_v1，错误码 rule_fallback_blocked 保持不变。
    assert "规则降级草稿" in exported.json()["detail"]
    assert "rule_v1" not in exported.json()["detail"]

    jobs = client.get("/api/exports")
    assert jobs.status_code == 200
    assert jobs.json() == []


def test_company_sql_export_rejects_non_company_sql_workspace():
    """非公司 SQL 口径（非 AI 十分类）的工作台不允许静默映射导出。"""
    session = make_session()
    workspace = seed_workspace(session, "hardware_intel")
    workspace.config_json = {
        "label_policy": {
            "label_set_code": "hardware_categories",
            "news_format_code": "tech_insight_v1",
            "allowed_primary_categories": ["算力芯片", "端侧设备"],
            "default_category": "算力芯片",
            "fallback_category": "算力芯片",
        },
    }
    from app.models.reports import DailyReport

    report = DailyReport(
        workspace_code="hardware_intel",
        domain_code="hardware",
        day_key="2026-05-05",
        title="2026-05-05 硬件情报日报",
        status="published",
    )
    session.add(report)
    session.flush()

    preflight = run_company_sql_preflight(session, report.id)
    assert preflight.status == "failed"
    assert "workspace_not_company_sql" in {issue.code for issue in preflight.errors}

    with pytest.raises(CompanySqlWorkspaceNotSupportedError) as exc_info:
        generate_company_sql_for_daily_report(session, report.id)
    assert "公司 SQL 口径" in str(exc_info.value)
    assert session.scalar(select(func.count(ExportJob.id))) == 0


def test_company_sql_export_api_returns_400_for_tool_workspace(monkeypatch, tmp_path):
    """种子 ai_tools 工作台（tool_intel_v1 口径）经 API 导出返回 400 + 指引。"""
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    from app.models.reports import DailyReport

    engine = get_engine()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        report = DailyReport(
            workspace_code="ai_tools",
            domain_code="ai",
            day_key="2026-05-05",
            title="2026-05-05 AI 工具日报",
            status="published",
        )
        session.add(report)
        session.commit()
        report_id = report.id

    blocked = client.post(f"/api/exports/company-sql/daily-reports/{report_id}")
    assert blocked.status_code == 400
    assert "公司 SQL 口径" in blocked.json()["detail"]

    preflight = client.post(f"/api/exports/company-sql/daily-reports/{report_id}/preflight")
    assert preflight.status_code == 200
    assert preflight.json()["status"] == "failed"
    assert "workspace_not_company_sql" in {issue["code"] for issue in preflight.json()["errors"]}

    batch = client.post(
        "/api/exports/company-sql/daily-reports/batch",
        json={"daily_report_ids": [report_id], "continue_on_error": True},
    )
    assert batch.status_code == 200
    assert batch.json()["items"][0]["status"] == "failed"

    jobs = client.get("/api/exports", params={"workspace_code": "ai_tools"})
    assert jobs.status_code == 200
    assert all(job["export_type"] != "company_sql" for job in jobs.json())


def test_export_category_mode_resolves_from_policy_and_locks_news_primary():
    session, report = _published_report_session()

    # 导出口径经工作台标签策略解析，当前契约只允许 news_primary
    assert _export_category_mode(session, report) == "news_primary"
    # 死参数防护：未知口径显式拒绝，避免未来扩展时静默失效
    with pytest.raises(ValueError):
        _export_category(report.items[0], "generated_only")


def _mark_all_generated_news_ready(engine) -> None:
    from app.models.content import GeneratedNews

    Session = sessionmaker(bind=engine)
    with Session() as session:
        for generated in session.scalars(select(GeneratedNews)).all():
            generated.generated_by = "minimax:test"
            generated.generation_status = "ready"
        session.commit()


def _create_workspace_user(engine, username: str, password: str, *, workspace_role: str) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        role = session.scalar(select(Role).where(Role.code == "viewer"))
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        assert role is not None
        assert workspace is not None
        user = User(
            external_provider="local",
            external_id=username,
            username=username,
            display_name=username.title(),
            password_hash=hash_password(password),
            status="active",
            roles=[role],
        )
        session.add(user)
        session.flush()
        session.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=user.id,
                workspace_role=workspace_role,
                enabled=True,
            ),
        )
        session.commit()
