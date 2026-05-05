from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, SyncMixin, TimestampMixin


class DataSource(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "data_sources"

    source_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_focus_id: Mapped[int] = mapped_column(Integer, default=1)
    backfill_days: Mapped[int] = mapped_column(Integer, default=7)
    credential_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fetch_config: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    paper_config: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    source_score: Mapped[float] = mapped_column(Float, default=0.0)

    raw_items: Mapped[list[RawItem]] = relationship(back_populates="data_source")
    news_items: Mapped[list[NewsItem]] = relationship(back_populates="data_source")


class RawItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "raw_items"
    __table_args__ = (UniqueConstraint("data_source_id", "entry_key", name="uq_raw_items_source_entry"),)

    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    entry_key: Mapped[str] = mapped_column(String(255), index=True)
    source_title: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    data_source: Mapped[DataSource] = relationship(back_populates="raw_items")
    news_items: Mapped[list[NewsItem]] = relationship(back_populates="raw_item")


class IngestionRun(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_runs"

    run_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    run_type: Mapped[str] = mapped_column(String(64), default="workspace_fetch", index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_total: Mapped[int] = mapped_column(Integer, default=0)
    source_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    source_failed: Mapped[int] = mapped_column(Integer, default=0)
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
    raw_created: Mapped[int] = mapped_column(Integer, default=0)
    raw_updated: Mapped[int] = mapped_column(Integer, default=0)
    params_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    summary_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)


class NewsItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "news_items"

    raw_item_id: Mapped[str] = mapped_column(ForeignKey("raw_items.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    focus_id: Mapped[int] = mapped_column(Integer, default=1)
    dedupe_key: Mapped[str] = mapped_column(String(512), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True)
    normalization_status: Mapped[str] = mapped_column(String(32), default="normalized", index=True)
    normalization_notes: Mapped[str] = mapped_column(Text, default="")

    raw_item: Mapped[RawItem] = relationship(back_populates="news_items")
    data_source: Mapped[DataSource] = relationship(back_populates="news_items")
    duplicate_of: Mapped[NewsItem | None] = relationship(remote_side="NewsItem.id")
    dedupe_group_items: Mapped[list[DedupeGroupItem]] = relationship(back_populates="news_item")
    recommendation_items: Mapped[list[RecommendationItem]] = relationship(back_populates="news_item")
    generated_news_items: Mapped[list[GeneratedNews]] = relationship(back_populates="news_item")


class DedupeGroup(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "dedupe_groups"

    dedupe_key: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    winner_news_item_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")

    winner_news_item: Mapped[NewsItem | None] = relationship(foreign_keys=[winner_news_item_id])
    items: Mapped[list[DedupeGroupItem]] = relationship(back_populates="dedupe_group")
    recommendation_items: Mapped[list[RecommendationItem]] = relationship(back_populates="dedupe_group")


class DedupeGroupItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "dedupe_group_items"
    __table_args__ = (
        UniqueConstraint("dedupe_group_id", "news_item_id", name="uq_dedupe_group_news_item"),
    )

    dedupe_group_id: Mapped[str] = mapped_column(ForeignKey("dedupe_groups.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_reason: Mapped[str] = mapped_column(Text, default="")
    rank_score: Mapped[float] = mapped_column(Float, default=0.0)

    dedupe_group: Mapped[DedupeGroup] = relationship(back_populates="items")
    news_item: Mapped[NewsItem] = relationship(back_populates="dedupe_group_items")
    recommendation_items: Mapped[list[RecommendationItem]] = relationship(back_populates="dedupe_group_item")


class RecommendationRun(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "recommendation_runs"

    run_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    params_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    summary_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    items: Mapped[list[RecommendationItem]] = relationship(back_populates="run")


class RecommendationItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "recommendation_items"

    run_id: Mapped[str] = mapped_column(ForeignKey("recommendation_runs.id"), index=True)
    dedupe_group_id: Mapped[str] = mapped_column(ForeignKey("dedupe_groups.id"), index=True)
    dedupe_group_item_id: Mapped[str] = mapped_column(ForeignKey("dedupe_group_items.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    topic_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    feedback_score: Mapped[float] = mapped_column(Float, default=0.0)
    diversity_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_score: Mapped[float] = mapped_column(Float, default=0.0)
    heat_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    recommendation_reason: Mapped[str] = mapped_column(Text, default="")

    run: Mapped[RecommendationRun] = relationship(back_populates="items")
    dedupe_group: Mapped[DedupeGroup] = relationship(back_populates="recommendation_items")
    dedupe_group_item: Mapped[DedupeGroupItem] = relationship(back_populates="recommendation_items")
    news_item: Mapped[NewsItem] = relationship(back_populates="recommendation_items")
    generated_news: Mapped[list[GeneratedNews]] = relationship(back_populates="recommendation_item")


class GeneratedNews(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "generated_news"

    recommendation_item_id: Mapped[str] = mapped_column(ForeignKey("recommendation_items.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    category: Mapped[str] = mapped_column(String(64), default="基础竞争力", index=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by: Mapped[str] = mapped_column(String(64), default="system")
    generation_status: Mapped[str] = mapped_column(String(32), default="draft", index=True)

    recommendation_item: Mapped[RecommendationItem] = relationship(back_populates="generated_news")
    news_item: Mapped[NewsItem] = relationship(back_populates="generated_news_items")
    daily_report_items: Mapped[list[DailyReportItem]] = relationship(back_populates="generated_news")
