from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GeneratedNewsRead(BaseModel):
    id: str
    category: str
    title: str
    summary: str
    key_points: str
    content_json: dict[str, Any]
    source_url: str | None
    generation_status: str
    news_item_id: str
    recommendation_item_id: str


class DailyReportItemRead(BaseModel):
    id: str
    generated_news: GeneratedNewsRead
    adoption_status: int
    is_headline: bool = False
    sort_order: int
    editor_title: str | None
    editor_summary: str | None
    editor_key_points: str | None
    editor_content_json: dict[str, Any] | None
    editor_notes: str
    reaction_count: int = 0
    rating_count: int = 0
    rating_avg: float = 0.0
    comment_count: int = 0


class DailyReportRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    day_key: str
    title: str
    summary: str
    status: str
    published_at: datetime | None
    items: list[DailyReportItemRead] = Field(default_factory=list)


class DailyReportItemUpdate(BaseModel):
    adoption_status: int | None = Field(default=None, ge=0, le=2)
    is_headline: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    editor_title: str | None = None
    editor_summary: str | None = None
    editor_key_points: str | None = None
    editor_content_json: dict[str, Any] | None = None
    editor_notes: str | None = None


class DailyReportGenerationRerunCreate(BaseModel):
    item_ids: list[str] | None = None
    limit: int | None = Field(default=None, ge=0, le=100)
    replace_ready: bool = False
    generation_timeout_seconds: float = Field(default=45.0, ge=5, le=180)


class DailyReportGenerationRerunRead(BaseModel):
    report: DailyReportRead
    attempted_total: int
    ready_total: int
    fallback_total: int
    skipped_total: int


class WeeklyReportItemRead(BaseModel):
    id: str
    daily_report_item_id: str | None
    daily_day_key: str | None
    generated_news: GeneratedNewsRead | None
    adoption_status: int
    sort_order: int
    editor_title: str | None
    editor_summary: str | None
    editor_content_json: dict[str, Any] | None


class WeeklyReportRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    week_key: str
    title: str
    summary: str
    status: str
    published_at: datetime | None
    items: list[WeeklyReportItemRead] = Field(default_factory=list)


class WeeklyReportCreate(BaseModel):
    workspace_code: str
    week_key: str
    limit: int = Field(default=50, ge=1, le=200)
    include_unpublished_daily: bool = False


class WeeklyReportItemUpdate(BaseModel):
    adoption_status: int | None = Field(default=None, ge=0, le=2)
    sort_order: int | None = Field(default=None, ge=0)
    editor_title: str | None = None
    editor_summary: str | None = None
    editor_content_json: dict[str, Any] | None = None


class ReactionCreate(BaseModel):
    reaction_type: str = "like"
    active: bool = True


class RatingCreate(BaseModel):
    dimension: str = "overall"
    score: int = Field(ge=1, le=5)
    comment: str = ""


class RatingRead(BaseModel):
    id: str
    dimension: str
    score: int
    comment: str


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)
    parent_id: str | None = None


class CommentRead(BaseModel):
    id: str
    user_id: str
    body: str
    status: str
    parent_id: str | None
    root_id: str | None
    created_at: datetime
