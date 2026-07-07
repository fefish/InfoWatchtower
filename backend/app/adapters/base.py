from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from app.models.content import DataSource

# 与 Tech Insight Loop 抓取行为对齐的浏览器请求头：
# 默认程序 UA 会被大量站点反爬拦截（403），旧系统用 Chrome UA 抓取成功率显著更高。
BROWSER_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class RawItemInput:
    entry_key: str
    source_title: str
    source_url: str | None
    raw_content: str
    raw_payload_json: dict[str, Any]
    published_at: datetime | None = None
    source_specific_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceFetchContext:
    mode: str = "regular"
    target_day_start: date | None = None
    target_day_end: date | None = None


class AdapterNotImplementedError(NotImplementedError):
    def __init__(self, source_type: str) -> None:
        super().__init__(f"source_type={source_type} adapter is not implemented")
        self.source_type = source_type


class SourceAdapter(Protocol):
    source_type: str

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        self._adapters[adapter.source_type] = adapter

    def get(self, source_type: str) -> SourceAdapter:
        adapter = self._adapters.get(source_type)
        if adapter is None:
            raise KeyError(f"No adapter registered for source_type={source_type}")
        return adapter

    def list_types(self) -> list[str]:
        return sorted(self._adapters)
