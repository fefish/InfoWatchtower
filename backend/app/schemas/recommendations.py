from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScorerPolicyPair(BaseModel):
    name: str
    value: float


class ScorerPolicyRead(BaseModel):
    workspace_code: str
    config_loaded: bool
    enabled: bool
    config_version: str
    config_path: str
    thresholds: dict[str, float] = Field(default_factory=dict)
    daily_levels: list[str] = Field(default_factory=list)
    weekly_levels: list[str] = Field(default_factory=list)
    weights: list[ScorerPolicyPair] = Field(default_factory=list)
    top_topics: list[ScorerPolicyPair] = Field(default_factory=list)
    source_tiers: list[ScorerPolicyPair] = Field(default_factory=list)
    source_channels: list[ScorerPolicyPair] = Field(default_factory=list)
    noise_rule_count: int
    direct_reject_noise_types: list[str] = Field(default_factory=list)
    formula_notes: list[str] = Field(default_factory=list)


class ScorerPreviewCreate(BaseModel):
    workspace_code: str
    source_title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=8000)
    source_type: str = Field(default="rss", max_length=64)
    source_name: str = Field(default="", max_length=255)
    source_url: str = Field(default="", max_length=2000)
    source_tier: str = Field(default="", max_length=64)
    source_channel_type: str = Field(default="", max_length=128)
    source_score: float = Field(default=0.0, ge=0, le=100)
    source_tags: list[str] = Field(default_factory=list)
    source_secondary_tags: list[str] = Field(default_factory=list)
    board_relevance_json: dict[str, Any] = Field(default_factory=dict)
    freshness_score: float = Field(default=80.0, ge=0, le=100)


class ScorerPreviewRead(BaseModel):
    workspace_code: str
    source_title: str
    admission_level: str
    admission_score: float
    admission_pool: str
    eligible_for_daily: bool
    noise_types: list[str] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    positive_reasons: list[str] = Field(default_factory=list)
    expert_routes: list[str] = Field(default_factory=list)
    scorer_breakdown: dict[str, Any] = Field(default_factory=dict)
    persistence: str = "not_persisted"


class RecommendationItemDailyReportRead(BaseModel):
    daily_report_id: str
    daily_report_item_id: str
    day_key: str
    report_status: str
    adoption_status: int
    generated_news_id: str
    generation_status: str


class RecommendationRunCreate(BaseModel):
    workspace_code: str
    day_key: str | None = None
    limit: int = Field(default=15, ge=0, le=100)
    source_daily_limit: int = Field(default=2, ge=1, le=20)
    create_daily_draft: bool = True
    generation_timeout_seconds: float = Field(default=45.0, ge=5, le=180)


class RecommendationItemRead(BaseModel):
    id: str
    news_item_id: str
    dedupe_group_id: str
    rank: int
    quality_score: float
    topic_score: float
    freshness_score: float
    feedback_score: float
    diversity_score: float
    source_score: float
    heat_score: float
    final_score: float
    # L3 精排可解释字段（recommendation-scoring-design §6）。
    coarse_score: float = 0.0
    llm_relevance_score: float | None = None
    llm_rerank_status: str = "not_run"
    llm_rerank_reason: str = ""
    rubric_hits: list[str] = Field(default_factory=list)
    rubric_version: int = 0
    selected: bool
    recommendation_reason: str
    admission_level: str
    admission_score: float
    admission_pool: str
    noise_types: list[str] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    scorer_breakdown: dict[str, Any] = Field(default_factory=dict)
    expert_routes: list[str] = Field(default_factory=list)
    source_title: str
    source_name: str
    source_url: str | None
    daily_report: RecommendationItemDailyReportRead | None = None


class RecommendationRunRead(BaseModel):
    id: str
    run_key: str
    workspace_code: str
    domain_code: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    params_json: dict[str, Any]
    summary_json: dict[str, Any]
    items: list[RecommendationItemRead] = Field(default_factory=list)


