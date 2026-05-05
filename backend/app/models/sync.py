from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
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
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)


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
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resolution_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    sync_run: Mapped[SyncRun] = relationship(back_populates="conflicts")
