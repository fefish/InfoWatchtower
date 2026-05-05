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
    workspace_link_enabled: bool | None = None
    workspace_source_weight: float | None = None
    workspace_daily_limit: int | None = None
    workspace_label_set_codes: list[str] = Field(default_factory=list)
    workspace_default_label_paths: list[str] = Field(default_factory=list)
    workspace_clustering_config: dict[str, Any] = Field(default_factory=dict)


class DataSourceWorkspaceConfigUpdate(BaseModel):
    workspace_code: str
    enabled: bool
    source_weight: float = Field(default=1.0, ge=0)
    daily_limit: int | None = Field(default=None, ge=0)
    label_set_codes: list[str] = Field(default_factory=list)
    default_label_paths: list[str] = Field(default_factory=list)
    clustering_config: dict[str, Any] = Field(default_factory=dict)


class LegacySeedImportRead(BaseModel):
    created: int
    updated: int
    total: int


class SourceFetchRead(BaseModel):
    data_source_id: str
    source_type: str
    fetched: int
    created: int
    updated: int
