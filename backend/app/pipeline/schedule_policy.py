"""工作台级调度策略（docs/backend/pipeline-jobs-design.md §8.1-§8.3）。

分层配置模型：
- 第 1 层实例 env 基线（INGESTION_SCHEDULER_* / DAILY_PIPELINE_DAY_OFFSET_DAYS）。
- 第 2 层工作台 ``workspaces.config_json.schedule_policy``（本模块负责校验与读写规范化）。
- 第 3 层 resolved schedule：每次现算不落库（:func:`resolve_workspace_schedule`）。

契约：config/contracts/workspace_model.json ``schedule_policy``。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as datetime_time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import KNOWN_INGESTION_SOURCE_TYPES, Settings
from app.models.workspace import Workspace

DEFAULT_SCHEDULE_POLICY: dict[str, Any] = {
    "enabled": None,
    "daily_time": None,
    "day_offset": None,
    "source_types": None,
    "retry": {"max_attempts": 1, "backoff_seconds": 900},
    "weekly": {"enabled": False, "weekly_day": 5, "weekly_time": "17:00"},
}

RETRY_MAX_ATTEMPTS_RANGE = (0, 5)
RETRY_BACKOFF_SECONDS_RANGE = (60, 21600)
DAY_OFFSET_RANGE = (-7, 0)


class SchedulePolicyValidationError(ValueError):
    """字段取值域校验失败（API 层转 422）。"""


def default_schedule_policy() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_SCHEDULE_POLICY)


def parse_time_of_day(raw_value: str | None) -> datetime_time | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    for format_string in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, format_string).time()
        except ValueError:
            continue
    return None


def normalize_schedule_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """全量规范化 schedule_policy 文档；非法取值抛 SchedulePolicyValidationError。"""
    if not isinstance(payload, dict):
        raise SchedulePolicyValidationError("schedule_policy must be an object")
    policy = default_schedule_policy()

    enabled = payload.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise SchedulePolicyValidationError("enabled must be null or boolean")
    policy["enabled"] = enabled

    daily_time = payload.get("daily_time")
    if daily_time is not None:
        if not isinstance(daily_time, str) or parse_time_of_day(daily_time) is None:
            raise SchedulePolicyValidationError("daily_time must be null or HH:MM")
        policy["daily_time"] = daily_time.strip()

    day_offset = payload.get("day_offset")
    if day_offset is not None:
        if isinstance(day_offset, bool) or not isinstance(day_offset, int):
            raise SchedulePolicyValidationError("day_offset must be null or integer")
        if not DAY_OFFSET_RANGE[0] <= day_offset <= DAY_OFFSET_RANGE[1]:
            raise SchedulePolicyValidationError("day_offset must be in -7..0")
        policy["day_offset"] = day_offset

    source_types = payload.get("source_types")
    if source_types is not None:
        if not isinstance(source_types, list):
            raise SchedulePolicyValidationError("source_types must be null or a list")
        normalized: list[str] = []
        for item in source_types:
            value = str(item or "").strip()
            if not value:
                continue
            if value not in KNOWN_INGESTION_SOURCE_TYPES:
                raise SchedulePolicyValidationError(f"unknown source_type: {value}")
            if value not in normalized:
                normalized.append(value)
        policy["source_types"] = normalized

    retry_payload = payload.get("retry")
    if retry_payload is not None:
        if not isinstance(retry_payload, dict):
            raise SchedulePolicyValidationError("retry must be an object")
        policy["retry"] = _normalize_retry(retry_payload)

    weekly_payload = payload.get("weekly")
    if weekly_payload is not None:
        if not isinstance(weekly_payload, dict):
            raise SchedulePolicyValidationError("weekly must be an object")
        policy["weekly"] = _normalize_weekly(weekly_payload)

    return policy


def _normalize_retry(payload: dict[str, Any]) -> dict[str, Any]:
    retry = dict(DEFAULT_SCHEDULE_POLICY["retry"])
    if "max_attempts" in payload and payload["max_attempts"] is not None:
        max_attempts = payload["max_attempts"]
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise SchedulePolicyValidationError("retry.max_attempts must be an integer")
        if not RETRY_MAX_ATTEMPTS_RANGE[0] <= max_attempts <= RETRY_MAX_ATTEMPTS_RANGE[1]:
            raise SchedulePolicyValidationError("retry.max_attempts must be in 0..5")
        retry["max_attempts"] = max_attempts
    if "backoff_seconds" in payload and payload["backoff_seconds"] is not None:
        backoff_seconds = payload["backoff_seconds"]
        if isinstance(backoff_seconds, bool) or not isinstance(backoff_seconds, int):
            raise SchedulePolicyValidationError("retry.backoff_seconds must be an integer")
        if not RETRY_BACKOFF_SECONDS_RANGE[0] <= backoff_seconds <= RETRY_BACKOFF_SECONDS_RANGE[1]:
            raise SchedulePolicyValidationError("retry.backoff_seconds must be in 60..21600")
        retry["backoff_seconds"] = backoff_seconds
    return retry


def _normalize_weekly(payload: dict[str, Any]) -> dict[str, Any]:
    weekly = dict(DEFAULT_SCHEDULE_POLICY["weekly"])
    if "enabled" in payload and payload["enabled"] is not None:
        if not isinstance(payload["enabled"], bool):
            raise SchedulePolicyValidationError("weekly.enabled must be boolean")
        weekly["enabled"] = payload["enabled"]
    if "weekly_day" in payload and payload["weekly_day"] is not None:
        weekly_day = payload["weekly_day"]
        if isinstance(weekly_day, bool) or not isinstance(weekly_day, int):
            raise SchedulePolicyValidationError("weekly.weekly_day must be an integer")
        if not 1 <= weekly_day <= 7:
            raise SchedulePolicyValidationError("weekly.weekly_day must be ISO weekday 1..7")
        weekly["weekly_day"] = weekly_day
    if "weekly_time" in payload and payload["weekly_time"] is not None:
        weekly_time = payload["weekly_time"]
        if not isinstance(weekly_time, str) or parse_time_of_day(weekly_time) is None:
            raise SchedulePolicyValidationError("weekly.weekly_time must be HH:MM")
        weekly["weekly_time"] = weekly_time.strip()
    return weekly


def stored_schedule_policy(workspace: Workspace) -> dict[str, Any] | None:
    """读取工作台已存策略；未配置返回 None（= 完全跟随实例基线）。"""
    config = workspace.config_json or {}
    policy = config.get("schedule_policy")
    if not isinstance(policy, dict) or not policy:
        return None
    return policy


def workspace_schedule_policy(workspace: Workspace) -> dict[str, Any]:
    """读取并规范化工作台策略（缺失字段回填契约默认）。"""
    stored = stored_schedule_policy(workspace)
    if stored is None:
        return default_schedule_policy()
    try:
        return normalize_schedule_policy(stored)
    except SchedulePolicyValidationError:
        # 存量脏数据不阻塞读路径：按契约默认兜底。
        return default_schedule_policy()


def has_workspace_schedule_policy(workspace: Workspace) -> bool:
    """工作台是否配置了会改变调度行为的策略（policy_source 判据）。

    存了策略但全部字段等于契约默认时视为跟随实例（policy_source=instance），
    也不触发 scheduler 的 per-workspace 遍历模式切换。
    """
    stored = stored_schedule_policy(workspace)
    if stored is None:
        return False
    try:
        normalized = normalize_schedule_policy(stored)
    except SchedulePolicyValidationError:
        return False
    return normalized != DEFAULT_SCHEDULE_POLICY


def scheduler_timezone(settings: Settings) -> ZoneInfo:
    timezone_name = getattr(settings, "ingestion_scheduler_timezone", "Asia/Shanghai")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown INGESTION_SCHEDULER_TIMEZONE: {timezone_name}") from exc


@dataclass(frozen=True)
class ResolvedWorkspaceSchedule:
    """第 3 层 resolved schedule（§8.1）：策略非 null 字段覆盖实例基线。"""

    workspace_code: str
    policy: dict[str, Any]
    policy_source: str  # workspace | instance
    effective_enabled: bool
    effective_daily_time: str | None
    effective_day_offset: int
    effective_source_types: list[str]
    retry_max_attempts: int
    retry_backoff_seconds: int
    weekly_enabled: bool
    weekly_day: int
    weekly_time: str
    next_run_at: datetime | None


def resolve_workspace_schedule(
    settings: Settings,
    workspace: Workspace,
    *,
    now: datetime | None = None,
) -> ResolvedWorkspaceSchedule:
    policy = workspace_schedule_policy(workspace)
    timezone = scheduler_timezone(settings)
    current = (now or datetime.now(timezone)).astimezone(timezone)

    instance_enabled = bool(settings.ingestion_scheduler_enabled)
    capability_ingestion = bool(settings.capability_ingestion)
    if policy["enabled"] is False:
        effective_enabled = False
    else:
        # null 跟随实例总闸；true 仅在总闸开时有效（不能越过总闸/部署能力）。
        effective_enabled = instance_enabled and capability_ingestion

    daily_time = policy["daily_time"] or (settings.ingestion_scheduler_daily_time or "").strip() or None
    day_offset = (
        policy["day_offset"]
        if policy["day_offset"] is not None
        else int(getattr(settings, "daily_pipeline_day_offset_days", 0) or 0)
    )
    source_types = (
        list(policy["source_types"])
        if policy["source_types"] is not None
        else list(settings.ingestion_source_type_list)
    )
    allowlist = settings.ingestion_source_type_allowlist
    if allowlist:
        source_types = [item for item in source_types if item in allowlist]

    next_run_at: datetime | None = None
    parsed_daily_time = parse_time_of_day(daily_time)
    if effective_enabled and parsed_daily_time is not None:
        candidate = datetime.combine(current.date(), parsed_daily_time, tzinfo=timezone)
        if candidate <= current:
            candidate += timedelta(days=1)
        next_run_at = candidate

    return ResolvedWorkspaceSchedule(
        workspace_code=workspace.code,
        policy=policy,
        policy_source="workspace" if has_workspace_schedule_policy(workspace) else "instance",
        effective_enabled=effective_enabled,
        effective_daily_time=daily_time,
        effective_day_offset=day_offset,
        effective_source_types=source_types,
        retry_max_attempts=int(policy["retry"]["max_attempts"]),
        retry_backoff_seconds=int(policy["retry"]["backoff_seconds"]),
        weekly_enabled=bool(policy["weekly"]["enabled"]),
        weekly_day=int(policy["weekly"]["weekly_day"]),
        weekly_time=str(policy["weekly"]["weekly_time"]),
        next_run_at=next_run_at,
    )


def resolve_retry_policy(
    workspace: Workspace | None,
    *,
    retry_max_attempts_override: int | None = None,
) -> dict[str, int]:
    """解析 run 级重试策略（§6.2）：请求级覆盖 > 工作台策略 > 契约默认。"""
    policy = workspace_schedule_policy(workspace) if workspace is not None else default_schedule_policy()
    retry = dict(policy["retry"])
    if retry_max_attempts_override is not None:
        low, high = RETRY_MAX_ATTEMPTS_RANGE
        retry["max_attempts"] = min(high, max(low, int(retry_max_attempts_override)))
    return {
        "max_attempts": int(retry["max_attempts"]),
        "backoff_seconds": int(retry["backoff_seconds"]),
    }
