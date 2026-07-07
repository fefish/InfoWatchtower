from __future__ import annotations

import re
from dataclasses import replace

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput
from app.adapters.page import _extract_links, _fetch_article
from app.models.content import DataSource

DEFAULT_MAX_ITEMS = 10
MAX_ITEMS_CEILING = 100
# 列表页先扫出的候选链接上限；正则过滤和 max_items 截断在其后进行。
LISTING_SCAN_LIMIT = 200


class CustomCrawlerAdapter:
    """通用列表页爬虫：抓列表页 → href 规则筛链接 → 逐链接抓正文（复用 page 抽取）。

    fetch_config 字段：
    - listing_url: 列表页地址（回落 page_url，再回落 data_source.url）
    - href_contains: 链接 URL 必须包含的子串列表（与 page_monitor 同名约定）
    - exclude_exact: 需要排除的完整 URL 集合（与 page_monitor 同名约定）
    - link_pattern: 链接 URL 必须匹配的正则（include）
    - link_exclude_pattern: 命中即排除的正则（exclude）
    - max_items: 单次最多抓取文章数，默认 10
    - fetch_article: 是否逐链接抓取正文，默认 true；false 时仅产出列表页链接条目
    """

    source_type = "crawler"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        listing_url = str(
            config.get("listing_url") or config.get("page_url") or data_source.url or "",
        ).strip()
        if not listing_url:
            return []
        max_items = _bounded_int(
            config.get("max_items") or config.get("max_links"),
            default=DEFAULT_MAX_ITEMS,
        )
        fetch_article = _config_flag(config.get("fetch_article"), default=True)
        include_pattern = _compile_pattern(config.get("link_pattern"))
        exclude_pattern = _compile_pattern(config.get("link_exclude_pattern"))

        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=BROWSER_FETCH_HEADERS,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(listing_url)
            response.raise_for_status()
            links = _extract_links(
                html=response.text,
                base_url=str(response.url),
                href_contains=list(config.get("href_contains") or []),
                exclude_exact=set(config.get("exclude_exact") or []),
                max_links=LISTING_SCAN_LIMIT,
            )
            selected = _filter_listing_links(
                links,
                include_pattern=include_pattern,
                exclude_pattern=exclude_pattern,
                max_items=max_items,
            )
            raw_items: list[RawItemInput] = []
            for url, link_text in selected:
                if fetch_article:
                    article = await _fetch_article(client, url, title_hint=link_text)
                    raw_items.append(
                        replace(
                            article,
                            raw_payload_json={
                                **article.raw_payload_json,
                                "listing_url": listing_url,
                                "link_text": link_text,
                            },
                        ),
                    )
                else:
                    raw_items.append(
                        RawItemInput(
                            entry_key=url,
                            source_title=link_text or url,
                            source_url=url,
                            raw_content=link_text or url,
                            raw_payload_json={
                                "listing_url": listing_url,
                                "url": url,
                                "link_text": link_text,
                            },
                        ),
                    )
            return raw_items


def _filter_listing_links(
    links: list[tuple[str, str]],
    *,
    include_pattern: re.Pattern[str] | None,
    exclude_pattern: re.Pattern[str] | None,
    max_items: int,
) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    for url, text in links:
        if include_pattern and not include_pattern.search(url):
            continue
        if exclude_pattern and exclude_pattern.search(url):
            continue
        selected.append((url, text))
        if len(selected) >= max_items:
            break
    return selected


def _compile_pattern(value: object) -> re.Pattern[str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    return re.compile(text)


def _config_flag(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text not in {"false", "0", "no", "off"}


def _bounded_int(value: object, *, default: int, maximum: int = MAX_ITEMS_CEILING) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)
