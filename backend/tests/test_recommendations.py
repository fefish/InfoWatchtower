from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.content import GeneratedNews, RawItem, RecommendationItem
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.service import RecommendationRunRequest, run_daily_recommendation
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
    assert session.scalar(select(func.count(GeneratedNews.id))) == 2
    assert session.scalar(select(func.count(DailyReportItem.id))) == 2

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
                source_title="API recommendation item",
                source_url="https://example.com/api-rec",
                raw_content="API recommendation body.",
                fetched_at=datetime(2026, 5, 5, 9, tzinfo=UTC),
                published_at=datetime(2026, 5, 5, 8, tzinfo=UTC),
                raw_payload_json={"title": "API recommendation item"},
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
