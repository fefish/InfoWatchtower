from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, SyncMixin, TimestampMixin
from app.models.content import DataSource


class Workspace(IdMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    workspace_type: Mapped[str] = mapped_column(String(64), default="intelligence", index=True)
    default_domain_code: Mapped[str] = mapped_column(String(64), default="ai")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # 工作台可见性：private（仅成员可见）| internal_public（登录用户可在
    # GET /api/workspaces/discover 发现并自助订阅为 viewer；游客会话可只读浏览）。
    # 种子只在建台时赋初值（planning_intel=internal_public），之后由
    # PATCH /api/workspaces/{code}/visibility 管理，重播种不回滚。
    visibility: Mapped[str] = mapped_column(String(32), default="private", index=True)
    config_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    sections: Mapped[list[WorkspaceSection]] = relationship(back_populates="workspace")
    memberships: Mapped[list[WorkspaceMembership]] = relationship(back_populates="workspace")
    source_links: Mapped[list[WorkspaceSourceLink]] = relationship(back_populates="workspace")


class WorkspaceSection(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspace_sections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "section_key", name="uq_workspace_sections_key"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    section_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    section_type: Mapped[str] = mapped_column(String(64), default="page", index=True)
    route_path: Mapped[str] = mapped_column(String(255), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    config_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    workspace: Mapped[Workspace] = relationship(back_populates="sections")


class WorkspaceMembership(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership_user"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_role: Mapped[str] = mapped_column(String(64), default="member", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")


class WorkspaceSourceLink(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspace_source_links"
    __table_args__ = (
        UniqueConstraint("workspace_id", "data_source_id", name="uq_workspace_source_link"),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    domain_code: Mapped[str] = mapped_column(String(64), default="ai", index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_weight: Mapped[float] = mapped_column(Float, default=1.0)
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    workspace: Mapped[Workspace] = relationship(back_populates="source_links")
    data_source: Mapped[DataSource] = relationship()
