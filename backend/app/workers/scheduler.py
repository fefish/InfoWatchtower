from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from datetime import time as datetime_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis import Redis
from rq import Queue

from app.core.config import get_settings
from app.ingestion.jobs import INGESTION_QUEUE_NAME, run_workspace_ingestion_job
from app.pipeline.daily import run_daily_pipeline_job

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    redis_connection = Redis.from_url(settings.redis_url)
    queue = Queue(INGESTION_QUEUE_NAME, connection=redis_connection)

    if not settings.ingestion_scheduler_enabled:
        logger.info(
            "Daily pipeline scheduler disabled. Set INGESTION_SCHEDULER_ENABLED=true to enable.",
        )
        while True:
            time.sleep(3600)

    daily_time = _parse_daily_time(settings.ingestion_scheduler_daily_time)
    scheduler_timezone = _scheduler_timezone(settings)
    if daily_time is not None:
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

    interval = max(60, settings.ingestion_scheduler_interval_seconds)
    while True:
        _enqueue_and_log(queue, settings)
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
        settings.daily_pipeline_recommendation_limit,
        settings.daily_pipeline_source_daily_limit,
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
