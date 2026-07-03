from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.ingestion.runs import (
    DEFAULT_BACKFILL_SOURCE_TYPES,
    DEFAULT_INGESTION_CONCURRENCY,
    DEFAULT_INGESTION_SOURCE_TYPES,
    DEFAULT_SOURCE_TIMEOUT_SECONDS,
)


class IngestionRunCreate(BaseModel):
    workspace_code: str
    source_types: list[str] = Field(default_factory=lambda: list(DEFAULT_INGESTION_SOURCE_TYPES))
    limit: int | None = Field(default=None, ge=0)
    concurrency: int = Field(default=DEFAULT_INGESTION_CONCURRENCY, ge=1, le=32)
    source_timeout_seconds: float = Field(default=DEFAULT_SOURCE_TIMEOUT_SECONDS, ge=3, le=120)
    max_items_per_source: int | None = Field(default=None, ge=0)


class HistoricalBackfillCreate(BaseModel):
    workspace_code: str
    target_day_start: str
    target_day_end: str
    source_types: list[str] = Field(default_factory=lambda: list(DEFAULT_BACKFILL_SOURCE_TYPES))
    limit: int | None = Field(default=None, ge=0)
    concurrency: int = Field(default=DEFAULT_INGESTION_CONCURRENCY, ge=1, le=32)
    source_timeout_seconds: float = Field(default=DEFAULT_SOURCE_TIMEOUT_SECONDS, ge=3, le=120)
    backfill_mode: str = "rss_window"
    source_scope: str = "source_type"
    retry_policy: str = "manual_run_no_retry"
    include_undated: bool = False
    manual_items: list[dict[str, Any]] = Field(default_factory=list)


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


class IngestionCoverageFunnelRead(BaseModel):
    enabled_sources: int
    run_sources: int
    source_succeeded: int
    source_failed: int
    items_fetched: int
    raw_created: int
    raw_updated: int
    raw_in_target: int
    news_items: int
    dedupe_winners: int
    recommendation_candidates: int
    recommendation_selected: int
    generated_ready: int
    daily_adopted: int


class IngestionCoverageSourceRead(BaseModel):
    data_source_id: str
    name: str
    source_type: str
    run_status: str
    error: str
    run_fetched: int
    run_created: int
    run_updated: int
    in_target_range: int
    out_of_target_range: int
    missing_published_at: int
    raw_in_target: int
    news_items: int
    dedupe_winners: int
    recommendation_candidates: int
    recommendation_selected: int
    generated_ready: int
    daily_adopted: int


class IngestionCoverageRead(BaseModel):
    workspace_code: str
    day_key: str
    run_id: str | None
    run_key: str | None
    run_type: str | None
    run_status: str | None
    target_range: str
    recommendation_run_id: str | None
    recommendation_run_key: str | None
    daily_report_id: str | None
    daily_report_status: str | None
    funnel: IngestionCoverageFunnelRead
    sources: list[IngestionCoverageSourceRead] = Field(default_factory=list)
