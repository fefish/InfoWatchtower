"""Scheduler 进程（docs/backend/pipeline-jobs-design.md §8）。

只负责投递任务，不执行重业务。tick 周期固定 60s，每个 tick：
1. 读实例总闸与 DEPLOY_MODE 能力开关（intranet 跳过全部 pipeline 投递，只留 sync）。
2. 无任何工作台配 ``schedule_policy`` 时走兼容模式：投递行为与旧版逐字节一致
   （只按实例 env 调度 ``INGESTION_SCHEDULER_WORKSPACE_CODE``）。
3. 任一工作台配了策略则切换为遍历 enabled 工作台模式（策略缺失的工作台只有
   兼容工作台参与），解析 resolved schedule 并按 (workspace, day_key) 幂等投递。
4. 扫描 §6.2 到期失败 run 投递 run 级重试（superseded 让位落 skipped）。
5. 扫描 ``weekly.enabled`` 工作台的周报节拍。
6. tick 结束 upsert 心跳行（scheduler_heartbeats，供 §8.5 status API 直读 DB）。

重启不补跑错过超过 ``SCHEDULER_MISSED_WINDOW_SECONDS`` 的触发点。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as datetime_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis import Redis
from rq import Queue
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.deploy_checks import validate_deploy_settings
from app.ingestion.jobs import INGESTION_QUEUE_NAME, run_workspace_ingestion_job
from app.ingestion.retry import run_failed_source_auto_retry_job
from app.pipeline.daily import DailyPipelineRequest, run_daily_pipeline_job
from app.sync.pull import run_sync_pull_job
from app.sync.retry import run_failed_sync_inbox_auto_retry_job

logger = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 60
DAILY_JOB_TIMEOUT = 60 * 60 * 3
DEFAULT_JOB_TIMEOUT = 60 * 60 * 2
JOB_RESULT_TTL = 60 * 60 * 24
JOB_FAILURE_TTL = 60 * 60 * 24 * 7

_UNSET = object()


@dataclass
class SchedulerState:
    """兼容模式与 interval 任务的进程内节拍状态。"""

    next_daily_run_at: datetime | None = None
    last_ingestion_at: float = 0.0
    # None = 本进程从未投递过该 interval 任务 → 首个 tick 立即投递。
    # 不能用 0.0 哨兵：time.monotonic() 零点是开机时刻，刚启动的机器（CI 虚拟机、
    # 重启后的生产主机）monotonic 值小于间隔，0.0 哨兵会让任务空等一个完整间隔。
    last_ingestion_auto_retry_at: float | None = None
    last_sync_pull_at: float | None = None
    last_sync_auto_retry_at: float | None = None
    dispatched: list[str] = field(default_factory=list)


def scheduler_instance_id(settings) -> str:
    # §3.1：settings.effective_instance_id + 进程标识；重启换行后由
    # pipeline_runs 幂等键兜底防重投。
    return f"{settings.effective_instance_id}:scheduler:{os.getpid()}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    validate_deploy_settings(settings)
    # 启动即校验 env 基线格式（非法 HH:MM / 时区直接 fail-fast）。
    _parse_daily_time(settings.ingestion_scheduler_daily_time)
    _scheduler_timezone(settings)
    redis_connection = Redis.from_url(settings.redis_url)
    queue = Queue(INGESTION_QUEUE_NAME, connection=redis_connection)
    state = SchedulerState()
    logger.info(
        "Scheduler started (instance=%s, deploy_mode=%s, tick=%ss).",
        scheduler_instance_id(settings),
        settings.deploy_mode,
        TICK_INTERVAL_SECONDS,
    )
    while True:
        try:
            scheduler_tick(queue, settings, state)
        except Exception:  # noqa: BLE001 - 单 tick 失败不终止调度进程
            logger.exception("Scheduler tick failed")
        time.sleep(TICK_INTERVAL_SECONDS)


def scheduler_tick(
    queue: Queue,
    settings,
    state: SchedulerState,
    *,
    now: datetime | None = None,
    monotonic_now: float | None = None,
    session_factory=_UNSET,
) -> list[str]:
    """执行一个调度 tick；返回本 tick 投递的 job 描述（测试友好）。"""
    from app.core.database import get_session_factory

    timezone = _scheduler_timezone(settings)
    wall_now = (now or datetime.now(timezone)).astimezone(timezone)
    if monotonic_now is None:
        monotonic_now = time.monotonic()
    if session_factory is _UNSET:
        session_factory = get_session_factory()

    ingestion_enabled = settings.capability_ingestion and settings.ingestion_scheduler_enabled
    ingestion_auto_retry_enabled = (
        settings.capability_ingestion and settings.ingestion_failed_source_auto_retry_effective
    )
    sync_pull_enabled = settings.capability_sync_consumer and settings.sync_pull_effective
    sync_auto_retry_enabled = settings.sync_failed_inbox_auto_retry_effective

    dispatched: list[str] = []
    session = session_factory() if session_factory is not None else None
    try:
        policy_mode = False
        workspaces: list = []
        if session is not None and ingestion_enabled:
            workspaces = _enabled_workspaces(session)
            policy_mode = _any_workspace_has_policy(workspaces)

        if ingestion_enabled:
            if policy_mode:
                dispatched += _dispatch_policy_daily(session, queue, settings, workspaces, wall_now)
                dispatched += _dispatch_weekly(session, queue, settings, workspaces, wall_now)
            else:
                dispatched += _dispatch_compat_daily(
                    session,
                    queue,
                    settings,
                    state,
                    wall_now,
                    monotonic_now,
                )
            if session is not None:
                dispatched += _dispatch_due_pipeline_retries(session, queue, settings, wall_now)

        dispatched += _dispatch_interval_jobs(
            session,
            queue,
            settings,
            state,
            wall_now,
            monotonic_now,
            ingestion_auto_retry_enabled=ingestion_auto_retry_enabled,
            sync_pull_enabled=sync_pull_enabled,
            sync_auto_retry_enabled=sync_auto_retry_enabled,
        )

        if session is not None:
            _finalize_tick_heartbeats(
                session,
                settings,
                wall_now,
                ingestion_enabled=ingestion_enabled,
                ingestion_auto_retry_enabled=ingestion_auto_retry_enabled,
                sync_pull_enabled=sync_pull_enabled,
                sync_auto_retry_enabled=sync_auto_retry_enabled,
            )
            session.commit()
    finally:
        if session is not None:
            session.close()
    state.dispatched.extend(dispatched)
    return dispatched


# --------------------------------------------------------------------------
# per-workspace 遍历模式（§8.2-§8.3）
# --------------------------------------------------------------------------


def _enabled_workspaces(session) -> list:
    from app.models.workspace import Workspace

    return list(
        session.scalars(
            select(Workspace).where(Workspace.enabled.is_(True)).order_by(Workspace.code),
        ).all(),
    )


def _any_workspace_has_policy(workspaces: list) -> bool:
    from app.pipeline.schedule_policy import has_workspace_schedule_policy

    return any(has_workspace_schedule_policy(workspace) for workspace in workspaces)


def _dispatch_policy_daily(session, queue: Queue, settings, workspaces: list, wall_now: datetime) -> list[str]:
    from app.pipeline.runs import (
        create_pipeline_run,
        has_scheduler_dispatched_run,
        upsert_scheduler_heartbeat,
    )
    from app.pipeline.schedule_policy import (
        has_workspace_schedule_policy,
        parse_time_of_day,
        resolve_workspace_schedule,
    )

    dispatched: list[str] = []
    timezone = wall_now.tzinfo
    missed_window = max(0, int(settings.scheduler_missed_window_seconds or 3600))
    for workspace in workspaces:
        if not has_workspace_schedule_policy(workspace) and (
            workspace.code != settings.ingestion_scheduler_workspace_code
        ):
            # 策略缺失的工作台只有兼容工作台参与调度（§8.3 兼容规则）。
            continue
        resolved = resolve_workspace_schedule(settings, workspace, now=wall_now)
        if not resolved.effective_enabled:
            continue
        parsed_time = parse_time_of_day(resolved.effective_daily_time)
        if parsed_time is None:
            continue
        trigger_at = datetime.combine(wall_now.date(), parsed_time, tzinfo=timezone)
        if wall_now < trigger_at:
            continue
        if (wall_now - trigger_at).total_seconds() > missed_window:
            continue
        day_key = (wall_now.date() + timedelta(days=resolved.effective_day_offset)).isoformat()
        if _heartbeat_enqueued_since(session, job_kind="daily_pipeline", workspace_code=workspace.code, since=trigger_at):
            continue
        if has_scheduler_dispatched_run(session, workspace_code=workspace.code, day_key=day_key):
            continue

        request = DailyPipelineRequest(
            workspace_code=workspace.code,
            day_key=day_key,
            source_types=resolved.effective_source_types,
            ingestion_limit=settings.ingestion_scheduler_limit,
            ingestion_concurrency=settings.ingestion_concurrency,
            ingestion_source_timeout_seconds=settings.ingestion_source_timeout_seconds,
            ingestion_max_items_per_source=getattr(settings, "ingestion_max_items_per_source", None),
            recommendation_limit=settings.daily_pipeline_recommendation_limit,
            source_daily_limit=settings.daily_pipeline_source_daily_limit,
            generation_timeout_seconds=45.0,
            create_daily_draft=settings.daily_pipeline_create_daily_draft,
            run_ingestion=settings.daily_pipeline_run_ingestion,
        )
        run = create_pipeline_run(
            session,
            request=request,
            trigger_type="scheduler",
            triggered_by="scheduler",
            status="queued",
            retry_policy={
                "max_attempts": resolved.retry_max_attempts,
                "backoff_seconds": resolved.retry_backoff_seconds,
            },
            now=wall_now,
        )
        job = queue.enqueue(
            run_daily_pipeline_job,
            workspace.code,
            resolved.effective_source_types,
            settings.ingestion_scheduler_limit,
            settings.ingestion_concurrency,
            settings.ingestion_source_timeout_seconds,
            getattr(settings, "ingestion_max_items_per_source", None),
            settings.daily_pipeline_recommendation_limit,
            settings.daily_pipeline_source_daily_limit,
            45.0,
            settings.daily_pipeline_create_daily_draft,
            settings.daily_pipeline_run_ingestion,
            day_key,
            pipeline_run_id=run.id,
            trigger_type="scheduler",
            job_timeout=DAILY_JOB_TIMEOUT,
            result_ttl=JOB_RESULT_TTL,
            failure_ttl=JOB_FAILURE_TTL,
        )
        upsert_scheduler_heartbeat(
            session,
            scheduler_instance=scheduler_instance_id(settings),
            job_kind="daily_pipeline",
            workspace_code=workspace.code,
            last_tick_at=wall_now,
            last_enqueued_at=wall_now,
            last_enqueued_job_id=str(getattr(job, "id", "")),
            next_run_at=trigger_at + timedelta(days=1),
            detail_json={"workspace_code": workspace.code, "day_key": day_key, "attempt": 1},
        )
        session.commit()
        logger.info(
            "Queued daily_pipeline job %s for workspace %s (day_key=%s, run=%s)",
            getattr(job, "id", ""),
            workspace.code,
            day_key,
            run.id,
        )
        dispatched.append(f"daily_pipeline:{workspace.code}:{day_key}")
    return dispatched


def _dispatch_weekly(session, queue: Queue, settings, workspaces: list, wall_now: datetime) -> list[str]:
    from app.pipeline.runs import run_weekly_report_draft_job, upsert_scheduler_heartbeat
    from app.pipeline.schedule_policy import parse_time_of_day, resolve_workspace_schedule

    dispatched: list[str] = []
    timezone = wall_now.tzinfo
    missed_window = max(0, int(settings.scheduler_missed_window_seconds or 3600))
    for workspace in workspaces:
        resolved = resolve_workspace_schedule(settings, workspace, now=wall_now)
        if not resolved.effective_enabled or not resolved.weekly_enabled:
            continue
        if wall_now.isoweekday() != resolved.weekly_day:
            continue
        parsed_time = parse_time_of_day(resolved.weekly_time)
        if parsed_time is None:
            continue
        trigger_at = datetime.combine(wall_now.date(), parsed_time, tzinfo=timezone)
        if wall_now < trigger_at:
            continue
        if (wall_now - trigger_at).total_seconds() > missed_window:
            continue
        if _heartbeat_enqueued_since(session, job_kind="weekly_report", workspace_code=workspace.code, since=trigger_at):
            continue
        iso = wall_now.isocalendar()
        week_key = f"{iso.year}-W{iso.week:02d}"
        job = queue.enqueue(
            run_weekly_report_draft_job,
            workspace.code,
            week_key,
            job_timeout=DEFAULT_JOB_TIMEOUT,
            result_ttl=JOB_RESULT_TTL,
            failure_ttl=JOB_FAILURE_TTL,
        )
        upsert_scheduler_heartbeat(
            session,
            scheduler_instance=scheduler_instance_id(settings),
            job_kind="weekly_report",
            workspace_code=workspace.code,
            last_tick_at=wall_now,
            last_enqueued_at=wall_now,
            last_enqueued_job_id=str(getattr(job, "id", "")),
            next_run_at=trigger_at + timedelta(days=7),
            detail_json={"workspace_code": workspace.code, "week_key": week_key},
        )
        session.commit()
        logger.info(
            "Queued weekly_report job %s for workspace %s (%s)",
            getattr(job, "id", ""),
            workspace.code,
            week_key,
        )
        dispatched.append(f"weekly_report:{workspace.code}:{week_key}")
    return dispatched


def _dispatch_due_pipeline_retries(session, queue: Queue, settings, wall_now: datetime) -> list[str]:
    from app.auth.service import write_audit
    from app.pipeline.runs import (
        create_pipeline_retry_run,
        due_pipeline_retry_runs,
        is_pipeline_run_superseded,
        pipeline_run_chain_ids,
        upsert_scheduler_heartbeat,
    )

    dispatched: list[str] = []
    for failed_run in due_pipeline_retry_runs(session, now=wall_now):
        superseded = is_pipeline_run_superseded(session, failed_run)
        retry_run = create_pipeline_retry_run(session, failed_run, superseded=superseded)
        if superseded:
            # 手动重跑已成功/日报已发布：自动重试让位（§6.2），不投递。
            session.commit()
            logger.info(
                "Pipeline retry superseded for workspace %s day %s (run=%s)",
                failed_run.workspace_code,
                failed_run.day_key,
                retry_run.id,
            )
            dispatched.append(f"pipeline_retry_superseded:{failed_run.workspace_code}:{failed_run.day_key}")
            continue
        job = queue.enqueue(
            run_daily_pipeline_job,
            retry_run.workspace_code,
            list((retry_run.parameters_json or {}).get("source_types") or []),
            pipeline_run_id=retry_run.id,
            trigger_type="retry",
            attempt=retry_run.attempt,
            retry_of_run_id=failed_run.id,
            day_key=retry_run.day_key,
            job_timeout=DAILY_JOB_TIMEOUT,
            result_ttl=JOB_RESULT_TTL,
            failure_ttl=JOB_FAILURE_TTL,
        )
        upsert_scheduler_heartbeat(
            session,
            scheduler_instance=scheduler_instance_id(settings),
            job_kind="pipeline_retry",
            workspace_code=retry_run.workspace_code,
            last_tick_at=wall_now,
            last_enqueued_at=wall_now,
            last_enqueued_job_id=str(getattr(job, "id", "")),
            detail_json={
                "workspace_code": retry_run.workspace_code,
                "day_key": retry_run.day_key,
                "attempt": retry_run.attempt,
            },
        )
        write_audit(
            session,
            None,
            action="pipeline.run.auto_retry",
            object_type="pipeline_run",
            object_id=retry_run.id,
            detail={
                "workspace_code": retry_run.workspace_code,
                "day_key": retry_run.day_key,
                "attempt": retry_run.attempt,
                "error_code": failed_run.error_code,
                "run_id_chain": pipeline_run_chain_ids(session, retry_run),
            },
        )
        session.commit()
        logger.info(
            "Queued pipeline_retry job %s for workspace %s day %s (attempt=%s)",
            getattr(job, "id", ""),
            retry_run.workspace_code,
            retry_run.day_key,
            retry_run.attempt,
        )
        dispatched.append(f"pipeline_retry:{retry_run.workspace_code}:{retry_run.day_key}:{retry_run.attempt}")
    return dispatched


# --------------------------------------------------------------------------
# 兼容模式（无任何工作台策略：投递行为与旧版逐字节一致）
# --------------------------------------------------------------------------


def _dispatch_compat_daily(
    session,
    queue: Queue,
    settings,
    state: SchedulerState,
    wall_now: datetime,
    monotonic_now: float,
) -> list[str]:
    dispatched: list[str] = []
    daily_time = _parse_daily_time(settings.ingestion_scheduler_daily_time)
    if daily_time is not None:
        if state.next_daily_run_at is None:
            # 与旧版启动行为一致：已过今天触发点则等明天，不补跑。
            state.next_daily_run_at = datetime.combine(wall_now.date(), daily_time, tzinfo=wall_now.tzinfo)
            if state.next_daily_run_at <= wall_now:
                state.next_daily_run_at += timedelta(days=1)
        if wall_now >= state.next_daily_run_at:
            _enqueue_and_log(queue, settings, now=wall_now)
            state.next_daily_run_at += timedelta(days=1)
            _record_compat_daily_heartbeat(session, settings, wall_now, state.next_daily_run_at)
            dispatched.append(
                f"{settings.scheduler_job_mode}:{settings.ingestion_scheduler_workspace_code}",
            )
    elif monotonic_now - state.last_ingestion_at >= max(60, settings.ingestion_scheduler_interval_seconds):
        _enqueue_and_log(queue, settings)
        state.last_ingestion_at = monotonic_now
        _record_compat_daily_heartbeat(session, settings, wall_now, None)
        dispatched.append(
            f"{settings.scheduler_job_mode}:{settings.ingestion_scheduler_workspace_code}",
        )
    return dispatched


def _record_compat_daily_heartbeat(session, settings, wall_now: datetime, next_run_at: datetime | None) -> None:
    if session is None:
        return
    from app.pipeline.runs import upsert_scheduler_heartbeat

    upsert_scheduler_heartbeat(
        session,
        scheduler_instance=scheduler_instance_id(settings),
        job_kind="daily_pipeline",
        workspace_code=settings.ingestion_scheduler_workspace_code,
        last_tick_at=wall_now,
        last_enqueued_at=wall_now,
        next_run_at=next_run_at,
        detail_json={
            "workspace_code": settings.ingestion_scheduler_workspace_code,
            "day_key": _scheduled_day_key(settings, now=wall_now),
            "mode": "compat",
        },
    )


# --------------------------------------------------------------------------
# interval 任务（对象级 ingestion 自动重试 / sync pull / sync inbox 重试）
# --------------------------------------------------------------------------


def _dispatch_interval_jobs(
    session,
    queue: Queue,
    settings,
    state: SchedulerState,
    wall_now: datetime,
    monotonic_now: float,
    *,
    ingestion_auto_retry_enabled: bool,
    sync_pull_enabled: bool,
    sync_auto_retry_enabled: bool,
) -> list[str]:
    dispatched: list[str] = []
    if ingestion_auto_retry_enabled and (state.last_ingestion_auto_retry_at is None or monotonic_now - state.last_ingestion_auto_retry_at >= max(
        60,
        settings.ingestion_failed_source_retry_base_seconds,
    )):
        job = queue.enqueue(
            run_failed_source_auto_retry_job,
            job_timeout=DEFAULT_JOB_TIMEOUT,
            result_ttl=JOB_RESULT_TTL,
            failure_ttl=JOB_FAILURE_TTL,
        )
        logger.info("Queued ingestion_failed_source_auto_retry job %s", getattr(job, "id", ""))
        state.last_ingestion_auto_retry_at = monotonic_now
        _record_interval_heartbeat(session, settings, "ingestion_auto_retry", wall_now, job)
        dispatched.append("ingestion_auto_retry")
    if sync_pull_enabled and (state.last_sync_pull_at is None or monotonic_now - state.last_sync_pull_at >= max(
        60,
        settings.sync_pull_interval_seconds,
    )):
        job = queue.enqueue(
            run_sync_pull_job,
            job_timeout=DEFAULT_JOB_TIMEOUT,
            result_ttl=JOB_RESULT_TTL,
            failure_ttl=JOB_FAILURE_TTL,
        )
        logger.info("Queued sync_pull job %s for remote %s", getattr(job, "id", ""), settings.sync_remote_base_url)
        state.last_sync_pull_at = monotonic_now
        _record_interval_heartbeat(session, settings, "sync_pull", wall_now, job)
        dispatched.append("sync_pull")
    if sync_auto_retry_enabled and (state.last_sync_auto_retry_at is None or monotonic_now - state.last_sync_auto_retry_at >= max(
        60,
        settings.sync_failed_inbox_retry_base_seconds,
    )):
        job = queue.enqueue(
            run_failed_sync_inbox_auto_retry_job,
            job_timeout=60 * 30,
            result_ttl=JOB_RESULT_TTL,
            failure_ttl=JOB_FAILURE_TTL,
        )
        logger.info("Queued sync_failed_inbox_auto_retry job %s", getattr(job, "id", ""))
        state.last_sync_auto_retry_at = monotonic_now
        _record_interval_heartbeat(session, settings, "sync_auto_retry", wall_now, job)
        dispatched.append("sync_auto_retry")
    return dispatched


def _record_interval_heartbeat(session, settings, job_kind: str, wall_now: datetime, job) -> None:
    if session is None:
        return
    from app.pipeline.runs import upsert_scheduler_heartbeat

    upsert_scheduler_heartbeat(
        session,
        scheduler_instance=scheduler_instance_id(settings),
        job_kind=job_kind,
        workspace_code="",
        last_tick_at=wall_now,
        last_enqueued_at=wall_now,
        last_enqueued_job_id=str(getattr(job, "id", "")),
    )


# --------------------------------------------------------------------------
# 心跳（§8.5）
# --------------------------------------------------------------------------


def _heartbeat_enqueued_since(session, *, job_kind: str, workspace_code: str, since: datetime) -> bool:
    """跨实例查询 (job_kind, workspace) 是否已在本触发点后投递过（幂等第一道）。"""
    from app.models.pipeline import SchedulerHeartbeat
    from app.pipeline.runs import ensure_aware

    rows = session.scalars(
        select(SchedulerHeartbeat.last_enqueued_at).where(
            SchedulerHeartbeat.job_kind == job_kind,
            SchedulerHeartbeat.workspace_code == workspace_code,
        ),
    ).all()
    return any(value is not None and ensure_aware(value) >= since for value in rows)


def _finalize_tick_heartbeats(
    session,
    settings,
    wall_now: datetime,
    *,
    ingestion_enabled: bool,
    ingestion_auto_retry_enabled: bool,
    sync_pull_enabled: bool,
    sync_auto_retry_enabled: bool,
) -> None:
    from app.models.pipeline import SchedulerHeartbeat
    from app.pipeline.runs import upsert_scheduler_heartbeat

    instance = scheduler_instance_id(settings)
    active_kinds: list[str] = []
    if ingestion_enabled:
        active_kinds += ["daily_pipeline", "pipeline_retry"]
    if ingestion_auto_retry_enabled:
        active_kinds.append("ingestion_auto_retry")
    if sync_pull_enabled:
        active_kinds.append("sync_pull")
    if sync_auto_retry_enabled:
        active_kinds.append("sync_auto_retry")
    for job_kind in active_kinds:
        upsert_scheduler_heartbeat(
            session,
            scheduler_instance=instance,
            job_kind=job_kind,
            workspace_code="",
            last_tick_at=wall_now,
        )
    # §8.3：每个 tick 结束 upsert 本实例所有心跳行的 last_tick_at。
    session.execute(
        update(SchedulerHeartbeat)
        .where(SchedulerHeartbeat.scheduler_instance == instance)
        .values(last_tick_at=wall_now),
    )


# --------------------------------------------------------------------------
# 兼容模式投递（保持与旧版逐字节一致，回归测试直接断言本函数）
# --------------------------------------------------------------------------


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
