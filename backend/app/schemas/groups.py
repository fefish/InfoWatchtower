from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.auth import UserRead


class UserGroupCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)


class UserGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class UserGroupRead(BaseModel):
    id: str
    code: str
    name: str
    description: str
    member_count: int


class UserGroupDetailRead(UserGroupRead):
    members: list[UserRead] = Field(default_factory=list)


class UserGroupMemberAdd(BaseModel):
    user_id: str = Field(min_length=1)


class WorkspaceMembersBulkAdd(BaseModel):
    group_code: str = Field(min_length=1, max_length=64)
    # 按组批量入台不允许直接铺 owner，owner 变更走单人流程 + 危险确认。
    workspace_role: str = Field(default="member", pattern=r"^(viewer|member|admin)$")


class WorkspaceMembersBulkAddRead(BaseModel):
    workspace_code: str
    group_code: str
    workspace_role: str
    added_count: int
    reactivated_count: int
    skipped_count: int
    member_count: int
