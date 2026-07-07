"""未实现 adapter 的占位实现。

注意：六类源的真实现已迁出本模块（wiseflow.py / crawler.py / csv_file.py /
paper_page.py / push_based.py），create_default_registry 注册的是真实现。
本模块保留同名 stub 仅用于验证 run 层 skipped_unimplemented 语义
（tests/test_ingestion_runs.py 显式注册 stub），请勿再向注册表注册这些类。
"""

from __future__ import annotations

from app.adapters.base import AdapterNotImplementedError, RawItemInput
from app.models.content import DataSource


class EmptyAdapter:
    source_type = "manual"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        raise AdapterNotImplementedError(self.source_type)


class WiseflowReadInfoAdapter(EmptyAdapter):
    source_type = "wiseflow"


class CustomCrawlerAdapter(EmptyAdapter):
    source_type = "crawler"


class CsvFileAdapter(EmptyAdapter):
    source_type = "csv"


class PaperPageAdapter(EmptyAdapter):
    source_type = "paper_page"


class ManualNewsAdapter(EmptyAdapter):
    source_type = "manual"


class InternalSourceAdapter(EmptyAdapter):
    source_type = "internal"
