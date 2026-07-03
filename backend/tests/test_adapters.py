import asyncio
from datetime import UTC, datetime

from app.adapters import AdapterRegistry, RawItemInput, create_default_registry
from app.adapters.page import _extract_links, _parse_html, _parse_iso_datetime
from app.adapters.rss import RssFeedAdapter
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
        "wiseflow",
    ]


def test_dummy_adapter_recipe_contract_example():
    class DummyAdapter:
        source_type = "dummy"

        async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
            return [
                RawItemInput(
                    entry_key=f"{data_source.source_type}:1",
                    source_title=f"{data_source.name} item",
                    source_url=data_source.url,
                    raw_content="dummy body",
                    raw_payload_json={"adapter": self.source_type},
                ),
            ]

    registry = AdapterRegistry()
    registry.register(DummyAdapter())
    source = DataSource(
        workspace_code="shared",
        domain_code="hardware",
        source_type="dummy",
        name="Dummy feed",
        url="https://example.com/dummy",
    )

    raw_items = asyncio.run(registry.get("dummy").fetch(source))

    assert registry.list_types() == ["dummy"]
    assert raw_items[0].entry_key == "dummy:1"
    assert raw_items[0].raw_payload_json == {"adapter": "dummy"}


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
