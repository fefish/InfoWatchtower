from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, SyncMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.content import GeneratedNews
    from app.models.feedback import Comment, Rating, Reaction


class DailyReport(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_code",
            "domain_code",
            "day_key",
            name="uq_daily_reports_workspace_domain_day",
        ),
    )

    day_key: Mapped[str] = mapped_column(String(10), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[DailyReportItem]] = relationship(back_populates="daily_report")


class DailyReportItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "daily_report_items"

    daily_report_id: Mapped[str] = mapped_column(ForeignKey("daily_reports.id"), index=True)
    generated_news_id: Mapped[str] = mapped_column(ForeignKey("generated_news.id"), index=True)
    adoption_status: Mapped[int] = mapped_column(Integer, default=0, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    editor_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    editor_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    editor_key_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    editor_content_json: Mapped[JsonDict | None] = mapped_column(JsonColumn, nullable=True)
    editor_notes: Mapped[str] = mapped_column(Text, default="")

    daily_report: Mapped[DailyReport] = relationship(back_populates="items")
    generated_news: Mapped[GeneratedNews] = relationship(back_populates="daily_report_items")
    reactions: Mapped[list[Reaction]] = relationship(back_populates="daily_report_item")
    ratings: Mapped[list[Rating]] = relationship(back_populates="daily_report_item")
    comments: Mapped[list[Comment]] = relationship(back_populates="daily_report_item")


class WeeklyReport(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint(
            "workspace_code",
            "domain_code",
            "week_key",
            name="uq_weekly_reports_workspace_domain_week",
        ),
    )

    week_key: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[WeeklyReportItem]] = relationship(back_populates="weekly_report")


class WeeklyReportItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "weekly_report_items"

    weekly_report_id: Mapped[str] = mapped_column(ForeignKey("weekly_reports.id"), index=True)
    daily_report_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_report_items.id"),
        nullable=True,
        index=True,
    )
    generated_news_id: Mapped[str | None] = mapped_column(
        ForeignKey("generated_news.id"),
        nullable=True,
        index=True,
    )
    adoption_status: Mapped[int] = mapped_column(Integer, default=0, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    editor_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    editor_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    editor_content_json: Mapped[JsonDict | None] = mapped_column(JsonColumn, nullable=True)

    weekly_report: Mapped[WeeklyReport] = relationship(back_populates="items")
    daily_report_item: Mapped[DailyReportItem | None] = relationship()
    generated_news: Mapped[GeneratedNews | None] = relationship()
