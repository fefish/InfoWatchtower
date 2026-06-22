from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
    task_count: int = 0
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RequirementCreate(BaseModel):
    workspace_code: str = "planning_intel"
    domain_code: str = "ai"
    title: str = Field(min_length=1)
    description: str = ""
    priority: str = "medium"
    status: str = "open"
    due_at: datetime | None = None
    owner_user_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


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
    assignee_user_id: str | None
    assignee_name: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TopicTaskCreate(BaseModel):
    workspace_code: str = "planning_intel"
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


class AuditLogRead(BaseModel):
    id: str
    user_id: str | None
    user_name: str | None
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
