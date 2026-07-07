from __future__ import annotations

from hashlib import sha1
from typing import Any

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput
from app.adapters.rss import _json_safe, _parse_feed_datetime
from app.core.credentials import resolve_source_token
from app.models.content import DataSource

DEFAULT_MAX_ITEMS = 200
MAX_ITEMS_CEILING = 1000
DEFAULT_ITEMS_KEYS = ("items", "data", "results", "records")
DEFAULT_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "title": ("source_title", "title", "name"),
    "url": ("source_url", "url", "link"),
    "content": ("raw_content", "content", "summary", "body"),
    "published_at": ("published_at", "published", "created_at", "created"),
    "entry_key": ("entry_key", "id", "guid"),
}


class ManualNewsAdapter:
    """手工导入源：推入式语义。

    条目由 manual-import 预览/回补路由写入 raw_items，定时抓取对这类源
    如实返回 0 条新增（成功、非失败），不再抛 AdapterNotImplementedError。
    """

    source_type = "manual"
    push_based = True

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        return []


class InternalSourceAdapter:
    """内部系统源：默认推入式；配置 api_url 后升级为通用 JSON API 拉取器。

    fetch_config 字段：
    - api_url: 内部 JSON API 地址；缺省时视为纯推入源，fetch 返回空列表
    - params: GET 查询参数字典（可选）
    - items_path: 响应中条目列表的点号路径（如 "result.rows"）；缺省时自动探测
      根列表或 items/data/results/records 键
    - field_map: {title/url/content/published_at/entry_key: 字段点号路径} 覆盖默认字段约定
    - max_items: 单次最多产出条目数，默认 200
    - Bearer token 推荐用 data_sources.credential_ref（env:VAR / file:/path 指针），
      解析顺序 credential_ref → auth_token_env → auth_token（后两者为过渡兼容）
    """

    source_type = "internal"
    push_based = True

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        api_url = str(config.get("api_url") or "").strip()
        if not api_url:
            return []
        max_items = _bounded_int(config.get("max_items"), default=DEFAULT_MAX_ITEMS)
        field_map = dict(config.get("field_map") or {})
        headers = {**BROWSER_FETCH_HEADERS, "Accept": "application/json"}
        # 推荐顺序：credential_ref → auth_token_env → auth_token（core/credentials.py）
        token = resolve_source_token(data_source, config)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(api_url, params=dict(config.get("params") or {}))
            response.raise_for_status()
        items = _resolve_items(response.json(), str(config.get("items_path") or "").strip())

        raw_items: list[RawItemInput] = []
        for item in items:
            raw_item = _item_to_raw_item(item, field_map=field_map, api_url=api_url)
            if raw_item is None:
                continue
            raw_items.append(raw_item)
            if len(raw_items) >= max_items:
                break
        return raw_items


def _item_to_raw_item(
    item: dict[str, Any],
    *,
    field_map: dict[str, Any],
    api_url: str,
) -> RawItemInput | None:
    title = _field_value(item, field_map, "title")
    url = _field_value(item, field_map, "url")
    content = _field_value(item, field_map, "content")
    published_text = _field_value(item, field_map, "published_at")
    explicit_key = _field_value(item, field_map, "entry_key")
    if not (title or url or content):
        return None
    if explicit_key:
        entry_key = explicit_key
    elif url:
        entry_key = url
    else:
        digest = sha1(f"{title}\x1f{content}".encode()).hexdigest()[:16]
        entry_key = f"internal:{digest}"
    return RawItemInput(
        entry_key=entry_key,
        source_title=title or url or content[:120],
        source_url=url or None,
        raw_content=content or title or url,
        published_at=_parse_feed_datetime(published_text),
        raw_payload_json=_json_safe({"api_url": api_url, "item": item}),
    )


def _resolve_items(payload: Any, items_path: str) -> list[dict[str, Any]]:
    node = payload
    if items_path:
        for part in items_path.split("."):
            if not isinstance(node, dict):
                raise ValueError(f"internal api items_path segment not found: {part}")
            node = node.get(part)
    elif isinstance(node, dict):
        for key in DEFAULT_ITEMS_KEYS:
            if isinstance(node.get(key), list):
                node = node[key]
                break
    if not isinstance(node, list):
        raise ValueError("internal api response does not contain a list of items")
    return [item for item in node if isinstance(item, dict)]


def _field_value(item: dict[str, Any], field_map: dict[str, Any], field: str) -> str:
    mapped = str(field_map.get(field) or "").strip()
    if mapped:
        return _text(_dig(item, mapped))
    for candidate in DEFAULT_FIELD_CANDIDATES[field]:
        value = _text(item.get(candidate))
        if value:
            return value
    return ""


def _dig(item: Any, path: str) -> Any:
    node = item
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bounded_int(value: object, *, default: int, maximum: int = MAX_ITEMS_CEILING) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)
