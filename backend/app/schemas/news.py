from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NewsNormalizeCreate(BaseModel):
    workspace_code: str = "planning_intel"
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
