from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    workspace_code: Mapped[str] = mapped_column(String(64), default="global", index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    user: Mapped["User | None"] = relationship()


class ActivityEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "activity_events"

    workspace_code: Mapped[str] = mapped_column(String(64), default="planning_intel", index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai", index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    target_object_type: Mapped[str] = mapped_column(String(64), default="", index=True)
    target_object_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    sync_policy: Mapped[str] = mapped_column(String(32), default="local_only", index=True)

    actor: Mapped["User | None"] = relationship()
    notifications: Mapped[list["Notification"]] = relationship(back_populates="activity_event")


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_code: Mapped[str] = mapped_column(String(64), default="planning_intel", index=True)
    activity_event_id: Mapped[str] = mapped_column(ForeignKey("activity_events.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="unread", index=True)
    priority: Mapped[str] = mapped_column(String(32), default="normal", index=True)
    delivery_channel: Mapped[str] = mapped_column(String(32), default="in_app")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
    activity_event: Mapped[ActivityEvent] = relationship(back_populates="notifications")


class NotificationPreference(IdMixin, TimestampMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_code",
            "event_type",
            name="uq_notification_preferences_user_workspace_event",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_code: Mapped[str] = mapped_column(String(64), default="planning_intel", index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship()


class ObjectWatcher(IdMixin, TimestampMixin, Base):
    __tablename__ = "object_watchers"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "workspace_code",
            "object_type",
            "object_id",
            name="uq_object_watchers_user_object",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_code: Mapped[str] = mapped_column(String(64), default="planning_intel", index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    user: Mapped["User"] = relationship()
