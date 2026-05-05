from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, SyncMixin, TimestampMixin


class ExportJob(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "export_jobs"

    export_type: Mapped[str] = mapped_column(String(64), default="company_sql", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    requested_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    file_path: Mapped[str] = mapped_column(Text, default="")
    params_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    result_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requested_by: Mapped["User | None"] = relationship()
    items: Mapped[list[ExportJobItem]] = relationship(back_populates="export_job")


class ExportJobItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "export_job_items"

    export_job_id: Mapped[str] = mapped_column(ForeignKey("export_jobs.id"), index=True)
    daily_report_item_id: Mapped[str] = mapped_column(ForeignKey("daily_report_items.id"), index=True)
    generated_news_id: Mapped[str] = mapped_column(ForeignKey("generated_news.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    sql_sequence: Mapped[int] = mapped_column(Integer, default=0)
    sql_table: Mapped[str] = mapped_column(String(128), default="")
    sql_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")

    export_job: Mapped[ExportJob] = relationship(back_populates="items")
    daily_report_item: Mapped["DailyReportItem"] = relationship()
    generated_news: Mapped["GeneratedNews"] = relationship()
    news_item: Mapped["NewsItem"] = relationship()
