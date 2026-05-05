from __future__ import annotations

from app.adapters.base import RawItemInput
from app.models.content import DataSource


class EmptyAdapter:
    source_type = "manual"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        return []


class WiseflowReadInfoAdapter(EmptyAdapter):
    source_type = "wiseflow"


class PageListingAdapter(EmptyAdapter):
    source_type = "page_monitor"


class ManualPageAdapter(EmptyAdapter):
    source_type = "page_manual"


class CustomCrawlerAdapter(EmptyAdapter):
    source_type = "crawler"


class PaperApiAdapter(EmptyAdapter):
    source_type = "paper_api"


class PaperPageAdapter(EmptyAdapter):
    source_type = "paper_page"


class ManualNewsAdapter(EmptyAdapter):
    source_type = "manual"


class InternalSourceAdapter(EmptyAdapter):
    source_type = "internal"
