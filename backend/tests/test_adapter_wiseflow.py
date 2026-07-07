import json
from datetime import UTC, date, datetime

import httpx
import pytest

from app.adapters.base import SourceFetchContext
from app.adapters.wiseflow import WiseflowReadInfoAdapter
from app.models.content import DataSource

RECORDS = [
    {
        "id": "a1b2c3d4e5f60708",
        "type": "web",
        "content": "英伟达发布新一代推理芯片……",
        "refers": "",
        "focus_statement": "AI 芯片动态",
        "focus_id": 3,
        "source_url": "https://example.com/nvidia-chip",
        "source_title": "英伟达新品",
        "created": "2026-07-01T08:00:00Z",
    },
    {
        "id": "b2c3d4e5f6071809",
        "type": "rss",
        "content": "多智能体系统进展……",
        "refers": "ref-1",
        "focus_statement": "Agent 进展",
        "focus_id": 4,
        "source_url": "https://example.com/agents",
        "source_title": "Agent 周报",
        "created": "2026-07-02 09:30:00",
    },
    {
        "id": "c3d4e5f607182910",
        "type": "web",
        "content": "数据中心液冷架构……",
        "refers": "",
        "focus_statement": "数据中心",
        "focus_id": 3,
        "source_url": "",
        "source_title": "液冷架构",
        "created": "",
    },
]


def make_source(
    fetch_config: dict,
    url: str | None = None,
    credential_ref: str | None = None,
) -> DataSource:
    return DataSource(
        source_type="wiseflow",
        name="Wiseflow",
        url=url,
        fetch_config=fetch_config,
        credential_ref=credential_ref,
    )


def paging_transport(records: list[dict], calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url).endswith("/read_info")
        body = json.loads(request.content.decode("utf-8"))
        calls.append({"url": str(request.url), "body": body, "headers": dict(request.headers)})
        offset = int(body.get("offset") or 0)
        limit = int(body.get("limit") or 20)
        return httpx.Response(
            200,
            json={"success": True, "msg": "", "data": records[offset : offset + limit]},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_wiseflow_paginates_read_info_and_maps_records():
    calls: list[dict] = []
    adapter = WiseflowReadInfoAdapter(transport=paging_transport(RECORDS, calls))
    items = await adapter.fetch(
        make_source(
            {
                "base_url": "http://wiseflow.internal:8077",
                "page_size": 2,
                "start_time": "2026-06-30T00:00:00Z",
                "focus_ids": [3, 4],
            },
        ),
    )

    assert [call["body"]["offset"] for call in calls] == [0, 2]
    assert calls[0]["url"] == "http://wiseflow.internal:8077/read_info"
    assert calls[0]["body"]["limit"] == 2
    assert calls[0]["body"]["start_time"] == "2026-06-30T00:00:00Z"
    assert calls[0]["body"]["focuses"] == [3, 4]

    assert len(items) == 3
    first = items[0]
    assert first.entry_key == "wiseflow:a1b2c3d4e5f60708"
    assert first.source_title == "英伟达新品"
    assert first.source_url == "https://example.com/nvidia-chip"
    assert first.raw_content == "英伟达发布新一代推理芯片……"
    assert first.published_at == datetime(2026, 7, 1, 8, tzinfo=UTC)
    assert first.raw_payload_json == RECORDS[0]
    assert first.source_specific_json["focus_id"] == 3
    assert first.source_specific_json["focus_statement"] == "AI 芯片动态"

    # 无时区的 created 按 UTC 解析；空 created 得到 None
    assert items[1].published_at == datetime(2026, 7, 2, 9, 30, tzinfo=UTC)
    assert items[2].published_at is None
    assert items[2].source_url is None


@pytest.mark.asyncio
async def test_wiseflow_max_items_caps_pagination():
    calls: list[dict] = []
    adapter = WiseflowReadInfoAdapter(transport=paging_transport(RECORDS, calls))
    items = await adapter.fetch(
        make_source({"base_url": "http://wiseflow.internal:8077", "page_size": 2, "max_items": 2}),
    )

    assert len(items) == 2
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_wiseflow_fetch_with_context_passes_target_day_window():
    calls: list[dict] = []
    adapter = WiseflowReadInfoAdapter(transport=paging_transport(RECORDS[:1], calls))
    items = await adapter.fetch_with_context(
        make_source({"base_url": "http://wiseflow.internal:8077"}),
        SourceFetchContext(
            mode="rss_window",
            target_day_start=date(2026, 5, 10),
            target_day_end=date(2026, 5, 12),
        ),
    )

    assert len(items) == 1
    assert calls[0]["body"]["start_time"] == "2026-05-10T00:00:00Z"
    assert calls[0]["body"]["end_time"] == "2026-05-12T23:59:59Z"


@pytest.mark.asyncio
async def test_wiseflow_uses_url_as_endpoint_and_sends_bearer_token():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "headers": dict(request.headers)})
        return httpx.Response(200, json={"success": True, "msg": "", "data": []})

    adapter = WiseflowReadInfoAdapter(transport=httpx.MockTransport(handler))
    items = await adapter.fetch(
        make_source({"auth_token": "secret-token"}, url="https://example.com/read-info"),
    )

    assert items == []
    # url 已指向 read-info 端点时直接使用，不再拼接 /read_info
    assert calls[0]["url"] == "https://example.com/read-info"
    assert calls[0]["headers"]["authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_wiseflow_credential_ref_wins_over_legacy_token_config(monkeypatch):
    """token 解析推荐顺序：credential_ref → auth_token_env → auth_token。"""
    monkeypatch.setenv("WISEFLOW_REF_TOKEN", "ref-token")
    monkeypatch.setenv("WISEFLOW_ENV_TOKEN", "env-token")
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"headers": dict(request.headers)})
        return httpx.Response(200, json={"success": True, "msg": "", "data": []})

    adapter = WiseflowReadInfoAdapter(transport=httpx.MockTransport(handler))
    await adapter.fetch(
        make_source(
            {
                "base_url": "http://wiseflow.internal:8077",
                "auth_token_env": "WISEFLOW_ENV_TOKEN",
                "auth_token": "inline-token",
            },
            credential_ref="env:WISEFLOW_REF_TOKEN",
        ),
    )

    assert calls[0]["headers"]["authorization"] == "Bearer ref-token"


