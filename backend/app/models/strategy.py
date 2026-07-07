from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, SyncMixin, TimestampMixin


class Insight(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "insights"

    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    raw_item_id: Mapped[str | None] = mapped_column(ForeignKey("raw_items.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    insight_type: Mapped[str] = mapped_column(String(64), default="trend", index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    source_report_type: Mapped[str] = mapped_column(String(16), default="", index=True)
    source_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_report_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    news_item: Mapped["NewsItem"] = relationship()
    raw_item: Mapped["RawItem | None"] = relationship()
    implications: Mapped[list[StrategicImplication]] = relationship(back_populates="insight")


class StrategicImplication(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "strategic_implications"

    insight_id: Mapped[str] = mapped_column(ForeignKey("insights.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    implication_type: Mapped[str] = mapped_column(String(64), default="opportunity", index=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    insight: Mapped[Insight] = relationship(back_populates="implications")
    requirements: Mapped[list[Requirement]] = relationship(back_populates="strategic_implication")


class Requirement(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "requirements"

    strategic_implication_id: Mapped[str | None] = mapped_column(
        ForeignKey("strategic_implications.id"),
        nullable=True,
        index=True,
    )
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(32), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    strategic_implication: Mapped[StrategicImplication | None] = relationship(
        back_populates="requirements",
    )
    owner: Mapped["User | None"] = relationship()
    source_links: Mapped[list[RequirementSourceLink]] = relationship(back_populates="requirement")
    topic_tasks: Mapped[list[TopicTask]] = relationship(back_populates="requirement")


class RequirementSourceLink(IdMixin, TimestampMixin, Base):
    __tablename__ = "requirement_source_links"

    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), index=True)
    insight_id: Mapped[str | None] = mapped_column(ForeignKey("insights.id"), nullable=True, index=True)
    daily_report_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_report_items.id"),
        nullable=True,
        index=True,
    )
    weekly_report_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("weekly_report_items.id"),
        nullable=True,
        index=True,
    )
    entity_milestone_id: Mapped[str | None] = mapped_column(
        ForeignKey("entity_milestones.id"),
        nullable=True,
        index=True,
    )
    historical_report_id: Mapped[str | None] = mapped_column(
        ForeignKey("historical_reports.id"),
        nullable=True,
        index=True,
    )
    historical_feedback_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("historical_feedback_items.id"),
        nullable=True,
        index=True,
    )
    news_item_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True, index=True)
    raw_item_id: Mapped[str | None] = mapped_column(ForeignKey("raw_items.id"), nullable=True, index=True)
    link_type: Mapped[str] = mapped_column(String(64), default="evidence", index=True)
    note: Mapped[str] = mapped_column(Text, default="")

    requirement: Mapped[Requirement] = relationship(back_populates="source_links")
    insight: Mapped[Insight | None] = relationship()
    daily_report_item: Mapped["DailyReportItem | None"] = relationship()
    weekly_report_item: Mapped["WeeklyReportItem | None"] = relationship()
    entity_milestone: Mapped["EntityMilestone | None"] = relationship()
    historical_report: Mapped["HistoricalReport | None"] = relationship()
    historical_feedback_item: Mapped["HistoricalFeedbackItem | None"] = relationship()
    news_item: Mapped["NewsItem | None"] = relationship()
    raw_item: Mapped["RawItem | None"] = relationship()


class TopicTask(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "topic_tasks"

    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("requirements.id"), nullable=True, index=True)
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    requirement: Mapped[Requirement | None] = relationship(back_populates="topic_tasks")
    assignee: Mapped["User | None"] = relationship()
