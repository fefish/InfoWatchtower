import re

import httpx
import pytest

from app.adapters.crawler import CustomCrawlerAdapter
from app.models.content import DataSource

LISTING_HTML = """
<html><body>
  <a href="/news/first-post">First Post</a>
  <a href="/news/second-post">Second Post</a>
  <a href="/news/draft-skip">Draft</a>
  <a href="/about">About</a>
  <a href="/news/first-post">Duplicate</a>
</body></html>
"""

ARTICLE_HTML = """
<html>
  <head><title>{title}</title><meta name="description" content="描述 {title}"></head>
  <body><h1>{title}</h1><p>正文 {title}。</p></body>
</html>
"""


def make_source(fetch_config: dict, url: str | None = None) -> DataSource:
    return DataSource(
        source_type="crawler",
        name="Crawler Source",
        url=url,
        fetch_config=fetch_config,
    )


def make_transport(requested: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if requested is not None:
            requested.append(url)
        if url == "https://example.com/news":
            return httpx.Response(200, text=LISTING_HTML, headers={"content-type": "text/html"})
        if "/news/" in url:
            slug = url.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                text=ARTICLE_HTML.format(title=slug),
                headers={"content-type": "text/html"},
            )
        return httpx.Response(404, text="not found")

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_crawler_fetches_listing_then_articles_with_link_filters():
    adapter = CustomCrawlerAdapter(transport=make_transport())
    items = await adapter.fetch(
        make_source(
            {
                "listing_url": "https://example.com/news",
                "href_contains": ["/news/"],
                "link_exclude_pattern": "draft",
                "max_items": 5,
            },
        ),
    )

    assert [item.entry_key for item in items] == [
        "https://example.com/news/first-post",
        "https://example.com/news/second-post",
    ]
    first = items[0]
    assert first.source_title == "first-post"
    assert "正文 first-post" in first.raw_content
    assert first.raw_payload_json["listing_url"] == "https://example.com/news"
    assert first.raw_payload_json["link_text"] == "First Post"
    assert first.raw_payload_json["final_url"] == "https://example.com/news/first-post"


@pytest.mark.asyncio
async def test_crawler_link_pattern_include_and_max_items_cap():
    adapter = CustomCrawlerAdapter(transport=make_transport())
    items = await adapter.fetch(
        make_source(
            {
                "listing_url": "https://example.com/news",
                "link_pattern": r"/news/\w+-post$",
                "max_items": 1,
            },
        ),
    )

    assert len(items) == 1
    assert items[0].entry_key == "https://example.com/news/first-post"


@pytest.mark.asyncio
async def test_crawler_can_skip_article_fetch_and_emit_listing_links_only():
    requested: list[str] = []
    adapter = CustomCrawlerAdapter(transport=make_transport(requested))
    items = await adapter.fetch(
        make_source(
            {
                "listing_url": "https://example.com/news",
                "href_contains": ["/news/"],
                "fetch_article": False,
            },
        ),
    )

    assert requested == ["https://example.com/news"]
    assert len(items) == 3
    assert items[0].entry_key == "https://example.com/news/first-post"
    assert items[0].source_title == "First Post"
    assert items[0].raw_payload_json["link_text"] == "First Post"


@pytest.mark.asyncio
async def test_crawler_invalid_link_pattern_raises_format_error():
    adapter = CustomCrawlerAdapter(transport=make_transport())
    with pytest.raises(re.error):
        await adapter.fetch(
            make_source({"listing_url": "https://example.com/news", "link_pattern": "["}),
        )


@pytest.mark.asyncio
async def test_crawler_raises_on_listing_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    adapter = CustomCrawlerAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch(make_source({"listing_url": "https://example.com/news"}))


@pytest.mark.asyncio
async def test_crawler_propagates_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    adapter = CustomCrawlerAdapter(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.TimeoutException):
        await adapter.fetch(make_source({"listing_url": "https://example.com/news"}))


@pytest.mark.asyncio
async def test_crawler_returns_empty_without_listing_url():
    adapter = CustomCrawlerAdapter(transport=make_transport())
    assert await adapter.fetch(make_source({})) == []


@pytest.mark.asyncio
async def test_crawler_entry_key_is_stable_across_refetch():
    adapter = CustomCrawlerAdapter(transport=make_transport())
    source = make_source({"listing_url": "https://example.com/news", "href_contains": ["/news/"]})

    first = await adapter.fetch(source)
    second = await adapter.fetch(source)

    assert [item.entry_key for item in first] == [item.entry_key for item in second]
