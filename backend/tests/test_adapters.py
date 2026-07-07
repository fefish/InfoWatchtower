from datetime import UTC, datetime

import httpx
import pytest

from app.adapters import create_default_registry
from app.adapters.page import _extract_links, _parse_html, _parse_iso_datetime
from app.adapters.paper import (
    build_arxiv_request,
    build_openalex_request,
    build_semantic_scholar_request,
    detect_paper_provider,
    parse_arxiv_atom,
    parse_openalex_works,
    parse_semantic_scholar_papers,
)
from app.adapters.rss import RssFeedAdapter
from app.adapters.base import SourceFetchContext
from app.models.content import DataSource


def test_default_adapter_registry_contains_first_phase_source_types():
    registry = create_default_registry()

    assert registry.list_types() == [
        "crawler",
        "csv",
        "internal",
        "manual",
        "page_manual",
        "page_monitor",
        "paper_api",
        "paper_page",
        "paper_rss",
        "rss",
        "wechat",
        "wiseflow",
    ]


def test_default_adapter_registry_uses_real_implementations_for_former_stub_types():
    registry = create_default_registry()

    assert type(registry.get("wiseflow")).__module__ == "app.adapters.wiseflow"
    assert type(registry.get("crawler")).__module__ == "app.adapters.crawler"
    assert type(registry.get("csv")).__module__ == "app.adapters.csv_file"
    assert type(registry.get("paper_page")).__module__ == "app.adapters.paper_page"
    assert type(registry.get("manual")).__module__ == "app.adapters.push_based"
    assert type(registry.get("internal")).__module__ == "app.adapters.push_based"
    assert type(registry.get("wechat")).__module__ == "app.adapters.wechat"
    # manual/internal 是推入式语义：fetch 返回空而非抛 AdapterNotImplementedError
    assert getattr(registry.get("manual"), "push_based", False) is True
    assert getattr(registry.get("internal"), "push_based", False) is True


@pytest.mark.asyncio
async def test_stub_module_keeps_unimplemented_semantics_for_run_layer_regression():
    # tests/test_ingestion_runs.py 显式注册 stubs.WiseflowReadInfoAdapter 验证
    # skipped_unimplemented 语义；stub 类必须继续抛 AdapterNotImplementedError。
    from app.adapters.base import AdapterNotImplementedError
    from app.adapters.stubs import WiseflowReadInfoAdapter as StubWiseflowAdapter

    stub = StubWiseflowAdapter()
    source = DataSource(source_type="wiseflow", name="Stub", url=None, fetch_config={})
    with pytest.raises(AdapterNotImplementedError):
        await stub.fetch(source)


def test_rss_adapter_payload_is_json_safe():
    adapter = RssFeedAdapter()
    raw_item = adapter._entry_to_raw_item(
        {
            "id": "1",
            "title": "Example",
            "link": "https://example.com/1",
            "published": "Tue, 05 May 2026 08:00:00 GMT",
            "published_parsed": (2026, 5, 5, 8, 0, 0, 1, 125, 0),
            "nested": {"value": object()},
        },
    )

    assert raw_item.raw_payload_json["nested"]["value"].startswith("<object object at")


def test_rss_adapter_parses_iso_published_datetime():
    adapter = RssFeedAdapter()
    raw_item = adapter._entry_to_raw_item(
        {
            "id": "yt:1",
            "title": "YouTube style timestamp",
            "link": "https://example.com/yt",
            "published": "2025-12-14T16:22:15+00:00",
            "summary": "Body",
        },
    )

    assert raw_item.published_at == datetime(2025, 12, 14, 16, 22, 15, tzinfo=UTC)


def test_rss_adapter_parses_feedparser_struct_time_when_string_is_missing():
    adapter = RssFeedAdapter()
    raw_item = adapter._entry_to_raw_item(
        {
            "id": "parsed:1",
            "title": "Parsed timestamp",
            "link": "https://example.com/parsed",
            "published_parsed": (2026, 5, 10, 8, 30, 0, 6, 130, 0),
            "summary": "Body",
        },
    )

    assert raw_item.published_at == datetime(2026, 5, 10, 8, 30, tzinfo=UTC)


