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
    limit: int | None = Field(default=None, ge=1)
    concurrency: int = Field(default=DEFAULT_INGESTION_CONCURRENCY, ge=1, le=32)
    source_timeout_seconds: float = Field(default=DEFAULT_SOURCE_TIMEOUT_SECONDS, ge=3, le=120)
    max_items_per_source: int | None = Field(default=None, ge=0)


class HistoricalBackfillCreate(BaseModel):
    workspace_code: str
    target_day_start: str
    target_day_end: str
    source_types: list[str] = Field(default_factory=lambda: list(DEFAULT_BACKFILL_SOURCE_TYPES))
    limit: int | None = Field(default=None, ge=1)
    concurrency: int = Field(default=DEFAULT_INGESTION_CONCURRENCY, ge=1, le=32)
    source_timeout_seconds: float = Field(default=DEFAULT_SOURCE_TIMEOUT_SECONDS, ge=3, le=120)
    backfill_mode: str = "rss_window"
    source_scope: str = "source_type"
    retry_policy: str = "manual_run_no_retry"
    include_undated: bool = False
    manual_items: list[dict[str, Any]] = Field(default_factory=list)


class ManualImportPreviewCreate(BaseModel):
    workspace_code: str
    source_types: list[str] = Field(default_factory=lambda: list(DEFAULT_BACKFILL_SOURCE_TYPES))
    default_data_source_id: str = ""
    input_text: str
    input_format: str = "auto"
    filename: str = ""


class ManualImportPreviewErrorRead(BaseModel):
    row_number: int
    code: str
    message: str
    raw_text: str = ""


class ManualImportPreviewRead(BaseModel):
    workspace_code: str
    input_format: str
    filename: str
    total_rows: int
    accepted_count: int
    rejected_count: int
    accepted_items: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[ManualImportPreviewErrorRead] = Field(default_factory=list)
    error_report_csv: str


class IngestionRetryFailedCreate(BaseModel):
    concurrency: int = Field(default=2, ge=1, le=32)
    source_timeout_seconds: float = Field(default=60.0, ge=3, le=120)
    max_items_per_source: int | None = Field(default=None, ge=0)


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


class IngestionCoverageTrendPointRead(BaseModel):
    day_key: str
    run_count: int
    latest_run_id: str | None = None
    latest_run_key: str | None = None
    latest_run_status: str | None = None
    source_total: int
    source_succeeded: int
    source_failed: int
    source_skipped_unimplemented: int
    items_fetched: int
    raw_created: int
    raw_updated: int
    success_rate: float


class IngestionCoverageFailureTrendRead(BaseModel):
    data_source_id: str
    name: str
    source_type: str
    failure_count: int
    last_error: str
    last_run_id: str
    last_run_key: str
    last_failed_at: datetime | None


class IngestionCoverageTrendsRead(BaseModel):
    workspace_code: str
    days: int
    generated_at: datetime
    total_runs: int
    total_source_failed: int
    total_raw_created: int
    average_success_rate: float
    points: list[IngestionCoverageTrendPointRead] = Field(default_factory=list)
    top_failed_sources: list[IngestionCoverageFailureTrendRead] = Field(default_factory=list)


class IngestionFailedSourceRetryRunRead(BaseModel):
    run_id: str
    run_key: str
    run_type: str
    status: str
    failed_source_count: int
    attempt_count: int
    last_attempt_at: datetime | None
    next_retry_at: datetime | None
    blocked: bool
    due: bool
    latest_retry_run_id: str | None = None
    latest_retry_run_key: str | None = None
    latest_retry_status: str | None = None


class IngestionFailedSourceRetrySummaryRead(BaseModel):
    workspace_code: str
    generated_at: datetime
    policy: dict[str, Any]
    due_count: int
    blocked_count: int
    next_retry_at: datetime | None
    runs: list[IngestionFailedSourceRetryRunRead] = Field(default_factory=list)
