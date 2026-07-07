from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


SyncHealthStatus = Literal["ok", "warning", "critical", "inactive"]


class SyncHealthAlertRead(BaseModel):
    severity: Literal["warning", "critical"]
    code: str
    message: str
    object_type: str | None = None


class SyncCursorHealthRead(BaseModel):
    object_type: str
    cursor: str
    last_pulled_at: datetime | None
    last_status: str
    last_error: str
    age_seconds: int | None
    status: SyncHealthStatus
    warnings: list[str] = Field(default_factory=list)


class SyncHealthRunRead(BaseModel):
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


class SyncHealthThresholdsRead(BaseModel):
    warning_after_seconds: int
    critical_after_seconds: int
    pull_interval_seconds: int


class SyncHealthRead(BaseModel):
    status: SyncHealthStatus
    generated_at: datetime
    sync_role: str
    summary: str
    thresholds: SyncHealthThresholdsRead
    cursor_count: int
    missing_cursor_count: int
    stale_cursor_count: int
    failed_cursor_count: int
    failed_inbox_count: int
    failed_inbox_by_object_type: dict[str, int]
    failed_inbox_retry_due_count: int
    failed_inbox_retry_blocked_count: int
    failed_inbox_next_retry_at: datetime | None
    failed_inbox_retry_policy: dict[str, Any]
    open_conflict_count: int
    recent_failed_run_count: int
    last_run: SyncHealthRunRead | None
    cursors: list[SyncCursorHealthRead] = Field(default_factory=list)
    alerts: list[SyncHealthAlertRead] = Field(default_factory=list)


class SyncConflictRead(BaseModel):
    id: str
    sync_run_id: str
    package_id: str | None
    source_instance_id: str | None
    target_instance_id: str | None
    direction: str | None
    object_type: str
    object_id: str
    local_revision: int
    incoming_revision: int
    field_name: str
    local_value_json: dict[str, Any]
    incoming_value_json: dict[str, Any]
    conflict_reason: str
    status: str
    resolution_json: dict[str, Any]
    resolved_by_user_id: str | None
    resolved_by_name: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SyncConflictResolve(BaseModel):
    strategy: Literal["keep_local", "ignored", "retry_after_dependency", "use_incoming", "manual_merge"] = "keep_local"
    reason: str = Field(default="", max_length=1000)
    merged_json: dict[str, Any] | None = None
