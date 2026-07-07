"""任务 C：每日自动发布 + 发布后修订 + viewer 阅读边界。

覆盖：
- 每日流水线出稿后按工作台 report_policy.auto_publish_daily（默认 true）自动发布：
  actor=system、audit action=daily_report.auto_publish、renditions 照常投影。
- 发布后修订：published 日报报告层字段（采信状态/头条/editor 覆盖/标题摘要）
  允许 workspace admin+ 修订，写 post_publish_revision 编辑审计并重投影 renditions；
  member/viewer 403；published 删除仍禁止；regenerate-generated-news 仍 409。
- 工作台 report-policy 端点与 sections min_role（viewer 阅读分区）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.adapters.base import AdapterRegistry
from app.main import create_app
from app.models.feedback import AuditLog, EditorialAction
from app.models.reports import DailyReport, ReportRendition
from app.pipeline.daily import DailyPipelineRequest, run_daily_pipeline
from tests.test_account_lifecycle import _create_local_user, _create_report_bundle, _login
from tests.test_auth import make_client
from tests.test_daily_pipeline import FakeRssAdapter, make_session
from tests.test_news_normalization import seed_source, seed_workspace


def _pipeline_session():
    session = make_session()
    workspace = seed_workspace(session)
    seed_source(session, workspace, name="Example RSS")
    registry = AdapterRegistry()
    registry.register(FakeRssAdapter())
    return session, workspace, registry


def _login_as(username: str, password: str = "password-123") -> TestClient:
    client = TestClient(create_app())
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    return client


def _pipeline_request(**overrides) -> DailyPipelineRequest:
    return DailyPipelineRequest(
        workspace_code="planning_intel",
        day_key="2026-05-05",
        source_types=["rss"],
        **overrides,
    )


@pytest.mark.asyncio
async def test_daily_pipeline_auto_publishes_draft_and_projects_renditions():
    session, _, registry = _pipeline_session()

    result = await run_daily_pipeline(session, _pipeline_request(), registry=registry)
    session.commit()

    report = result.recommendation.daily_report
    assert report is not None
    assert result.auto_published is True
    assert report.status == "published"
    assert report.published_at is not None

    audit = session.scalar(select(AuditLog).where(AuditLog.action == "daily_report.auto_publish"))
    assert audit is not None
    assert audit.user_id is None, "auto publish actor must be system (no user)"
    assert audit.detail_json["actor"] == "system"
    assert audit.detail_json["workspace_code"] == "planning_intel"

    rendition_codes = {
        rendition.format_code
        for rendition in session.scalars(
            select(ReportRendition).where(
                ReportRendition.report_type == "daily",
                ReportRendition.report_id == report.id,
            ),
        ).all()
    }
    assert rendition_codes >= {"company_sql_v1", "tech_insight_v1"}


@pytest.mark.asyncio
async def test_daily_pipeline_respects_auto_publish_disabled_policy():
    session, workspace, registry = _pipeline_session()
    workspace.config_json = {
        **(workspace.config_json or {}),
        "report_policy": {"auto_publish_daily": False},
    }
    session.flush()

    result = await run_daily_pipeline(session, _pipeline_request(), registry=registry)
    session.commit()

    report = result.recommendation.daily_report
    assert report is not None
    assert result.auto_published is False
    assert report.status == "draft"
    auto_publish_audit = session.scalar(
        select(AuditLog).where(AuditLog.action == "daily_report.auto_publish"),
    )
    assert auto_publish_audit is None


@pytest.mark.asyncio
async def test_daily_pipeline_request_override_keeps_draft():
    # 手动触发（如生成日报草稿按钮）可显式传 False，即便工作台策略是自动发布。
    session, _, registry = _pipeline_session()

    result = await run_daily_pipeline(
        session,
        _pipeline_request(auto_publish_daily=False),
        registry=registry,
    )
    session.commit()

    assert result.auto_published is False
    assert result.recommendation.daily_report.status == "draft"


def test_post_publish_revision_roles_audit_and_rendition_rerender(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert _login(admin).status_code == 200
    bundle = _create_report_bundle(engine)
    report_id = bundle["daily_report_id"]
    item_id = bundle["daily_item_id"]
    _create_local_user(engine, "viewer", "password-123", workspace_role="viewer")
    _create_local_user(engine, "member", "password-123", workspace_role="member")
    _create_local_user(engine, "wsadmin", "password-123", workspace_role="admin")

    published = admin.post(f"/api/daily-reports/{report_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    # 发布即投影：viewer 无需 member 权限的 regenerate 也能读到成稿。
    Session = sessionmaker(bind=engine)
    with Session() as db:
        renditions = db.scalars(
            select(ReportRendition).where(
                ReportRendition.report_type == "daily",
                ReportRendition.report_id == report_id,
            ),
        ).all()
        rendition_codes = {rendition.format_code for rendition in renditions}
        assert rendition_codes >= {"company_sql_v1", "tech_insight_v1"}

    viewer = _login_as("viewer")
    viewer_item = viewer.patch(f"/api/daily-report-items/{item_id}", json={"editor_title": "Nope"})
    assert viewer_item.status_code == 403
    viewer_report = viewer.patch(f"/api/daily-reports/{report_id}", json={"title": "Nope"})
    assert viewer_report.status_code == 403

    member = _login_as("member")
    # published 后 member 不再能改（draft 阶段的 member 编辑由既有用例守护）。
    member_item = member.patch(
        f"/api/daily-report-items/{item_id}",
        json={"editor_title": "Blocked"},
    )
    assert member_item.status_code == 403
    member_report = member.patch(f"/api/daily-reports/{report_id}", json={"title": "Blocked"})
    assert member_report.status_code == 403

    wsadmin = _login_as("wsadmin")
    revised_item = wsadmin.patch(
        f"/api/daily-report-items/{item_id}",
        json={"editor_title": "发布后修订标题", "is_headline": True},
    )
    assert revised_item.status_code == 200
    assert revised_item.json()["editor_title"] == "发布后修订标题"

    revised_report = wsadmin.patch(
        f"/api/daily-reports/{report_id}",
        json={"title": "发布后修订日报", "summary": "修订后的摘要"},
    )
    assert revised_report.status_code == 200
    assert revised_report.json()["title"] == "发布后修订日报"
    assert revised_report.json()["status"] == "published"

    with Session() as db:
        item_actions = db.scalars(
            select(EditorialAction).where(
                EditorialAction.object_type == "daily_report_item",
                EditorialAction.object_id == item_id,
                EditorialAction.action_type == "post_publish_revision",
            ),
        ).all()
        assert item_actions, "post publish item revision must write editorial audit"
        assert item_actions[-1].after_json["editor_title"] == "发布后修订标题"
        report_actions = db.scalars(
            select(EditorialAction).where(
                EditorialAction.object_type == "daily_report",
                EditorialAction.object_id == report_id,
                EditorialAction.action_type == "post_publish_revision",
            ),
        ).all()
        assert report_actions, "post publish report revision must write editorial audit"

        # renditions 自动重渲染：快照标题跟随 editor 覆盖。
        rendition = db.scalar(
            select(ReportRendition).where(
                ReportRendition.report_type == "daily",
                ReportRendition.report_id == report_id,
                ReportRendition.format_code == "tech_insight_v1",
            ),
        )
        snapshots = (rendition.body_json.get("items") or {}).values()
        snapshot_titles = {snapshot["title"] for snapshot in snapshots}
        assert "发布后修订标题" in snapshot_titles

        report_row = db.get(DailyReport, report_id)
        assert report_row.title == "发布后修订日报"
        assert report_row.status == "published"

    # 底线不动摇：published 不可删除（无删除端点）、raw/generated 不可动。
    assert wsadmin.delete(f"/api/daily-reports/{report_id}").status_code == 405
    regenerate = wsadmin.post(f"/api/daily-reports/{report_id}/regenerate-generated-news", json={})
    assert regenerate.status_code == 409


def test_workspace_report_policy_defaults_and_patch(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert _login(admin).status_code == 200
    _create_local_user(engine, "viewer", "password-123", workspace_role="viewer")
    _create_local_user(engine, "wsadmin", "password-123", workspace_role="admin")

    viewer = _login_as("viewer")
    default_policy = viewer.get("/api/workspaces/planning_intel/report-policy")
    assert default_policy.status_code == 200
    assert default_policy.json() == {"workspace_code": "planning_intel", "auto_publish_daily": True}
    assert (
        viewer.patch(
            "/api/workspaces/planning_intel/report-policy",
            json={"auto_publish_daily": False},
        ).status_code
        == 403
    )

    wsadmin = _login_as("wsadmin")
    updated = wsadmin.patch(
        "/api/workspaces/planning_intel/report-policy",
        json={"auto_publish_daily": False},
    )
    assert updated.status_code == 200
    assert updated.json()["auto_publish_daily"] is False
    refreshed = viewer.get("/api/workspaces/planning_intel/report-policy").json()
    assert refreshed["auto_publish_daily"] is False

    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "workspace.report_policy.update"),
        )
        assert audit is not None
        assert audit.detail_json["after"] == {"auto_publish_daily": False}


def test_workspace_sections_expose_min_role_for_viewer_navigation(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    _create_local_user(engine, "viewer", "password-123", workspace_role="viewer")

    viewer = _login_as("viewer")
    sections = viewer.get("/api/workspaces/planning_intel/sections")
    assert sections.status_code == 200
    min_roles = {section["section_key"]: section["min_role"] for section in sections.json()}

    # 阅读分区对 viewer 可见。
    reading_sections = (
        "daily_reports",
        "weekly_reports",
        "historical_reports",
        "entity_milestones",
    )
    for section_key in reading_sections:
        assert min_roles[section_key] == "viewer", section_key
    # 管理分区默认 member 起（前端导航按 min_role 过滤后 viewer 看不到）。
    for section_key in (
        "dashboard",
        "source_management",
        "ingestion_coverage",
        "candidate_pool",
        "sync",
        "exports",
        "users",
        "audit_logs",
    ):
        assert min_roles[section_key] == "member", section_key
