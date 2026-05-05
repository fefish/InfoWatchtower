from app.adapters import create_default_registry


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
