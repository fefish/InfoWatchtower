from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.auth import UserRead


class SetupStatusRead(BaseModel):
    needs_setup: bool


class SetupCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=10, max_length=256)


class SetupCreateRead(BaseModel):
    user: UserRead
