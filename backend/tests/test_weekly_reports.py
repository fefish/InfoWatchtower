import pytest

from app.models.reports import WeeklyReportItem
from app.reports.weekly import (
    PublishedWeeklyReportError,
    WeeklyReportDraftRequest,
    create_weekly_report_draft,
)
from tests.test_company_sql_export import _published_report_session
from tests.test_recommendations import make_client


def test_weekly_report_draft_uses_published_daily_adopted_items():
    session, _ = _published_report_session()

    report = create_weekly_report_draft(
        session,
        WeeklyReportDraftRequest(
            workspace_code="planning_intel",
            week_key="2026-W18",
        ),
    )
    session.commit()

    assert report.week_key == "2026-W18"
    assert report.status == "draft"
    assert "本周候选 1 条" in report.summary
    assert "关键亮点" in report.summary
    assert len(report.items) == 1
    item = report.items[0]
    assert item.adoption_status == 1
    assert item.daily_report_item_id is not None
    assert item.generated_news_id is not None

    regenerated = create_weekly_report_draft(
        session,
        WeeklyReportDraftRequest(
            workspace_code="planning_intel",
            week_key="2026-W18",
        ),
    )
    session.commit()

    assert regenerated.id == report.id
    assert session.query(WeeklyReportItem).count() == 1


def test_weekly_rebuild_preserves_adopted_and_edited_items():
    session, _ = _published_report_session()
    request = WeeklyReportDraftRequest(workspace_code="planning_intel", week_key="2026-W18")
    report = create_weekly_report_draft(session, request)
    item = report.items[0]
    item.adoption_status = 2
    item.editor_title = "编辑后的周报标题"
    item.editor_content_json = {"takeaway": "编辑后的结论"}
    item_id = item.id
    session.commit()

    rebuilt = create_weekly_report_draft(session, request)
    session.commit()

    assert rebuilt.id == report.id
    assert session.query(WeeklyReportItem).count() == 1
    item_after = session.get(WeeklyReportItem, item_id)
    assert item_after is not None
    assert item_after.adoption_status == 2
    assert item_after.editor_title == "编辑后的周报标题"
    assert item_after.editor_content_json == {"takeaway": "编辑后的结论"}
    assert "本周采信 1 条" in rebuilt.summary


def test_weekly_rebuild_removes_unedited_item_when_candidate_gone():
    session, daily_report = _published_report_session()
    request = WeeklyReportDraftRequest(workspace_code="planning_intel", week_key="2026-W18")
    report = create_weekly_report_draft(session, request)
    assert len(report.items) == 1
    daily_report.items[0].adoption_status = 0
    session.commit()

    rebuilt = create_weekly_report_draft(session, request)
    session.commit()

    assert rebuilt.id == report.id
    assert session.query(WeeklyReportItem).count() == 0


def test_weekly_rebuild_keeps_edited_item_even_when_candidate_gone():
    session, daily_report = _published_report_session()
    request = WeeklyReportDraftRequest(workspace_code="planning_intel", week_key="2026-W18")
    report = create_weekly_report_draft(session, request)
    item = report.items[0]
    item.adoption_status = 2
    item.editor_title = "编辑后保留的周报条目"
    item_id = item.id
    daily_report.items[0].adoption_status = 0
    session.commit()

    rebuilt = create_weekly_report_draft(session, request)
    session.commit()

    assert rebuilt.id == report.id
    assert session.query(WeeklyReportItem).count() == 1
    item_after = session.get(WeeklyReportItem, item_id)
    assert item_after is not None
    assert item_after.editor_title == "编辑后保留的周报条目"


def test_published_weekly_report_rebuild_is_still_rejected():
    session, _ = _published_report_session()
    request = WeeklyReportDraftRequest(workspace_code="planning_intel", week_key="2026-W18")
    report = create_weekly_report_draft(session, request)
    report.status = "published"
    session.commit()

    with pytest.raises(PublishedWeeklyReportError):
        create_weekly_report_draft(session, request)


def test_weekly_report_api_creates_edits_and_publishes(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    daily = client.post(
        "/api/recommendation/runs",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "limit": 15,
            "source_daily_limit": 2,
            "create_daily_draft": True,
        },
    )
    assert daily.status_code == 200
    daily_report_id = daily.json()["daily_report_id"]
    assert client.post(f"/api/daily-reports/{daily_report_id}/publish").status_code == 200

    created = client.post(
        "/api/weekly-reports",
        json={
            "workspace_code": "planning_intel",
            "week_key": "2026-W19",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["week_key"] == "2026-W19"
    assert payload["status"] == "draft"
    assert len(payload["items"]) == 1
    weekly_item_id = payload["items"][0]["id"]
    assert payload["items"][0]["adoption_status"] == 1
    assert payload["items"][0]["daily_day_key"] == "2026-05-05"

    patched = client.patch(
        f"/api/weekly-report-items/{weekly_item_id}",
        json={
            "adoption_status": 2,
            "editor_title": "编辑后的周报标题",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["adoption_status"] == 2
    assert patched.json()["editor_title"] == "编辑后的周报标题"

    detail = client.get(f"/api/weekly-reports/{payload['id']}")
    assert detail.status_code == 200
    assert "本周采信 1 条" in detail.json()["summary"]
    assert "编辑后的周报标题" in detail.json()["summary"]

    published = client.post(f"/api/weekly-reports/{payload['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    listed = client.get("/api/weekly-reports?workspace_code=planning_intel")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == payload["id"]
