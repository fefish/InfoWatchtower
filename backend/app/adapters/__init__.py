from app.adapters.base import AdapterRegistry, RawItemInput, SourceAdapter, SourceFetchContext
from app.adapters.crawler import CustomCrawlerAdapter
from app.adapters.csv_file import CsvFileAdapter
from app.adapters.page import ManualPageAdapter, PageListingAdapter
from app.adapters.paper import PaperApiAdapter
from app.adapters.paper_page import PaperPageAdapter
from app.adapters.push_based import InternalSourceAdapter, ManualNewsAdapter
from app.adapters.rss import PaperRssFeedAdapter, RssFeedAdapter
from app.adapters.wiseflow import WiseflowReadInfoAdapter


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
    "SourceFetchContext",
    "WiseflowReadInfoAdapter",
    "create_default_registry",
]
