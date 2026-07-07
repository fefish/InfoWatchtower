"""WP3-C generation_template 模板驱动生成验收（report-renditions-design §10.7 断言 1-10）。

复用 tests/test_generation_provider.py 的 fixture provider（httpx.MockTransport 注入），
不外呼。公司 SQL 锁死不变式（断言 10）：模板任意配置下导出逐字节一致。
"""

import json
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select

from app.models.feedback import AuditLog
from app.models.reports import ReportFormat, WeeklyReport, WeeklyReportItem
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.service import RecommendationRunRequest, run_daily_recommendation
from app.reports.generation_template import (
    generated_field_keys,
    parse_generation_template,
)
from app.reports.rendition_html import render_html
from app.reports.renditions import (
    build_daily_rendition,
    build_weekly_rendition,
    ensure_report_formats,
    render_markdown,
)
from tests.test_generation_provider import (
    RecordingHandler,
    _completion_response,
    _install_fixture_provider,
    _login,
    _quality_payload,
    make_client,
)
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace
from tests.test_recommendations import make_session

ONE_LINER_TEXT = "一句话结论：推理框架单卡吞吐显著提升"

PURE_PROJECTION_TEMPLATE = {
    "carrier": "json",
    "item_schema": {
        "fields": [
            {"key": "headline", "label": "标题", "type": "string", "map_from": "title"},
            {"key": "summary", "label": "摘要", "type": "text"},
            {"key": "background", "label": "背景", "type": "text"},
            {"key": "source_link", "label": "来源", "type": "url"},
        ],
    },
}

EXTRA_FIELD_TEMPLATE = {
    "carrier": "json",
    "item_schema": {
        "fields": [
            {"key": "headline", "label": "标题", "type": "string", "map_from": "title"},
            {
                "key": "one_liner",
                "label": "一句话结论",
                "type": "string",
                "required": True,
                "max_length": 80,
                "example": "X 公司开源 Y 推理框架，单卡吞吐提升。",
                "guidance": "面向高管的一句话，不带技术细节",
            },
            {"key": "source_link", "label": "来源", "type": "url"},
        ],
    },
}


def _dual_responder(request: httpx.Request, payload: dict) -> httpx.Response:
    """基稿调用返回质量稿；模板增量调用（outputSchema 含 one_liner）返回增量字段。"""
    user_content = payload["messages"][-1]["content"]
    if '"one_liner"' in user_content:
        return _completion_response({"one_liner": ONE_LINER_TEXT})
    return _completion_response(_quality_payload())


def _register_template_format(session, workspace_code: str, format_code: str, template: dict) -> ReportFormat:
    canonical, errors = parse_generation_template(template)
    assert canonical is not None, errors
    fmt = ReportFormat(
        workspace_code=workspace_code,
        format_code=format_code,
        name="自定义模板版",
        description="",
        builtin=False,
        locked=False,
        group_by="category",
        headline_enabled=False,
        headline_auto_top_n=0,
        item_fields={"fields": ["summary", "source_link"]},
        export_targets={"targets": ["md", "html"]},
        enabled=True,
        sort_order=100,
        generation_template=canonical,
        generation_template_source=json.dumps(template, ensure_ascii=False),
    )
    session.add(fmt)
    session.flush()
    return fmt


def _pipeline_session(item_total: int = 2):
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Example Official RSS")
    for index in range(item_total):
        add_raw_item(
            session,
            source,
            f"rss:tpl-{index}",
            f"Agent model release {index} improves tool orchestration",
            f"https://example.com/tpl-{index}",
            "Agent platform release with detailed architecture and benchmark body.",
            published_at=datetime(2026, 4, 30, 8 + index, tzinfo=UTC),
        )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    return session, workspace


def _run_pipeline(session):
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
    return result


# --- 断言 1：map_from 全覆盖 = 纯投影格式，生成 step 零额外模型调用 ---


