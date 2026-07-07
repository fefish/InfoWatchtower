from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from app.adapters.base import BROWSER_FETCH_HEADERS, RawItemInput, SourceFetchContext
from app.core.config import get_settings
from app.models.content import DataSource

ARXIV_API_URL = "https://export.arxiv.org/api/query"
DEFAULT_ARXIV_QUERY = "cat:cs.AI OR cat:cs.CL OR cat:cs.LG"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DEFAULT_OPENALEX_SEARCH = "artificial intelligence"
SEMANTIC_SCHOLAR_BULK_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
DEFAULT_SEMANTIC_SCHOLAR_QUERY = "artificial intelligence"
SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,title,abstract,year,publicationDate,authors,url,venue,externalIds,openAccessPdf"
)
# OpenReview API v2（api2.openreview.net）：GET /notes?content.venueid=<venue>
# 返回 {"notes": [note...], "count": N}；note.content 字段为 {"value": ...} 信封。
OPENREVIEW_NOTES_URL = "https://api2.openreview.net/notes"
OPENREVIEW_SITE_URL = "https://openreview.net"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class PaperApiAdapter:
    source_type = "paper_api"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        return await self._fetch_by_provider(data_source, None)

    async def fetch_with_context(
        self,
        data_source: DataSource,
        context: SourceFetchContext,
    ) -> list[RawItemInput]:
        return await self._fetch_by_provider(data_source, context)

    async def _fetch_by_provider(
        self,
        data_source: DataSource,
        context: SourceFetchContext | None,
    ) -> list[RawItemInput]:
        provider = detect_paper_provider(data_source)
        if provider == "arxiv":
            return await self._fetch_arxiv(data_source, context)
        if provider == "openalex":
            return await self._fetch_openalex(data_source, context)
        if provider == "semantic_scholar":
            return await self._fetch_semantic_scholar(data_source, context)
        if provider == "openreview":
            return await self._fetch_openreview(data_source, context)
        raise ValueError(f"paper_api provider is not implemented: {provider}")

    async def _fetch_arxiv(
        self,
        data_source: DataSource,
        context: SourceFetchContext | None,
    ) -> list[RawItemInput]:
        endpoint, params = build_arxiv_request(data_source, context)
        headers = {
            **BROWSER_FETCH_HEADERS,
            "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
        return parse_arxiv_atom(response.text)

    async def _fetch_openalex(
        self,
        data_source: DataSource,
        context: SourceFetchContext | None,
    ) -> list[RawItemInput]:
        endpoint, params = build_openalex_request(data_source, context)
        headers = {
            **BROWSER_FETCH_HEADERS,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
        return parse_openalex_works(response.json())

    async def _fetch_semantic_scholar(
        self,
        data_source: DataSource,
        context: SourceFetchContext | None,
    ) -> list[RawItemInput]:
        endpoint, params = build_semantic_scholar_request(data_source, context)
        headers = {
            **BROWSER_FETCH_HEADERS,
            "Accept": "application/json",
        }
        api_key = get_settings().semantic_scholar_api_key.strip()
        if api_key:
            headers["x-api-key"] = api_key
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
        return parse_semantic_scholar_papers(response.json())

    async def _fetch_openreview(
        self,
        data_source: DataSource,
        context: SourceFetchContext | None,
    ) -> list[RawItemInput]:
        endpoint, params = build_openreview_request(data_source, context)
        headers = {
            **BROWSER_FETCH_HEADERS,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
            trust_env=False,
            transport=self._transport,
        ) as client:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
        items = parse_openreview_notes(response.json())
        # notes API 没有发布日期过滤参数，历史回补窗口只能在解析后按
        # pdate/cdate 客户端过滤（无日期的 note 保留，避免静默漏采）。
        return _filter_by_target_window(items, context)


def detect_paper_provider(data_source: DataSource) -> str:
    config = _paper_config(data_source)
    parsed = urlparse(str(data_source.url or ""))
    url_params = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    explicit = _normalize_provider(config.get("provider") or url_params.get("provider") or "")
    if explicit:
        return explicit
    host = parsed.netloc.lower()
    if host.endswith("api.openalex.org"):
        return "openalex"
    if host.endswith("api.semanticscholar.org") or host.endswith("semanticscholar.org"):
        return "semantic_scholar"
    if host.endswith("openreview.net"):
        return "openreview"
    if host.endswith("export.arxiv.org") or host.endswith("arxiv.org"):
        return "arxiv"
    return "arxiv"


def build_arxiv_request(
    data_source: DataSource,
    context: SourceFetchContext | None = None,
) -> tuple[str, dict[str, str]]:
    config = _paper_config(data_source)
    parsed = urlparse(str(data_source.url or ""))
    url_params = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    endpoint = str(config.get("api_url") or _url_without_query(data_source.url) or ARXIV_API_URL)
    provider = detect_paper_provider(data_source)
    if provider != "arxiv":
        raise ValueError(f"paper_api provider is not implemented: {provider}")

    base_query = str(
        config.get("search_query")
        or url_params.get("search_query")
        or _query_from_categories(config)
        or DEFAULT_ARXIV_QUERY,
    ).strip()
    search_query = _query_with_target_window(base_query, context)

    params = {
        "search_query": search_query,
        "start": str(config.get("start") or url_params.get("start") or "0"),
        "max_results": str(_bounded_int(config.get("max_results") or url_params.get("max_results"), default=50)),
        "sortBy": str(config.get("sortBy") or config.get("sort_by") or url_params.get("sortBy") or "submittedDate"),
        "sortOrder": str(config.get("sortOrder") or config.get("sort_order") or url_params.get("sortOrder") or "descending"),
    }
    return endpoint, params


def build_openalex_request(
    data_source: DataSource,
    context: SourceFetchContext | None = None,
) -> tuple[str, dict[str, str]]:
    config = _paper_config(data_source)
    parsed = urlparse(str(data_source.url or ""))
    url_params = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    endpoint = str(config.get("api_url") or _url_without_query(data_source.url) or OPENALEX_WORKS_URL)
    params = dict(url_params)
    params.pop("provider", None)
    search = str(
        config.get("search")
        or config.get("search_query")
        or params.pop("search_query", "")
        or params.get("search")
        or DEFAULT_OPENALEX_SEARCH,
    ).strip()
    if search:
        params["search"] = search
    params["filter"] = _openalex_filter_with_target_window(
        str(config.get("filter") or params.get("filter") or "").strip(),
        context,
    )
    if not params["filter"]:
        params.pop("filter", None)
    params["per_page"] = str(
        _bounded_int(config.get("per_page") or params.get("per_page") or config.get("max_results"), default=50),
    )
    params["sort"] = str(config.get("sort") or params.get("sort") or "publication_date:desc")
    return endpoint, params


def build_semantic_scholar_request(
    data_source: DataSource,
    context: SourceFetchContext | None = None,
) -> tuple[str, dict[str, str]]:
    config = _paper_config(data_source)
    parsed = urlparse(str(data_source.url or ""))
    url_params = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    endpoint = str(
        config.get("api_url")
        or _url_without_query(data_source.url)
        or SEMANTIC_SCHOLAR_BULK_SEARCH_URL,
    )
    params = dict(url_params)
    params.pop("provider", None)
    query = str(
        config.get("query")
        or config.get("search_query")
        or params.pop("search_query", "")
        or params.get("query")
        or DEFAULT_SEMANTIC_SCHOLAR_QUERY,
    ).strip()
    params["query"] = query
    params["fields"] = str(config.get("fields") or params.get("fields") or SEMANTIC_SCHOLAR_FIELDS)
    params["limit"] = str(
        _bounded_int(config.get("limit") or params.get("limit") or config.get("max_results"), default=50),
    )
    publication_window = _semantic_scholar_publication_window(
        str(
            config.get("publicationDateOrYear")
            or config.get("publication_date_or_year")
            or params.get("publicationDateOrYear")
            or "",
        ).strip(),
        context,
    )
    if publication_window:
        params["publicationDateOrYear"] = publication_window
    sort = str(config.get("sort") or params.get("sort") or "").strip()
    if sort:
        params["sort"] = sort
    return endpoint, params


def build_openreview_request(
    data_source: DataSource,
    context: SourceFetchContext | None = None,
) -> tuple[str, dict[str, str]]:
    """OpenReview provider：venue 查询 → notes 列表。

    fetch_config 字段：
    - venue / venueid: 会议 venue id（如 "ICLR.cc/2026/Conference"），映射到
      notes API 的 content.venueid 过滤参数；
    - invitation: 备选过滤方式（如 "ICLR.cc/2026/Conference/-/Submission"）；
    - api_url: notes 端点覆盖（默认 https://api2.openreview.net/notes）；
    - limit / max_results: 单次条数上限（默认 50，上限 200）；
    - sort: 排序（默认 cdate:desc）。
    """
    config = _paper_config(data_source)
    parsed = urlparse(str(data_source.url or ""))
    url_params = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    endpoint = str(
        config.get("api_url")
        or _url_without_query(data_source.url)
        or OPENREVIEW_NOTES_URL,
    )
    params = dict(url_params)
    params.pop("provider", None)
    venue = str(
        config.get("venueid")
        or config.get("venue")
        or params.pop("venueid", "")
        or params.pop("venue", "")
        or params.get("content.venueid")
        or "",
    ).strip()
    if venue:
        params["content.venueid"] = venue
    invitation = str(config.get("invitation") or params.get("invitation") or "").strip()
    if invitation:
        params["invitation"] = invitation
    if not params.get("content.venueid") and not params.get("invitation"):
        raise ValueError(
            "paper_api openreview requires fetch_config.venue/venueid "
            "(e.g. ICLR.cc/2026/Conference) or invitation",
        )
    params["limit"] = str(
        _bounded_int(config.get("limit") or config.get("max_results") or params.get("limit"), default=50),
    )
    params["sort"] = str(config.get("sort") or params.get("sort") or "cdate:desc")
    return endpoint, params


def parse_openreview_notes(payload: dict[str, Any]) -> list[RawItemInput]:
    notes = payload.get("notes")
    if not isinstance(notes, list):
        return []
    raw_items: list[RawItemInput] = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        content = note.get("content") if isinstance(note.get("content"), dict) else {}
        note_id = str(note.get("id") or "").strip()
        forum = str(note.get("forum") or "").strip() or note_id
        title = _squash(_openreview_field(content, "title"))
        abstract = _squash(_openreview_field(content, "abstract"))
        venue = _openreview_field(content, "venue")
        venueid = _openreview_field(content, "venueid")
        authors = _openreview_authors(content)
        pdf_url = _openreview_pdf_url(content)
        source_url = f"{OPENREVIEW_SITE_URL}/forum?id={forum}" if forum else None
        published_at = _parse_epoch_millis(note.get("pdate")) or _parse_epoch_millis(
            note.get("cdate"),
        )
        raw_payload = {
            "provider": "openreview",
            "note_id": note_id,
            "forum": forum,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "venue": venue,
            "venueid": venueid,
            "source_url": source_url,
            "pdf_url": pdf_url,
            "cdate": note.get("cdate"),
            "pdate": note.get("pdate"),
            "payload": note,
        }
        raw_items.append(
            RawItemInput(
                entry_key=f"openreview:{note_id}" if note_id else title,
                source_title=title or note_id,
                source_url=source_url,
                raw_content=abstract or title,
                published_at=published_at,
                raw_payload_json=raw_payload,
                source_specific_json={
                    "provider": "openreview",
                    "note_id": note_id,
                    "forum": forum,
                    "venue": venue,
                    "venueid": venueid,
                    "pdf_url": pdf_url,
                },
            ),
        )
    return raw_items


def _filter_by_target_window(
    items: list[RawItemInput],
    context: SourceFetchContext | None,
) -> list[RawItemInput]:
    if not context or context.target_day_start is None or context.target_day_end is None:
        return items
    return [
        item
        for item in items
        if item.published_at is None
        or context.target_day_start <= item.published_at.date() <= context.target_day_end
    ]


def parse_arxiv_atom(xml_text: str) -> list[RawItemInput]:
    root = ElementTree.fromstring(xml_text.encode("utf-8"))
    raw_items: list[RawItemInput] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        entry_id = _child_text(entry, "id")
        arxiv_id = _arxiv_id(entry_id)
        title = _squash(_child_text(entry, "title"))
        summary = _squash(_child_text(entry, "summary"))
        published_text = _child_text(entry, "published")
        updated_text = _child_text(entry, "updated")
        authors = [
            _squash(_child_text(author, "name"))
            for author in entry.findall(f"{ATOM_NS}author")
            if _squash(_child_text(author, "name"))
        ]
        categories = [
            str(category.attrib.get("term") or "").strip()
            for category in entry.findall(f"{ATOM_NS}category")
            if str(category.attrib.get("term") or "").strip()
        ]
        primary_category_node = entry.find(f"{ARXIV_NS}primary_category")
        primary_category = ""
        if primary_category_node is not None:
            primary_category = str(primary_category_node.attrib.get("term") or "").strip()
        links = _links(entry)
        source_url = links.get("alternate") or entry_id or None
        pdf_url = links.get("pdf") or None
        raw_payload = {
            "provider": "arxiv",
            "entry_id": entry_id,
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "authors": authors,
            "categories": categories,
            "primary_category": primary_category,
            "published": published_text,
            "updated": updated_text,
            "source_url": source_url,
            "pdf_url": pdf_url,
            "doi": _child_text(entry, "doi", namespace=ARXIV_NS),
            "comment": _child_text(entry, "comment", namespace=ARXIV_NS),
            "journal_ref": _child_text(entry, "journal_ref", namespace=ARXIV_NS),
            "links": links,
        }
        raw_items.append(
            RawItemInput(
                entry_key=f"arxiv:{arxiv_id}" if arxiv_id else entry_id or title,
                source_title=title or arxiv_id or entry_id,
                source_url=source_url,
                raw_content=summary or title,
                published_at=_parse_atom_datetime(published_text) or _parse_atom_datetime(updated_text),
                raw_payload_json=raw_payload,
                source_specific_json={"provider": "arxiv", "primary_category": primary_category},
            ),
        )
    return raw_items


def parse_openalex_works(payload: dict[str, Any]) -> list[RawItemInput]:
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    raw_items: list[RawItemInput] = []
    for work in results:
        if not isinstance(work, dict):
            continue
        openalex_id = _openalex_id(work)
        doi = str(work.get("doi") or (work.get("ids") or {}).get("doi") or "").strip()
        title = _squash(str(work.get("display_name") or work.get("title") or ""))
        abstract = _squash(_openalex_abstract(work.get("abstract_inverted_index")))
        authors = _openalex_authors(work)
        topics = _openalex_topics(work)
        publication_date = str(work.get("publication_date") or "").strip()
        source_url = _openalex_source_url(work, doi, openalex_id)
        primary_location = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
        source = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
        raw_payload = {
            "provider": "openalex",
            "openalex_id": openalex_id,
            "doi": doi,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "topics": topics,
            "publication_date": publication_date,
            "publication_year": work.get("publication_year"),
            "type": work.get("type"),
            "source_url": source_url,
            "source_display_name": source.get("display_name") if isinstance(source, dict) else "",
            "open_access": work.get("open_access"),
            "primary_location": work.get("primary_location"),
            "best_oa_location": work.get("best_oa_location"),
            "payload": work,
        }
        raw_items.append(
            RawItemInput(
                entry_key=_openalex_entry_key(openalex_id, doi, title),
                source_title=title or openalex_id or doi,
                source_url=source_url,
                raw_content=abstract or title,
                published_at=_parse_publication_date(publication_date),
                raw_payload_json=raw_payload,
                source_specific_json={
                    "provider": "openalex",
                    "openalex_id": openalex_id,
                    "doi": doi,
                    "type": str(work.get("type") or ""),
                    "topics": topics[:8],
                    "source_display_name": str(source.get("display_name") or "") if isinstance(source, dict) else "",
                },
            ),
        )
    return raw_items


def parse_semantic_scholar_papers(payload: dict[str, Any]) -> list[RawItemInput]:
    papers = payload.get("data")
    if not isinstance(papers, list):
        return []
    raw_items: list[RawItemInput] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        paper_id = str(paper.get("paperId") or "").strip()
        external_ids = paper.get("externalIds") if isinstance(paper.get("externalIds"), dict) else {}
        doi = str(external_ids.get("DOI") or "").strip()
        arxiv_id = str(external_ids.get("ArXiv") or "").strip()
        corpus_id = str(external_ids.get("CorpusId") or "").strip()
        title = _squash(str(paper.get("title") or ""))
        abstract = _squash(str(paper.get("abstract") or ""))
        authors = _semantic_scholar_authors(paper)
        publication_date = str(paper.get("publicationDate") or "").strip()
        source_url = _semantic_scholar_source_url(paper, doi, arxiv_id, paper_id)
        open_access_pdf = paper.get("openAccessPdf") if isinstance(paper.get("openAccessPdf"), dict) else {}
        pdf_url = str(open_access_pdf.get("url") or "").strip() if isinstance(open_access_pdf, dict) else ""
        raw_payload = {
            "provider": "semantic_scholar",
            "paper_id": paper_id,
            "corpus_id": corpus_id,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "venue": str(paper.get("venue") or ""),
            "year": paper.get("year"),
            "publication_date": publication_date,
            "source_url": source_url,
            "pdf_url": pdf_url,
            "open_access_pdf": open_access_pdf,
            "external_ids": external_ids,
            "payload": paper,
        }
        raw_items.append(
            RawItemInput(
                entry_key=_semantic_scholar_entry_key(paper_id, doi, arxiv_id, title),
                source_title=title or paper_id or doi,
                source_url=source_url,
                raw_content=abstract or title,
                published_at=_parse_publication_date(publication_date),
                raw_payload_json=raw_payload,
                source_specific_json={
                    "provider": "semantic_scholar",
                    "paper_id": paper_id,
                    "corpus_id": corpus_id,
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "venue": str(paper.get("venue") or ""),
                    "year": paper.get("year"),
                },
            ),
        )
    return raw_items


def _paper_config(data_source: DataSource) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if isinstance(data_source.paper_config, dict):
        config.update(data_source.paper_config)
    if isinstance(data_source.fetch_config, dict):
        config.update(data_source.fetch_config)
    return config


def _normalize_provider(value: object) -> str:
    provider = str(value or "").strip().lower().replace("-", "_")
    if provider in {"semanticscholar", "s2", "semantic"}:
        return "semantic_scholar"
    return provider


def _url_without_query(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _query_from_categories(config: dict[str, Any]) -> str:
    categories = [str(category).strip() for category in config.get("categories") or [] if str(category).strip()]
    if not categories:
        return ""
    return " OR ".join(f"cat:{category}" for category in categories)


def _query_with_target_window(base_query: str, context: SourceFetchContext | None) -> str:
    if not context or context.target_day_start is None or context.target_day_end is None:
        return base_query
    if "submittedDate:" in base_query:
        return base_query
    date_query = (
        f"submittedDate:[{_arxiv_day_start(context.target_day_start)} "
        f"TO {_arxiv_day_end(context.target_day_end)}]"
    )
    if not base_query:
        return date_query
    return f"({base_query}) AND {date_query}"


def _openalex_filter_with_target_window(base_filter: str, context: SourceFetchContext | None) -> str:
    filters = [part.strip() for part in base_filter.split(",") if part.strip()]
    joined = ",".join(filters)
    if context and context.target_day_start is not None and context.target_day_end is not None:
        if "from_publication_date:" not in joined:
            filters.append(f"from_publication_date:{context.target_day_start.isoformat()}")
        if "to_publication_date:" not in joined:
            filters.append(f"to_publication_date:{context.target_day_end.isoformat()}")
    return ",".join(filters)


def _semantic_scholar_publication_window(
    base_window: str,
    context: SourceFetchContext | None,
) -> str:
    if base_window:
        return base_window
    if not context or context.target_day_start is None or context.target_day_end is None:
        return ""
    return f"{context.target_day_start.isoformat()}:{context.target_day_end.isoformat()}"


def _arxiv_day_start(value: date) -> str:
    return value.strftime("%Y%m%d0000")


def _arxiv_day_end(value: date) -> str:
    return value.strftime("%Y%m%d2359")


def _bounded_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), 200)


def _child_text(node: ElementTree.Element, tag: str, *, namespace: str = ATOM_NS) -> str:
    child = node.find(f"{namespace}{tag}")
    return (child.text or "").strip() if child is not None else ""


def _links(entry: ElementTree.Element) -> dict[str, str]:
    links: dict[str, str] = {}
    for link in entry.findall(f"{ATOM_NS}link"):
        href = str(link.attrib.get("href") or "").strip()
        if not href:
            continue
        rel = str(link.attrib.get("rel") or "").strip() or "alternate"
        title = str(link.attrib.get("title") or "").strip()
        mime_type = str(link.attrib.get("type") or "").strip()
        if title == "pdf" or mime_type == "application/pdf":
            links["pdf"] = href
        elif rel == "alternate":
            links["alternate"] = href
        else:
            links[rel] = href
    return links


def _parse_atom_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_publication_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return datetime.combine(parsed, time.min, tzinfo=UTC)


def _arxiv_id(entry_id: str) -> str:
    value = (entry_id or "").strip().rstrip("/")
    if not value:
        return ""
    return value.rsplit("/", 1)[-1]


def _openalex_id(work: dict[str, Any]) -> str:
    value = str(work.get("id") or (work.get("ids") or {}).get("openalex") or "").strip().rstrip("/")
    if not value:
        return ""
    return value.rsplit("/", 1)[-1]


def _openalex_entry_key(openalex_id: str, doi: str, title: str) -> str:
    if openalex_id:
        return f"openalex:{openalex_id}"
    if doi:
        return f"doi:{doi.removeprefix('https://doi.org/')}"
    return title


def _openalex_abstract(inverted_index: object) -> str:
    if not isinstance(inverted_index, dict):
        return ""
    words_by_position: dict[int, str] = {}
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            try:
                words_by_position[int(position)] = str(word)
            except (TypeError, ValueError):
                continue
    return " ".join(words_by_position[index] for index in sorted(words_by_position))


def _openalex_authors(work: dict[str, Any]) -> list[str]:
    authors: list[str] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if not isinstance(author, dict):
            continue
        name = _squash(str(author.get("display_name") or ""))
        if name:
            authors.append(name)
    return authors


def _openalex_topics(work: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    primary_topic = work.get("primary_topic")
    if isinstance(primary_topic, dict):
        primary_name = _squash(str(primary_topic.get("display_name") or ""))
        if primary_name:
            topics.append(primary_name)
    for topic in work.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        name = _squash(str(topic.get("display_name") or ""))
        if name and name not in topics:
            topics.append(name)
    return topics


def _openalex_source_url(work: dict[str, Any], doi: str, openalex_id: str) -> str | None:
    for location_key in ("primary_location", "best_oa_location"):
        location = work.get(location_key)
        if not isinstance(location, dict):
            continue
        landing_page_url = str(location.get("landing_page_url") or "").strip()
        if landing_page_url:
            return landing_page_url
    if doi:
        return doi
    if openalex_id:
        return f"https://openalex.org/{openalex_id}"
    return None


def _openreview_field(content: dict[str, Any] | Any, key: str) -> str:
    """OpenReview API v2 的 content 字段是 {"value": ...} 信封；v1 为裸值，两者都兼容。"""
    if not isinstance(content, dict):
        return ""
    value = content.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def _openreview_authors(content: dict[str, Any] | Any) -> list[str]:
    if not isinstance(content, dict):
        return []
    value = content.get("authors")
    if isinstance(value, dict):
        value = value.get("value")
    if not isinstance(value, list):
        return []
    return [_squash(str(author)) for author in value if _squash(str(author))]


def _openreview_pdf_url(content: dict[str, Any] | Any) -> str:
    pdf = _openreview_field(content, "pdf")
    if not pdf:
        return ""
    if pdf.startswith(("http://", "https://")):
        return pdf
    # v2 的 pdf 是站内相对路径（如 /pdf/xxx.pdf）
    return f"{OPENREVIEW_SITE_URL}/{pdf.lstrip('/')}"


def _parse_epoch_millis(value: Any) -> datetime | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _semantic_scholar_entry_key(paper_id: str, doi: str, arxiv_id: str, title: str) -> str:
    if paper_id:
        return f"semantic_scholar:{paper_id}"
    if doi:
        return f"doi:{doi.removeprefix('https://doi.org/')}"
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return title


def _semantic_scholar_authors(paper: dict[str, Any]) -> list[str]:
    authors: list[str] = []
    for author in paper.get("authors") or []:
        if not isinstance(author, dict):
            continue
        name = _squash(str(author.get("name") or ""))
        if name:
            authors.append(name)
    return authors


def _semantic_scholar_source_url(
    paper: dict[str, Any],
    doi: str,
    arxiv_id: str,
    paper_id: str,
) -> str | None:
    url = str(paper.get("url") or "").strip()
    if url:
        return url
    if doi:
        return f"https://doi.org/{doi.removeprefix('https://doi.org/')}"
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    if paper_id:
        return f"https://www.semanticscholar.org/paper/{paper_id}"
    return None


def _squash(value: str) -> str:
    return " ".join((value or "").split())
