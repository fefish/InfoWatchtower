"""Local retry for failed sync inbox records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.models.common import utc_now
from app.models.sync import SyncInbox, SyncRun
from app.sync.apply import apply_sync_records
from app.sync.records import sort_records_by_dependency


@dataclass(frozen=True)
class FailedInboxRetryPolicy:
    enabled: bool
    base_delay_seconds: int
    max_delay_seconds: int
    max_attempts: int
    limit: int


def failed_inbox_retry_policy(settings: Settings) -> FailedInboxRetryPolicy:
    base_delay_seconds = max(1, int(settings.sync_failed_inbox_retry_base_seconds or 300))
    max_delay_seconds = max(base_delay_seconds, int(settings.sync_failed_inbox_retry_max_seconds or 3600))
    return FailedInboxRetryPolicy(
        enabled=bool(settings.sync_failed_inbox_auto_retry_effective),
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        max_attempts=max(1, int(settings.sync_failed_inbox_retry_max_attempts or 5)),
        limit=min(500, max(1, int(settings.sync_failed_inbox_retry_limit or 50))),
    )


def failed_inbox_retry_summary(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    policy = failed_inbox_retry_policy(settings)
    current_time = _ensure_aware(now or utc_now())
    rows = session.scalars(select(SyncInbox).where(SyncInbox.status == "failed")).all()
    due_count = 0
    blocked_count = 0
    next_retry_at: datetime | None = None
    for row in rows:
        if _retry_attempts_exhausted(row, policy):
            blocked_count += 1
            continue
        retry_at = failed_inbox_next_retry_at(row, policy)
        if retry_at is None or retry_at <= current_time:
            due_count += 1
        elif next_retry_at is None or retry_at < next_retry_at:
            next_retry_at = retry_at

    return {
        "policy": asdict(policy),
        "due_count": due_count,
        "blocked_count": blocked_count,
        "next_retry_at": next_retry_at,
    }


def failed_inbox_next_retry_at(row: SyncInbox, policy: FailedInboxRetryPolicy) -> datetime | None:
    if row.last_attempt_at is None:
        return None
    return _ensure_aware(row.last_attempt_at) + timedelta(seconds=_retry_delay_seconds(row, policy))


def failed_inbox_retry_is_due(
    row: SyncInbox,
    policy: FailedInboxRetryPolicy,
    *,
    now: datetime | None = None,
) -> bool:
    if row.status != "failed" or _retry_attempts_exhausted(row, policy):
        return False
    retry_at = failed_inbox_next_retry_at(row, policy)
    return retry_at is None or retry_at <= _ensure_aware(now or utc_now())


def retry_failed_sync_inbox(
    session: Session,
    settings: Settings,
    *,
    object_type: str | None = None,
    limit: int = 100,
    due_only: bool = False,
    direction: str = "inbox_retry",
    package_prefix: str = "inbox_retry",
) -> SyncRun:
    """Replay locally stored failed sync envelopes and summarize the retry run."""
    now = utc_now()
    inbox_rows = _select_failed_inbox_rows(
        session,
        settings,
        object_type=object_type,
        limit=limit,
        due_only=due_only,
        now=now,
    )
    run = SyncRun(
        package_id=f"{package_prefix}_{now.strftime('%Y%m%d%H%M%S%f')}",
        source_instance_id="failed_inbox",
        target_instance_id=settings.effective_instance_id,
        direction=direction,
        status="running",
        counts_json={},
        started_at=now,
    )
    session.add(run)
    session.flush()

    records_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_record_ids: list[str] = []
    retry_inbox_ids: list[str] = []
    retry_event_ids: list[str] = []
    for row in inbox_rows:
        retry_inbox_ids.append(row.id)
        retry_event_ids.append(row.event_id)
        if not isinstance(row.record_json, dict) or not row.record_json:
            missing_record_ids.append(row.id)
            row.error_message = "failed inbox cannot be retried because record_json is empty"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.last_attempt_at = now
            continue
        records_by_source[row.source_instance_id or "remote"].append(dict(row.record_json))

    totals = {"received": 0, "applied": 0, "skipped": 0, "failed": 0, "conflicts": 0}
    all_errors: list[str] = []
    per_source: dict[str, dict[str, Any]] = {}
    for source_instance_id, records in sorted(records_by_source.items()):
        # 按外键依赖序重放：failed 批里父子对象同时在场时一轮即净，
        # 而不是按 updated_at 顺序多轮 backoff 才收敛
        outcome = apply_sync_records(
            session,
            run,
            sort_records_by_dependency(records),
            source_instance_id=source_instance_id,
        )
        source_stats = {
            "received": outcome.received,
            "applied": outcome.applied,
            "skipped": outcome.skipped,
            "failed": outcome.failed,
            "conflicts": outcome.conflicts,
            "errors": outcome.errors,
        }
        per_source[source_instance_id] = source_stats
        for key in totals:
            totals[key] += int(source_stats[key] or 0)
        all_errors.extend(f"{source_instance_id}: {error}" for error in outcome.errors)

    if missing_record_ids:
        totals["failed"] += len(missing_record_ids)
        all_errors.append(f"{len(missing_record_ids)} failed inbox records have empty record_json")

    run.status = _retry_status(totals, selected_count=len(inbox_rows))
    run.completed_at = utc_now()
    run.counts_json = {
        **totals,
        "selected_failed_inbox": len(inbox_rows),
        "retry_inbox_ids": retry_inbox_ids,
        "retry_event_ids": retry_event_ids,
        "missing_record_ids": missing_record_ids,
        "object_type": object_type or "",
        "retry_mode": "auto_backoff" if due_only else "manual",
        "per_source": per_source,
        "errors": all_errors,
    }
    session.flush()
    return run


def run_failed_sync_inbox_auto_retry_job() -> dict[str, Any]:
    settings = get_settings()
    if not settings.sync_failed_inbox_auto_retry_effective:
        return {"status": "skipped", "reason": "auto retry disabled"}
    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for sync inbox auto retry jobs.")

    with session_factory() as session:
        summary = failed_inbox_retry_summary(session, settings)
        if int(summary["due_count"] or 0) <= 0:
            return {
                "status": "skipped",
                "reason": "no due failed inbox records",
                "summary": _jsonable_retry_summary(summary),
            }
        run = retry_failed_sync_inbox(
            session,
            settings,
            limit=failed_inbox_retry_policy(settings).limit,
            due_only=True,
            direction="inbox_auto_retry",
            package_prefix="inbox_auto_retry",
        )
        payload = {
            "id": run.id,
            "package_id": run.package_id,
            "direction": run.direction,
            "status": run.status,
            "counts_json": run.counts_json,
        }
        session.commit()
        return payload


def _retry_status(totals: dict[str, int], *, selected_count: int) -> str:
    if selected_count == 0:
        return "completed"
    if totals["failed"]:
        return "completed_with_errors"
    if totals["conflicts"]:
        return "completed_with_conflicts"
    return "completed"


def _select_failed_inbox_rows(
    session: Session,
    settings: Settings,
    *,
    object_type: str | None,
    limit: int,
    due_only: bool,
    now: datetime,
) -> list[SyncInbox]:
    statement = select(SyncInbox).where(SyncInbox.status == "failed")
    if object_type:
        statement = statement.where(SyncInbox.object_type == object_type)
    statement = statement.order_by(SyncInbox.updated_at.asc(), SyncInbox.id.asc())
    if not due_only:
        statement = statement.limit(limit)
        return list(session.scalars(statement).all())

    policy = failed_inbox_retry_policy(settings)
    selected: list[SyncInbox] = []
    for row in session.scalars(statement).all():
        if failed_inbox_retry_is_due(row, policy, now=now):
            selected.append(row)
            if len(selected) >= limit:
                break
    return selected


def _retry_delay_seconds(row: SyncInbox, policy: FailedInboxRetryPolicy) -> int:
    attempt_count = max(1, int(row.attempt_count or 0))
    delay = policy.base_delay_seconds * (2 ** max(0, attempt_count - 1))
    return min(policy.max_delay_seconds, delay)


def _retry_attempts_exhausted(row: SyncInbox, policy: FailedInboxRetryPolicy) -> bool:
    return int(row.attempt_count or 0) >= policy.max_attempts


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _jsonable_retry_summary(summary: dict[str, Any]) -> dict[str, Any]:
    retry_at = summary.get("next_retry_at")
    return {
        **summary,
        "next_retry_at": retry_at.isoformat() if isinstance(retry_at, datetime) else None,
    }
