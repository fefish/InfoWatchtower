from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, SyncMixin, TimestampMixin, new_id
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


class WorkspaceJoinCode(IdMixin, TimestampMixin, Base):
    """工作台加入码：已注册用户的团队自助入台入口（不建号、不改全局角色）。

    - `code`：8 位大写字母+数字，剔除易混字符 0/O/1/I，全局唯一；
    - 每个工作台同一时刻至多一个 `status=active` 的码，「轮换」在单事务内
      将旧码置 disabled 并生成新码；历史码保留不删（审计追溯）；
    - `default_role` 只允许 viewer|member，admin/owner 走成员管理单人流程。
    事实源：docs/backend/workspace-configuration-design.md §14。
    """

    __tablename__ = "workspace_join_codes"

    global_id: Mapped[str] = mapped_column(String(64), default=new_id, unique=True, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    default_role: Mapped[str] = mapped_column(String(16), default="viewer")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped[Workspace] = relationship()


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
