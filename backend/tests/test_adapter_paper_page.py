from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.paper_page import PaperPageAdapter
from app.models.content import DataSource

LISTING_HTML = """
<html><body>
  <a href="/papers/great-paper">Great Paper</a>
  <a href="/papers/plain-page">Plain Page</a>
  <a href="/papers/direct.pdf">Direct PDF Paper</a>
  <a href="/sponsors">Sponsors</a>
</body></html>
"""

DETAIL_WITH_CITATION_META = """
<html>
  <head>
    <title>Great Paper | Example Conf</title>
    <meta name="citation_title" content="Great Paper on Agents">
    <meta name="citation_author" content="Alice Example">
    <meta name="citation_author" content="Bob Example">
    <meta name="citation_abstract" content="We study multi-agent systems.">
    <meta name="citation_pdf_url" content="/papers/great-paper.pdf">
    <meta name="citation_doi" content="10.1234/great-paper">
    <meta name="citation_publication_date" content="2026/05/10">
  </head>
  <body><h1>Great Paper on Agents</h1><p>Intro paragraph.</p></body>
</html>
"""

DETAIL_WITHOUT_META = """
<html>
  <head><title>Plain Paper Page</title></head>
  <body><h1>Plain Paper Heading</h1><p>Some abstract-ish text on the page.</p></body>
</html>
"""


def make_source(fetch_config: dict, url: str | None = None) -> DataSource:
    return DataSource(
        source_type="paper_page",
        name="Paper Page",
        url=url,
        fetch_config=fetch_config,
    )


def make_transport(requested: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if requested is not None:
            requested.append(url)
        if url == "https://conf.example.com/accepted":
            return httpx.Response(200, text=LISTING_HTML, headers={"content-type": "text/html"})
        if url == "https://conf.example.com/papers/great-paper":
            return httpx.Response(
                200,
                text=DETAIL_WITH_CITATION_META,
                headers={"content-type": "text/html"},
            )
        if url == "https://conf.example.com/papers/plain-page":
            return httpx.Response(
                200,
                text=DETAIL_WITHOUT_META,
                headers={"content-type": "text/html"},
            )
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_paper_page_extracts_citation_metadata_and_degrades_gracefully():
    requested: list[str] = []
    adapter = PaperPageAdapter(transport=make_transport(requested))
    items = await adapter.fetch(
        make_source(
            {"page_url": "https://conf.example.com/accepted", "href_contains": ["/papers/"]},
        ),
    )

    assert len(items) == 3

    rich = items[0]
    assert rich.entry_key == "doi:10.1234/great-paper"
    assert rich.source_title == "Great Paper on Agents"
    assert rich.raw_content == "We study multi-agent systems."
    assert rich.published_at == datetime(2026, 5, 10, tzinfo=UTC)
    assert rich.raw_payload_json["authors"] == ["Alice Example", "Bob Example"]
    assert rich.raw_payload_json["pdf_url"] == "https://conf.example.com/papers/great-paper.pdf"
    assert rich.raw_payload_json["doi"] == "10.1234/great-paper"
    assert rich.raw_payload_json["meta"]["citation_title"] == ["Great Paper on Agents"]
    assert rich.source_specific_json["doi"] == "10.1234/great-paper"

    plain = items[1]
    assert plain.entry_key == "https://conf.example.com/papers/plain-page"
    assert plain.source_title == "Plain Paper Heading"
    assert "abstract-ish" in plain.raw_content
    assert plain.published_at is None

    pdf_item = items[2]
    assert pdf_item.entry_key == "https://conf.example.com/papers/direct.pdf"
    assert pdf_item.source_title == "Direct PDF Paper"
    assert pdf_item.raw_payload_json["pdf_url"] == "https://conf.example.com/papers/direct.pdf"
    # PDF 直链不应被抓取正文
    assert "https://conf.example.com/papers/direct.pdf" not in requested


@pytest.mark.asyncio
async def test_paper_page_max_items_caps_detail_fetches():
    adapter = PaperPageAdapter(transport=make_transport())
    items = await adapter.fetch(
        make_source(
            {
                "page_url": "https://conf.example.com/accepted",
                "href_contains": ["/papers/"],
                "max_items": 1,
            },
        ),
    )

    assert len(items) == 1
    assert items[0].entry_key == "doi:10.1234/great-paper"


@pytest.mark.asyncio
async def test_paper_page_fetch_detail_false_emits_link_only_items():
    requested: list[str] = []
    adapter = PaperPageAdapter(transport=make_transport(requested))
    items = await adapter.fetch(
        make_source(
            {
                "page_url": "https://conf.example.com/accepted",
                "href_contains": ["/papers/"],
                "fetch_detail": False,
            },
        ),
    )

    assert requested == ["https://conf.example.com/accepted"]
    assert [item.entry_key for item in items] == [
        "https://conf.example.com/papers/great-paper",
        "https://conf.example.com/papers/plain-page",
        "https://conf.example.com/papers/direct.pdf",
    ]


@pytest.mark.asyncio
async def test_paper_page_raises_on_listing_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    adapter = PaperPageAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch(make_source({"page_url": "https://conf.example.com/accepted"}))


@pytest.mark.asyncio
async def test_paper_page_propagates_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    adapter = PaperPageAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.TimeoutException):
        await adapter.fetch(make_source({"page_url": "https://conf.example.com/accepted"}))


@pytest.mark.asyncio
async def test_paper_page_returns_empty_without_page_url():
    adapter = PaperPageAdapter(transport=make_transport())
    assert await adapter.fetch(make_source({})) == []


@pytest.mark.asyncio
async def test_paper_page_entry_key_is_stable_across_refetch():
    adapter = PaperPageAdapter(transport=make_transport())
    source = make_source(
        {"page_url": "https://conf.example.com/accepted", "href_contains": ["/papers/"]},
    )

    first = await adapter.fetch(source)
    second = await adapter.fetch(source)

    assert [item.entry_key for item in first] == [item.entry_key for item in second]
