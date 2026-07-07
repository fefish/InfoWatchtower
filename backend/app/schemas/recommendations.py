from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScorerPolicyPair(BaseModel):
    name: str
    value: float


class ScorerPolicyRead(BaseModel):
    workspace_code: str
    config_loaded: bool
    enabled: bool
    config_version: str
    config_path: str
    thresholds: dict[str, float] = Field(default_factory=dict)
    daily_levels: list[str] = Field(default_factory=list)
    weekly_levels: list[str] = Field(default_factory=list)
    weights: list[ScorerPolicyPair] = Field(default_factory=list)
    top_topics: list[ScorerPolicyPair] = Field(default_factory=list)
    source_tiers: list[ScorerPolicyPair] = Field(default_factory=list)
    source_channels: list[ScorerPolicyPair] = Field(default_factory=list)
    noise_rule_count: int
    direct_reject_noise_types: list[str] = Field(default_factory=list)
    formula_notes: list[str] = Field(default_factory=list)


class ScorerPreviewCreate(BaseModel):
    workspace_code: str
    source_title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=8000)
    source_type: str = Field(default="rss", max_length=64)
    source_name: str = Field(default="", max_length=255)
    source_url: str = Field(default="", max_length=2000)
    source_tier: str = Field(default="", max_length=64)
    source_channel_type: str = Field(default="", max_length=128)
    source_score: float = Field(default=0.0, ge=0, le=100)
    source_tags: list[str] = Field(default_factory=list)
    source_secondary_tags: list[str] = Field(default_factory=list)
    board_relevance_json: dict[str, Any] = Field(default_factory=dict)
    freshness_score: float = Field(default=80.0, ge=0, le=100)


class ScorerPreviewRead(BaseModel):
    workspace_code: str
    source_title: str
    admission_level: str
    admission_score: float
    admission_pool: str
    eligible_for_daily: bool
    noise_types: list[str] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    positive_reasons: list[str] = Field(default_factory=list)
    expert_routes: list[str] = Field(default_factory=list)
    scorer_breakdown: dict[str, Any] = Field(default_factory=dict)
    persistence: str = "not_persisted"


class RecommendationItemDailyReportRead(BaseModel):
    daily_report_id: str
    daily_report_item_id: str
    day_key: str
    report_status: str
    adoption_status: int
    generated_news_id: str
    generation_status: str


class RecommendationRunCreate(BaseModel):
    workspace_code: str
    day_key: str | None = None
    limit: int = Field(default=15, ge=0, le=100)
    source_daily_limit: int = Field(default=2, ge=1, le=20)
    create_daily_draft: bool = True
    generation_timeout_seconds: float = Field(default=45.0, ge=5, le=180)


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
    admission_level: str
    admission_score: float
    admission_pool: str
    noise_types: list[str] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    scorer_breakdown: dict[str, Any] = Field(default_factory=dict)
    expert_routes: list[str] = Field(default_factory=list)
    source_title: str
    source_name: str
    source_url: str | None
    daily_report: RecommendationItemDailyReportRead | None = None


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
