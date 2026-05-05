from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.models.content import DataSource


@dataclass(frozen=True)
class RawItemInput:
    entry_key: str
    source_title: str
    source_url: str | None
    raw_content: str
    raw_payload_json: dict[str, Any]
    published_at: datetime | None = None
    source_specific_json: dict[str, Any] = field(default_factory=dict)


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
