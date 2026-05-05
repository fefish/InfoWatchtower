from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, TimestampMixin
from app.models.identity import User


class LabelSet(IdMixin, ScopeMixin, TimestampMixin, Base):
    __tablename__ = "label_sets"
    __table_args__ = (UniqueConstraint("workspace_code", "domain_code", "code", name="uq_label_sets_scope_code"),)

    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    scope_type: Mapped[str] = mapped_column(String(32), default="domain", index=True)
    target_types: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    config_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    labels: Mapped[list[Label]] = relationship(back_populates="label_set")


class Label(IdMixin, TimestampMixin, Base):
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("label_set_id", "code", name="uq_labels_set_code"),)

    label_set_id: Mapped[str] = mapped_column(ForeignKey("label_sets.id"), index=True)
    parent_label_id: Mapped[str | None] = mapped_column(ForeignKey("labels.id"), nullable=True)
    label_level: Mapped[int] = mapped_column(Integer, default=1, index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    color: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    label_set: Mapped[LabelSet] = relationship(back_populates="labels")
    parent_label: Mapped[Label | None] = relationship(remote_side="Label.id")
    bindings: Mapped[list[ContentLabel]] = relationship(back_populates="label")


class ContentLabel(IdMixin, ScopeMixin, TimestampMixin, Base):
    __tablename__ = "content_labels"
    __table_args__ = (UniqueConstraint("label_id", "target_type", "target_id", name="uq_content_labels_target"),)

    label_id: Mapped[str] = mapped_column(ForeignKey("labels.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    assigned_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assignment_source: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    label: Mapped[Label] = relationship(back_populates="bindings")
    assigned_by_user: Mapped[User | None] = relationship()
