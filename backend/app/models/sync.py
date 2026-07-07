from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, TimestampMixin


class SyncOutbox(IdMixin, ScopeMixin, TimestampMixin, Base):
    __tablename__ = "sync_outbox"

    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    payload_hash: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)


class SyncInbox(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_inbox"

    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_instance_id: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    payload_hash: Mapped[str] = mapped_column(String(128), default="")
    record_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_runs"

    package_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_instance_id: Mapped[str] = mapped_column(String(64), index=True)
    target_instance_id: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    counts_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conflicts: Mapped[list[SyncConflict]] = relationship(back_populates="sync_run")


class SyncCursor(TimestampMixin, Base):
    """consumer 侧每类对象的拉取水位（docs/deployment/deployment-topology.md §3.5）。

    cursor 是 publisher 下发的不透明 keyset 游标，空串表示从头拉取。
    """

    __tablename__ = "sync_cursors"

    object_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    cursor: Mapped[str] = mapped_column(String(255), default="")
    last_pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")


class SyncConflict(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_conflicts"

    sync_run_id: Mapped[str] = mapped_column(ForeignKey("sync_runs.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    local_revision: Mapped[int] = mapped_column(Integer, default=0)
    incoming_revision: Mapped[int] = mapped_column(Integer, default=0)
    field_name: Mapped[str] = mapped_column(String(128), default="")
    local_value_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    incoming_value_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    conflict_reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resolution_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    resolved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sync_run: Mapped[SyncRun] = relationship(back_populates="conflicts")
