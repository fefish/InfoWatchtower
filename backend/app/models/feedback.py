from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, TimestampMixin


class Reaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "reactions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    news_item_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True, index=True)
    daily_report_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_report_items.id"),
        nullable=True,
        index=True,
    )
    reaction_type: Mapped[str] = mapped_column(String(32), default="like", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship()
    news_item: Mapped["NewsItem | None"] = relationship()
    daily_report_item: Mapped["DailyReportItem | None"] = relationship(back_populates="reactions")


class Rating(IdMixin, TimestampMixin, Base):
    __tablename__ = "ratings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    news_item_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True, index=True)
    daily_report_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_report_items.id"),
        nullable=True,
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(64), default="overall", index=True)
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")

    user: Mapped["User"] = relationship()
    news_item: Mapped["NewsItem | None"] = relationship()
    daily_report_item: Mapped["DailyReportItem | None"] = relationship(back_populates="ratings")


class Comment(IdMixin, TimestampMixin, Base):
    __tablename__ = "comments"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    news_item_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True, index=True)
    daily_report_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_report_items.id"),
        nullable=True,
        index=True,
    )
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    root_id: Mapped[str | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="visible", index=True)

    user: Mapped["User"] = relationship()
    news_item: Mapped["NewsItem | None"] = relationship()
    daily_report_item: Mapped["DailyReportItem | None"] = relationship(back_populates="comments")
    parent: Mapped["Comment | None"] = relationship(
        foreign_keys=[parent_id],
        remote_side="Comment.id",
        back_populates="replies",
    )
    replies: Mapped[list["Comment"]] = relationship(
        foreign_keys=[parent_id],
        back_populates="parent",
    )
    root: Mapped["Comment | None"] = relationship(foreign_keys=[root_id], remote_side="Comment.id")


class EditorialAction(IdMixin, TimestampMixin, Base):
    __tablename__ = "editorial_actions"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    action_type: Mapped[str] = mapped_column(String(64), index=True)
    before_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    after_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")

    user: Mapped["User | None"] = relationship()


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    user: Mapped["User | None"] = relationship()
