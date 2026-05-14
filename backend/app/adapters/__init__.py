from app.adapters.base import AdapterRegistry, RawItemInput, SourceAdapter
from app.adapters.page import ManualPageAdapter, PageListingAdapter
from app.adapters.rss import PaperRssFeedAdapter, RssFeedAdapter
from app.adapters.stubs import (
    CsvFileAdapter,
    CustomCrawlerAdapter,
    InternalSourceAdapter,
    ManualNewsAdapter,
    PaperApiAdapter,
    PaperPageAdapter,
    WiseflowReadInfoAdapter,
)


def create_default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    for adapter in [
        RssFeedAdapter(),
        PaperRssFeedAdapter(),
        WiseflowReadInfoAdapter(),
        PageListingAdapter(),
        ManualPageAdapter(),
        CustomCrawlerAdapter(),
        CsvFileAdapter(),
        PaperApiAdapter(),
        PaperPageAdapter(),
        ManualNewsAdapter(),
        InternalSourceAdapter(),
    ]:
        registry.register(adapter)
    return registry


__all__ = [
    "AdapterRegistry",
    "CsvFileAdapter",
    "CustomCrawlerAdapter",
    "InternalSourceAdapter",
    "ManualNewsAdapter",
    "ManualPageAdapter",
    "PageListingAdapter",
    "PaperApiAdapter",
    "PaperPageAdapter",
    "PaperRssFeedAdapter",
    "RawItemInput",
    "RssFeedAdapter",
    "SourceAdapter",
    "WiseflowReadInfoAdapter",
    "create_default_registry",
]