@pytest.mark.asyncio
async def test_wiseflow_broken_credential_ref_falls_back_to_auth_token_env(monkeypatch):
    monkeypatch.delenv("WISEFLOW_REF_TOKEN", raising=False)
    monkeypatch.setenv("WISEFLOW_ENV_TOKEN", "env-token")
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"headers": dict(request.headers)})
        return httpx.Response(200, json={"success": True, "msg": "", "data": []})

    adapter = WiseflowReadInfoAdapter(transport=httpx.MockTransport(handler))
    await adapter.fetch(
        make_source(
            {
                "base_url": "http://wiseflow.internal:8077",
                "auth_token_env": "WISEFLOW_ENV_TOKEN",
                "auth_token": "inline-token",
            },
            credential_ref="env:WISEFLOW_REF_TOKEN",
        ),
    )

    assert calls[0]["headers"]["authorization"] == "Bearer env-token"


@pytest.mark.asyncio
async def test_wiseflow_missing_endpoint_raises_config_error():
    adapter = WiseflowReadInfoAdapter()
    with pytest.raises(ValueError, match="missing read_info endpoint"):
        await adapter.fetch(make_source({}))


@pytest.mark.asyncio
async def test_wiseflow_api_failure_envelope_raises_runtime_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "msg": "查询信息失败", "data": []})

    adapter = WiseflowReadInfoAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="查询信息失败"):
        await adapter.fetch(make_source({"base_url": "http://wiseflow.internal:8077"}))


@pytest.mark.asyncio
async def test_wiseflow_malformed_data_raises_value_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "msg": "", "data": {"not": "a list"}})

    adapter = WiseflowReadInfoAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="data must be a list"):
        await adapter.fetch(make_source({"base_url": "http://wiseflow.internal:8077"}))


@pytest.mark.asyncio
async def test_wiseflow_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    adapter = WiseflowReadInfoAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch(make_source({"base_url": "http://wiseflow.internal:8077"}))


@pytest.mark.asyncio
async def test_wiseflow_propagates_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    adapter = WiseflowReadInfoAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.TimeoutException):
        await adapter.fetch(make_source({"base_url": "http://wiseflow.internal:8077"}))


@pytest.mark.asyncio
async def test_wiseflow_entry_key_is_stable_across_refetch():
    adapter = WiseflowReadInfoAdapter(transport=paging_transport(RECORDS, []))
    source = make_source({"base_url": "http://wiseflow.internal:8077", "page_size": 2})

    first = await adapter.fetch(source)
    second = await adapter.fetch(source)

    assert [item.entry_key for item in first] == [item.entry_key for item in second]


@pytest.mark.asyncio
async def test_wiseflow_resolves_endpoint_from_legacy_env_config(monkeypatch):
    monkeypatch.setenv("SOURCE_API_BASE", "http://wiseflow.internal:8077")
    calls: list[dict] = []
    adapter = WiseflowReadInfoAdapter(transport=paging_transport(RECORDS[:1], calls))
    items = await adapter.fetch(
        make_source({"base_url_env": "SOURCE_API_BASE", "page_size_env": "READ_INFO_PAGE_SIZE"}),
    )

    assert len(items) == 1
    assert calls[0]["url"] == "http://wiseflow.internal:8077/read_info"
