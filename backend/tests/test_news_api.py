from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.content import DataSource, GeneratedNews, RawItem
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace, WorkspaceSourceLink


def make_client(monkeypatch, tmp_path):
    database_path = tmp_path / "news_api.sqlite"
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
        settings = get_settings()
        ensure_auth_seed(session, settings)
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        assert workspace is not None
        source = DataSource(
            workspace_code="shared",
            domain_code="ai",
            source_type="rss",
            name="API RSS",
            url="https://example.com/feed.xml",
        )
        session.add(
            WorkspaceSourceLink(
                workspace=workspace,
                data_source=source,
                domain_code="ai",
                enabled=True,
            ),
        )
        for index, url in enumerate(
            [
                "https://example.com/news/1?utm_source=folo",
                "https://example.com/news/1",
            ],
            start=1,
        ):
            session.add(
                RawItem(
                    data_source=source,
                    workspace_code="shared",
                    domain_code="ai",
                    source_type="rss",
                    source_name="API RSS",
                    entry_key=f"entry:{index}",
                    source_title=f"API Item {index}",
                    source_url=url,
                    raw_content=f"Body {index}",
                    fetched_at=datetime(2026, 5, 5, 9, tzinfo=UTC),
                    published_at=datetime(2026, 5, 5, 8, tzinfo=UTC),
                    raw_payload_json={"title": f"API Item {index}"},
                ),
            )
        session.commit()

    return TestClient(create_app())


def test_super_admin_can_normalize_and_list_news(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    normalized = client.post(
        "/api/news-items/normalize",
        json={"workspace_code": "planning_intel", "source_types": ["rss"]},
    )
    assert normalized.status_code == 200
    payload = normalized.json()
    assert payload["raw_scanned"] == 2
    assert payload["news_created"] == 2
    assert payload["dedupe_groups_updated"] == 1
    assert payload["winners"] == 1
    assert payload["losers"] == 1

    winners = client.get(
        "/api/news-items",
        params={"workspace_code": "planning_intel", "active": True},
    )
    assert winners.status_code == 200
    winner_payload = winners.json()
    assert len(winner_payload) == 1
    assert winner_payload[0]["dedupe_key"] == "url:https://example.com/news/1"
    assert winner_payload[0]["raw_item_id"]

    groups = client.get("/api/dedupe-groups", params={"workspace_code": "planning_intel"})
    assert groups.status_code == 200
    group_payload = groups.json()
    assert len(group_payload) == 1
    assert group_payload[0]["item_count"] == 2
    assert sum(1 for item in group_payload[0]["items"] if item["is_winner"]) == 1
    lineage_nodes = group_payload[0]["lineage"]["nodes"]
    lineage_by_type = {node["object_type"]: node for node in lineage_nodes}
    assert {"data_source", "raw_item", "news_item", "dedupe_group"}.issubset(lineage_by_type)
    assert lineage_by_type["data_source"]["target_path"].startswith("/sources/")
    assert "数据源" in lineage_by_type["data_source"]["review_note"]
    assert lineage_by_type["raw_item"]["target_path"].startswith("/news?raw_item_id=")
    assert "完整入库" in lineage_by_type["raw_item"]["review_note"]
    assert lineage_by_type["raw_item"]["metadata"]["payload_keys"] == ["title"]
    assert "raw_payload_json" not in lineage_by_type["raw_item"]["metadata"]
    assert lineage_by_type["news_item"]["target_path"].startswith("/news?news_item_id=")
    assert lineage_by_type["dedupe_group"]["target_path"] == f"/news?dedupe_group_id={group_payload[0]['id']}"

    coverage = client.get(
        "/api/ingestion/coverage",
        params={"workspace_code": "planning_intel", "day_key": "2026-05-05"},
    )
    assert coverage.status_code == 200
    coverage_payload = coverage.json()
    assert coverage_payload["funnel"]["raw_in_target"] == 2
    assert coverage_payload["funnel"]["news_items"] == 2
    assert coverage_payload["funnel"]["dedupe_winners"] == 1


def test_candidate_pool_bulk_adopt_adds_recommended_winners_to_daily_report(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    normalized = client.post(
        "/api/news-items/normalize",
        json={"workspace_code": "planning_intel", "source_types": ["rss"]},
    )
    assert normalized.status_code == 200
    created_run = client.post(
        "/api/recommendation/runs",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "limit": 5,
            "source_daily_limit": 2,
            "create_daily_draft": False,
        },
    )
    assert created_run.status_code == 200
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
    payload = adopted.json()
    assert payload["created_total"] == 1
    assert payload["updated_total"] == 0
    assert payload["skipped_total"] == 0
    assert payload["report"]["day_key"] == "2026-05-05"
    assert len(payload["report"]["items"]) == 1
    assert payload["report"]["items"][0]["adoption_status"] == 2

    adopted_again = client.post(
        "/api/daily-reports/bulk-adopt-from-candidates",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "dedupe_group_ids": [group_id],
        },
    )
    assert adopted_again.status_code == 200
    assert adopted_again.json()["created_total"] == 0

    database_url = get_settings().database_url
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert len(session.scalars(select(DailyReport)).all()) == 1
        assert len(session.scalars(select(DailyReportItem)).all()) == 1