def test_pure_projection_template_makes_zero_extra_model_calls(monkeypatch):
    handler = RecordingHandler(_dual_responder)
    _install_fixture_provider(monkeypatch, handler)
    session, workspace = _pipeline_session(item_total=2)
    fmt = _register_template_format(session, workspace.code, "custom_pure_v1", PURE_PROJECTION_TEMPLATE)
    assert generated_field_keys(fmt.generation_template) == []

    result = _run_pipeline(session)
    assert len(handler.requests) == 2, "pure projection format must not add model calls"

    rendition = build_daily_rendition(session, result.daily_report, fmt)
    session.commit()
    body = rendition.body_json
    assert body["item_fields"] == ["headline", "summary", "background", "source_link"]
    assert [field["key"] for field in body["template"]["fields"]] == body["item_fields"]
    for snapshot in body["items"].values():
        assert snapshot["template_values"]["headline"] == snapshot["title"]
        assert snapshot["template_values"]["summary"] == snapshot["summary"]
        assert snapshot["template_values"]["background"] == snapshot["five_fields"]["background"]
        assert snapshot["template_fallback"] is False


# --- 断言 2：增量字段生成进 template_extras_json，基稿三件套不被触碰 ---


def test_extra_field_generation_fills_extras_without_touching_base_draft(monkeypatch):
    handler = RecordingHandler(_dual_responder)
    _install_fixture_provider(monkeypatch, handler)
    session, workspace = _pipeline_session(item_total=2)
    result = _run_pipeline(session)
    report = result.daily_report
    base_snapshot = {
        item.generated_news.id: (
            json.dumps(item.generated_news.content_json, ensure_ascii=False, sort_keys=True),
            json.dumps(item.generated_news.insight_json, ensure_ascii=False, sort_keys=True),
            item.generated_news.category,
        )
        for item in report.items
    }

    fmt = _register_template_format(session, workspace.code, "exec_brief_v1", EXTRA_FIELD_TEMPLATE)
    rendition = build_daily_rendition(session, report, fmt)
    session.commit()

    for item in report.items:
        news = item.generated_news
        bucket = news.template_extras_json["exec_brief_v1"]
        assert bucket["values"]["one_liner"] == ONE_LINER_TEXT
        assert bucket["template_version"] == 1
        assert bucket["generated_by"].startswith("minimax:")
        # 增量字段永不进入 content_json / insight_json / category（§10.6）
        assert base_snapshot[news.id] == (
            json.dumps(news.content_json, ensure_ascii=False, sort_keys=True),
            json.dumps(news.insight_json, ensure_ascii=False, sort_keys=True),
            news.category,
        )
        assert "one_liner" not in json.dumps(news.content_json, ensure_ascii=False)

    for snapshot in rendition.body_json["items"].values():
        assert snapshot["template_values"]["one_liner"] == ONE_LINER_TEXT
        assert snapshot["template_fallback"] is False
    markdown = render_markdown(rendition)
    assert "**一句话结论**" in markdown
    assert ONE_LINER_TEXT in markdown
    html = render_html(rendition)
    assert "一句话结论" in html
    assert ONE_LINER_TEXT in html


# --- 断言 3：XML 与 JSON 载体规范形完全相等；DTD/外部实体 422 ---

XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<template version="9">
  <item>
    <field key="headline" type="string" map-from="title"><label>标题</label></field>
    <field key="one_liner" type="string" required="true" max-length="80">
      <label>一句话结论</label>
      <example>X 公司开源 Y 推理框架，单卡吞吐提升。</example>
      <guidance>面向高管的一句话，不带技术细节</guidance>
    </field>
    <field key="source_link" type="url"><label>来源</label></field>
  </item>
