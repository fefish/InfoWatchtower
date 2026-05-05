from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.content import DataSource, DedupeGroup, NewsItem, RawItem
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.normalization.news import (
    NewsNormalizationRequest,
    canonicalize_url,
    normalize_title,
    normalize_workspace_raw_items,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_workspace(session, code: str = "planning_intel") -> Workspace:
    workspace = Workspace(
        code=code,
        name="规划部情报工作台",
        description="",
        default_domain_code="ai",
    )
    session.add(workspace)
    session.flush()
    return workspace


def seed_source(
    session,
    workspace: Workspace,
    source_type: str = "rss",
    name: str = "Official RSS",
) -> DataSource:
    source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type=source_type,
        name=name,
        url="https://example.com/feed.xml",
        metadata_json={"primary_category": "official"},
    )
    session.add(
        WorkspaceSourceLink(
            workspace=workspace,
            data_source=source,
            domain_code="ai",
            enabled=True,
        ),
    )
    session.flush()
    return source


def add_raw_item(
    session,
    source: DataSource,
    entry_key: str,
    title: str,
    url: str | None,
    content: str,
    published_at: datetime | None = datetime(2026, 5, 5, 8, tzinfo=UTC),
) -> RawItem:
    raw_item = RawItem(
        data_source=source,
        workspace_code="shared",
        domain_code=source.domain_code,
        visibility_scope=source.visibility_scope,
        sync_policy=source.sync_policy,
        source_type=source.source_type,
        source_name=source.name,
        entry_key=entry_key,
        source_title=title,
        source_url=url,
        raw_content=content,
        fetched_at=datetime(2026, 5, 5, 9, tzinfo=UTC),
        published_at=published_at,
        raw_payload_json={"title": title, "author": "Example Team"},
    )
    session.add(raw_item)
    session.flush()
    return raw_item


def test_canonicalize_url_removes_tracking_query_and_fragment():
    assert (
        canonicalize_url("https://Example.com/news/1/?utm_source=x&b=2&a=1#frag")
        == "https://example.com/news/1?a=1&b=2"
    )


def test_normalize_title_keeps_text_but_removes_punctuation_noise():
    assert normalize_title("  Kimi-K2 发布：AI Infra!  ") == "kimi k2 发布 ai infra"


def test_same_canonical_url_keeps_one_winner_and_raw_lineage():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Official RSS")
    add_raw_item(
        session,
        source,
        "rss:1",
        "Kimi K2 released",
        "https://Example.com/news/1?utm_source=folo#frag",
        "short body",
    )
    add_raw_item(
        session,
        source,
        "rss:2",
        "Kimi K2 released again",
        "https://example.com/news/1",
        "longer useful body with more details",
    )

    result = normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    session.commit()

    assert result.raw_scanned == 2
    assert result.news_created == 2
    assert result.raw_skipped == 0
    assert result.dedupe_groups_updated == 1
    assert session.scalar(select(func.count(RawItem.id))) == 2
    assert session.scalar(select(func.count(NewsItem.id))) == 2

    news_items = session.scalars(select(NewsItem).order_by(NewsItem.created_at)).all()
    winners = [item for item in news_items if item.active]
    losers = [item for item in news_items if not item.active]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].duplicate_of_id == winners[0].id
    assert winners[0].canonical_url == "https://example.com/news/1"
    assert winners[0].raw_item.raw_payload_json["author"] == "Example Team"

    group = session.scalar(select(DedupeGroup))
    assert group is not None
    assert group.workspace_code == "planning_intel"
    assert group.dedupe_key == "url:https://example.com/news/1"
    assert group.item_count == 2
    assert group.winner_news_item_id == winners[0].id


def test_different_urls_with_similar_titles_are_not_merged_in_phase_4():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    add_raw_item(session, source, "rss:1", "Same topic", "https://example.com/a", "Body A")
    add_raw_item(session, source, "rss:2", "Same topic", "https://example.com/b", "Body B")

    result = normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    session.commit()

    assert result.news_created == 2
    assert session.scalar(select(func.count(DedupeGroup.id))) == 2
    assert session.scalar(select(func.count(NewsItem.id)).where(NewsItem.active.is_(True))) == 2


def test_title_date_fallback_only_when_url_is_missing():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    add_raw_item(session, source, "manual:1", "No URL Topic!", None, "Body A")
    add_raw_item(session, source, "manual:2", "No URL Topic", None, "Body B")

    result = normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    session.commit()

    assert result.news_created == 2
    assert session.scalar(select(func.count(DedupeGroup.id))) == 1
    group = session.scalar(select(DedupeGroup))
    assert group is not None
    assert group.dedupe_key == "title:no url topic|date:2026-05-05"
    assert group.item_count == 2


def test_existing_news_is_removed_from_candidate_pool_when_raw_becomes_invalid():
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace)
    raw_item = add_raw_item(session, source, "rss:1", "Valid item", "https://example.com/a", "Body")

    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
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
    news_item = session.scalar(select(NewsItem))
    assert news_item is not None
    assert news_item.active is False
    assert news_item.duplicate_of_id is None
    assert news_item.normalization_status == "skipped"
    group = session.scalar(select(DedupeGroup))
    assert group is not None
    assert group.item_count == 0
    assert group.status == "empty"


def test_same_raw_can_normalize_independently_per_workspace():
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
    session.commit()

    assert session.scalar(select(func.count(NewsItem.id))) == 2
    assert session.scalar(select(func.count(DedupeGroup.id))) == 2
    assert {
        item.workspace_code
        for item in session.scalars(select(NewsItem).where(NewsItem.raw_item_id.is_not(None))).all()
    } == {"planning_intel", "ai_tools"}
