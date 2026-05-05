from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.content import DataSource, RawItem
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
