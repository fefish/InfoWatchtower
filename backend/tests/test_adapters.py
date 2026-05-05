from app.adapters import create_default_registry
from app.adapters.rss import RssFeedAdapter


def test_default_adapter_registry_contains_first_phase_source_types():
    registry = create_default_registry()

    assert registry.list_types() == [
        "crawler",
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