def test_page_link_extractor_filters_and_absolutizes_listing_links():
    html = """
    <a href="/news/launch">Launch</a>
    <a href="https://example.com/news">Index</a>
    <a href="/about">About</a>
    <a href="/news/launch">Duplicate</a>
    """

    links = _extract_links(
        html=html,
        base_url="https://example.com/news",
        href_contains=["/news/"],
        exclude_exact={"https://example.com/news"},
        max_links=5,
    )

    assert links == [("https://example.com/news/launch", "Launch")]


def test_page_html_parser_extracts_title_description_and_body_text():
    parsed = _parse_html(
        """
        <html>
          <head>
            <title>Example Article</title>
            <meta name="description" content="Short description">
          </head>
          <body><h1>Headline</h1><p>First paragraph.</p><script>ignore()</script></body>
        </html>
        """,
    )

    assert parsed["title"] == "Example Article"
    assert parsed["description"] == "Short description"
    assert "Headline First paragraph." in parsed["text"]
    assert "ignore" not in parsed["text"]


def test_page_created_hint_parses_iso_datetime_as_utc():
    parsed = _parse_iso_datetime("2026-04-30T08:00:00Z")

    assert parsed is not None
    assert parsed.isoformat() == "2026-04-30T08:00:00+00:00"


def test_resolve_feed_url_rewrites_public_rsshub_to_configured_instance(monkeypatch):
    from app.adapters.rss import resolve_feed_url
    from app.core.config import get_settings

    monkeypatch.setenv("RSSHUB_BASE_URL", "https://rsshub.internal.example:1200")
    get_settings.cache_clear()
    try:
        assert (
            resolve_feed_url("https://rsshub.app/twitter/user/openai")
            == "https://rsshub.internal.example:1200/twitter/user/openai"
        )
        assert resolve_feed_url("https://example.com/feed.xml") == "https://example.com/feed.xml"
    finally:
        monkeypatch.delenv("RSSHUB_BASE_URL", raising=False)
        get_settings.cache_clear()


def test_resolve_feed_url_keeps_public_rsshub_without_configuration(monkeypatch):
    from app.adapters.rss import resolve_feed_url
    from app.core.config import get_settings

    monkeypatch.delenv("RSSHUB_BASE_URL", raising=False)
    get_settings.cache_clear()
    assert resolve_feed_url("https://rsshub.app/x/user/openai") == "https://rsshub.app/x/user/openai"


def test_arxiv_request_adds_backfill_submitted_date_window():
    source = DataSource(
        source_type="paper_api",
        name="arXiv AI",
        url="https://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=25",
        fetch_config={},
    )

    endpoint, params = build_arxiv_request(
        source,
        SourceFetchContext(
            mode="paper_api",
            target_day_start=datetime(2026, 5, 10, tzinfo=UTC).date(),
            target_day_end=datetime(2026, 5, 12, tzinfo=UTC).date(),
        ),
    )

    assert endpoint == "https://export.arxiv.org/api/query"
    assert params["max_results"] == "25"
    assert params["sortBy"] == "submittedDate"
    assert params["sortOrder"] == "descending"
    assert params["search_query"] == "(cat:cs.AI) AND submittedDate:[202605100000 TO 202605122359]"


def test_paper_api_detects_openalex_provider_from_url():
    source = DataSource(
        source_type="paper_api",
        name="OpenAlex AI",
        url="https://api.openalex.org/works?search=multi-agent",
        fetch_config={},
    )

    assert detect_paper_provider(source) == "openalex"


def test_paper_api_detects_semantic_scholar_provider_from_url():
    source = DataSource(
        source_type="paper_api",
        name="Semantic Scholar AI",
        url="https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=agent%20memory",
        fetch_config={},
    )

    assert detect_paper_provider(source) == "semantic_scholar"