class RecommendationRunCreateRead(BaseModel):
    run: RecommendationRunRead
    daily_report_id: str | None
    candidates_total: int
    selected_total: int
    generated_total: int


class RecommendationPolicyGuidance(BaseModel):
    want: str = ""
    avoid: str = ""
    boost: str = ""


class FeedbackWorkflowPolicyRead(BaseModel):
    """feedback_workflow 策略块（feedback-heat-scoring §15/§16.1）。"""

    weekly_rollup_enabled: bool = True
    monthly_review_enabled: bool = True
    proposal_generation_enabled: bool = True
    exploration_epsilon: float = 0.0


class RecommendationPolicyRead(BaseModel):
    guidance: RecommendationPolicyGuidance
    active_rubric: dict[str, Any] | None = None
    rubric_version: int = 0
    rubric_status: str = "none"
    llm_rerank_enabled: bool = False
    rerank_top_m: int = 60
    rerank_window_size: int = 12
    daily_rerank_call_budget: int | None = 60
    fusion_weights: dict[str, float] = Field(default_factory=lambda: {"llm": 0.6, "coarse": 0.4})
    semantic_layer_enabled: bool = False
    feedback_workflow: FeedbackWorkflowPolicyRead = Field(
        default_factory=FeedbackWorkflowPolicyRead,
    )


class RecommendationPolicyResolvedRead(BaseModel):
    """只读 resolved 状态（仿 generation-policy）；永不含任何 key 材料。"""

    llm_rerank_available: bool
    provider_usable: bool
    rerank_calls_used_today: int
    rerank_budget: int | None
    active_rubric_version: int
    semantic_layer_available: bool


class WorkspaceRecommendationPolicyRead(BaseModel):
    workspace_code: str
    policy: RecommendationPolicyRead
    resolved: RecommendationPolicyResolvedRead


class RubricCompileRead(BaseModel):
    rubric: dict[str, Any]
    fingerprint: str
    persistence: str = "not_persisted"
    cached: bool = False


class RubricActivateCreate(BaseModel):
    fingerprint: str = Field(min_length=8, max_length=128)


class FeedbackRollupRead(BaseModel):
    """rollup 列表条目（feedback-heat-scoring §16.2；空样本指标为 null 不为 0）。"""

    id: str
    workspace_code: str
    period_type: str
    period_key: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    status: str
    proposal_status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime | None = None


class FeedbackRollupDetailRead(FeedbackRollupRead):
    source_breakdown: dict[str, Any] = Field(default_factory=dict)
    topic_breakdown: dict[str, Any] = Field(default_factory=dict)
    sample_refs: dict[str, Any] = Field(default_factory=dict)


class FeedbackRollupListRead(BaseModel):
    items: list[FeedbackRollupRead] = Field(default_factory=list)
    total: int = 0


class FeedbackRollupRunCreate(BaseModel):
    period_type: str = Field(default="weekly")
    # 缺省 = 上一完整周期（ISO 周 / 自然月）。
    period_key: str | None = None


class RubricRevisionProposalRead(BaseModel):
    id: str
    workspace_code: str
    rollup_id: str
    rollup_period_key: str = ""
    base_rubric_version: int
    prompt_version: str
    proposed_rubric: dict[str, Any] = Field(default_factory=dict)
    change_summary: list[dict[str, Any]] = Field(default_factory=list)
    sample_refs: dict[str, Any] = Field(default_factory=dict)
    status: str
    review_comment: str = ""
    reviewed_at: datetime | None = None
    compile_fingerprint: str = ""
    created_at: datetime | None = None


class RubricRevisionProposalListRead(BaseModel):
    items: list[RubricRevisionProposalRead] = Field(default_factory=list)


class RubricRevisionProposalReviewCreate(BaseModel):
    action: str = Field(pattern="^(accept|reject)$")
    comment: str = Field(default="", max_length=2000)
