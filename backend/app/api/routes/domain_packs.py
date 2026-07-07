"""Domain pack 目录接口。

让 config/domain_packs/ 下的领域包可被发现、可被消费：建台向导按此列表
选择领域，选中后把 pack 的 domain_code 写入 workspace.default_domain_code
即完成关联；策略解析（app.workspaces.policy）随后真正读取 pack 的
label set / boards / scoring / category_keywords。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.models.identity import User
from app.workspaces.policy import list_domain_packs

router = APIRouter(prefix="/api/domain-packs", tags=["domain-packs"])


class DomainPackBoardRead(BaseModel):
    code: str
    name: str
    description: str = ""
    suggested_categories: list[str] = Field(default_factory=list)


class DomainPackLabelSetRead(BaseModel):
    code: str
    name: str
    categories: list[str] = Field(default_factory=list)
    secondary_labels_by_primary: dict[str, list[str]] = Field(default_factory=dict)


class DomainPackScoringRead(BaseModel):
    prior_keywords: list[str] = Field(default_factory=list)
    source_weight_hints: dict[str, float] = Field(default_factory=dict)


class DomainPackRead(BaseModel):
    domain_code: str
    name: str
    description: str = ""
    boards: list[DomainPackBoardRead] = Field(default_factory=list)
    fallback_board: str = ""
    label_sets: list[DomainPackLabelSetRead] = Field(default_factory=list)
    category_keywords: dict[str, list[str]] = Field(default_factory=dict)
    scoring: DomainPackScoringRead = Field(default_factory=DomainPackScoringRead)
    # 关联方式：把 domain_code 写入 workspace.default_domain_code。
    associate_by: str = "workspace.default_domain_code"


@router.get("", response_model=list[DomainPackRead])
def list_available_domain_packs(
    _: User = Depends(get_current_user),
) -> list[DomainPackRead]:
    return [DomainPackRead.model_validate(pack) for pack in list_domain_packs()]
