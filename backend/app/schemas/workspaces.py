from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceRead(BaseModel):
    code: str
    name: str
    description: str
    workspace_type: str
    default_domain_code: str


class WorkspaceSectionRead(BaseModel):
    section_key: str
    name: str
    section_type: str
    route_path: str
    sort_order: int


class WorkspaceLabelPolicyRead(BaseModel):
    workspace_code: str
    label_set_code: str
    allowed_primary_categories: list[str]
    default_category: str
    fallback_category: str
    tagging_stages: list[str]


class WorkspaceLabelPolicyUpdate(BaseModel):
    label_set_code: str = "ai_sql_categories"
    allowed_primary_categories: list[str] = Field(default_factory=list)
    default_category: str = "AI 应用"
    fallback_category: str = "AI 应用"
