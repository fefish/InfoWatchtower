from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.auth import UserRead

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
    enabled: bool = True
    # private（仅成员可见）| internal_public（登录用户可发现/订阅，游客可只读浏览）
    visibility: str = "private"
    current_user_workspace_role: str | None = None


class WorkspaceCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    workspace_type: str = Field(default="intelligence_workspace", min_length=1, max_length=64)
    default_domain_code: str = Field(default="ai", min_length=1, max_length=64)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    enabled: bool | None = None
    default_domain_code: str | None = Field(default=None, min_length=1, max_length=64)


class WorkspaceMemberUpsert(BaseModel):
    user_id: str = Field(min_length=1)
    workspace_role: str = Field(default="member", pattern=r"^(viewer|member|admin|owner)$")
    confirm_dangerous_change: bool = False


class WorkspaceMemberRead(BaseModel):
    user: UserRead
    workspace_role: str
    enabled: bool


class WorkspaceSectionRead(BaseModel):
    section_key: str
    name: str
    section_type: str
    route_path: str
    sort_order: int
    group: str = "system"
    # 分区可见的最低工作台角色：阅读分区（日报/周报/历史报告/实体大事记）为
    # viewer，管理分区默认 member。前端导航与路由守卫按此数据驱动过滤。
    min_role: str = "member"


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


class WorkspaceFeedbackPolicyRead(BaseModel):
    workspace_code: str
    viewer_can_react: bool = True
    viewer_can_rate: bool = True
    viewer_can_comment: bool = True
    viewer_can_edit: bool = False
    notify_on_comment: bool = True
    notify_on_publish: bool = False


class WorkspaceFeedbackPolicyUpdate(BaseModel):
    viewer_can_react: bool = True
    viewer_can_rate: bool = True
    viewer_can_comment: bool = True
    viewer_can_edit: bool = False
    notify_on_comment: bool = True
    notify_on_publish: bool = False


class WorkspaceReportPolicyRead(BaseModel):
    workspace_code: str
    # 每日流水线出稿后是否自动发布（actor=system）。默认 true：
    # 用户口径“每天 12 点默认直接推送，采编只在需要时修订”。
    auto_publish_daily: bool = True


class WorkspaceReportPolicyUpdate(BaseModel):
    auto_publish_daily: bool = True


class WorkspaceDiscoverRead(BaseModel):
    """GET /api/workspaces/discover 的条目：登录用户可见的 internal_public 工作台。"""

    code: str
    name: str
    description: str
    member_count: int
    # 当前用户是否已有 enabled membership（游客恒为 False：游客不建 membership）
    joined: bool
    # 已加入时的工作台角色；游客对 internal_public 返回 "viewer"（隐式只读视角）
    workspace_role: str | None = None


class WorkspaceSubscriptionRead(BaseModel):
    workspace_code: str
    workspace_role: str
    subscribed: bool = True


class WorkspaceVisibilityUpdate(BaseModel):
    visibility: str = Field(pattern=r"^(private|internal_public)$")


class WorkspaceJoinCodeRead(BaseModel):
    """当前 active 加入码（GET/POST /api/workspaces/{code}/join-code）。"""

    code: str
    default_role: str
    expires_at: datetime | None = None
    max_uses: int | None = None
    use_count: int = 0
    created_at: datetime
    created_by: str | None = None


class WorkspaceJoinCodeCreate(BaseModel):
    """生成/轮换加入码。default_role 只允许 viewer|member（admin/owner 走
    成员管理单人流程 + 危险确认），否则 422。"""

    default_role: str = Field(default="viewer", pattern=r"^(viewer|member)$")
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    max_uses: int | None = Field(default=None, ge=1, le=100000)


class WorkspaceJoinByCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class WorkspaceJoinByCodeRead(BaseModel):
    workspace_code: str
    workspace_name: str
    workspace_role: str
    # 本次是否真实新增或重新启用 membership（已是 enabled 成员时 False，幂等不降级）
    joined: bool


class WorkspaceDepartmentMembershipTarget(BaseModel):
    department: str = Field(min_length=1, max_length=128)
    workspace_role: str = Field(default="viewer", pattern=r"^(viewer|member|admin|owner)$")


class WorkspaceAuthMembershipMappingRead(BaseModel):
    workspace_code: str
    department_workspaces: list[WorkspaceDepartmentMembershipTarget] = Field(default_factory=list)


class WorkspaceAuthMembershipMappingUpdate(BaseModel):
    department_workspaces: list[WorkspaceDepartmentMembershipTarget] = Field(default_factory=list, max_length=100)
