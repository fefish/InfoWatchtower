from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import (
    IdMixin,
    JsonColumn,
    JsonDict,
    JsonList,
    ScopeMixin,
    SyncMixin,
    TimestampMixin,
)


class HistoricalReport(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "historical_reports"
    __table_args__ = (
        UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_historical_reports_legacy_identity",
        ),
    )

    legacy_system: Mapped[str] = mapped_column(String(64), default="tech_insight_loop", index=True)
    legacy_table: Mapped[str] = mapped_column(String(64), default="reports", index=True)
    legacy_id: Mapped[str] = mapped_column(String(128), index=True)
    report_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="imported", index=True)
    period_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    source_refs_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)


class TrackedEntity(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "tracked_entities"
    __table_args__ = (
        UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_tracked_entities_legacy_identity",
        ),
    )

    legacy_system: Mapped[str] = mapped_column(String(64), default="tech_insight_loop", index=True)
    legacy_table: Mapped[str] = mapped_column(String(64), default="ai_entities", index=True)
    legacy_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(String(128), default="", index=True)
    rank: Mapped[str] = mapped_column(String(32), default="", index=True)
    aliases_json: Mapped[JsonList] = mapped_column(JsonColumn, default=list)
    influence_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    milestones: Mapped[list["EntityMilestone"]] = relationship(back_populates="tracked_entity")


class EntityMilestone(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "entity_milestones"
    __table_args__ = (
        UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_entity_milestones_legacy_identity",
        ),
    )

    legacy_system: Mapped[str] = mapped_column(String(64), default="tech_insight_loop", index=True)
    legacy_table: Mapped[str] = mapped_column(String(64), default="entity_milestones", index=True)
    legacy_id: Mapped[str] = mapped_column(String(128), index=True)
    tracked_entity_id: Mapped[str] = mapped_column(ForeignKey("tracked_entities.id"), index=True)
    legacy_entity_id: Mapped[str] = mapped_column(String(128), index=True)
    legacy_article_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    legacy_report_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_item_id: Mapped[str | None] = mapped_column(ForeignKey("raw_items.id"), nullable=True, index=True)
    historical_report_id: Mapped[str | None] = mapped_column(
        ForeignKey("historical_reports.id"),
        nullable=True,
        index=True,
    )
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128), default="", index=True)
    title: Mapped[str] = mapped_column(Text)
    event_content: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    event_brief: Mapped[str] = mapped_column(Text, default="")
    impact_brief: Mapped[str] = mapped_column(Text, default="")
    timeline_brief: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_name: Mapped[str] = mapped_column(Text, default="")
    board: Mapped[str] = mapped_column(String(128), default="", index=True)
    selected_for_timeline: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    importance_level: Mapped[str] = mapped_column(String(32), default="medium", index=True)
    event_dedupe_key: Mapped[str] = mapped_column(String(256), default="", index=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    tracked_entity: Mapped[TrackedEntity] = relationship(back_populates="milestones")
    raw_item: Mapped["RawItem | None"] = relationship()
    historical_report: Mapped[HistoricalReport | None] = relationship()


class HistoricalFeedbackItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "historical_feedback_items"
    __table_args__ = (
        UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_historical_feedback_items_legacy_identity",
        ),
    )

    legacy_system: Mapped[str] = mapped_column(String(64), default="tech_insight_loop", index=True)
    legacy_table: Mapped[str] = mapped_column(String(64), index=True)
    legacy_id: Mapped[str] = mapped_column(String(128), index=True)
    legacy_article_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_item_id: Mapped[str | None] = mapped_column(ForeignKey("raw_items.id"), nullable=True, index=True)
    feedback_kind: Mapped[str] = mapped_column(String(64), index=True)
    user_name: Mapped[str] = mapped_column(Text, default="")
    feedback_type: Mapped[str] = mapped_column(String(128), default="", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    raw_item: Mapped["RawItem | None"] = relationship()


class HistoricalJobRun(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "historical_job_runs"
    __table_args__ = (
        UniqueConstraint(
            "legacy_system",
            "legacy_table",
            "legacy_id",
            name="uq_historical_job_runs_legacy_identity",
        ),
    )

    legacy_system: Mapped[str] = mapped_column(String(64), default="tech_insight_loop", index=True)
    legacy_table: Mapped[str] = mapped_column(String(64), default="jobs", index=True)
    legacy_id: Mapped[str] = mapped_column(String(128), index=True)
    job_type: Mapped[str] = mapped_column(String(128), default="", index=True)
    status: Mapped[str] = mapped_column(String(64), default="", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legacy_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_sources: Mapped[int] = mapped_column(Integer, default=0)
    processed_sources: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    details_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
