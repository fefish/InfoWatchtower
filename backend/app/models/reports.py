from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    is_headline: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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


class ReportFormat(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    """成稿格式注册表。company_sql_v1 为 locked 内置格式，结构不可改。

    格式只影响成稿（rendition）的分组、字段与导出目标，
    永远不影响采信状态、generated_news 和公司 SQL 出口。
    """

    __tablename__ = "report_formats"
    __table_args__ = (
        UniqueConstraint("workspace_code", "format_code", name="uq_report_formats_workspace_code"),
    )

    format_code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    group_by: Mapped[str] = mapped_column(String(32), default="category")
    headline_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    headline_auto_top_n: Mapped[int] = mapped_column(Integer, default=6)
    item_fields: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    export_targets: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 模板驱动生成（report-renditions-design §10.1）：解析后的模板规范形
    # （运行时只读规范形；内置格式恒为 null）与用户上传原文（JSON/XML，仅回显编辑）。
    generation_template: Mapped[JsonDict | None] = mapped_column(JsonColumn, nullable=True)
    generation_template_source: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReportRendition(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    """某报告按某格式渲染出的成稿快照（视图层，可随时重生成）。"""

    __tablename__ = "report_renditions"
    __table_args__ = (
        UniqueConstraint(
            "report_type",
            "report_id",
            "format_code",
            name="uq_report_renditions_report_format",
        ),
    )

    report_type: Mapped[str] = mapped_column(String(16), index=True)
    report_id: Mapped[str] = mapped_column(String(36), index=True)
    format_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    summary_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    body_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    generated_by: Mapped[str] = mapped_column(String(64), default="rule_projection_v1")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
