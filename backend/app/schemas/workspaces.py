from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_REQUIRED_CONTENT_FIELDS = [
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact",
]


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
    news_format_code: str
    export_category_mode: str = "news_primary"
    required_content_fields: list[str]
    allowed_primary_categories: list[str]
    secondary_labels_by_primary: dict[str, list[str]] = Field(default_factory=dict)
    default_category: str
    fallback_category: str
    tagging_stages: list[str]


class WorkspaceLabelPolicyUpdate(BaseModel):
    label_set_code: str = "ai_sql_categories"
    news_format_code: str = "company_sql_v1"
    export_category_mode: str = "news_primary"
    required_content_fields: list[str] = Field(
        default_factory=lambda: list(DEFAULT_REQUIRED_CONTENT_FIELDS),
    )
    allowed_primary_categories: list[str] = Field(default_factory=list)
    secondary_labels_by_primary: dict[str, list[str]] = Field(default_factory=dict)
    default_category: str = "AI 应用"
    fallback_category: str = "AI 应用"
