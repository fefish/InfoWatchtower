from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from typing import Any

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput, SourceFetchContext
from app.adapters.rss import _json_safe
from app.models.content import DataSource

# wiseflow 4.x backend（references/private/wiseflow-4x/core/backend/app.py）：
# 全量同步必须走 POST /read_info 分页（GET /list_info 每 focus 上限 12 条，禁止用于全量），
# 响应为 APIResponse 信封 {"success": bool, "msg": str, "data": [info...]}，
# info 记录字段：id/type/content/refers/focus_statement/focus_id/source_url/source_title/created。
READ_INFO_PATH = "read_info"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
DEFAULT_MAX_ITEMS = 200
MAX_ITEMS_CEILING = 2000
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class WiseflowReadInfoAdapter:
    """对接 wiseflow 4.x 实例的 POST /read_info 分页拉取适配器。

    fetch_config 字段：
    - read_info_url: /read_info 完整地址（优先级最高）
    - base_url: wiseflow backend 根地址，自动拼 /read_info
    - read_info_url_env / base_url_env: 从环境变量读取上述地址（legacy 种子约定，
      如 SOURCE_READ_INFO_URL / SOURCE_API_BASE）；都缺省时回落 data_source.url
    - page_size: 分页大小，默认 50（回落 page_size_env 指定的环境变量）
    - max_items: 单次拉取条目总上限，默认 200
    - focus_ids: 只拉取指定 wiseflow focus id 列表（可选）
    - start_time: 固定增量起点（ISO 8601 UTC，可选）
    - lookback_days / lookback_seconds: 相对增量窗口（回落 lookback_seconds_env）
    - auth_token / auth_token_env: Bearer token（待迁移 credential_ref 机制的过渡债务）

    历史回补（fetch_with_context）时按 target day 窗口传 start_time/end_time。
    """

    source_type = "wiseflow"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        return await self._fetch(data_source, None)

    async def fetch_with_context(
        self,
        data_source: DataSource,
        context: SourceFetchContext,
    ) -> list[RawItemInput]:
        return await self._fetch(data_source, context)

    async def _fetch(
        self,
        data_source: DataSource,
        context: SourceFetchContext | None,
    ) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        endpoint = _resolve_read_info_url(data_source, config)
        if not endpoint:
            raise ValueError(
                "wiseflow source is missing read_info endpoint: "
                "set fetch_config.read_info_url/base_url, the *_env variables, or url",
            )
        page_size = _bounded_int(
            config.get("page_size") or _env_value(config.get("page_size_env")),
            default=DEFAULT_PAGE_SIZE,
            maximum=MAX_PAGE_SIZE,
        )
        max_items = _bounded_int(
            config.get("max_items"),
            default=DEFAULT_MAX_ITEMS,
            maximum=MAX_ITEMS_CEILING,
        )
        start_time, end_time = _time_window(config, context)
        focus_ids = _focus_ids(config)
        headers = {**BROWSER_FETCH_HEADERS, "Accept": "application/json"}
        token = _resolve_auth_token(config)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
            trust_env=False,
            transport=self._transport,
        ) as client:
            offset = 0
            while len(records) < max_items:
                body: dict[str, Any] = {"limit": page_size, "offset": offset}
                if focus_ids:
                    body["focuses"] = focus_ids
                if start_time:
                    body["start_time"] = start_time
                if end_time:
                    body["end_time"] = end_time
                response = await client.post(endpoint, json=body)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("wiseflow read_info returned a non-object payload")
                if not payload.get("success", False):
                    raise RuntimeError(
                        f"wiseflow read_info failed: {payload.get('msg') or 'unknown error'}",
                    )
                batch = payload.get("data")
                if not isinstance(batch, list):
                    raise ValueError("wiseflow read_info data must be a list")
                records.extend(item for item in batch if isinstance(item, dict))
                if len(batch) < page_size:
                    break
                offset += page_size
        return [_record_to_raw_item(record) for record in records[:max_items]]


def _record_to_raw_item(record: dict[str, Any]) -> RawItemInput:
    info_id = str(record.get("id") or "").strip()
    source_url = str(record.get("source_url") or "").strip() or None
    title = _squash(str(record.get("source_title") or ""))
    content = str(record.get("content") or "")
    if info_id:
        entry_key = f"wiseflow:{info_id}"
    elif source_url:
        entry_key = source_url
    else:
        digest = sha1(f"{title}\x1f{content}".encode()).hexdigest()[:16]
        entry_key = f"wiseflow:{digest}"
    return RawItemInput(
        entry_key=entry_key,
        source_title=title or _squash(content)[:120] or entry_key,
        source_url=source_url,
        raw_content=content or title,
        published_at=_parse_created(record.get("created")),
        raw_payload_json=_json_safe(record),
        source_specific_json={
            "focus_id": record.get("focus_id"),
            "info_type": str(record.get("type") or ""),
            "focus_statement": str(record.get("focus_statement") or ""),
        },
    )


def _resolve_read_info_url(data_source: DataSource, config: dict[str, Any]) -> str:
    explicit = str(
        config.get("read_info_url") or _env_value(config.get("read_info_url_env")) or "",
    ).strip()
    if explicit:
        return explicit
    base = str(
        config.get("base_url")
        or _env_value(config.get("base_url_env"))
        or data_source.url
        or "",
    ).strip().rstrip("/")
    if not base:
        return ""
    last_segment = base.rsplit("/", 1)[-1].lower()
    if last_segment in {"read_info", "read-info"}:
        return base
    return f"{base}/{READ_INFO_PATH}"


def _time_window(
    config: dict[str, Any],
    context: SourceFetchContext | None,
) -> tuple[str, str]:
    if context is not None and context.target_day_start and context.target_day_end:
        return (
            f"{context.target_day_start.isoformat()}T00:00:00Z",
            f"{context.target_day_end.isoformat()}T23:59:59Z",
        )
    start_time = str(config.get("start_time") or "").strip()
    if start_time:
        return start_time, ""
    lookback_seconds = _optional_int(
        config.get("lookback_seconds") or _env_value(config.get("lookback_seconds_env")),
    )
    lookback_days = _optional_int(config.get("lookback_days"))
    if lookback_seconds is None and lookback_days is not None:
        lookback_seconds = lookback_days * 86400
    if lookback_seconds is not None and lookback_seconds > 0:
        start = datetime.now(UTC) - timedelta(seconds=lookback_seconds)
        return start.strftime(TIME_FORMAT), ""
    return "", ""


def _focus_ids(config: dict[str, Any]) -> list[int]:
    focus_ids: list[int] = []
    for value in config.get("focus_ids") or []:
        try:
            focus_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return focus_ids


def _resolve_auth_token(config: dict[str, Any]) -> str:
    token = str(config.get("auth_token") or "").strip()
    if token:
        return token
    env_name = str(config.get("auth_token_env") or "").strip()
    if env_name:
        return os.environ.get(env_name, "").strip()
    return ""


def _env_value(name: object) -> str:
    env_name = str(name or "").strip()
    if not env_name:
        return ""
    return os.environ.get(env_name, "").strip()


def _parse_created(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _bounded_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)


def _squash(value: str) -> str:
    return " ".join((value or "").split())
