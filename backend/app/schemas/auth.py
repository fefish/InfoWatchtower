from __future__ import annotations

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
    roles: list[str]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class AuthResponse(BaseModel):
    user: UserRead


class UpdateUserRolesRequest(BaseModel):
    role_codes: list[str] = Field(default_factory=list)
