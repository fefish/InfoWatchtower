from __future__ import annotations

import json
from calendar import timegm
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any

import feedparser
import httpx

from app.adapters.base import RawItemInput
from app.models.content import DataSource


class RssFeedAdapter:
    source_type = "rss"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        if not data_source.url:
            return []
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(data_source.url)
            response.raise_for_status()

        parsed = feedparser.parse(response.content)
        return [self._entry_to_raw_item(entry) for entry in parsed.entries]

    def _entry_to_raw_item(self, entry: Any) -> RawItemInput:
        source_url = entry.get("link")
        title = entry.get("title", "")
        published_at = _first_feed_datetime(
            entry.get("published"),
            entry.get("updated"),
            entry.get("created"),
            entry.get("published_parsed"),
            entry.get("updated_parsed"),
            entry.get("created_parsed"),
        )
        entry_key = entry.get("id") or entry.get("guid") or source_url or title
        summary = entry.get("summary", "")
        content = ""
        if entry.get("content"):
            content = entry.content[0].get("value", "")
        return RawItemInput(
            entry_key=str(entry_key),
            source_title=title,
            source_url=source_url,
            raw_content=content or summary,
            published_at=published_at,
            raw_payload_json=_json_safe(dict(entry)),
        )


class PaperRssFeedAdapter(RssFeedAdapter):
    source_type = "paper_rss"


def _first_feed_datetime(*values: Any) -> datetime | None:
    for value in values:
        parsed = _parse_feed_datetime(value)
        if parsed is not None:
            return parsed
    return None


def _parse_feed_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    tuple_like_feed_time = (
        isinstance(value, tuple)
        and len(value) >= 9
        and all(isinstance(part, int) for part in value[:6])
    )
    if isinstance(value, struct_time) or tuple_like_feed_time:
        try:
            return datetime.fromtimestamp(timegm(value[:9]), tz=UTC)
        except (OverflowError, TypeError, ValueError):
            return None

    text = str(value).strip()
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_safe(value: Any) -> dict[str, Any]:
    return json.loads(json.dumps(value, default=str))
