from __future__ import annotations

import logging
import time

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

    interval = max(60, settings.ingestion_scheduler_interval_seconds)
    while True:
        job = _enqueue_scheduled_job(queue, settings)
        logger.info(
            "Queued %s job %s for workspace %s",
            settings.scheduler_job_mode,
            job.id,
            settings.ingestion_scheduler_workspace_code,
        )
        time.sleep(interval)


def _enqueue_scheduled_job(queue: Queue, settings):
    if settings.scheduler_job_mode == "ingestion_only":
        return queue.enqueue(
            run_workspace_ingestion_job,
            settings.ingestion_scheduler_workspace_code,
            settings.ingestion_source_type_list,
            settings.ingestion_scheduler_limit,
            job_timeout=60 * 60 * 2,
            result_ttl=60 * 60 * 24,
            failure_ttl=60 * 60 * 24 * 7,
        )

    return queue.enqueue(
        run_daily_pipeline_job,
        settings.ingestion_scheduler_workspace_code,
        settings.ingestion_source_type_list,
        settings.ingestion_scheduler_limit,
        settings.daily_pipeline_recommendation_limit,
        settings.daily_pipeline_source_daily_limit,
        settings.daily_pipeline_create_daily_draft,
        settings.daily_pipeline_run_ingestion,
        job_timeout=60 * 60 * 3,
        result_ttl=60 * 60 * 24,
        failure_ttl=60 * 60 * 24 * 7,
    )


if __name__ == "__main__":
    main()
