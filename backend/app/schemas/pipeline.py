from __future__ import annotations

from pydantic import BaseModel, Field


class DailyPipelineRunCreate(BaseModel):
    workspace_code: str = "planning_intel"
    day_key: str | None = None
    source_types: list[str] = Field(default_factory=lambda: ["rss", "paper_rss"])
    ingestion_limit: int | None = Field(default=None, ge=1, le=500)
    recommendation_limit: int = Field(default=15, ge=0, le=100)
    source_daily_limit: int = Field(default=2, ge=1, le=20)
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
