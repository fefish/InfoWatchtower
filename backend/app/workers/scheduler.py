from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from datetime import time as datetime_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.core.deploy_checks import validate_deploy_settings
from app.ingestion.jobs import INGESTION_QUEUE_NAME, run_workspace_ingestion_job
from app.ingestion.retry import run_failed_source_auto_retry_job
from app.pipeline.daily import run_daily_pipeline_job
from app.sync.pull import run_sync_pull_job
from app.sync.retry import run_failed_sync_inbox_auto_retry_job

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    validate_deploy_settings(settings)
    redis_connection = Redis.from_url(settings.redis_url)
    queue = Queue(INGESTION_QUEUE_NAME, connection=redis_connection)

    ingestion_enabled = settings.capability_ingestion and settings.ingestion_scheduler_enabled
    ingestion_auto_retry_enabled = settings.capability_ingestion and settings.ingestion_failed_source_auto_retry_effective
    sync_pull_enabled = settings.capability_sync_consumer and settings.sync_pull_effective
    sync_auto_retry_enabled = settings.sync_failed_inbox_auto_retry_effective

    if not ingestion_enabled and not ingestion_auto_retry_enabled and not sync_pull_enabled and not sync_auto_retry_enabled:
        logger.info("No scheduled jobs enabled for DEPLOY_MODE=%s.", settings.deploy_mode)
        while True:
            time.sleep(3600)

    daily_time = _parse_daily_time(settings.ingestion_scheduler_daily_time)
    scheduler_timezone = _scheduler_timezone(settings)
    if ingestion_enabled and daily_time is not None and not ingestion_auto_retry_enabled and not sync_pull_enabled and not sync_auto_retry_enabled:
        while True:
            now = datetime.now(scheduler_timezone)
            sleep_seconds = _seconds_until_next_daily_run(now, daily_time)
            logger.info(
                "Next %s job for workspace %s at %s %s in %.0f seconds",
                settings.scheduler_job_mode,
                settings.ingestion_scheduler_workspace_code,
                daily_time.isoformat(timespec="minutes"),
                scheduler_timezone.key,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)
            _enqueue_and_log(queue, settings, now=datetime.now(scheduler_timezone))

    interval_candidates: list[int] = []
    if ingestion_enabled and daily_time is None:
        interval_candidates.append(max(60, settings.ingestion_scheduler_interval_seconds))
    if sync_pull_enabled:
        interval_candidates.append(max(60, settings.sync_pull_interval_seconds))
    if sync_auto_retry_enabled:
        interval_candidates.append(max(60, settings.sync_failed_inbox_retry_base_seconds))
    if ingestion_auto_retry_enabled:
        interval_candidates.append(max(60, settings.ingestion_failed_source_retry_base_seconds))
    interval = min(interval_candidates or [3600])
    last_ingestion_at = 0.0
    last_ingestion_auto_retry_at = 0.0
    last_sync_pull_at = 0.0
    last_sync_auto_retry_at = 0.0
    next_daily_run_at: datetime | None = None
    if ingestion_enabled and daily_time is not None:
        now = datetime.now(scheduler_timezone)
        next_daily_run_at = datetime.combine(now.date(), daily_time, tzinfo=now.tzinfo)
        if next_daily_run_at <= now:
            next_daily_run_at += timedelta(days=1)

    while True:
        monotonic_now = time.monotonic()
        wall_now = datetime.now(scheduler_timezone)
        if ingestion_enabled:
            if next_daily_run_at is not None:
                if wall_now >= next_daily_run_at:
                    _enqueue_and_log(queue, settings, now=wall_now)
                    next_daily_run_at += timedelta(days=1)
            elif monotonic_now - last_ingestion_at >= max(60, settings.ingestion_scheduler_interval_seconds):
                _enqueue_and_log(queue, settings)
                last_ingestion_at = monotonic_now
        if ingestion_auto_retry_enabled and monotonic_now - last_ingestion_auto_retry_at >= max(
            60,
            settings.ingestion_failed_source_retry_base_seconds,
        ):
            job = queue.enqueue(
                run_failed_source_auto_retry_job,
                job_timeout=60 * 60 * 2,
                result_ttl=60 * 60 * 24,
                failure_ttl=60 * 60 * 24 * 7,
            )
            logger.info("Queued ingestion_failed_source_auto_retry job %s", job.id)
            last_ingestion_auto_retry_at = monotonic_now
        if sync_pull_enabled and monotonic_now - last_sync_pull_at >= max(60, settings.sync_pull_interval_seconds):
            job = queue.enqueue(
                run_sync_pull_job,
                job_timeout=60 * 60 * 2,
                result_ttl=60 * 60 * 24,
                failure_ttl=60 * 60 * 24 * 7,
            )
            logger.info("Queued sync_pull job %s for remote %s", job.id, settings.sync_remote_base_url)
            last_sync_pull_at = monotonic_now
        if sync_auto_retry_enabled and monotonic_now - last_sync_auto_retry_at >= max(
            60,
            settings.sync_failed_inbox_retry_base_seconds,
        ):
            job = queue.enqueue(
                run_failed_sync_inbox_auto_retry_job,
                job_timeout=60 * 30,
                result_ttl=60 * 60 * 24,
                failure_ttl=60 * 60 * 24 * 7,
            )
            logger.info("Queued sync_failed_inbox_auto_retry job %s", job.id)
            last_sync_auto_retry_at = monotonic_now
        time.sleep(interval)


