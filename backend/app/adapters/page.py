from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput
from app.models.content import DataSource


class PageListingAdapter:
    source_type = "page_monitor"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        page_url = str(config.get("page_url") or data_source.url or "").strip()
        if not page_url:
            return []
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=BROWSER_FETCH_HEADERS,
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
            return [await _fetch_article(client, url, title_hint=title) for url, title in links]


class ManualPageAdapter:
    source_type = "page_manual"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        articles = list(config.get("articles") or [])
        if not articles and data_source.url:
            articles = [{"url": data_source.url}]
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=BROWSER_FETCH_HEADERS,
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
    text = parsed["text"] or parsed["description"] or title
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
            "text": text,
        },
    )


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

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.text_parts: list[str] = []
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._tag_stack.append(tag)
        attr_dict: dict[str, Any] = dict(attrs)
        if tag == "meta" and attr_dict.get("name") == "description":
            self.description = str(attr_dict.get("content") or "")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text or not self._tag_stack:
            return
        current = self._tag_stack[-1]
        if current == "title" and not self.title:
            self.title = text
        elif current in self.TEXT_TAGS:
            self.text_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._tag_stack[::-1]:
            while self._tag_stack:
                current = self._tag_stack.pop()
                if current == tag:
                    break
