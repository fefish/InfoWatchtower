from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RoleRead(BaseModel):
    id: str
    code: str
    name: str
    description: str


class UserRead(BaseModel):
    id: str
    external_provider: str
    external_id: str
    employee_no: str | None
    username: str
    display_name: str
    department: str | None
    email: str | None
    status: str
    is_active: bool
    roles: list[str]


class WorkspaceInviteTarget(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    workspace_role: str = Field(default="member", max_length=64)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class AuthResponse(BaseModel):
    user: UserRead


class UpdateUserRolesRequest(BaseModel):
    role_codes: list[str] = Field(default_factory=list)


class InviteCreateRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    role_code: str = Field(default="viewer", min_length=1, max_length=64)
    workspaces: list[WorkspaceInviteTarget] = Field(default_factory=list)
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InviteRead(BaseModel):
    id: str
    code: str
    email: str | None
    role_code: str
    workspaces: list[WorkspaceInviteTarget]
    invite_url: str
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InvitePublicRead(BaseModel):
    code: str
    email_hint: str | None
    role_code: str
    workspaces: list[WorkspaceInviteTarget]
    status: str
    expires_at: datetime


class InviteAcceptRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class PasswordForgotRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AdminResetPasswordRead(BaseModel):
    temporary_password: str


class UserPatchRequest(BaseModel):
    is_active: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=255)


class PermissionChangeDiffRead(BaseModel):
    field: str
    label: str
    before: Any = None
    after: Any = None
    explanation: str


class PermissionChangeRead(BaseModel):
    id: str
    action: str
    object_type: str
    object_id: str
    actor_name: str | None = None
    created_at: datetime
    scope: str
    title: str
    summary: str
    rollback_available: bool
    rollback_reason: str | None = None
    diffs: list[PermissionChangeDiffRead] = Field(default_factory=list)


class PermissionRollbackRequest(BaseModel):
    audit_log_ids: list[str] = Field(min_length=1, max_length=20)
    confirm_dangerous_change: bool = False


class PermissionRollbackResultItem(BaseModel):
    audit_log_id: str
    status: str
    message: str


class PermissionRollbackRead(BaseModel):
    results: list[PermissionRollbackResultItem]