def _enqueue_and_log(queue: Queue, settings, now: datetime | None = None) -> None:
    job = _enqueue_scheduled_job(queue, settings, now=now)
    logger.info(
        "Queued %s job %s for workspace %s",
        settings.scheduler_job_mode,
        job.id,
        settings.ingestion_scheduler_workspace_code,
    )


def _enqueue_scheduled_job(queue: Queue, settings, now: datetime | None = None):
    if settings.scheduler_job_mode == "ingestion_only":
        return queue.enqueue(
            run_workspace_ingestion_job,
            settings.ingestion_scheduler_workspace_code,
            settings.ingestion_source_type_list,
            settings.ingestion_scheduler_limit,
            settings.ingestion_concurrency,
            settings.ingestion_source_timeout_seconds,
            getattr(settings, "ingestion_max_items_per_source", None),
            job_timeout=60 * 60 * 2,
            result_ttl=60 * 60 * 24,
            failure_ttl=60 * 60 * 24 * 7,
        )

    daily_pipeline_args = [
        settings.ingestion_scheduler_workspace_code,
        settings.ingestion_source_type_list,
        settings.ingestion_scheduler_limit,
        settings.ingestion_concurrency,
        settings.ingestion_source_timeout_seconds,
        getattr(settings, "ingestion_max_items_per_source", None),
        settings.daily_pipeline_recommendation_limit,
        settings.daily_pipeline_source_daily_limit,
        45.0,
        settings.daily_pipeline_create_daily_draft,
        settings.daily_pipeline_run_ingestion,
    ]
    day_key = _scheduled_day_key(settings, now=now)
    if day_key:
        daily_pipeline_args.append(day_key)

    return queue.enqueue(
        run_daily_pipeline_job,
        *daily_pipeline_args,
        job_timeout=60 * 60 * 3,
        result_ttl=60 * 60 * 24,
        failure_ttl=60 * 60 * 24 * 7,
    )


def _parse_daily_time(raw_value: str | None) -> datetime_time | None:
    value = (raw_value or "").strip()
    if not value:
        return None

    formats = ("%H:%M", "%H:%M:%S")
    for format_string in formats:
        try:
            return datetime.strptime(value, format_string).time()
        except ValueError:
            continue
    raise ValueError(
        "INGESTION_SCHEDULER_DAILY_TIME must use HH:MM or HH:MM:SS, "
        f"got {raw_value!r}",
    )


def _scheduler_timezone(settings) -> ZoneInfo:
    timezone_name = getattr(settings, "ingestion_scheduler_timezone", "Asia/Shanghai")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown INGESTION_SCHEDULER_TIMEZONE: {timezone_name}") from exc


def _seconds_until_next_daily_run(now: datetime, daily_time: datetime_time) -> float:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    next_run = datetime.combine(now.date(), daily_time, tzinfo=now.tzinfo)
    if next_run <= now:
        next_run += timedelta(days=1)
    return max(0.0, (next_run - now).total_seconds())


def _scheduled_day_key(settings, now: datetime | None = None) -> str | None:
    offset_days = getattr(settings, "daily_pipeline_day_offset_days", 0)
    if offset_days == 0:
        return None

    scheduler_timezone = _scheduler_timezone(settings)
    current = now.astimezone(scheduler_timezone) if now else datetime.now(scheduler_timezone)
    return (current.date() + timedelta(days=offset_days)).isoformat()


if __name__ == "__main__":
    main()
