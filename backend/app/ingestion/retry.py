"""Automatic retry support for failed ingestion sources."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.collaboration.notifications import record_ingestion_failed_source_retry_alert_activity
from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.ingestion.runs import (
    HistoricalBackfillRequest,
    WorkspaceIngestionRequest,
    run_historical_backfill,
    run_workspace_ingestion,
)
from app.models.common import utc_now
from app.models.content import DataSource, IngestionRun
from app.models.workspace import Workspace, WorkspaceSourceLink


@dataclass(frozen=True)
class FailedSourceRetryPolicy:
    enabled: bool
    base_delay_seconds: int
    max_delay_seconds: int
    max_attempts: int
    limit: int


@dataclass(frozen=True)
class FailedSourceRetryCandidate:
    run: IngestionRun
    failed_source_ids: list[str]
    attempt_count: int
    last_attempt_at: datetime
    next_retry_at: datetime
    latest_retry_run: IngestionRun | None
    blocked: bool
    due: bool


def failed_source_retry_policy(settings: Settings) -> FailedSourceRetryPolicy:
    base_delay_seconds = max(1, int(settings.ingestion_failed_source_retry_base_seconds or 900))
    max_delay_seconds = max(base_delay_seconds, int(settings.ingestion_failed_source_retry_max_seconds or 3600))
    return FailedSourceRetryPolicy(
        enabled=bool(settings.ingestion_failed_source_auto_retry_effective and settings.capability_ingestion),
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        max_attempts=max(1, int(settings.ingestion_failed_source_retry_max_attempts or 3)),
        limit=min(100, max(1, int(settings.ingestion_failed_source_retry_limit or 10))),
    )


def failed_source_retry_summary(
    session: Session,
    settings: Settings,
    *,
    workspace_code: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    policy = failed_source_retry_policy(settings)
    candidates = failed_source_retry_candidates(
        session,
        settings,
        workspace_code=workspace_code,
        now=now,
    )
    due_candidates = [candidate for candidate in candidates if candidate.due]
    blocked_candidates = [candidate for candidate in candidates if candidate.blocked]
    future_retry_times = [candidate.next_retry_at for candidate in candidates if not candidate.due and not candidate.blocked]
    next_retry_at = min(future_retry_times) if future_retry_times else None
    return {
        "policy": asdict(policy),
        "due_count": len(due_candidates),
        "blocked_count": len(blocked_candidates),
        "next_retry_at": next_retry_at,
        "runs": [_candidate_to_summary(candidate) for candidate in candidates[:50]],
    }


def failed_source_retry_candidates(
    session: Session,
    settings: Settings,
    *,
    workspace_code: str | None = None,
    now: datetime | None = None,
) -> list[FailedSourceRetryCandidate]:
    policy = failed_source_retry_policy(settings)
    current_time = _ensure_aware(now or utc_now())
    runs = list(
        session.scalars(
            select(IngestionRun)
            .order_by(desc(IngestionRun.created_at), desc(IngestionRun.id))
            .limit(500),
        ).all(),
    )
    if workspace_code:
        runs = [run for run in runs if run.workspace_code == workspace_code]

    retry_runs_by_original: dict[str, list[IngestionRun]] = {}
    base_runs: list[IngestionRun] = []
    for run in runs:
        retry_of = str((run.params_json or {}).get("retry_of_run_id") or "").strip()
        if retry_of:
            retry_runs_by_original.setdefault(retry_of, []).append(run)
            continue
        if int(run.source_failed or 0) <= 0:
            continue
        base_runs.append(run)

    candidates: list[FailedSourceRetryCandidate] = []
    for run in base_runs:
        if _is_manual_import_run(run):
            continue
        failed_source_ids = _failed_run_source_ids(run)
        if not failed_source_ids:
            continue
        attempts = sorted(
            retry_runs_by_original.get(run.id, []),
            key=_run_occurred_at,
        )
        latest_retry = attempts[-1] if attempts else None
        if latest_retry is not None and int(latest_retry.source_failed or 0) <= 0:
            continue
        attempt_count = len(attempts)
        last_attempt_at = _run_occurred_at(latest_retry or run)
        blocked = attempt_count >= policy.max_attempts
        retry_delay = _retry_delay_seconds(attempt_count, policy)
        next_retry_at = last_attempt_at + timedelta(seconds=retry_delay)
        candidates.append(
            FailedSourceRetryCandidate(
                run=run,
                failed_source_ids=failed_source_ids,
                attempt_count=attempt_count,
                last_attempt_at=last_attempt_at,
                next_retry_at=next_retry_at,
                latest_retry_run=latest_retry,
                blocked=blocked,
                due=(not blocked and next_retry_at <= current_time),
            ),
        )

    candidates.sort(key=lambda candidate: (candidate.blocked, not candidate.due, candidate.next_retry_at, candidate.run.run_key))
    return candidates


async def retry_due_failed_sources(
    session: Session,
    settings: Settings,
    *,
    workspace_code: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    policy = failed_source_retry_policy(settings)
    if not policy.enabled:
        return {"status": "skipped", "reason": "auto retry disabled", "summary": failed_source_retry_summary(session, settings, workspace_code=workspace_code, now=now)}

    candidates = failed_source_retry_candidates(session, settings, workspace_code=workspace_code, now=now)
    alert_counts = _record_retry_alerts(session, candidates)
    due_candidates = [candidate for candidate in candidates if candidate.due][: policy.limit]
    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    for candidate in due_candidates:
        try:
            retry_run = await retry_failed_ingestion_run_from_original(session, candidate.run, settings)
            runs.append(
                {
                    "id": retry_run.id,
                    "run_key": retry_run.run_key,
                    "workspace_code": retry_run.workspace_code,
                    "status": retry_run.status,
                    "retry_of_run_id": candidate.run.id,
                    "source_total": retry_run.source_total,
                    "source_failed": retry_run.source_failed,
                    "raw_created": retry_run.raw_created,
                },
            )
        except Exception as exc:  # pragma: no cover - surfaced in job payload and tests can monkeypatch happy path
            errors.append(f"{candidate.run.run_key}: {exc}")

    return {
        "status": "completed_with_errors" if errors else "completed",
        "selected_failed_runs": len(due_candidates),
        "alerted_due_runs": alert_counts["due"],
        "alerted_blocked_runs": alert_counts["blocked"],
        "runs": runs,
        "errors": errors,
    }


async def retry_failed_ingestion_run_from_original(
    session: Session,
    original: IngestionRun,
    settings: Settings,
) -> IngestionRun:
    failed_source_ids = _failed_run_source_ids(original)
    retryable_sources = _retryable_failed_sources(
        session,
        workspace_code=original.workspace_code,
        failed_source_ids=failed_source_ids,
    )
    if not retryable_sources:
        raise ValueError("failed sources are disabled or no longer linked to the workspace")

    retry_source_ids = [source.id for source in retryable_sources]
    retry_source_types = _unique(source.source_type for source in retryable_sources)
    original_params = original.params_json or {}
    original_summary = original.summary_json or {}

    if original.run_type == "historical_backfill":
        backfill_mode = str(original_params.get("backfill_mode") or original_summary.get("backfill_mode") or "rss_window")
        if backfill_mode == "manual_import":
            raise ValueError("manual_import runs must be retried by re-uploading manual import data")
        target_day_start = str(original_params.get("target_day_start") or original_summary.get("target_day_start") or "")
        target_day_end = str(original_params.get("target_day_end") or original_summary.get("target_day_end") or "")
        if not target_day_start or not target_day_end:
            raise ValueError("historical backfill run is missing target_day_start/target_day_end")
        return await run_historical_backfill(
            session,
            HistoricalBackfillRequest(
                workspace_code=original.workspace_code,
                target_day_start=target_day_start,
                target_day_end=target_day_end,
                source_types=retry_source_types,
                source_ids=retry_source_ids,
                limit=None,
                concurrency=2,
                source_timeout_seconds=max(60.0, float(settings.ingestion_source_timeout_seconds or 25.0)),
                backfill_mode=backfill_mode,
                source_scope="failed_sources",
                retry_policy="auto_retry_failed_sources",
                include_undated=_bool_value(original_params.get("include_undated")),
                manual_items=[],
                retry_of_run_id=original.id,
            ),
        )

    if original.run_type != "workspace_fetch":
        raise ValueError(f"unsupported ingestion run_type for retry: {original.run_type}")

    max_items_per_source = _optional_int(original_params.get("max_items_per_source"))
    return await run_workspace_ingestion(
        session,
        WorkspaceIngestionRequest(
            workspace_code=original.workspace_code,
            source_types=retry_source_types,
            source_ids=retry_source_ids,
            limit=None,
            concurrency=2,
            source_timeout_seconds=max(60.0, float(settings.ingestion_source_timeout_seconds or 25.0)),
            max_items_per_source=max_items_per_source,
            retry_of_run_id=original.id,
        ),
    )


def run_failed_source_auto_retry_job() -> dict[str, Any]:
    return asyncio.run(_run_failed_source_auto_retry_job())


async def _run_failed_source_auto_retry_job() -> dict[str, Any]:
    settings = get_settings()
    if not failed_source_retry_policy(settings).enabled:
        return {"status": "skipped", "reason": "auto retry disabled"}
    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for ingestion failed-source auto retry jobs.")

    with session_factory() as session:
        payload = await retry_due_failed_sources(
            session,
            settings,
            workspace_code=settings.ingestion_scheduler_workspace_code,
        )
        session.commit()
        return payload


def _candidate_to_summary(candidate: FailedSourceRetryCandidate) -> dict[str, Any]:
    return {
        "run_id": candidate.run.id,
        "run_key": candidate.run.run_key,
        "run_type": candidate.run.run_type,
        "status": candidate.run.status,
        "failed_source_count": len(candidate.failed_source_ids),
        "attempt_count": candidate.attempt_count,
        "last_attempt_at": candidate.last_attempt_at,
        "next_retry_at": candidate.next_retry_at,
        "blocked": candidate.blocked,
        "due": candidate.due,
        "latest_retry_run_id": candidate.latest_retry_run.id if candidate.latest_retry_run else None,
        "latest_retry_run_key": candidate.latest_retry_run.run_key if candidate.latest_retry_run else None,
        "latest_retry_status": candidate.latest_retry_run.status if candidate.latest_retry_run else None,
    }


def _record_retry_alerts(session: Session, candidates: list[FailedSourceRetryCandidate]) -> dict[str, int]:
    counts = {"due": 0, "blocked": 0}
    for candidate in candidates:
        event_type = ""
        alert_key = ""
        if candidate.blocked:
            event_type = "ingestion.failed_source_retry_blocked"
            alert_key = "blocked"
        elif candidate.due:
            event_type = "ingestion.failed_source_retry_due"
            alert_key = "due"
        if not event_type:
            continue
        event = record_ingestion_failed_source_retry_alert_activity(
            session,
            run=candidate.run,
            event_type=event_type,
            failed_source_count=len(candidate.failed_source_ids),
            attempt_count=candidate.attempt_count,
            next_retry_at=candidate.next_retry_at,
            latest_retry_run=candidate.latest_retry_run,
        )
        if event is not None:
            counts[alert_key] += 1
    return counts


def _failed_run_source_ids(run: IngestionRun) -> list[str]:
    source_ids: list[str] = []
    sources = (run.summary_json or {}).get("sources")
    if not isinstance(sources, list):
        return source_ids
    for source in sources:
        if not isinstance(source, dict) or source.get("status") != "failed":
            continue
        source_id = str(source.get("data_source_id") or "").strip()
        if source_id and source_id not in source_ids:
            source_ids.append(source_id)
    return source_ids


def _retryable_failed_sources(
    session: Session,
    *,
    workspace_code: str,
    failed_source_ids: list[str],
) -> list[DataSource]:
    sources = session.scalars(
        select(DataSource)
        .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
        .join(Workspace, Workspace.id == WorkspaceSourceLink.workspace_id)
        .where(
            Workspace.code == workspace_code,
            Workspace.enabled.is_(True),
            WorkspaceSourceLink.enabled.is_(True),
            DataSource.enabled.is_(True),
            DataSource.id.in_(failed_source_ids),
        ),
    ).all()
    sources_by_id = {source.id: source for source in sources}
    return [sources_by_id[source_id] for source_id in failed_source_ids if source_id in sources_by_id]


def _retry_delay_seconds(attempt_count: int, policy: FailedSourceRetryPolicy) -> int:
    retry_attempt = max(1, attempt_count + 1)
    delay = policy.base_delay_seconds * (2 ** max(0, retry_attempt - 1))
    return min(policy.max_delay_seconds, delay)


def _is_manual_import_run(run: IngestionRun) -> bool:
    return str((run.params_json or {}).get("backfill_mode") or (run.summary_json or {}).get("backfill_mode") or "") == "manual_import"


def _run_occurred_at(run: IngestionRun) -> datetime:
    return _ensure_aware(run.completed_at or run.started_at or run.created_at)


def _ensure_aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
