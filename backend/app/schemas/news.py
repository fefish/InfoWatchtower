from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NewsNormalizeCreate(BaseModel):
    workspace_code: str
    source_types: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=0)


class NewsNormalizeRead(BaseModel):
    workspace_code: str
    raw_scanned: int
    news_created: int
    news_updated: int
    raw_skipped: int
    dedupe_groups_updated: int
    winners: int
    losers: int


class NewsItemRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    raw_item_id: str
    data_source_id: str
    source_type: str
    source_name: str
    source_url: str | None
    canonical_url: str | None
    source_title: str
    normalized_title: str
    summary: str
    author: str
    published_at: datetime | None
    focus_id: int
    dedupe_key: str
    active: bool
    duplicate_of_id: str | None
    normalization_status: str
    normalization_notes: str


class DedupeGroupItemRead(BaseModel):
    id: str
    news_item_id: str
    is_winner: bool
    duplicate_reason: str
    rank_score: float
    title: str
    source_name: str
    source_url: str | None


class DedupeGroupRecommendationRead(BaseModel):
    run_id: str
    run_key: str
    day_key: str | None
    recommendation_item_id: str
    rank: int
    selected: bool
    final_score: float
    quality_score: float
    topic_score: float
    freshness_score: float
    feedback_score: float
    diversity_score: float
    source_score: float
    heat_score: float
    recommendation_reason: str
    admission_level: str
    admission_score: float
    admission_pool: str
    noise_types: list[str] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    scorer_breakdown: dict[str, object] = Field(default_factory=dict)
    expert_routes: list[str] = Field(default_factory=list)


class DedupeGroupDailyReportRead(BaseModel):
    daily_report_id: str
    daily_report_item_id: str
    day_key: str
    report_status: str
    adoption_status: int
    generated_news_id: str
    generation_status: str
    category: str


class DedupeGroupRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    dedupe_key: str
    winner_news_item_id: str | None
    winner_title: str | None
    item_count: int
    status: str
    items: list[DedupeGroupItemRead] = Field(default_factory=list)
    recommendation: DedupeGroupRecommendationRead | None = None
    daily_report: DedupeGroupDailyReportRead | None = None
