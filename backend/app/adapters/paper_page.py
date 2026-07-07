from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput
from app.adapters.crawler import (
    LISTING_SCAN_LIMIT,
    _bounded_int,
    _compile_pattern,
    _config_flag,
    _filter_listing_links,
)
from app.adapters.page import _extract_links
from app.models.content import DataSource

DEFAULT_MAX_ITEMS = 20


class PaperPageAdapter:
    """论文列表页适配器（会议 accepted papers / 实验室 publications 页）。

    fetch_config 字段：
    - page_url: 论文列表页地址（回落 listing_url，再回落 data_source.url）
    - href_contains / exclude_exact: 与 page_monitor 同名链接过滤约定
    - link_pattern / link_exclude_pattern: 链接正则 include/exclude（与 crawler 同名约定）
    - max_items: 单次最多抓取论文数，默认 20
    - fetch_detail: 是否抓取论文详情页抽取元数据，默认 true

    详情页尽力抽取 citation_* meta（title/authors/abstract/pdf/doi/日期），
    抽不到时退化为 title+url；PDF 直链不下载正文、直接产出退化条目。
    """

    source_type = "paper_page"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        config = data_source.fetch_config or {}
        page_url = str(
            config.get("page_url") or config.get("listing_url") or data_source.url or "",
        ).strip()
        if not page_url:
            return []
        max_items = _bounded_int(
            config.get("max_items") or config.get("max_links"),
            default=DEFAULT_MAX_ITEMS,
        )
        fetch_detail = _config_flag(config.get("fetch_detail"), default=True)
        include_pattern = _compile_pattern(config.get("link_pattern"))
        exclude_pattern = _compile_pattern(config.get("link_exclude_pattern"))

        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=BROWSER_FETCH_HEADERS,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(page_url)
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
                if not fetch_detail or _is_pdf_url(url):
                    raw_items.append(_link_only_paper_item(page_url, url, link_text))
                    continue
                raw_items.append(
                    await _fetch_paper_detail(client, page_url, url, link_text),
                )
            return raw_items


async def _fetch_paper_detail(
    client: httpx.AsyncClient,
    listing_url: str,
    url: str,
    link_text: str,
) -> RawItemInput:
    response = await client.get(url)
    response.raise_for_status()
    final_url = str(response.url)
    parsed = _parse_paper_page(response.text)
    title = parsed["title"] or link_text or final_url
    abstract = parsed["abstract"]
    pdf_url = urljoin(final_url, parsed["pdf_url"]) if parsed["pdf_url"] else ""
    doi = parsed["doi"]
    entry_key = f"doi:{doi}" if doi else final_url
    raw_payload = {
        "listing_url": listing_url,
        "link_text": link_text,
        "url": url,
        "final_url": final_url,
        "title": title,
        "authors": parsed["authors"],
        "abstract": abstract,
        "pdf_url": pdf_url,
        "doi": doi,
        "publication_date": parsed["publication_date"],
        "text": parsed["text"],
        "meta": parsed["meta"],
    }
    return RawItemInput(
        entry_key=entry_key,
        source_title=title.strip(),
        source_url=final_url,
        raw_content=(abstract or parsed["text"] or title).strip(),
        published_at=_parse_paper_datetime(parsed["publication_date"]),
        raw_payload_json=raw_payload,
        source_specific_json={
            "authors": parsed["authors"],
            "pdf_url": pdf_url,
            "doi": doi,
        },
    )


def _link_only_paper_item(listing_url: str, url: str, link_text: str) -> RawItemInput:
    title = link_text or _title_from_url(url)
    pdf_url = url if _is_pdf_url(url) else ""
    return RawItemInput(
        entry_key=url,
        source_title=title,
        source_url=url,
        raw_content=title,
        raw_payload_json={
            "listing_url": listing_url,
            "link_text": link_text,
            "url": url,
            "title": title,
            "pdf_url": pdf_url,
        },
        source_specific_json={"pdf_url": pdf_url} if pdf_url else {},
    )


def _parse_paper_page(html: str) -> dict[str, Any]:
    parser = PaperMetaExtractor()
    parser.feed(html)
    metas = parser.metas

    def meta_first(*keys: str) -> str:
        for key in keys:
            values = metas.get(key) or []
            if values:
                return values[0].strip()
        return ""

    title = _squash(
        meta_first("citation_title", "og:title", "dc.title")
        or parser.h1
        or parser.title,
    )
    authors = [
        _squash(value)
        for value in (metas.get("citation_author") or metas.get("author") or [])
        if _squash(value)
    ]
    abstract = _squash(
        meta_first("citation_abstract", "dcterms.abstract", "description", "og:description"),
    )
    text = _squash(" ".join(parser.paragraphs))[:8000]
    if not abstract:
        abstract = text[:4000]
    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "pdf_url": meta_first("citation_pdf_url"),
        "doi": meta_first("citation_doi", "dc.identifier"),
        "publication_date": meta_first(
            "citation_publication_date",
            "citation_online_date",
            "article:published_time",
            "dc.date",
        ),
        "text": text,
        "meta": {key: list(values) for key, values in metas.items()},
    }


class PaperMetaExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metas: dict[str, list[str]] = {}
        self.title = ""
        self.h1 = ""
        self.paragraphs: list[str] = []
        self._in_title = False
        self._in_h1 = False
        self._in_p = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_dict: dict[str, Any] = dict(attrs)
        if tag == "meta":
            key = str(attr_dict.get("name") or attr_dict.get("property") or "").strip().lower()
            content = str(attr_dict.get("content") or "").strip()
            if key and content:
                self.metas.setdefault(key, []).append(content)
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "p":
            self._in_p = True

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text
        elif self._in_h1 and not self.h1:
            self.h1 = text
        elif self._in_p:
            self.paragraphs.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "p":
            self._in_p = False


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _title_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    candidate = path.rsplit("/", 1)[-1] if path else ""
    return candidate.replace("-", " ").replace("_", " ").strip() or url


def _parse_paper_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        for pattern in ("%Y/%m/%d", "%Y-%m-%d", "%Y/%m", "%Y"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _squash(value: str) -> str:
    return " ".join((value or "").split())
