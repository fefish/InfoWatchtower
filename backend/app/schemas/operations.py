from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RequirementSourceLinkRead(BaseModel):
    id: str
    link_type: str
    note: str
    insight_id: str | None
    daily_report_item_id: str | None
    weekly_report_item_id: str | None
    entity_milestone_id: str | None
    historical_report_id: str | None
    historical_feedback_item_id: str | None
    news_item_id: str | None
    raw_item_id: str | None
    source_object_type: str
    source_title: str
    source_url: str | None
    data_source_name: str | None
    created_at: datetime


class RequirementSourceLinkCreate(BaseModel):
    insight_id: str | None = None
    daily_report_item_id: str | None = None
    weekly_report_item_id: str | None = None
    entity_milestone_id: str | None = None
    historical_report_id: str | None = None
    historical_feedback_item_id: str | None = None
    news_item_id: str | None = None
    raw_item_id: str | None = None
    link_type: str = "evidence"
    note: str = ""


class InsightRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    news_item_id: str
    raw_item_id: str | None
    title: str
    summary: str
    insight_type: str
    status: str
    source_report_type: str
    source_report_id: str | None
    source_report_item_id: str | None
    source_title: str
    source_url: str | None
    data_source_name: str | None
    implication_count: int = 0
    confidence_score: float
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class InsightCreate(BaseModel):
    workspace_code: str
    domain_code: str = "ai"
    news_item_id: str
    raw_item_id: str | None = None
    title: str = Field(min_length=1)
    summary: str = ""
    insight_type: str = "trend"
    status: str = "draft"
    source_report_type: str = ""
    source_report_id: str | None = None
    source_report_item_id: str | None = None
    confidence_score: float = Field(default=0.7, ge=0, le=1)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class InsightUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    insight_type: str | None = None
    status: str | None = None
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    metadata_json: dict[str, Any] | None = None


class StrategicImplicationRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    insight_id: str
    insight_title: str | None = None
    title: str
    description: str
    implication_type: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class StrategicImplicationCreate(BaseModel):
    insight_id: str
    title: str = Field(min_length=1)
    description: str = ""
    implication_type: str = "opportunity"
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class StrategicImplicationUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    implication_type: str | None = None
    metadata_json: dict[str, Any] | None = None


class ReportItemStrategyLoopCreate(BaseModel):
    insight_title: str | None = None
    insight_summary: str | None = None
    insight_type: str = "trend"
    confidence_score: float = Field(default=0.8, ge=0, le=1)
    implication_title: str | None = None
    implication_description: str | None = None
    implication_type: str = "opportunity"
    requirement_title: str | None = None
    requirement_description: str | None = None
    requirement_priority: str = "medium"
    requirement_status: str = "draft"
    requirement_due_at: datetime | None = None
    owner_user_id: str | None = None
    source_note: str = ""
    create_task: bool = False
    task_title: str | None = None
    task_description: str | None = None
    task_status: str = "open"
    task_due_at: datetime | None = None
    task_assignee_user_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ReportItemEntityMilestoneCreate(BaseModel):
    entity_name: str = Field(min_length=1)
    entity_type: str = "company"
    entity_rank: str = ""
    tracked_entity_id: str | None = None
    event_title: str | None = None
    event_type: str = "report_signal"
    event_time: datetime | None = None
    event_brief: str | None = None
    impact_brief: str | None = None
    board: str | None = None
    importance_level: str = "medium"
    importance_score: float = Field(default=70.0, ge=0, le=100)
    confidence_score: float = Field(default=0.8, ge=0, le=1)
    source_note: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class EntityMilestoneUpdate(BaseModel):
    event_title: str | None = None
    event_type: str | None = None
    event_time: datetime | None = None
    event_brief: str | None = None
    event_content: str | None = None
    impact_brief: str | None = None
    impact: str | None = None
    timeline_brief: str | None = None
    source_url: str | None = None
    source_name: str | None = None
    board: str | None = None
    selected_for_timeline: bool | None = None
    importance_level: str | None = None
    importance_score: float | None = Field(default=None, ge=0, le=100)
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    curation_status: str | None = None
    curation_note: str | None = None
    metadata_json: dict[str, Any] | None = None


class RequirementRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    title: str
    description: str
    priority: str
    status: str
    due_at: datetime | None
    owner_user_id: str | None
    owner_name: str | None
    source_count: int = 0
    source_links: list[RequirementSourceLinkRead] = Field(default_factory=list)
    task_count: int = 0
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RequirementCreate(BaseModel):
    workspace_code: str
    domain_code: str = "ai"
    title: str = Field(min_length=1)
    description: str = ""
    priority: str = "medium"
    status: str = "open"
    due_at: datetime | None = None
    owner_user_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    source_daily_report_item_id: str | None = None
    source_weekly_report_item_id: str | None = None
    source_entity_milestone_id: str | None = None
    source_historical_report_id: str | None = None
    source_historical_feedback_item_id: str | None = None
    source_news_item_id: str | None = None
    source_raw_item_id: str | None = None
    source_insight_id: str | None = None
    source_note: str = ""


class RequirementUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    status: str | None = None
    due_at: datetime | None = None
    owner_user_id: str | None = None
    metadata_json: dict[str, Any] | None = None


class TopicTaskRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    requirement_id: str | None
    requirement_title: str | None
    title: str
    description: str
    status: str
    due_at: datetime | None
    is_overdue: bool = False
    blocked_reason: str = ""
    assignee_user_id: str | None
    assignee_name: str | None
    requirement_source_count: int = 0
    requirement_source_links: list[RequirementSourceLinkRead] = Field(default_factory=list)
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TopicTaskCreate(BaseModel):
    workspace_code: str
    domain_code: str = "ai"
    requirement_id: str | None = None
    title: str = Field(min_length=1)
    description: str = ""
    status: str = "open"
    due_at: datetime | None = None
    assignee_user_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TopicTaskUpdate(BaseModel):
    requirement_id: str | None = None
    title: str | None = None
    description: str | None = None
    status: str | None = None
    due_at: datetime | None = None
    assignee_user_id: str | None = None
    metadata_json: dict[str, Any] | None = None


class TopicTaskBatchUpdate(BaseModel):
    workspace_code: str
    task_ids: list[str] = Field(min_length=1, max_length=100)
    status: str | None = None
    blocked_reason: str | None = None


class TopicTaskBatchUpdateRead(BaseModel):
    updated_count: int
    tasks: list[TopicTaskRead] = Field(default_factory=list)


class ReportItemStrategyLoopRead(BaseModel):
    insight: InsightRead
    implication: StrategicImplicationRead
    requirement: RequirementRead
    task: TopicTaskRead | None = None


class SyncRunRead(BaseModel):
    id: str
    package_id: str
    source_instance_id: str
    target_instance_id: str
    direction: str
    status: str
    counts_json: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class SyncRunCreate(BaseModel):
    source_instance_id: str = "public"
    target_instance_id: str = "intranet"
    direction: str = "export"
    limit: int = Field(default=200, ge=0, le=1000)


class SyncPackageExportCreate(BaseModel):
    source_instance_id: str = "public"
    target_instance_id: str = "intranet"
    direction: str = "public_to_intranet"
    limit: int = Field(default=200, ge=0, le=1000)


class SyncPackageExportRead(BaseModel):
    sync_run: SyncRunRead
    package_manifest: dict[str, Any]
    records: list[dict[str, Any]]


class SyncPackageImportCreate(BaseModel):
    package_manifest: dict[str, Any]
    records: list[dict[str, Any]] = Field(default_factory=list)


class SyncPackageImportRead(BaseModel):
    package_id: str
    status: str
    received: int
    applied: int
    skipped: int
    failed: int
    conflicts: int = 0
    errors: list[str] = Field(default_factory=list)


class AuditLogRead(BaseModel):
    id: str
    user_id: str | None
    user_name: str | None
    workspace_code: str
    action: str
    object_type: str
    object_id: str
    ip_address: str
    user_agent: str
    detail_json: dict[str, Any]
    created_at: datetime


class HistoricalReportSummaryRead(BaseModel):
    workspace_code: str
    total: int
    by_report_type: dict[str, int]
    by_status: dict[str, int]
    unresolved_report_count: int
    unresolved_ref_count: int
    earliest_period_start_at: datetime | None
    latest_period_start_at: datetime | None


