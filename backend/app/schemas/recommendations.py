from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RecommendationRunCreate(BaseModel):
    workspace_code: str = "planning_intel"
    day_key: str | None = None
    limit: int = Field(default=15, ge=0, le=100)
    source_daily_limit: int = Field(default=2, ge=1, le=20)
    create_daily_draft: bool = True


class RecommendationItemRead(BaseModel):
    id: str
    news_item_id: str
    dedupe_group_id: str
    rank: int
    quality_score: float
    topic_score: float
    freshness_score: float
    feedback_score: float
    diversity_score: float
    source_score: float
    heat_score: float
    final_score: float
    selected: bool
    recommendation_reason: str
    source_title: str
    source_name: str
    source_url: str | None


class RecommendationRunRead(BaseModel):
    id: str
    run_key: str
    workspace_code: str
    domain_code: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    params_json: dict[str, Any]
    summary_json: dict[str, Any]
    items: list[RecommendationItemRead] = Field(default_factory=list)


class RecommendationRunCreateRead(BaseModel):
    run: RecommendationRunRead
    daily_report_id: str | None
    candidates_total: int
    selected_total: int
    generated_total: int