def test_candidate_pool_bulk_adopt_skips_candidates_without_recommendation(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    normalized = client.post(
        "/api/news-items/normalize",
        json={"workspace_code": "planning_intel", "source_types": ["rss"]},
    )
    assert normalized.status_code == 200
    groups = client.get("/api/dedupe-groups", params={"workspace_code": "planning_intel"})
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
    payload = adopted.json()
    assert payload["created_total"] == 0
    assert payload["skipped_total"] == 1
    assert payload["skipped_items"][0]["reason"] == "missing_recommendation"


def test_candidate_pool_filters_sort_and_bulk_reject_candidates(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    normalized = client.post(
        "/api/news-items/normalize",
        json={"workspace_code": "planning_intel", "source_types": ["rss"]},
    )
    assert normalized.status_code == 200
    created_run = client.post(
        "/api/recommendation/runs",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "limit": 0,
            "source_daily_limit": 2,
            "create_daily_draft": False,
        },
    )
    assert created_run.status_code == 200
    assert created_run.json()["generated_total"] == 0

    groups = client.get(
        "/api/dedupe-groups",
        params={
            "workspace_code": "planning_intel",
            "q": "API",
            "recommendation_status": "recommended",
            "daily_status": "not_in_report",
            "source_type": "rss",
            "sort": "score_desc",
        },
    )
    assert groups.status_code == 200
    group_payload = groups.json()
    assert len(group_payload) == 1
    assert group_payload[0]["winner_published_at"]
    assert group_payload[0]["winner_source_type"] == "rss"
    assert group_payload[0]["items"][0]["source_type"] == "rss"
    assert group_payload[0]["recommendation"]["selected"] is False
    assert any(node["object_type"] == "recommendation_item" for node in group_payload[0]["lineage"]["nodes"])
    admission_level = group_payload[0]["recommendation"]["admission_level"]
    group_id = group_payload[0]["id"]

    invite = client.post(
        "/api/auth/invites",
        json={
            "role_code": "viewer",
            "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
        },
    )
    assert invite.status_code == 200
    watcher = TestClient(create_app())
    accepted = watcher.post(
        f"/api/auth/invites/{invite.json()['code']}/accept",
        json={"username": "candidate-watcher", "display_name": "Candidate Watcher", "password": "watch-password"},
    )
    assert accepted.status_code == 200
    watch_response = watcher.patch(
        "/api/object-watchers",
        json={"object_type": "dedupe_group", "object_id": group_id, "watching": True},
    )
    assert watch_response.status_code == 200
    assert watch_response.json()["watching"] is True

    admission_filtered = client.get(
        "/api/dedupe-groups",
        params={
            "workspace_code": "planning_intel",
            "admission_level": admission_level,
            "sort": "published_desc",
        },
    )
    assert admission_filtered.status_code == 200
    assert [item["id"] for item in admission_filtered.json()] == [group_id]

    rejected = client.post(
        "/api/daily-reports/bulk-reject-from-candidates",
        json={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "dedupe_group_ids": [group_id],
        },
    )
    assert rejected.status_code == 200
    rejected_payload = rejected.json()
    assert rejected_payload["created_total"] == 1
    assert rejected_payload["updated_total"] == 0
    assert rejected_payload["skipped_total"] == 0
    assert rejected_payload["report"]["items"][0]["adoption_status"] == 0
    assert rejected_payload["report"]["items"][0]["generated_news"]["generation_status"] == "rejected_candidate"

    rejected_groups = client.get(
        "/api/dedupe-groups",
        params={
            "workspace_code": "planning_intel",
            "daily_status": "rejected",
        },
    )
    assert rejected_groups.status_code == 200
    assert rejected_groups.json()[0]["daily_report"]["adoption_status"] == 0
    rejected_lineage_types = [node["object_type"] for node in rejected_groups.json()[0]["lineage"]["nodes"]]
    assert "generated_news" in rejected_lineage_types
    assert "daily_report_item" in rejected_lineage_types

    notifications = watcher.get("/api/notifications", params={"status": "unread"})
    assert notifications.status_code == 200
    notification_payload = notifications.json()
    assert len(notification_payload) == 1
    assert notification_payload[0]["activity_event"]["event_type"] == "dedupe_group.adoption_changed"
    assert notification_payload[0]["activity_event"]["object_id"] == group_id
    assert notification_payload[0]["target_label"] == "查看候选"
    assert notification_payload[0]["target_path"] == f"/news?dedupe_group_id={group_id}"

    database_url = get_settings().database_url
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        generated = session.scalar(select(GeneratedNews))
        assert generated is not None
        assert generated.generated_by == "bulk_reject_placeholder_v1"
        assert generated.generation_status == "rejected_candidate"


def test_candidate_pool_default_sort_is_score_desc_with_stable_ties():
    """候选池默认排序契约（recommendation_ranking.json ordering_consistency
    candidate_pool）：GET /api/dedupe-groups 不带 sort 时默认 score_desc
    （final_score 降序，并列按 news_item_id 升序，未推荐候选排在最后）。"""
    import inspect

    from app.api.routes.news import _sort_dedupe_group_reads, list_dedupe_groups
    from app.schemas.news import DedupeGroupRead, DedupeGroupRecommendationRead

    sort_query = inspect.signature(list_dedupe_groups).parameters["sort"].default
    assert sort_query.default == "score_desc"

    def group(group_id: str, news_item_id: str, final_score: float | None) -> DedupeGroupRead:
        recommendation = (
            DedupeGroupRecommendationRead.model_construct(final_score=final_score)
            if final_score is not None
            else None
        )
        return DedupeGroupRead.model_construct(
            id=group_id,
            winner_news_item_id=news_item_id,
            recommendation=recommendation,
        )

    shuffled = [
        group("group-tie-b", "news-b", 80.0),
        group("group-unscored", "news-z", None),
        group("group-top", "news-t", 91.5),
        group("group-tie-a", "news-a", 80.0),
    ]
    ordered = _sort_dedupe_group_reads(shuffled, "score_desc")
    assert [record.id for record in ordered] == [
        "group-top",
        "group-tie-a",
        "group-tie-b",
        "group-unscored",
    ]
