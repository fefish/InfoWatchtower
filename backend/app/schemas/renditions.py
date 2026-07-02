from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

REPORT_FORMAT_GROUP_BY = ["category", "board", "none"]
REPORT_FORMAT_ITEM_FIELDS = [
    "tag_line",
    "bullet_points",
    "takeaway",
    "five_fields",
    "summary",
    "source_link",
    "score",
]
REPORT_FORMAT_EXPORT_TARGETS = ["md", "html"]


class ReportFormatRead(BaseModel):
    id: str
    workspace_code: str
    format_code: str
    name: str
    description: str
    builtin: bool
    locked: bool
    group_by: str
    headline_enabled: bool
    headline_auto_top_n: int
    item_fields: list[str] = Field(default_factory=list)
    export_targets: list[str] = Field(default_factory=list)
    enabled: bool
    sort_order: int


class ReportFormatCreate(BaseModel):
    workspace_code: str
    format_code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    group_by: str = "category"
    headline_enabled: bool = False
    headline_auto_top_n: int = Field(default=6, ge=0, le=20)
    item_fields: list[str] = Field(default_factory=lambda: ["summary", "source_link"])
    export_targets: list[str] = Field(default_factory=list)


class ReportFormatUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    group_by: str | None = None
    headline_enabled: bool | None = None
    headline_auto_top_n: int | None = Field(default=None, ge=0, le=20)
    item_fields: list[str] | None = None
    export_targets: list[str] | None = None
    enabled: bool | None = None


class ReportRenditionRead(BaseModel):
    id: str
    report_type: str
    report_id: str
    format_code: str
    status: str
    title: str
    summary_json: dict[str, Any] = Field(default_factory=dict)
    body_json: dict[str, Any] = Field(default_factory=dict)
    generated_by: str
    generated_at: datetime | None
