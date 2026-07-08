from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import IdMixin, JsonColumn, JsonDict, ScopeMixin, SyncMixin, TimestampMixin


class DataSource(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "data_sources"

    source_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_focus_id: Mapped[int] = mapped_column(Integer, default=1)
    backfill_days: Mapped[int] = mapped_column(Integer, default=7)
    credential_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fetch_config: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    paper_config: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    metadata_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    source_score: Mapped[float] = mapped_column(Float, default=0.0)

    raw_items: Mapped[list[RawItem]] = relationship(back_populates="data_source")
    news_items: Mapped[list[NewsItem]] = relationship(back_populates="data_source")


class RawItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "raw_items"
    __table_args__ = (UniqueConstraint("data_source_id", "entry_key", name="uq_raw_items_source_entry"),)

    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    entry_key: Mapped[str] = mapped_column(String(255), index=True)
    source_title: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    data_source: Mapped[DataSource] = relationship(back_populates="raw_items")
    news_items: Mapped[list[NewsItem]] = relationship(back_populates="raw_item")


class IngestionRun(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_runs"

    run_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    run_type: Mapped[str] = mapped_column(String(64), default="workspace_fetch", index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_total: Mapped[int] = mapped_column(Integer, default=0)
    source_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    source_failed: Mapped[int] = mapped_column(Integer, default=0)
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
    raw_created: Mapped[int] = mapped_column(Integer, default=0)
    raw_updated: Mapped[int] = mapped_column(Integer, default=0)
    params_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    summary_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)


class NewsItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "news_items"

    raw_item_id: Mapped[str] = mapped_column(ForeignKey("raw_items.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    focus_id: Mapped[int] = mapped_column(Integer, default=1)
    dedupe_key: Mapped[str] = mapped_column(String(512), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True)
    normalization_status: Mapped[str] = mapped_column(String(32), default="normalized", index=True)
    normalization_notes: Mapped[str] = mapped_column(Text, default="")

    raw_item: Mapped[RawItem] = relationship(back_populates="news_items")
    data_source: Mapped[DataSource] = relationship(back_populates="news_items")
    duplicate_of: Mapped[NewsItem | None] = relationship(remote_side="NewsItem.id")
    dedupe_group_items: Mapped[list[DedupeGroupItem]] = relationship(back_populates="news_item")
    recommendation_items: Mapped[list[RecommendationItem]] = relationship(back_populates="news_item")
    generated_news_items: Mapped[list[GeneratedNews]] = relationship(back_populates="news_item")


class DedupeGroup(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "dedupe_groups"
    __table_args__ = (
        UniqueConstraint("workspace_code", "dedupe_key", name="uq_dedupe_groups_workspace_key"),
    )

    dedupe_key: Mapped[str] = mapped_column(String(512), index=True)
    winner_news_item_id: Mapped[str | None] = mapped_column(ForeignKey("news_items.id"), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")

    winner_news_item: Mapped[NewsItem | None] = relationship(foreign_keys=[winner_news_item_id])
    items: Mapped[list[DedupeGroupItem]] = relationship(back_populates="dedupe_group")
    recommendation_items: Mapped[list[RecommendationItem]] = relationship(back_populates="dedupe_group")


class DedupeGroupItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "dedupe_group_items"
    __table_args__ = (
        UniqueConstraint("dedupe_group_id", "news_item_id", name="uq_dedupe_group_news_item"),
    )

    dedupe_group_id: Mapped[str] = mapped_column(ForeignKey("dedupe_groups.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_reason: Mapped[str] = mapped_column(Text, default="")
    rank_score: Mapped[float] = mapped_column(Float, default=0.0)

    dedupe_group: Mapped[DedupeGroup] = relationship(back_populates="items")
    news_item: Mapped[NewsItem] = relationship(back_populates="dedupe_group_items")
    recommendation_items: Mapped[list[RecommendationItem]] = relationship(back_populates="dedupe_group_item")


class RecommendationRun(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "recommendation_runs"

    run_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    params_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    summary_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    items: Mapped[list[RecommendationItem]] = relationship(back_populates="run")


class RecommendationItem(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "recommendation_items"

    run_id: Mapped[str] = mapped_column(ForeignKey("recommendation_runs.id"), index=True)
    dedupe_group_id: Mapped[str] = mapped_column(ForeignKey("dedupe_groups.id"), index=True)
    dedupe_group_item_id: Mapped[str] = mapped_column(ForeignKey("dedupe_group_items.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    topic_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    feedback_score: Mapped[float] = mapped_column(Float, default=0.0)
    diversity_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_score: Mapped[float] = mapped_column(Float, default=0.0)
    heat_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    # L1 粗排分快照（recommendation-scoring-design §4.2/§6）：无 LLM 精排时
    # final_score == coarse_score（回归红线）；存量行迁移回填 = final_score。
    coarse_score: Mapped[float] = mapped_column(Float, default=0.0)
    # L3 listwise 精排产物（§4.4/§6）：只产排序信号，永不改准入。
    llm_relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 枚举 not_run/scored/cached/window_failed/skipped/disabled
    llm_rerank_status: Mapped[str] = mapped_column(String(24), default="not_run")
    llm_rerank_reason: Mapped[str] = mapped_column(Text, default="")
    rubric_hits_json: Mapped[list[str]] = mapped_column(JsonColumn, default=list)
    rubric_version: Mapped[int] = mapped_column(Integer, default=0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    recommendation_reason: Mapped[str] = mapped_column(Text, default="")
    admission_level: Mapped[str] = mapped_column(String(16), default="", index=True)
    admission_score: Mapped[float] = mapped_column(Float, default=0.0)
    admission_pool: Mapped[str] = mapped_column(String(64), default="", index=True)
    noise_types_json: Mapped[list[str]] = mapped_column(JsonColumn, default=list)
    reject_reasons_json: Mapped[list[str]] = mapped_column(JsonColumn, default=list)
    scorer_breakdown_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    expert_routes_json: Mapped[list[str]] = mapped_column(JsonColumn, default=list)

    run: Mapped[RecommendationRun] = relationship(back_populates="items")
    dedupe_group: Mapped[DedupeGroup] = relationship(back_populates="recommendation_items")
    dedupe_group_item: Mapped[DedupeGroupItem] = relationship(back_populates="recommendation_items")
    news_item: Mapped[NewsItem] = relationship(back_populates="recommendation_items")
    generated_news: Mapped[list[GeneratedNews]] = relationship(back_populates="recommendation_item")


class GeneratedNews(IdMixin, ScopeMixin, SyncMixin, TimestampMixin, Base):
    __tablename__ = "generated_news"

    # nullable：intranet 侧联动同步的成稿没有本地推荐链（docs/deployment/deployment-topology.md §3.4）
    recommendation_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("recommendation_items.id"),
        nullable=True,
        index=True,
    )
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    category: Mapped[str] = mapped_column(String(64), default="基础竞争力", index=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    # 技术洞察成稿辅助字段（board/bullet_points/takeaway/tag_line）。
    # 与 content_json 严格隔离：公司 SQL 导出不读取本字段。
    insight_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_by: Mapped[str] = mapped_column(String(64), default="system")
    generation_status: Mapped[str] = mapped_column(String(32), default="draft", index=True)

    # 按 format_code 分桶的模板增量字段产出（report-renditions-design §10.1）。
    # 与 content_json/insight_json/category 严格隔离：永不进公司 SQL、dedupe 与推荐输入。
    template_extras_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)

    recommendation_item: Mapped[RecommendationItem | None] = relationship(back_populates="generated_news")
    news_item: Mapped[NewsItem] = relationship(back_populates="generated_news_items")
    daily_report_items: Mapped[list[DailyReportItem]] = relationship(back_populates="generated_news")


class GenerationUsage(IdMixin, TimestampMixin, Base):
    """工作台每日模型调用计数（generation_policy.daily_generation_budget 口径）。

    计数按 (workspace_code, day_key, purpose) 统计当日模型调用（成功+失败都计，
    含模板增量字段生成）。purpose 四桶
    （generation/rerank/rubric_compile/feedback_rollup）配额互不挤占
    （recommendation-scoring-design §9.1、feedback-heat-scoring §17 第 5 条）：
    - generation：generation_policy.daily_generation_budget（现状语义不变）；
    - rerank：recommendation_policy.daily_rerank_call_budget（默认 60）；
    - rubric_compile：固定 20 次/工作台/日，不可配；
    - feedback_rollup：固定 4 次/工作台/日，不可配（周 rollup 提案生成专用）。
    Wave2 模板包等新用途消费同一分桶语义：读写一律带 purpose 过滤。
    """

    __tablename__ = "generation_daily_usage"
    __table_args__ = (
        UniqueConstraint(
            "workspace_code",
            "day_key",
            "purpose",
            name="uq_generation_daily_usage_ws_day_purpose",
        ),
    )

    workspace_code: Mapped[str] = mapped_column(String(64), index=True)
    day_key: Mapped[str] = mapped_column(String(10), index=True)
    # 枚举 generation | rerank | rubric_compile（存量行迁移回填 'generation'）。
    purpose: Mapped[str] = mapped_column(String(24), default="generation", index=True)
    calls_total: Mapped[int] = mapped_column(Integer, default=0)


class RecommendationRubricCompile(IdMixin, TimestampMixin, Base):
    """内容导向 rubric 编译缓存与审计回溯（recommendation-scoring-design §5.3/§10）。

    (workspace_code, fingerprint) 唯一：相同 guidance 的重复编译命中缓存，
    零模型调用（幂等预览）。activate 时校验 fingerprint 7 天内存在。
    """

    __tablename__ = "recommendation_rubric_compiles"
    __table_args__ = (
        UniqueConstraint(
            "workspace_code",
            "fingerprint",
            name="uq_recommendation_rubric_compiles_ws_fp",
        ),
    )

    workspace_code: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    guidance_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    rubric_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    prompt_version: Mapped[str] = mapped_column(String(32), default="compile_prompt_v1")
    model_called: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")


class SourceScoreSnapshot(IdMixin, TimestampMixin, Base):
    """源先验周期再估计快照（feedback-heat-scoring §10.1）。

    每日全量重估、非累加：同 (workspace, source, window, day_key) 重跑覆盖当日
    快照；L1 `_source_score` 只读取最新 day_key 的 delta，无快照时 delta=0。
    """

    __tablename__ = "source_score_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "workspace_code",
            "data_source_id",
            "window",
            "day_key",
            name="uq_source_score_snapshots_ws_src_window_day",
        ),
    )

    workspace_code: Mapped[str] = mapped_column(String(64), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    window: Mapped[str] = mapped_column(String(16), default="14d")
    recommended_count: Mapped[int] = mapped_column(Integer, default=0)
    adopted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    adopt_rate: Mapped[float] = mapped_column(Float, default=0.0)
    reject_rate: Mapped[float] = mapped_column(Float, default=0.0)
    like_rate: Mapped[float] = mapped_column(Float, default=0.0)
    # clamp(8*adopt-6*reject+2*like, -6.0, +6.0)：硬界防漂移发散。
    source_prior_delta: Mapped[float] = mapped_column(Float, default=0.0)
    day_key: Mapped[str] = mapped_column(String(10), index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RubricTopicPrior(IdMixin, TimestampMixin, Base):
    """rubric 主题权重再估计快照（feedback-heat-scoring §10.2）。

    effective_weight 钳制在 authored weight 的 [0.5, 1.5] 倍；authored rubric
    永不被改写；rubric_version 变更后统计清零重来。
    """

    __tablename__ = "rubric_topic_priors"
    __table_args__ = (
        UniqueConstraint(
            "workspace_code",
            "rubric_version",
            "topic_code",
            "day_key",
            name="uq_rubric_topic_priors_ws_ver_topic_day",
        ),
    )

    workspace_code: Mapped[str] = mapped_column(String(64), index=True)
    rubric_version: Mapped[int] = mapped_column(Integer, default=0, index=True)
    topic_code: Mapped[str] = mapped_column(String(32), index=True)
    pos_count: Mapped[int] = mapped_column(Integer, default=0)
    neg_count: Mapped[int] = mapped_column(Integer, default=0)
    effective_weight: Mapped[float] = mapped_column(Float, default=0.0)
    day_key: Mapped[str] = mapped_column(String(10), index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FeedbackRollup(IdMixin, TimestampMixin, Base):
    """反馈回哺周/月评估快照（feedback-heat-scoring §13/§14/§16.1）。

    无 SyncMixin——永不进同步 feed。零直接改分：本表只存评估指标、
    advisory 建议与代表样本引用；进分数的路径仍只有每日 job 的两个快照
    （source_score_snapshots / rubric_topic_priors）。空样本指标一律 null 不写 0。
    """

    __tablename__ = "feedback_rollups"
    __table_args__ = (
        UniqueConstraint(
            "workspace_code",
            "period_type",
            "period_key",
            name="uq_feedback_rollups_ws_period",
        ),
    )

    workspace_code: Mapped[str] = mapped_column(String(64), index=True)
    # weekly | monthly
    period_type: Mapped[str] = mapped_column(String(16), index=True)
    # ISO 周 2026-W28 / 自然月 2026-06
    period_key: Mapped[str] = mapped_column(String(16), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # succeeded | empty | failed
    status: Mapped[str] = mapped_column(String(16), default="succeeded")
    # none | generated | failed | skipped_*（feedback-heat-scoring §13.5）
    proposal_status: Mapped[str] = mapped_column(String(32), default="none")
    metrics_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    source_breakdown_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    topic_breakdown_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    sample_refs_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RubricRevisionProposal(IdMixin, TimestampMixin, Base):
    """rubric 修订提案（RLHF-lite，人审硬门；feedback-heat-scoring §13.5/§16.1）。

    无 SyncMixin。提案入库对现行 rubric 零影响；唯一生效路径是人审 accept →
    登记 compile 记录（model_called=false）→ 既有 activate 链（rubric_version+1）。
    """

    __tablename__ = "rubric_revision_proposals"
    __table_args__ = (
        Index("ix_rubric_revision_proposals_ws_status", "workspace_code", "status"),
    )

    workspace_code: Mapped[str] = mapped_column(String(64), index=True)
    rollup_id: Mapped[str] = mapped_column(ForeignKey("feedback_rollups.id"), index=True)
    # 生成时的 rubric_version（stale 防护：accept 时不匹配当前版本 → 422）。
    base_rubric_version: Mapped[int] = mapped_column(Integer, default=0)
    prompt_version: Mapped[str] = mapped_column(String(32), default="revision_prompt_v1")
    proposed_rubric_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    change_summary_json: Mapped[list] = mapped_column(JsonColumn, default=list)
    sample_refs_json: Mapped[JsonDict] = mapped_column(JsonColumn, default=dict)
    # pending_review | accepted | rejected | superseded | expired
    status: Mapped[str] = mapped_column(String(24), default="pending_review")
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # accept 时回填的 compile fingerprint（审计回溯）。
    compile_fingerprint: Mapped[str] = mapped_column(String(80), default="")


class NewsItemEmbedding(IdMixin, TimestampMixin, Base):
    """L2 语义层向量（仅 EMBEDDING_ENABLED=true 时写入；本期默认关闭，迁移留位）。"""

    __tablename__ = "news_item_embeddings"
    __table_args__ = (
        UniqueConstraint("news_item_id", "model", name="uq_news_item_embeddings_item_model"),
    )

    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    model: Mapped[str] = mapped_column(String(128))
    dim: Mapped[int] = mapped_column(Integer, default=0)
    vector_json: Mapped[list] = mapped_column(JsonColumn, default=list)
