from __future__ import annotations

from pydantic import BaseModel


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
