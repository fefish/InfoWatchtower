from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.ingestion.runs import DEFAULT_INGESTION_SOURCE_TYPES


class IngestionRunCreate(BaseModel):
    workspace_code: str = "planning_intel"
    source_types: list[str] = Field(default_factory=lambda: list(DEFAULT_INGESTION_SOURCE_TYPES))
    limit: int | None = Field(default=None, ge=0)


class IngestionRunRead(BaseModel):
    id: str
    run_key: str
    workspace_code: str
    domain_code: str
    run_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    source_total: int
    source_succeeded: int
    source_failed: int
    items_fetched: int
    raw_created: int
    raw_updated: int
    params_json: dict[str, Any]
    summary_json: dict[str, Any]