class HistoricalReportListItem(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    legacy_system: str
    legacy_id: str
    report_type: str
    title: str
    status: str
    period_start_at: datetime | None
    period_end_at: datetime | None
    resolved_ref_count: int
    unresolved_ref_count: int
    content_excerpt: str
    created_at: datetime
    updated_at: datetime


class HistoricalReportDetailRead(HistoricalReportListItem):
    content: str
    source_refs_json: dict[str, Any]
    metadata_json: dict[str, Any]


class LegacyImportMetricRead(BaseModel):
    key: str
    label: str
    expected: int
    actual: int
    missing: int
    coverage_rate: float
    status: str


class LegacyImportRefStatsRead(BaseModel):
    total: int
    resolved: int
    unresolved: int


class LegacyImportSummaryRead(BaseModel):
    workspace_code: str
    generated_at: datetime
    expected_counts: dict[str, int]
    metrics: list[LegacyImportMetricRead]
    report_refs: LegacyImportRefStatsRead
    milestone_article_refs: LegacyImportRefStatsRead
    milestone_report_refs: LegacyImportRefStatsRead
    feedback_article_refs: LegacyImportRefStatsRead
    total_unresolved_refs: int
    gap_item_count: int


class LegacyImportGapItemRead(BaseModel):
    kind: str
    id: str
    legacy_id: str
    title: str
    ref_type: str
    unresolved_refs: list[Any]
    unresolved_count: int
    detail_path: str
    context: dict[str, Any]


class EntityTimelineSummaryRead(BaseModel):
    workspace_code: str
    total_entities: int
    total_milestones: int
    selected_milestones: int
    unresolved_milestone_count: int
    unresolved_ref_count: int
    by_entity_type: dict[str, int]
    by_event_type: dict[str, int]
    by_importance_level: dict[str, int]
    earliest_event_time: datetime | None
    latest_event_time: datetime | None


class TrackedEntityListItem(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    legacy_system: str
    legacy_id: str
    name: str
    entity_type: str
    rank: str
    aliases_json: list[Any]
    influence_score: float
    milestone_count: int
    latest_event_time: datetime | None
    created_at: datetime
    updated_at: datetime


class EntityMilestoneListItem(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    legacy_system: str
    legacy_id: str
    tracked_entity_id: str
    entity_name: str
    entity_type: str
    legacy_article_id: str | None
    legacy_report_id: str | None
    raw_item_id: str | None
    historical_report_id: str | None
    event_time: datetime | None
    event_type: str
    title: str
    timeline_brief: str
    source_url: str | None
    source_name: str
    board: str
    selected_for_timeline: bool
    curation_status: str
    importance_score: float
    importance_level: str
    article_ref_resolved: bool | None
    report_ref_resolved: bool | None
    created_at: datetime
    updated_at: datetime


class EntityMilestoneDetailRead(EntityMilestoneListItem):
    event_content: str
    impact: str
    event_brief: str
    impact_brief: str
    confidence_score: float
    event_dedupe_key: str
    legacy_refs: dict[str, Any]
    metadata_json: dict[str, Any]


class QualityArchiveSummaryRead(BaseModel):
    workspace_code: str
    total_feedback: int
    total_quality_feedback: int
    total_job_runs: int
    unresolved_feedback_count: int
    unresolved_feedback_ref_count: int
    total_job_failures: int
    by_feedback_type: dict[str, int]
    by_quality_reason: dict[str, int]
    by_job_type: dict[str, int]
    by_job_status: dict[str, int]
    latest_feedback_at: datetime | None
    latest_job_started_at: datetime | None


class HistoricalFeedbackListItem(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    legacy_system: str
    legacy_table: str
    legacy_id: str
    legacy_article_id: str | None
    raw_item_id: str | None
    feedback_kind: str
    user_name: str
    feedback_type: str
    reason: str
    comment: str
    feedback_at: datetime | None
    article_ref_resolved: bool | None
    created_at: datetime
    updated_at: datetime


class HistoricalJobRunListItem(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    legacy_system: str
    legacy_table: str
    legacy_id: str
    job_type: str
    status: str
    message: str
    started_at: datetime | None
    ended_at: datetime | None
    total_sources: int
    processed_sources: int
    inserted_count: int
    failed_count: int
    details_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
