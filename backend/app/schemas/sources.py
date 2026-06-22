from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DataSourceRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    source_type: str
    name: str
    url: str | None
    enabled: bool
    default_focus_id: int
    backfill_days: int
    source_score: float
    last_fetch_at: datetime | None
    last_success_at: datetime | None
    last_error: str
    primary_category: str
    info_category: str
    source_tags: list[str] = Field(default_factory=list)
    source_secondary_tags: list[str] = Field(default_factory=list)
    source_tier: str = ""
    source_channel_type: str = ""
    expert_routes: list[str] = Field(default_factory=list)
    inclusion_recommendation: str = ""
    metadata_only: bool = False
    needs_entry: bool = False
    fetch_entry_status: str = ""
    source_quality_notes: str = ""
    workspace_link_enabled: bool | None = None
    workspace_source_weight: float | None = None
    workspace_daily_limit: int | None = None
    workspace_clustering_config: dict[str, Any] = Field(default_factory=dict)


class DataSourceWorkspaceConfigUpdate(BaseModel):
    workspace_code: str
    enabled: bool
    source_weight: float = Field(default=1.0, ge=0)
    daily_limit: int | None = Field(default=None, ge=0)


class LegacySeedImportRead(BaseModel):
    created: int
    updated: int
    total: int


class TechInsightLoopImportRead(BaseModel):
    created: int
    updated: int
    total: int
    fetchable: int
    metadata_only: int


class SourceFetchRead(BaseModel):
    data_source_id: str
    source_type: str
    fetched: int
    created: int
    updated: int