def test_openalex_request_adds_backfill_publication_date_window():
    source = DataSource(
        source_type="paper_api",
        name="OpenAlex AI",
        url="https://api.openalex.org/works?search=agent%20memory&filter=type:article&per_page=25",
        fetch_config={},
    )

    endpoint, params = build_openalex_request(
        source,
        SourceFetchContext(
            mode="paper_api",
            target_day_start=datetime(2026, 5, 10, tzinfo=UTC).date(),
            target_day_end=datetime(2026, 5, 12, tzinfo=UTC).date(),
        ),
    )

    assert endpoint == "https://api.openalex.org/works"
    assert params["search"] == "agent memory"
    assert params["per_page"] == "25"
    assert params["sort"] == "publication_date:desc"
    assert params["filter"] == (
        "type:article,from_publication_date:2026-05-10,to_publication_date:2026-05-12"
    )


def test_semantic_scholar_request_adds_backfill_publication_date_window():
    source = DataSource(
        source_type="paper_api",
        name="Semantic Scholar AI",
        url="https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=agent%20memory&limit=25",
        fetch_config={},
    )

    endpoint, params = build_semantic_scholar_request(
        source,
        SourceFetchContext(
            mode="paper_api",
            target_day_start=datetime(2026, 5, 10, tzinfo=UTC).date(),
            target_day_end=datetime(2026, 5, 12, tzinfo=UTC).date(),
        ),
    )

    assert endpoint == "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
    assert params["query"] == "agent memory"
    assert params["limit"] == "25"
    assert "paperId,title,abstract" in params["fields"]
    assert params["publicationDateOrYear"] == "2026-05-10:2026-05-12"


def test_openalex_parser_preserves_work_payload_and_reconstructs_abstract():
    raw_items = parse_openalex_works(
        {
            "results": [
                {
                    "id": "https://openalex.org/W1234567890",
                    "doi": "https://doi.org/10.1234/openalex-demo",
                    "display_name": "Agent Memory Systems",
                    "publication_date": "2026-05-10",
                    "publication_year": 2026,
                    "type": "article",
                    "abstract_inverted_index": {
                        "Memory": [1],
                        "systems": [2],
                        "Agent": [0],
                        "coordinate": [3],
                        "tools": [4],
                    },
                    "authorships": [
                        {"author": {"display_name": "Alice Example"}},
                        {"author": {"display_name": "Bob Example"}},
                    ],
                    "primary_topic": {"display_name": "Artificial intelligence"},
                    "topics": [
                        {"display_name": "Artificial intelligence"},
                        {"display_name": "Software engineering"},
                    ],
                    "primary_location": {
                        "landing_page_url": "https://example.org/paper",
                        "source": {"display_name": "Example Journal"},
                    },
                    "open_access": {"is_oa": True},
                }
            ]
        },
    )

    assert len(raw_items) == 1
    item = raw_items[0]
    assert item.entry_key == "openalex:W1234567890"
    assert item.source_title == "Agent Memory Systems"
    assert item.source_url == "https://example.org/paper"
    assert item.raw_content == "Agent Memory systems coordinate tools"
    assert item.published_at == datetime(2026, 5, 10, tzinfo=UTC)
    assert item.raw_payload_json["provider"] == "openalex"
    assert item.raw_payload_json["payload"]["id"] == "https://openalex.org/W1234567890"
    assert item.raw_payload_json["authors"] == ["Alice Example", "Bob Example"]
    assert item.raw_payload_json["topics"] == ["Artificial intelligence", "Software engineering"]
    assert item.source_specific_json["source_display_name"] == "Example Journal"


