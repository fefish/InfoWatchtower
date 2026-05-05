from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Comment,
    DailyReport,
    DailyReportItem,
    DataSource,
    DedupeGroup,
    DedupeGroupItem,
    GeneratedNews,
    NewsItem,
    RawItem,
    RecommendationItem,
    RecommendationRun,
    User,
)


EXPECTED_STAGE1_TABLES = {
    "audit_logs",
    "comments",
    "daily_report_items",
    "daily_reports",
    "data_sources",
    "dedupe_group_items",
    "dedupe_groups",
    "editorial_actions",
    "export_job_items",
    "export_jobs",
    "generated_news",
    "insights",
    "news_items",
    "permissions",
    "ratings",
    "raw_items",
    "reactions",
    "recommendation_items",
    "recommendation_runs",
    "requirement_source_links",
    "requirements",
    "role_permissions",
    "roles",
    "strategic_implications",
    "sync_conflicts",
    "sync_inbox",
    "sync_outbox",
    "sync_runs",
    "topic_tasks",
    "user_roles",
    "users",
    "weekly_report_items",
    "weekly_reports",
}


def make_session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_daily_report_item(session):
    fetched_at = datetime(2026, 5, 5, 8, 30, tzinfo=timezone.utc)
    source = DataSource(
        source_type="rss",
        name="Example RSS",
        url="https://example.com/feed.xml",
        fetch_config={"parser": "rss"},
    )
    raw_item = RawItem(
        data_source=source,
        source_type="rss",
        source_name="Example RSS",
        entry_key="rss:item:001",
        source_title="Original source title",
        source_url="https://example.com/news/001",
        raw_content="<item><title>Original source title</title></item>",
        raw_payload_json={
            "id": "001",
            "title": "Original source title",
            "source_extra_field": "kept for traceability",
        },
        fetched_at=fetched_at,
    )
    news_item = NewsItem(
        raw_item=raw_item,
        data_source=source,
        source_type="rss",
        source_name="Example RSS",
        source_url="https://example.com/news/001",
        canonical_url="https://example.com/news/001",
        source_title="Original source title",
        normalized_title="Normalized title",
        summary="Normalized summary",
        content="Normalized content",
        published_at=fetched_at,
        focus_id=1,
        dedupe_key="normalized-title",
    )
    dedupe_group = DedupeGroup(
        dedupe_key="normalized-title",
        item_count=1,
        winner_news_item=news_item,
    )
    dedupe_group_item = DedupeGroupItem(
        dedupe_group=dedupe_group,
        news_item=news_item,
        is_winner=True,
        rank_score=0.98,
    )
    recommendation_run = RecommendationRun(run_key="2026-05-05:daily")
    recommendation_item = RecommendationItem(
        run=recommendation_run,
        dedupe_group=dedupe_group,
        dedupe_group_item=dedupe_group_item,
        news_item=news_item,
        rank=1,
        quality_score=0.92,
        topic_score=0.88,
        freshness_score=0.77,
        feedback_score=0.31,
        diversity_score=0.64,
        source_score=0.83,
        heat_score=0.72,
        final_score=0.86,
        selected=True,
        recommendation_reason="high quality and fresh",
    )
    generated_news = GeneratedNews(
        recommendation_item=recommendation_item,
        news_item=news_item,
        category="基础竞争力",
        title="Generated daily title",
        summary="Generated daily summary",
        key_points="point one\npoint two",
        content_json={"body": "Generated article body"},
        source_url="https://example.com/news/001",
        generation_status="ready",
    )
    daily_report = DailyReport(
        day_key="2026-05-05",
        title="2026-05-05 Daily",
        summary="Daily summary",
    )
    daily_report_item = DailyReportItem(
        daily_report=daily_report,
        generated_news=generated_news,
        adoption_status=1,
        sort_order=1,
    )
    session.add(daily_report_item)
    session.commit()
    return daily_report_item.id


def test_stage1_metadata_contains_core_tables():
    assert EXPECTED_STAGE1_TABLES.issubset(Base.metadata.tables.keys())


def test_daily_report_item_keeps_lineage_back_to_raw_payload_after_edit():
    session = make_session()
    daily_report_item_id = seed_daily_report_item(session)

    item = session.scalar(select(DailyReportItem).where(DailyReportItem.id == daily_report_item_id))
    assert item is not None

    raw_payload = (
        item.generated_news.recommendation_item.dedupe_group_item.news_item.raw_item.raw_payload_json
    )
    assert raw_payload["title"] == "Original source title"
    assert raw_payload["source_extra_field"] == "kept for traceability"

    item.editor_title = "Editor polished title"
    item.editor_summary = "Editor polished summary"
    session.commit()
    session.refresh(item)

    assert item.editor_title == "Editor polished title"
    assert item.generated_news.title == "Generated daily title"
    assert (
        item.generated_news.recommendation_item.news_item.raw_item.raw_payload_json["title"]
        == "Original source title"
    )


def test_comments_support_nested_replies_on_daily_report_items():
    session = make_session()
    daily_report_item_id = seed_daily_report_item(session)
    item = session.get(DailyReportItem, daily_report_item_id)
    user = User(
        username="feiyu",
        display_name="Feiyu",
        external_provider="local",
        external_id="feiyu",
        employee_no="001",
    )
    root = Comment(user=user, daily_report_item=item, body="This should enter the weekly report.")
    reply = Comment(
        user=user,
        daily_report_item=item,
        parent=root,
        root=root,
        body="Agree, and add a hardware angle.",
    )
    session.add_all([root, reply])
    session.commit()

    loaded_root = session.scalar(select(Comment).where(Comment.id == root.id))
    assert loaded_root is not None
    assert loaded_root.replies[0].body == "Agree, and add a hardware angle."
    assert loaded_root.replies[0].root_id == loaded_root.id
