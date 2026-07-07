"""schedule_policy 与调度心跳 API 的 Pydantic 模型（pipeline-jobs-design §8.2/§8.5）。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.config import KNOWN_INGESTION_SOURCE_TYPES
from app.pipeline.schedule_policy import parse_time_of_day


class SchedulePolicyRetry(BaseModel):
    max_attempts: int = Field(default=1, ge=0, le=5)
    backoff_seconds: int = Field(default=900, ge=60, le=21600)


class SchedulePolicyWeekly(BaseModel):
    enabled: bool = False
    weekly_day: int = Field(default=5, ge=1, le=7)
    weekly_time: str = "17:00"

    @field_validator("weekly_time")
    @classmethod
    def _validate_weekly_time(cls, value: str) -> str:
        if parse_time_of_day(value) is None:
            raise ValueError("weekly_time must use HH:MM")
        return value.strip()


class WorkspaceSchedulePolicyUpdate(BaseModel):
    """PATCH body：全量策略文档（缺省字段回落契约默认）。"""

    enabled: bool | None = None
    daily_time: str | None = None
    day_offset: int | None = Field(default=None, ge=-7, le=0)
    source_types: list[str] | None = None
    retry: SchedulePolicyRetry = Field(default_factory=SchedulePolicyRetry)
    weekly: SchedulePolicyWeekly = Field(default_factory=SchedulePolicyWeekly)

    @field_validator("daily_time")
    @classmethod
    def _validate_daily_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if parse_time_of_day(value) is None:
            raise ValueError("daily_time must use HH:MM")
        return value.strip()

    @field_validator("source_types")
    @classmethod
    def _validate_source_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            if text not in KNOWN_INGESTION_SOURCE_TYPES:
                raise ValueError(f"unknown source_type: {text}")
            if text not in normalized:
                normalized.append(text)
        return normalized


class SchedulePolicyDocument(BaseModel):
    enabled: bool | None = None
    daily_time: str | None = None
    day_offset: int | None = None
    source_types: list[str] | None = None
    retry: SchedulePolicyRetry
    weekly: SchedulePolicyWeekly


class ResolvedScheduleRead(BaseModel):
    effective_enabled: bool
    effective_daily_time: str | None
    effective_day_offset: int
    effective_source_types: list[str]
    policy_source: str
    next_run_at: str | None
    retry: SchedulePolicyRetry
    weekly: SchedulePolicyWeekly


class ScheduleInstanceBaselineRead(BaseModel):
    scheduler_enabled: bool
    daily_time: str | None
    timezone: str
    day_offset: int
    source_types: list[str]
    workspace_code: str


class WorkspaceSchedulePolicyRead(BaseModel):
    workspace_code: str
    policy: SchedulePolicyDocument
    resolved: ResolvedScheduleRead
    instance: ScheduleInstanceBaselineRead


class SchedulerStatusRunRead(BaseModel):
    run_id: str
    day_key: str
    status: str
    trigger_type: str
    attempt: int
    error_code: str = ""
    skip_reason: str = ""
    finished_at: str | None = None


class SchedulerStatusPendingRetryRead(BaseModel):
    run_id: str
    attempt: int
    next_attempt: int
    next_retry_at: str | None
    error_code: str = ""


class SchedulerStatusWorkspaceRead(BaseModel):
    workspace_code: str
    effective_enabled: bool
    effective_daily_time: str | None
    effective_day_offset: int
    policy_source: str
    next_run_at: str | None
    weekly_enabled: bool = False
    last_runs: list[SchedulerStatusRunRead]
    pending_retry: SchedulerStatusPendingRetryRead | None = None


class SchedulerStatusRead(BaseModel):
    instance_enabled: bool
    deploy_mode: str
    capability_ingestion: bool
    timezone: str
    heartbeat_at: str | None
    heartbeat_stale: bool
    workspaces: list[SchedulerStatusWorkspaceRead]
