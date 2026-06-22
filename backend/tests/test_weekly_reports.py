from app.models.reports import WeeklyReportItem
from app.reports.weekly import WeeklyReportDraftRequest, create_weekly_report_draft
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

    published = client.post(f"/api/weekly-reports/{payload['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    listed = client.get("/api/weekly-reports?workspace_code=planning_intel")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == payload["id"]
