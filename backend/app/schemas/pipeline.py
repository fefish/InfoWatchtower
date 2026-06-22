from __future__ import annotations

from pydantic import BaseModel, Field

from app.ingestion.runs import (
    DEFAULT_INGESTION_CONCURRENCY,
    DEFAULT_INGESTION_SOURCE_TYPES,
    DEFAULT_SOURCE_TIMEOUT_SECONDS,
)


class DailyPipelineRunCreate(BaseModel):
    workspace_code: str = "planning_intel"
    day_key: str | None = None
    source_types: list[str] = Field(default_factory=lambda: list(DEFAULT_INGESTION_SOURCE_TYPES))
    ingestion_limit: int | None = Field(default=None, ge=1, le=500)
    ingestion_concurrency: int = Field(default=DEFAULT_INGESTION_CONCURRENCY, ge=1, le=32)
    ingestion_source_timeout_seconds: float = Field(
        default=DEFAULT_SOURCE_TIMEOUT_SECONDS,
        ge=3,
        le=120,
    )
    recommendation_limit: int = Field(default=15, ge=0, le=100)
    source_daily_limit: int = Field(default=2, ge=1, le=20)
    generation_timeout_seconds: float = Field(default=45.0, ge=5, le=180)
    create_daily_draft: bool = True
    run_ingestion: bool = True


class DailyPipelineRunRead(BaseModel):
    workspace_code: str
    day_key: str | None
    ingestion_run_id: str | None
    ingestion_status: str
    raw_scanned: int
    news_created: int
    news_updated: int
    raw_skipped: int
    dedupe_groups_updated: int
    recommendation_run_id: str
    daily_report_id: str | None
    candidates_total: int
    selected_total: int
    generated_total: int
