from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, SyncMixin, TimestampMixin

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(IdMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("external_provider", "external_id", name="uq_users_external_identity"),
    )

    external_provider: Mapped[str] = mapped_column(String(64), default="local", index=True)
    external_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    employee_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        back_populates="users",
    )


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    users: Mapped[list[User]] = relationship(
        secondary=user_roles,
        back_populates="roles",
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions,
        back_populates="roles",
    )


class Permission(IdMixin, TimestampMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions,
        back_populates="permissions",
    )


class UserGroup(IdMixin, TimestampMixin, Base):
    """运营用户组：批量把一组人加入工作台、组织任务协作视图。

    组本身不构成第三层权限；权限仍由全局角色和 workspace membership 决定。
    """

    __tablename__ = "user_groups"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    members: Mapped[list[UserGroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )


class UserGroupMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_user_group_members_user"),
    )

    group_id: Mapped[str] = mapped_column(
        ForeignKey("user_groups.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    group: Mapped[UserGroup] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class UserInvite(IdMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "user_invites"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_code: Mapped[str] = mapped_column(String(64), index=True)
    workspace_codes: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    invited_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invited_by: Mapped[User] = relationship(foreign_keys=[invited_by_id])
    accepted_by: Mapped[User | None] = relationship(foreign_keys=[accepted_by_id])


class PasswordResetToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class LoginAttempt(IdMixin, TimestampMixin, Base):
    __tablename__ = "login_attempts"

    username: Mapped[str] = mapped_column(String(128), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