</template>
"""

DTD_XML_TEMPLATE = """<?xml version="1.0"?>
<!DOCTYPE template [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<template><item><field key="a" type="string"><label>&xxe;</label></field></item></template>
"""


def test_xml_and_json_carriers_normalize_to_equal_canonical_form():
    canonical_xml, xml_errors = parse_generation_template(XML_TEMPLATE, "xml")
    canonical_json, json_errors = parse_generation_template(EXTRA_FIELD_TEMPLATE, "json")
    assert xml_errors == [] and json_errors == []
    assert json.dumps(canonical_xml, ensure_ascii=False, sort_keys=True) == json.dumps(
        canonical_json,
        ensure_ascii=False,
        sort_keys=True,
    )


def test_xml_with_dtd_or_entities_is_rejected(monkeypatch, tmp_path):
    canonical, errors = parse_generation_template(DTD_XML_TEMPLATE, "xml")
    assert canonical is None
    assert any("DTD" in error["error"] for error in errors)

    client, _engine = make_client(monkeypatch, tmp_path, filename="template_dtd.sqlite")
    _login(client)
    response = client.post(
        "/api/report-formats",
        json={
            "workspace_code": "planning_intel",
            "format_code": "evil_xml_v1",
            "name": "XML 模板",
            "generation_template": DTD_XML_TEMPLATE,
            "generation_template_carrier": "xml",
        },
    )
    assert response.status_code == 422


# --- 断言 4：非法模板逐条报错且错误定位到字段 ---


def test_invalid_templates_report_field_level_errors():
    def fields_template(fields):
        return {"item_schema": {"fields": fields}}

    duplicate, errors = parse_generation_template(
        fields_template(
            [
                {"key": "alpha", "type": "string"},
                {"key": "alpha", "type": "text"},
            ],
        ),
    )
    assert duplicate is None
    assert any(error["field"] == "alpha" and "duplicate" in error["error"] for error in errors)

    bad_key, errors = parse_generation_template(fields_template([{"key": "1abc", "type": "string"}]))
    assert bad_key is None
    assert any("key must match" in error["error"] for error in errors)

    bad_type, errors = parse_generation_template(fields_template([{"key": "abc", "type": "script"}]))
    assert bad_type is None
    assert any(error["field"] == "abc" and "type must be one of" in error["error"] for error in errors)

    too_many, errors = parse_generation_template(
        fields_template([{"key": f"field_{index}", "type": "string"} for index in range(25)]),
    )
    assert too_many is None
    assert any("at most 24 fields" in error["error"] for error in errors)

    script_example, errors = parse_generation_template(
        fields_template(
            [{"key": "abc", "type": "string", "example": "<script>alert(1)</script>"}],
        ),
    )
    assert script_example is None
    assert any(error["field"] == "abc" and "example" in error["error"] for error in errors)


# --- 断言 5：validate-template 干跑不写任何表，返回字段划分与 preview ---


def test_validate_template_endpoint_is_dry_run(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, filename="template_validate.sqlite")
    _login(client)
    # 先触达一次 report-formats（内置格式登记完成），再统计行数基线
    assert client.get("/api/report-formats", params={"workspace_code": "planning_intel"}).status_code == 200

    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    with Session() as session:
        formats_before = session.scalar(select(func.count(ReportFormat.id)))
        audits_before = session.scalar(select(func.count(AuditLog.id)))

    response = client.post(
        "/api/report-formats/validate-template",
        json={"workspace_code": "planning_intel", "generation_template": EXTRA_FIELD_TEMPLATE},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["projection_fields"] == ["headline", "source_link"]
    assert body["generated_fields"] == ["one_liner"]
    assert body["normalized_template"]["item_schema"]["fields"][0]["key"] == "headline"
    preview = body["preview_item"]
    assert preview["values"]["headline"], "projection field must be filled from sample base draft"
    assert preview["values"]["one_liner"] == "X 公司开源 Y 推理框架，单卡吞吐提升。"

    invalid = client.post(
        "/api/report-formats/validate-template",
        json={
            "workspace_code": "planning_intel",
            "generation_template": {"item_schema": {"fields": [{"key": "1abc", "type": "string"}]}},
        },
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert invalid.json()["errors"]

    with Session() as session:
        assert session.scalar(select(func.count(ReportFormat.id))) == formats_before
        assert session.scalar(select(func.count(AuditLog.id))) == audits_before


# --- 断言 6：locked / builtin 格式提交 generation_template 一律 400 ---


def test_builtin_formats_reject_generation_template(monkeypatch, tmp_path):
    client, _engine = make_client(monkeypatch, tmp_path, filename="template_builtin.sqlite")
    _login(client)
    formats = client.get("/api/report-formats", params={"workspace_code": "planning_intel"}).json()
    by_code = {fmt["format_code"]: fmt for fmt in formats}
    for code in ("company_sql_v1", "tech_insight_v1"):
        response = client.patch(
            f"/api/report-formats/{by_code[code]['id']}",
            json={"generation_template": json.dumps(PURE_PROJECTION_TEMPLATE, ensure_ascii=False)},
        )
        assert response.status_code == 400, code
        assert "generation_template" in response.json()["detail"]
    # 行为回归：locked 仍只允许启停、builtin 仍可正常改名
    assert (
        client.patch(f"/api/report-formats/{by_code['company_sql_v1']['id']}", json={"enabled": True}).status_code
        == 200
    )
    assert (
        client.patch(f"/api/report-formats/{by_code['tech_insight_v1']['id']}", json={"name": "技术洞察版"}).status_code
        == 200
    )


# --- 断言 7：provider 关闭照常投影 + template_fallback；恢复后 regenerate 补齐 ---


def test_provider_off_projects_with_fallback_then_regenerate_backfills(monkeypatch):
    session, workspace = _pipeline_session(item_total=2)
    result = _run_pipeline(session)  # provider 默认关闭：基稿走规则降级
    report = result.daily_report
    fmt = _register_template_format(session, workspace.code, "exec_brief_v1", EXTRA_FIELD_TEMPLATE)

    rendition = build_daily_rendition(session, report, fmt)
    session.commit()
    adoption_before = [(item.id, item.adoption_status, item.is_headline) for item in report.items]
    for snapshot in rendition.body_json["items"].values():
        assert snapshot["template_fallback"] is True
        assert snapshot["missing_fields"] == ["one_liner"]
        assert snapshot["template_values"]["one_liner"] == ""
        assert snapshot["template_values"]["headline"], "projection must not be blocked"

    # 开启 provider 后 regenerate 补齐 extras；采信与头条不变（投影不变式回归）
    handler = RecordingHandler(_dual_responder)
    _install_fixture_provider(monkeypatch, handler)
    rendition = build_daily_rendition(session, report, fmt)
    session.commit()
    assert len(handler.requests) == len(report.items)
    for snapshot in rendition.body_json["items"].values():
        assert snapshot["template_fallback"] is False
        assert snapshot["template_values"]["one_liner"] == ONE_LINER_TEXT
    assert [(item.id, item.adoption_status, item.is_headline) for item in report.items] == adoption_before


# --- 断言 8：模板 PATCH version+1、旧 extras 过期重生；删除格式不影响采信 ---


def test_template_patch_bumps_version_and_stales_old_extras(monkeypatch, tmp_path):
    client, _engine = make_client(monkeypatch, tmp_path, filename="template_version.sqlite")
    _login(client)
    created = client.post(
        "/api/report-formats",
        json={
            "workspace_code": "planning_intel",
            "format_code": "exec_brief_v1",
            "name": "高管简报",
            "generation_template": EXTRA_FIELD_TEMPLATE,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["generation_template"]["version"] == 1
    assert body["generated_fields"] == ["one_liner"]

    patched = client.patch(
        f"/api/report-formats/{body['id']}",
        json={"generation_template": XML_TEMPLATE, "generation_template_carrier": "xml"},
    )
    assert patched.status_code == 200
    assert patched.json()["generation_template"]["version"] == 2

    # 旧 extras（version 1）按新模板判定过期
    from types import SimpleNamespace

    from app.reports.generation_template import extras_bucket_stale

    fake_fmt = SimpleNamespace(
        format_code="exec_brief_v1",
        generation_template=patched.json()["generation_template"],
    )
    fake_news = SimpleNamespace(
        template_extras_json={
            "exec_brief_v1": {"values": {"one_liner": "旧值"}, "template_version": 1},
        },
    )
    assert extras_bucket_stale(fake_news, fake_fmt) is True

    # 删除格式：204，且不影响其他格式与采信层（renditions 清理由既有逻辑覆盖）
    assert client.delete(f"/api/report-formats/{body['id']}").status_code == 204
    remaining = client.get("/api/report-formats", params={"workspace_code": "planning_intel"}).json()
    assert {fmt["format_code"] for fmt in remaining} >= {"company_sql_v1", "tech_insight_v1"}


# --- 断言 9：report_type=weekly 同机制（extras 经 weekly_report_items.generated_news_id 读） ---


def test_weekly_template_rendition_uses_same_mechanism(monkeypatch):
    handler = RecordingHandler(_dual_responder)
    _install_fixture_provider(monkeypatch, handler)
    session, workspace = _pipeline_session(item_total=2)
    result = _run_pipeline(session)
    report = result.daily_report
    fmt = _register_template_format(session, workspace.code, "exec_brief_v1", EXTRA_FIELD_TEMPLATE)

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

    rendition = build_weekly_rendition(session, weekly, fmt, "规划部情报工作台")
    session.commit()
    assert rendition.report_type == "weekly"
    for snapshot in rendition.body_json["items"].values():
        assert snapshot["template_values"]["one_liner"] == ONE_LINER_TEXT
        assert snapshot["template_fallback"] is False
    markdown = render_markdown(rendition)
    assert "**一句话结论**" in markdown

    # 断言 2 同机制：extras 落在 generated_news 上、基稿不被触碰
    for item in report.items:
        bucket = item.generated_news.template_extras_json["exec_brief_v1"]
        assert bucket["values"]["one_liner"] == ONE_LINER_TEXT
        assert "one_liner" not in json.dumps(item.generated_news.content_json, ensure_ascii=False)


# --- 断言 10：模板任意配置下公司 SQL 导出逐字节不变（负向断言） ---


def _sql_without_generated_at(sql_text: str) -> str:
    return "\n".join(line for line in sql_text.splitlines() if not line.startswith("-- 生成时间"))


def test_company_sql_export_is_byte_identical_with_templates(monkeypatch):
    from app.exports.company_sql import generate_company_sql_for_daily_report
    from tests.test_company_sql_export import _published_report_session

    session, report = _published_report_session()
    ensure_report_formats(session, "planning_intel")
    baseline = _sql_without_generated_at(
        generate_company_sql_for_daily_report(session, report.id).sql_text,
    )

    # 注册模板格式 + 写入 extras + 重建 rendition，再导出：输出必须逐字节一致
    fmt = _register_template_format(session, "planning_intel", "exec_brief_v1", EXTRA_FIELD_TEMPLATE)
    for item in report.items:
        news = item.generated_news
        news.template_extras_json = {
            "exec_brief_v1": {
                "values": {"one_liner": ONE_LINER_TEXT},
                "generated_by": "minimax:test",
                "generated_at": "2026-07-07T12:00:00+08:00",
                "template_version": 1,
            },
        }
    session.flush()
    build_daily_rendition(session, report, fmt)
    session.commit()

    with_template = _sql_without_generated_at(
        generate_company_sql_for_daily_report(session, report.id).sql_text,
    )
    assert with_template == baseline
    assert ONE_LINER_TEXT not in with_template
