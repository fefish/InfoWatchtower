from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


class LegacySeedImportRead(BaseModel):
    created: int
    updated: int
    total: int
