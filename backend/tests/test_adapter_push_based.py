from datetime import UTC, datetime

import httpx
import pytest

from app.adapters import create_default_registry
from app.adapters.push_based import InternalSourceAdapter, ManualNewsAdapter
from app.models.content import DataSource

API_PAYLOAD = {
    "items": [
        {
            "id": 101,
            "title": "内部通告一",
            "url": "https://intranet.example.com/notice/101",
            "content": "内部正文一",
            "published_at": "2026-07-01T08:00:00Z",
            "department": "规划部",
        },
        {
            "id": 102,
            "title": "内部通告二",
            "url": "https://intranet.example.com/notice/102",
            "content": "内部正文二",
            "published_at": "2026-07-02T08:00:00Z",
        },
    ],
}


def make_source(source_type: str, fetch_config: dict) -> DataSource:
    return DataSource(
        source_type=source_type,
        name=f"{source_type} source",
        url=None,
        fetch_config=fetch_config,
    )


@pytest.mark.asyncio
async def test_manual_adapter_is_push_based_and_returns_empty():
    adapter = ManualNewsAdapter()

    assert adapter.push_based is True
    assert await adapter.fetch(make_source("manual", {})) == []


@pytest.mark.asyncio
async def test_internal_adapter_without_api_url_is_push_based_empty_fetch():
    adapter = InternalSourceAdapter()

    assert adapter.push_based is True
    assert await adapter.fetch(make_source("internal", {})) == []


def test_default_registry_marks_manual_and_internal_as_push_based():
    registry = create_default_registry()

    assert getattr(registry.get("manual"), "push_based", False) is True
    assert getattr(registry.get("internal"), "push_based", False) is True


@pytest.mark.asyncio
async def test_internal_adapter_pulls_json_api_with_default_field_candidates():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "headers": dict(request.headers)})
        return httpx.Response(200, json=API_PAYLOAD)

    adapter = InternalSourceAdapter(transport=httpx.MockTransport(handler))
    items = await adapter.fetch(
        make_source(
            "internal",
            {
                "api_url": "https://intranet.example.com/api/notices",
                "params": {"days": "7"},
                "auth_token": "internal-token",
            },
        ),
    )

    assert calls[0]["url"] == "https://intranet.example.com/api/notices?days=7"
    assert calls[0]["headers"]["authorization"] == "Bearer internal-token"
    assert len(items) == 2
    first = items[0]
    assert first.entry_key == "101"
    assert first.source_title == "内部通告一"
    assert first.source_url == "https://intranet.example.com/notice/101"
    assert first.raw_content == "内部正文一"
    assert first.published_at == datetime(2026, 7, 1, 8, tzinfo=UTC)
    assert first.raw_payload_json["item"]["department"] == "规划部"
    assert first.raw_payload_json["api_url"] == "https://intranet.example.com/api/notices"


@pytest.mark.asyncio
async def test_internal_adapter_supports_items_path_and_field_map_dot_paths():
    payload = {
        "result": {
            "rows": [
                {
                    "key": "row-1",
                    "attributes": {"headline": "映射标题", "link": "https://intranet.example.com/r/1"},
                    "body": {"text": "映射正文"},
                    "meta": {"published": "2026-07-03T10:00:00Z"},
                },
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = InternalSourceAdapter(transport=httpx.MockTransport(handler))
    items = await adapter.fetch(
        make_source(
            "internal",
            {
                "api_url": "https://intranet.example.com/api/rows",
                "items_path": "result.rows",
                "field_map": {
                    "entry_key": "key",
                    "title": "attributes.headline",
                    "url": "attributes.link",
                    "content": "body.text",
                    "published_at": "meta.published",
                },
            },
        ),
    )

    assert len(items) == 1
    assert items[0].entry_key == "row-1"
    assert items[0].source_title == "映射标题"
    assert items[0].raw_content == "映射正文"
    assert items[0].published_at == datetime(2026, 7, 3, 10, tzinfo=UTC)
    assert items[0].raw_payload_json["item"]["attributes"]["headline"] == "映射标题"


@pytest.mark.asyncio
async def test_internal_adapter_max_items_and_skips_rows_without_payload():
    payload = {
        "items": [
            {"note": "没有可映射字段"},
            {"title": "第一条", "content": "正文一"},
            {"title": "第二条", "content": "正文二"},
            {"title": "第三条", "content": "正文三"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = InternalSourceAdapter(transport=httpx.MockTransport(handler))
    items = await adapter.fetch(
        make_source(
            "internal",
            {"api_url": "https://intranet.example.com/api/notices", "max_items": 2},
        ),
    )

    assert [item.source_title for item in items] == ["第一条", "第二条"]


@pytest.mark.asyncio
async def test_internal_adapter_malformed_payload_raises_value_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    adapter = InternalSourceAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="does not contain a list"):
        await adapter.fetch(make_source("internal", {"api_url": "https://intranet.example.com/api/notices"}))


@pytest.mark.asyncio
async def test_internal_adapter_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    adapter = InternalSourceAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch(make_source("internal", {"api_url": "https://intranet.example.com/api/notices"}))


@pytest.mark.asyncio
async def test_internal_adapter_propagates_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    adapter = InternalSourceAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.TimeoutException):
        await adapter.fetch(make_source("internal", {"api_url": "https://intranet.example.com/api/notices"}))


@pytest.mark.asyncio
async def test_internal_adapter_entry_key_is_stable_across_refetch():
    payload = {"items": [{"title": "无 id 无 url 的条目", "content": "正文"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = InternalSourceAdapter(transport=httpx.MockTransport(handler))
    source = make_source("internal", {"api_url": "https://intranet.example.com/api/notices"})

    first = await adapter.fetch(source)
    second = await adapter.fetch(source)

    assert first[0].entry_key.startswith("internal:")
    assert [item.entry_key for item in first] == [item.entry_key for item in second]
