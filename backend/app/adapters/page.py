from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha1
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput
from app.models.content import DataSource


class PageListingAdapter:
    """列表页监控（source_type=page_monitor）。

    fetch_config 增量选项 content_hash_diff=true：把条目正文 sha1 编进 entry_key。
    fetch.py 的幂等行为是按 (data_source_id, entry_key) upsert——同 entry_key 重抓
    会幂等刷新（同内容刷新无实质变化）；hash 进 key 之后：
    - 未变更条目 → 同 entry_key → 不新增 raw_item（按既有幂等语义跳过）；
    - 正文变更   → 新 entry_key → 新 raw_item，首次版本的 raw_payload_json
      原样保留，不被新版覆盖（raw 不覆盖不变式）。
    """

    source_type = "page_monitor"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        page_url = str(config.get("page_url") or data_source.url or "").strip()
        if not page_url:
            return []
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=BROWSER_FETCH_HEADERS,
            transport=self._transport,
        ) as client:
            response = await client.get(page_url)
            response.raise_for_status()
            links = _extract_links(
                html=response.text,
                base_url=str(response.url),
                href_contains=list(config.get("href_contains") or []),
                exclude_exact=set(config.get("exclude_exact") or []),
                max_links=int(config.get("max_links") or 10),
            )
            items = [await _fetch_article(client, url, title_hint=title) for url, title in links]
        if _flag(config.get("content_hash_diff")):
            items = [_with_content_hash_key(item) for item in items]
        return items


class ManualPageAdapter:
    source_type = "page_manual"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        articles = list(config.get("articles") or [])
        if not articles and data_source.url:
            articles = [{"url": data_source.url}]
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=BROWSER_FETCH_HEADERS,
            transport=self._transport,
        ) as client:
            return [
                await _fetch_article(
                    client,
                    str(article.get("url") or ""),
                    title_hint="",
                    created_hint=str(article.get("created_hint") or ""),
                )
                for article in articles
                if article.get("url")
            ]


async def _fetch_article(
    client: httpx.AsyncClient,
    url: str,
    title_hint: str = "",
    created_hint: str = "",
) -> RawItemInput:
    response = await client.get(url)
    response.raise_for_status()
    parsed = _parse_html(response.text)
    title = parsed["title"] or title_hint or str(response.url)
    # 正文兜底链：结构化标签正文 → meta description → og:description →
    # 首个成段文本块（div/span 排版页的"首段落"）→ 标题。
    text = (
        parsed["text"]
        or parsed["description"]
        or parsed["og_description"]
        or parsed["first_block"]
        or title
    )
    return RawItemInput(
        entry_key=str(response.url),
        source_title=title.strip(),
        source_url=str(response.url),
        raw_content=text.strip(),
        published_at=_parse_iso_datetime(created_hint),
        raw_payload_json={
            "url": url,
            "final_url": str(response.url),
            "title": title,
            "description": parsed["description"],
            "og_description": parsed["og_description"],
            "first_block": parsed["first_block"],
            "text": text,
        },
    )


def _with_content_hash_key(item: RawItemInput) -> RawItemInput:
    """content_hash_diff=true：正文 sha1 编进 entry_key（增量语义见类 docstring）。

    hash 同步写入 raw_payload_json.content_hash 方便排查；entry_key 超长由
    fetch.normalize_raw_entry_key 统一截断。
    """
    digest = sha1(item.raw_content.encode("utf-8")).hexdigest()[:16]
    return replace(
        item,
        entry_key=f"{item.entry_key}#body:{digest}",
        raw_payload_json={**item.raw_payload_json, "content_hash": digest},
    )


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _extract_links(
    html: str,
    base_url: str,
    href_contains: list[str],
    exclude_exact: set[str],
    max_links: int,
) -> list[tuple[str, str]]:
    parser = LinkExtractor(base_url)
    parser.feed(html)
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for url, text in parser.links:
        if url in seen or url in exclude_exact:
            continue
        if href_contains and not any(pattern in url for pattern in href_contains):
            continue
        seen.add(url)
        links.append((url, text))
        if len(links) >= max_links:
            break
    return links


def _parse_html(html: str) -> dict[str, str]:
    parser = ArticleTextExtractor()
    parser.feed(html)
    text = " ".join(parser.text_parts)
    return {
        "title": parser.title.strip(),
        "description": parser.description.strip(),
        "og_description": parser.og_description.strip(),
        "first_block": " ".join(parser.first_block.split())[:2000],
        "text": " ".join(text.split())[:8000],
    }


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._current_href = ""
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        self._current_href = urljoin(self.base_url, href) if href else ""
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._current_href:
            return
        text = " ".join(part for part in self._current_text if part).strip()
        self.links.append((self._current_href, text))
        self._current_href = ""
        self._current_text = []


class ArticleTextExtractor(HTMLParser):
    TEXT_TAGS = {"h1", "h2", "h3", "p", "li"}
    # 兜底"首段落"排除的非正文标签（script/style 等内嵌代码文本不是段落）
    NON_CONTENT_TAGS = {"script", "style", "title", "noscript", "template", "head"}
    # 首段落兜底的最小长度：过滤导航/按钮等零碎短文本
    FIRST_BLOCK_MIN_LENGTH = 20

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.og_description = ""
        self.first_block = ""
        self.text_parts: list[str] = []
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._tag_stack.append(tag)
        attr_dict: dict[str, Any] = dict(attrs)
        if tag == "meta":
            meta_key = attr_dict.get("name") or attr_dict.get("property") or ""
            content = str(attr_dict.get("content") or "")
            if meta_key == "description" and not self.description:
                self.description = content
            elif meta_key == "og:description" and not self.og_description:
                self.og_description = content

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text or not self._tag_stack:
            return
        current = self._tag_stack[-1]
        if current == "title" and not self.title:
            self.title = text
        elif current in self.TEXT_TAGS:
            self.text_parts.append(text)
        elif (
            not self.first_block
            and current not in self.NON_CONTENT_TAGS
            and len(text) >= self.FIRST_BLOCK_MIN_LENGTH
        ):
            # 兜底"首段落"：div/span 排版页没有 h*/p/li 时取首个成段文本块
            self.first_block = text

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._tag_stack[::-1]:
            while self._tag_stack:
                current = self._tag_stack.pop()
                if current == tag:
                    break
