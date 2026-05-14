from app.adapters import create_default_registry
from app.adapters.page import _extract_links, _parse_html, _parse_iso_datetime
from app.adapters.rss import RssFeedAdapter


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
