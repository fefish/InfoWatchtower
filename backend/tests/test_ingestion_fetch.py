from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.adapters.base import AdapterRegistry, RawItemInput
from app.core.database import Base
from app.ingestion.fetch import (
    MAX_RAW_ENTRY_KEY_LENGTH,
    fetch_source_to_raw_items,
    normalize_raw_entry_key,
)
from app.models.content import DataSource, RawItem


class FakeRssAdapter:
    source_type = "rss"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        return [
            RawItemInput(
                entry_key="rss:1",
                source_title="First title",
                source_url="https://example.com/1",
                raw_content="First body",
                published_at=datetime(2026, 5, 5, 8, tzinfo=UTC),
                raw_payload_json={"title": "First title", "source": data_source.name},
            ),
            RawItemInput(
                entry_key="rss:2",
                source_title="Second title",
                source_url="https://example.com/2",
                raw_content="Second body",
                published_at=None,
                raw_payload_json={"title": "Second title", "source": data_source.name},
            ),
        ]


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.mark.asyncio
async def test_fetch_source_persists_raw_items_idempotently():
    session = make_session()
    data_source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type="rss",
        name="Example RSS",
        url="https://example.com/rss.xml",
    )
    session.add(data_source)
    session.commit()

    registry = AdapterRegistry()
    registry.register(FakeRssAdapter())
    fetched_at = datetime(2026, 5, 5, 9, tzinfo=UTC)

    first = await fetch_source_to_raw_items(session, data_source.id, registry, fetched_at)
    session.commit()

    assert first.fetched == 2
    assert first.created == 2
    assert first.updated == 0
    assert session.scalar(select(func.count(RawItem.id))) == 2

    raw_item = session.scalar(select(RawItem).where(RawItem.entry_key == "rss:1"))
    assert raw_item is not None
    assert raw_item.data_source_id == data_source.id
    assert raw_item.workspace_code == "shared"
    assert raw_item.domain_code == "ai"
    assert raw_item.source_title == "First title"
    assert raw_item.raw_payload_json["source"] == "Example RSS"

    second = await fetch_source_to_raw_items(session, data_source.id, registry, fetched_at)
    session.commit()

    assert second.fetched == 2
    assert second.created == 0
    assert second.updated == 2
    assert session.scalar(select(func.count(RawItem.id))) == 2

    session.refresh(data_source)
    assert data_source.last_success_at == fetched_at.replace(tzinfo=None)
    assert data_source.last_error == ""


def test_raw_entry_key_is_deterministically_shortened_for_long_feed_ids():
    long_key = "https://example.com/feed?" + ("q=" + "x" * 400)

    normalized = normalize_raw_entry_key(long_key)

    assert len(normalized) == MAX_RAW_ENTRY_KEY_LENGTH
    assert normalized == normalize_raw_entry_key(long_key)
    assert normalized != long_key
    assert "#" in normalized


class DuplicateLinkListingAdapter:
    """真实列表页形态：同一篇文章在轮播位与列表位出现两次，entry_key 相同。"""

    source_type = "page_monitor"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        first = RawItemInput(
            entry_key="https://example.com/news/ocr/",
            source_title="OCR announcement (hero)",
            source_url="https://example.com/news/ocr/",
            raw_content="hero copy",
            published_at=None,
            raw_payload_json={"slot": "hero"},
        )
        second = RawItemInput(
            entry_key="https://example.com/news/ocr/",
            source_title="OCR announcement (list)",
            source_url="https://example.com/news/ocr/",
            raw_content="list copy",
            published_at=None,
            raw_payload_json={"slot": "list"},
        )
        return [first, second]


@pytest.mark.asyncio
async def test_duplicate_entry_keys_within_one_batch_upsert_once():
    session = make_session()
    data_source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type="page_monitor",
        name="Example Pages",
        url="https://example.com/news/",
    )
    session.add(data_source)
    session.commit()

    registry = AdapterRegistry()
    registry.register(DuplicateLinkListingAdapter())
    fetched_at = datetime(2026, 7, 7, 9, tzinfo=UTC)

    outcome = await fetch_source_to_raw_items(session, data_source.id, registry, fetched_at)
    session.commit()

    # 批内重复 entry_key 只落一行，不撞 uq_raw_items_source_entry
    assert session.scalar(select(func.count(RawItem.id))) == 1
    assert outcome.created == 1
    assert outcome.updated == 0

    row = session.scalar(select(RawItem))
    assert row is not None
    # 后出现者覆盖先出现者，与"同 entry_key 重抓刷新"语义一致
    assert row.raw_payload_json["slot"] == "list"