def test_semantic_scholar_parser_preserves_paper_payload():
    raw_items = parse_semantic_scholar_papers(
        {
            "data": [
                {
                    "paperId": "00b73d9fd2d5b971dc5322e71d6e4202ed2ac678",
                    "externalIds": {
                        "ArXiv": "2605.21224",
                        "DOI": "10.1109/example",
                        "CorpusId": 289840112,
                    },
                    "url": "https://www.semanticscholar.org/paper/00b73d9fd2d5b971dc5322e71d6e4202ed2ac678",
                    "title": "Phishing Email Detection with AI",
                    "venue": "Example Conference",
                    "year": 2026,
                    "publicationDate": "2026-05-11",
                    "authors": [
                        {"authorId": "1", "name": "Alice Example"},
                        {"authorId": "2", "name": "Bob Example"},
                    ],
                    "abstract": "A study of phishing detection using AI systems.",
                    "openAccessPdf": {
                        "url": "https://example.org/paper.pdf",
                        "status": "GOLD",
                        "license": "CCBY",
                    },
                }
            ]
        },
    )

    assert len(raw_items) == 1
    item = raw_items[0]
    assert item.entry_key == "semantic_scholar:00b73d9fd2d5b971dc5322e71d6e4202ed2ac678"
    assert item.source_title == "Phishing Email Detection with AI"
    assert item.source_url == "https://www.semanticscholar.org/paper/00b73d9fd2d5b971dc5322e71d6e4202ed2ac678"
    assert item.raw_content == "A study of phishing detection using AI systems."
    assert item.published_at == datetime(2026, 5, 11, tzinfo=UTC)
    assert item.raw_payload_json["provider"] == "semantic_scholar"
    assert item.raw_payload_json["authors"] == ["Alice Example", "Bob Example"]
    assert item.raw_payload_json["pdf_url"] == "https://example.org/paper.pdf"
    assert item.raw_payload_json["payload"]["externalIds"]["CorpusId"] == 289840112
    assert item.source_specific_json["venue"] == "Example Conference"


def test_arxiv_atom_parser_preserves_paper_metadata():
    raw_items = parse_arxiv_atom(
        """
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>http://arxiv.org/abs/2605.12345v1</id>
            <updated>2026-05-11T12:30:00Z</updated>
            <published>2026-05-10T08:00:00Z</published>
            <title>  An Agentic System for Planning  </title>
            <summary>
              We describe a planning agent with tool use.
            </summary>
            <author><name>Alice Example</name></author>
            <author><name>Bob Example</name></author>
            <arxiv:primary_category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
            <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
            <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
            <arxiv:doi>10.1234/example</arxiv:doi>
            <link href="http://arxiv.org/abs/2605.12345v1" rel="alternate" type="text/html"/>
            <link title="pdf" href="http://arxiv.org/pdf/2605.12345v1" rel="related" type="application/pdf"/>
          </entry>
        </feed>
        """,
    )

    assert len(raw_items) == 1
    item = raw_items[0]
    assert item.entry_key == "arxiv:2605.12345v1"
    assert item.source_title == "An Agentic System for Planning"
    assert item.source_url == "http://arxiv.org/abs/2605.12345v1"
    assert item.published_at == datetime(2026, 5, 10, 8, tzinfo=UTC)
    assert item.raw_payload_json["authors"] == ["Alice Example", "Bob Example"]
    assert item.raw_payload_json["categories"] == ["cs.AI", "cs.CL"]
    assert item.raw_payload_json["primary_category"] == "cs.AI"
    assert item.raw_payload_json["pdf_url"] == "http://arxiv.org/pdf/2605.12345v1"
    assert item.raw_payload_json["doi"] == "10.1234/example"


# ---- page_monitor 深度抽取兜底链与 content_hash_diff 增量语义 ----


def test_page_html_parser_falls_back_to_og_description():
    parsed = _parse_html(
        """
        <html>
          <head>
            <title>JS Rendered Page</title>
            <meta property="og:description" content="og 描述兜底正文。">
          </head>
          <body><div id="app"></div></body>
        </html>
        """,
    )

    assert parsed["text"] == ""
    assert parsed["og_description"] == "og 描述兜底正文。"


def test_page_html_parser_captures_first_text_block_for_div_layout_pages():
    parsed = _parse_html(
        """
        <html>
          <head><title>Div Layout</title></head>
          <body>
            <div class="nav">首页</div>
            <script>var x = "script text is never a paragraph and must be skipped";</script>
            <div class="article-body">这是没有 p 标签的正文首段，长度足够被识别为段落。</div>
          </body>
        </html>
        """,
    )

    assert parsed["text"] == ""
    assert parsed["first_block"] == "这是没有 p 标签的正文首段，长度足够被识别为段落。"


LISTING_HTML = """
<html><body>
<a href="/news/a1">Article One</a>
</body></html>
"""

