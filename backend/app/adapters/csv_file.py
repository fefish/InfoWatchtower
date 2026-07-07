from __future__ import annotations

import csv
import io
from hashlib import sha1
from pathlib import Path
from typing import Any

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput
from app.adapters.rss import _json_safe, _parse_feed_datetime
from app.models.content import DataSource

DEFAULT_MAX_ITEMS = 200
MAX_ITEMS_CEILING = 1000
# 列映射默认候选：与 manual-import 预览 CSV 的列名约定
# （source_title/source_url/raw_content/published_at）保持一致。
DEFAULT_COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "title": ("source_title", "title", "name"),
    "url": ("source_url", "url", "link"),
    "content": ("raw_content", "content", "summary", "description"),
    "published_at": ("published_at", "published", "pub_date", "date", "created"),
    "entry_key": ("entry_key", "id", "guid"),
}


class CsvFileAdapter:
    """CSV 数据源适配器。

    fetch_config 字段：
    - csv_text: 内联 CSV 文本（优先级最高）
    - csv_path: 本地 CSV 文件路径
    - csv_url:  CSV 下载地址（缺省回落 data_source.url）
    - column_map: {title/url/content/published_at/entry_key: 实际列名} 覆盖默认列名约定
    - delimiter: 分隔符，默认 ","
    - encoding: URL/文件读取编码，默认 utf-8（URL 未指定时按响应头推断）
    - max_items: 单次最多产出条目数，默认 200
    """

    source_type = "csv"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        text, origin = await self._load_csv_text(data_source, config)
        column_map = dict(config.get("column_map") or {})
        max_items = _bounded_int(config.get("max_items"), default=DEFAULT_MAX_ITEMS)
        delimiter = str(config.get("delimiter") or ",")
        reader = csv.DictReader(
            io.StringIO(text),
            delimiter=delimiter,
            restkey="_extra",
            restval="",
        )
        raw_items: list[RawItemInput] = []
        for row_number, row in enumerate(reader, start=1):
            raw_item = _row_to_raw_item(
                row=row,
                row_number=row_number,
                column_map=column_map,
                origin=origin,
            )
            if raw_item is None:
                continue
            raw_items.append(raw_item)
            if len(raw_items) >= max_items:
                break
        return raw_items

    async def _load_csv_text(
        self,
        data_source: DataSource,
        config: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        inline_text = str(config.get("csv_text") or "")
        if inline_text.strip():
            return inline_text, {"csv_origin": "inline"}

        csv_path = str(config.get("csv_path") or "").strip()
        if csv_path:
            encoding = str(config.get("encoding") or "utf-8")
            return (
                Path(csv_path).read_text(encoding=encoding),
                {"csv_origin": "path", "csv_path": csv_path},
            )

        csv_url = str(config.get("csv_url") or data_source.url or "").strip()
        if not csv_url:
            raise ValueError(
                "csv source is missing input: set fetch_config.csv_text, csv_path, csv_url or url",
            )
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=BROWSER_FETCH_HEADERS,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(csv_url)
            response.raise_for_status()
        encoding = str(config.get("encoding") or "").strip()
        text = response.content.decode(encoding) if encoding else response.text
        return text, {"csv_origin": "url", "csv_url": csv_url}


def _row_to_raw_item(
    *,
    row: dict[Any, Any],
    row_number: int,
    column_map: dict[str, Any],
    origin: dict[str, Any],
) -> RawItemInput | None:
    values = {str(key): value for key, value in row.items() if key is not None}
    title = _first_mapped_value(values, column_map, "title")
    url = _first_mapped_value(values, column_map, "url")
    content = _first_mapped_value(values, column_map, "content")
    published_text = _first_mapped_value(values, column_map, "published_at")
    explicit_key = _first_mapped_value(values, column_map, "entry_key")
    if not (title or url or content):
        return None
    entry_key = explicit_key or url or title or f"csv:{_row_digest(values)}"
    return RawItemInput(
        entry_key=entry_key,
        source_title=title or url or content[:120],
        source_url=url or None,
        raw_content=content or title or url,
        published_at=_parse_feed_datetime(published_text),
        raw_payload_json=_json_safe({**origin, "row_number": row_number, "row": values}),
    )


def _first_mapped_value(
    values: dict[str, Any],
    column_map: dict[str, Any],
    field: str,
) -> str:
    mapped = str(column_map.get(field) or "").strip()
    candidates = (mapped,) if mapped else DEFAULT_COLUMN_CANDIDATES[field]
    for candidate in candidates:
        value = str(values.get(candidate) or "").strip()
        if value:
            return value
    return ""


def _row_digest(values: dict[str, Any]) -> str:
    joined = "\x1f".join(f"{key}={values[key]}" for key in sorted(values))
    return sha1(joined.encode("utf-8")).hexdigest()[:16]


def _bounded_int(value: object, *, default: int, maximum: int = MAX_ITEMS_CEILING) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)
