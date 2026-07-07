from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SearchResultRead(BaseModel):
    object_type: str
    object_id: str
    title: str
    summary: str = ""
    matched_fields: list[str] = Field(default_factory=list)
    highlight: str = ""
    route: str
    score: float = 0.0
    updated_at: datetime | None = None


class SearchRead(BaseModel):
    query: str
    workspace_code: str
    results: list[SearchResultRead] = Field(default_factory=list)
    next_cursor: str | None = None