ARTICLE_V1_HTML = """
<html><head><title>Article One</title></head>
<body><p>original body version one.</p></body></html>
"""

ARTICLE_V2_HTML = """
<html><head><title>Article One</title></head>
<body><p>updated body version two.</p></body></html>
"""

OG_ONLY_ARTICLE_HTML = """
<html><head>
<title>OG Only</title>
<meta property="og:description" content="仅有 og 描述的内容页。">
</head><body><div id="root"></div></body></html>
"""


def _page_transport(article_html: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/news"):
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(200, text=article_html)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_page_monitor_content_hash_diff_keeps_key_stable_until_body_changes():
    from app.adapters.page import PageListingAdapter

    source = DataSource(
        source_type="page_monitor",
        name="监控页",
        url="https://example.com/news",
        fetch_config={"href_contains": ["/news/"], "content_hash_diff": True},
    )

    first = await PageListingAdapter(transport=_page_transport(ARTICLE_V1_HTML)).fetch(source)
    second = await PageListingAdapter(transport=_page_transport(ARTICLE_V1_HTML)).fetch(source)
    changed = await PageListingAdapter(transport=_page_transport(ARTICLE_V2_HTML)).fetch(source)

    assert len(first) == len(second) == len(changed) == 1
    # 未变更 → entry_key 稳定：fetch.py 幂等 upsert 不新增 raw_item（增量跳过语义）
    assert first[0].entry_key == second[0].entry_key
    assert first[0].entry_key.startswith("https://example.com/news/a1#body:")
    assert first[0].raw_payload_json["content_hash"]
    # 正文变更 → 新 entry_key → 新 raw_item，首次版本的 raw 不被覆盖（不变式）
    assert changed[0].entry_key != first[0].entry_key
    assert changed[0].entry_key.startswith("https://example.com/news/a1#body:")


@pytest.mark.asyncio
async def test_page_monitor_without_hash_diff_keeps_url_entry_key():
    from app.adapters.page import PageListingAdapter

    source = DataSource(
        source_type="page_monitor",
        name="监控页",
        url="https://example.com/news",
        fetch_config={"href_contains": ["/news/"]},
    )

    items = await PageListingAdapter(transport=_page_transport(ARTICLE_V1_HTML)).fetch(source)

    assert items[0].entry_key == "https://example.com/news/a1"


@pytest.mark.asyncio
async def test_page_monitor_article_falls_back_to_og_description_body():
    from app.adapters.page import PageListingAdapter

    source = DataSource(
        source_type="page_monitor",
        name="监控页",
        url="https://example.com/news",
        fetch_config={"href_contains": ["/news/"]},
    )

    items = await PageListingAdapter(transport=_page_transport(OG_ONLY_ARTICLE_HTML)).fetch(source)

    assert items[0].raw_content == "仅有 og 描述的内容页。"
    assert items[0].raw_payload_json["og_description"] == "仅有 og 描述的内容页。"


# ---- paper_api openreview provider ----

OPENREVIEW_NOTES_PAYLOAD = {
    "count": 2,
    "notes": [
        {
            "id": "abcDEF123",
            "forum": "abcDEF123",
            "cdate": 1751328000000,
            "pdate": 1751414400000,
            "content": {
                "title": {"value": "Scaling Agent Memory"},
                "abstract": {"value": "We study long-horizon agent memory."},
                "authors": {"value": ["Ada Lovelace", "Alan Turing"]},
                "venue": {"value": "ICLR 2026 Poster"},
                "venueid": {"value": "ICLR.cc/2026/Conference"},
                "pdf": {"value": "/pdf/abcDEF123.pdf"},
            },
        },
        {
            "id": "xyzUVW789",
            "forum": "xyzUVW789",
            "cdate": 1751241600000,
            "content": {
                # v1 风格裸值也要兼容
                "title": "Legacy Envelope Note",
                "abstract": "Plain content values.",
                "pdf": "https://example.com/paper.pdf",
            },
        },
    ],
}


def test_paper_api_detects_openreview_provider_from_url():
    source = DataSource(
        source_type="paper_api",
        name="OpenReview ICLR",
        url="https://api2.openreview.net/notes",
        fetch_config={"venue": "ICLR.cc/2026/Conference"},
    )

    assert detect_paper_provider(source) == "openreview"


def test_openreview_request_builds_venue_query():
    from app.adapters.paper import build_openreview_request

    source = DataSource(
        source_type="paper_api",
        name="OpenReview ICLR",
        url=None,
        fetch_config={
            "provider": "openreview",
            "venue": "ICLR.cc/2026/Conference",
            "max_results": 25,
        },
    )

    endpoint, params = build_openreview_request(source)

    assert endpoint == "https://api2.openreview.net/notes"
    assert params["content.venueid"] == "ICLR.cc/2026/Conference"
    assert params["limit"] == "25"
    assert params["sort"] == "cdate:desc"


def test_openreview_request_without_venue_or_invitation_raises():
    from app.adapters.paper import build_openreview_request

    source = DataSource(
        source_type="paper_api",
        name="OpenReview 缺配置",
        url=None,
        fetch_config={"provider": "openreview"},
    )

    with pytest.raises(ValueError, match="venue"):
        build_openreview_request(source)


def test_openreview_parser_maps_title_abstract_pdf_and_epoch_dates():
    from app.adapters.paper import parse_openreview_notes

    items = parse_openreview_notes(OPENREVIEW_NOTES_PAYLOAD)

    assert len(items) == 2
    first = items[0]
    assert first.entry_key == "openreview:abcDEF123"
    assert first.source_title == "Scaling Agent Memory"
    assert first.source_url == "https://openreview.net/forum?id=abcDEF123"
    assert first.raw_content == "We study long-horizon agent memory."
    # pdate（epoch 毫秒）优先于 cdate
    assert first.published_at == datetime.fromtimestamp(1751414400, tz=UTC)
    assert first.raw_payload_json["pdf_url"] == "https://openreview.net/pdf/abcDEF123.pdf"
    assert first.raw_payload_json["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert first.raw_payload_json["payload"] == OPENREVIEW_NOTES_PAYLOAD["notes"][0]
    assert first.source_specific_json["provider"] == "openreview"
    assert first.source_specific_json["venueid"] == "ICLR.cc/2026/Conference"

    second = items[1]
    assert second.source_title == "Legacy Envelope Note"
    assert second.published_at == datetime.fromtimestamp(1751241600, tz=UTC)
    assert second.raw_payload_json["pdf_url"] == "https://example.com/paper.pdf"


@pytest.mark.asyncio
async def test_openreview_fetch_queries_venue_and_returns_items():
    from app.adapters.paper import PaperApiAdapter

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=OPENREVIEW_NOTES_PAYLOAD)

    adapter = PaperApiAdapter(transport=httpx.MockTransport(handler))
    source = DataSource(
        source_type="paper_api",
        name="OpenReview ICLR",
        url=None,
        fetch_config={"provider": "openreview", "venue": "ICLR.cc/2026/Conference"},
    )

    items = await adapter.fetch(source)

    assert len(items) == 2
    assert calls[0].startswith("https://api2.openreview.net/notes?")
    assert "content.venueid=ICLR.cc%2F2026%2FConference" in calls[0]


@pytest.mark.asyncio
async def test_openreview_backfill_window_filters_by_publish_date():
    from app.adapters.paper import PaperApiAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OPENREVIEW_NOTES_PAYLOAD)

    adapter = PaperApiAdapter(transport=httpx.MockTransport(handler))
    source = DataSource(
        source_type="paper_api",
        name="OpenReview ICLR",
        url=None,
        fetch_config={"provider": "openreview", "venue": "ICLR.cc/2026/Conference"},
    )

    # 只保留 pdate/cdate 落在目标窗口内的 note（notes API 无服务端日期过滤）
    items = await adapter.fetch_with_context(
        source,
        SourceFetchContext(
            mode="paper_api",
            target_day_start=datetime.fromtimestamp(1751414400, tz=UTC).date(),
            target_day_end=datetime.fromtimestamp(1751414400, tz=UTC).date(),
        ),
    )

    assert [item.entry_key for item in items] == ["openreview:abcDEF123"]
