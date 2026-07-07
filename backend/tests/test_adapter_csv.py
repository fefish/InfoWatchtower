from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.csv_file import CsvFileAdapter
from app.models.content import DataSource

CSV_TEXT = (
    "source_title,source_url,raw_content,published_at\n"
    "新闻一,https://example.com/a,正文一,2026-07-01T08:00:00Z\n"
    "新闻二,https://example.com/b,正文二,not-a-date\n"
)


def make_source(fetch_config: dict, url: str | None = None) -> DataSource:
    return DataSource(source_type="csv", name="CSV Source", url=url, fetch_config=fetch_config)


@pytest.mark.asyncio
async def test_csv_adapter_parses_inline_text_with_default_columns():
    adapter = CsvFileAdapter()
    items = await adapter.fetch(make_source({"csv_text": CSV_TEXT}))

    assert len(items) == 2
    first = items[0]
    assert first.entry_key == "https://example.com/a"
    assert first.source_title == "新闻一"
    assert first.source_url == "https://example.com/a"
    assert first.raw_content == "正文一"
    assert first.published_at == datetime(2026, 7, 1, 8, tzinfo=UTC)
    assert first.raw_payload_json["csv_origin"] == "inline"
    assert first.raw_payload_json["row_number"] == 1
    assert first.raw_payload_json["row"]["source_title"] == "新闻一"
    assert first.raw_payload_json["row"]["published_at"] == "2026-07-01T08:00:00Z"
    assert items[1].published_at is None


@pytest.mark.asyncio
async def test_csv_adapter_fetches_url_and_applies_column_map_and_max_items():
    csv_body = (
        "标题,链接,内容,日期\n"
        "A,https://example.com/1,内容A,2026-07-01T08:00:00Z\n"
        "B,https://example.com/2,内容B,2026-07-02T08:00:00Z\n"
        "C,https://example.com/3,内容C,2026-07-03T08:00:00Z\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/list.csv"
        return httpx.Response(
            200,
            text=csv_body,
            headers={"content-type": "text/csv; charset=utf-8"},
        )

    adapter = CsvFileAdapter(transport=httpx.MockTransport(handler))
    items = await adapter.fetch(
        make_source(
            {
                "csv_url": "https://example.com/list.csv",
                "column_map": {
                    "title": "标题",
                    "url": "链接",
                    "content": "内容",
                    "published_at": "日期",
                },
                "max_items": 2,
            },
        ),
    )

    assert len(items) == 2
    assert items[0].source_title == "A"
    assert items[0].entry_key == "https://example.com/1"
    assert items[0].raw_payload_json["csv_origin"] == "url"
    assert items[0].raw_payload_json["row"]["标题"] == "A"


@pytest.mark.asyncio
async def test_csv_adapter_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    adapter = CsvFileAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch(make_source({}, url="https://example.com/list.csv"))


@pytest.mark.asyncio
async def test_csv_adapter_propagates_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    adapter = CsvFileAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.TimeoutException):
        await adapter.fetch(make_source({"csv_url": "https://example.com/list.csv"}))


@pytest.mark.asyncio
async def test_csv_adapter_requires_a_configured_input():
    adapter = CsvFileAdapter()
    with pytest.raises(ValueError, match="csv source is missing input"):
        await adapter.fetch(make_source({}))


@pytest.mark.asyncio
async def test_csv_adapter_skips_empty_rows_and_handles_header_only_text():
    adapter = CsvFileAdapter()

    header_only = await adapter.fetch(make_source({"csv_text": "source_title,source_url\n"}))
    assert header_only == []

    with_empty_rows = await adapter.fetch(
        make_source({"csv_text": "source_title,source_url,raw_content\n,,\n有效,https://example.com/x,正文\n"}),
    )
    assert len(with_empty_rows) == 1
    assert with_empty_rows[0].source_title == "有效"


@pytest.mark.asyncio
async def test_csv_adapter_entry_key_is_stable_across_refetch():
    csv_text = (
        "source_title,raw_content\n"
        "只有标题和内容,正文（无链接列）\n"
    )
    adapter = CsvFileAdapter()
    source = make_source({"csv_text": csv_text})

    first = await adapter.fetch(source)
    second = await adapter.fetch(source)

    assert [item.entry_key for item in first] == [item.entry_key for item in second]
    # 无 url 时优先用标题作为稳定键
    assert first[0].entry_key == "只有标题和内容"


@pytest.mark.asyncio
async def test_csv_adapter_content_only_rows_get_stable_digest_entry_key():
    csv_text = "raw_content\n只有正文的一行\n"
    adapter = CsvFileAdapter()
    source = make_source({"csv_text": csv_text})

    first = await adapter.fetch(source)
    second = await adapter.fetch(source)

    assert first[0].entry_key.startswith("csv:")
    assert first[0].entry_key == second[0].entry_key
