"""Daily pipeline run 记录与 run 级自动重试（docs/backend/pipeline-jobs-design.md §3.1/§6.1-§6.2）。

两级重试分工（§6.1）：
- 对象级 failed-source auto-retry 处理 run 内单源失败（app/ingestion/retry.py，已有）。
- 本模块是 run 级：整条 daily pipeline run 落 ``failed``（不是 ``partial``）且
  error_code 可重试时按 schedule_policy.retry 指数退避自动重投。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.collaboration.notifications import record_pipeline_retry_exhausted_activity
from app.ingestion.runs import WorkspaceNotFoundError as IngestionWorkspaceNotFoundError
from app.models.common import utc_now
from app.models.pipeline import PipelineRun, SchedulerHeartbeat
from app.models.reports import DailyReport
from app.models.workspace import Workspace
from app.pipeline.daily import DailyPipelineRequest, daily_pipeline_payload, run_daily_pipeline
from app.pipeline.schedule_policy import default_schedule_policy, resolve_retry_policy
from app.recommendations.service import PublishedDailyReportError, WorkspaceNotFoundError

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
DAILY_PIPELINE_TYPE = "daily_report"

# 错误码显式分类（§6.1）：不可重试类重试也必然失败，直接终态。
NON_RETRYABLE_ERROR_CODES = frozenset(
    {
        "published_report_conflict",
        "capability_disabled",
        "invalid_parameters",
        "workspace_not_found",
    },
)
DEFAULT_ERROR_CODE = "pipeline_execution_error"


def classify_pipeline_error(exc: BaseException) -> str:
    if isinstance(exc, PublishedDailyReportError):
        return "published_report_conflict"
    if isinstance(exc, (WorkspaceNotFoundError, IngestionWorkspaceNotFoundError)):
        return "workspace_not_found"
    if isinstance(exc, (ValueError, TypeError)):
        return "invalid_parameters"
    return DEFAULT_ERROR_CODE


def is_retryable_error_code(error_code: str) -> bool:
    return bool(error_code) and error_code not in NON_RETRYABLE_ERROR_CODES


def resolve_pipeline_day_key(day_key: str | None, *, now: datetime | None = None) -> str:
    """重试链必须钉死 day_key：首跑未显式指定时按推荐链路口径取北京时间当日。"""
    if day_key:
        return day_key
    current = now or utc_now()
    return current.astimezone(BEIJING_TZ).date().isoformat()


def pipeline_request_parameters(request: DailyPipelineRequest) -> dict[str, Any]:
    return {
        "workspace_code": request.workspace_code,
        "day_key": request.day_key,
        "source_types": list(request.source_types or []),
        "ingestion_limit": request.ingestion_limit,
        "ingestion_concurrency": request.ingestion_concurrency,
        "ingestion_source_timeout_seconds": request.ingestion_source_timeout_seconds,
        "ingestion_max_items_per_source": request.ingestion_max_items_per_source,
        "recommendation_limit": request.recommendation_limit,
        "source_daily_limit": request.source_daily_limit,
        "generation_timeout_seconds": request.generation_timeout_seconds,
        "create_daily_draft": request.create_daily_draft,
        "run_ingestion": request.run_ingestion,
        "auto_publish_daily": request.auto_publish_daily,
    }


def pipeline_request_from_parameters(parameters: dict[str, Any]) -> DailyPipelineRequest:
    return DailyPipelineRequest(
        workspace_code=str(parameters.get("workspace_code") or ""),
        day_key=parameters.get("day_key"),
        source_types=list(parameters.get("source_types") or []),
        ingestion_limit=parameters.get("ingestion_limit"),
        ingestion_concurrency=int(parameters.get("ingestion_concurrency") or 8),
        ingestion_source_timeout_seconds=float(
            parameters.get("ingestion_source_timeout_seconds") or 25.0,
        ),
        ingestion_max_items_per_source=parameters.get("ingestion_max_items_per_source"),
        recommendation_limit=int(parameters.get("recommendation_limit") or 15),
        source_daily_limit=int(parameters.get("source_daily_limit") or 2),
        generation_timeout_seconds=float(parameters.get("generation_timeout_seconds") or 45.0),
        create_daily_draft=bool(parameters.get("create_daily_draft", True)),
        run_ingestion=bool(parameters.get("run_ingestion", True)),
        auto_publish_daily=parameters.get("auto_publish_daily"),
    )


def create_pipeline_run(
    session: Session,
    *,
    request: DailyPipelineRequest,
    trigger_type: str,
    triggered_by: str = "",
    status: str = "queued",
    attempt: int = 1,
    retry_of_run_id: str | None = None,
    retry_max_attempts_override: int | None = None,
    retry_policy: dict[str, int] | None = None,
    now: datetime | None = None,
) -> PipelineRun:
    workspace = session.scalar(
        select(Workspace).where(Workspace.code == request.workspace_code),
    )
    if retry_policy is None:
        retry_policy = resolve_retry_policy(
            workspace,
            retry_max_attempts_override=retry_max_attempts_override,
        )
    day_key = resolve_pipeline_day_key(request.day_key, now=now)
    pinned_request = DailyPipelineRequest(
        **{**pipeline_request_parameters(request), "day_key": day_key},
    )
    parameters = pipeline_request_parameters(pinned_request)
    parameters["retry"] = dict(retry_policy)
    run = PipelineRun(
        workspace_code=request.workspace_code,
        domain_code=workspace.default_domain_code if workspace else "ai",
        sync_policy="local_only",
        pipeline_type=DAILY_PIPELINE_TYPE,
        day_key=day_key,
        status=status,
        trigger_type=trigger_type,
        triggered_by=triggered_by or "",
        parameters_json=parameters,
        attempt=max(1, int(attempt)),
        max_attempts=int(retry_policy["max_attempts"]) + 1,
        retry_of_run_id=retry_of_run_id,
    )
    session.add(run)
    session.flush()
    return run


async def execute_pipeline_run(
    session: Session,
    run: PipelineRun,
    *,
    registry=None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """执行并终态化一个 pipeline run；失败时按 §6.2 写重试链或耗尽告警。

    始终返回 job payload（不上抛业务异常）：失败信息落 run 行与 payload，
    调用方（API 路由/worker job）按 status/error_code 决定响应语义。
    """
    run_id = run.id
    run.status = "running"
    run.started_at = now or utc_now()
    session.commit()
    run = session.get(PipelineRun, run_id)
    request = pipeline_request_from_parameters(run.parameters_json or {})
    try:
        result = await run_daily_pipeline(session, request, registry=registry)
    except Exception as exc:  # noqa: BLE001 - 失败分类后落 run 行
        session.rollback()
        run = session.get(PipelineRun, run_id)
        run.status = "failed"
        run.error_code = classify_pipeline_error(exc)
        run.error_message = str(exc)
        run.finished_at = utc_now()
        schedule_pipeline_retry(session, run)
        session.commit()
        run = session.get(PipelineRun, run_id)
        return pipeline_failure_payload(run)

    payload = daily_pipeline_payload(result)
    ingestion_run = result.ingestion_run
    partial = ingestion_run is not None and (
        int(ingestion_run.source_failed or 0) > 0 or ingestion_run.status == "partial"
    )
    run.status = "partial" if partial else "succeeded"
    run.finished_at = utc_now()
    run.summary_json = dict(payload)
    payload["pipeline_run_id"] = run.id
    payload["pipeline_run_status"] = run.status
    payload["attempt"] = run.attempt
    session.commit()
    return payload


def pipeline_failure_payload(run: PipelineRun) -> dict[str, Any]:
    return {
        "status": "failed",
        "pipeline_run_id": run.id,
        "pipeline_run_status": run.status,
        "workspace_code": run.workspace_code,
        "day_key": run.day_key,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "attempt": run.attempt,
        "max_attempts": run.max_attempts,
        "next_retry_at": run.next_retry_at.isoformat() if run.next_retry_at else None,
    }


def schedule_pipeline_retry(session: Session, run: PipelineRun) -> None:
    """failed 终态处置（§6.2）：可重试且未达上限写 next_retry_at；耗尽发告警。

    ``partial`` 永不进入本函数（partial 交给对象级 failed-source 重试）。
    """
    if run.status != "failed":
        return
    if not is_retryable_error_code(run.error_code):
        return
    retry_policy = (run.parameters_json or {}).get("retry") or default_schedule_policy()["retry"]
    backoff_seconds = int(retry_policy.get("backoff_seconds") or 900)
    if run.attempt < run.max_attempts:
        finished_at = _ensure_aware(run.finished_at or utc_now())
        run.next_retry_at = finished_at + timedelta(
            seconds=backoff_seconds * (2 ** max(0, run.attempt - 1)),
        )
        run.retry_reason = run.error_code
        return
    if run.max_attempts <= 1:
        # retry.max_attempts=0（或请求级覆盖 0=本次不自动重试）：没有可耗尽的
        # 自动重试，不发 exhausted 告警（管理员显式选择了人工处置）。
        return
    record_pipeline_retry_exhausted_activity(
        session,
        workspace_code=run.workspace_code,
        domain_code=run.domain_code,
        run_id=run.id,
        day_key=run.day_key,
        attempt=run.attempt,
        error_code=run.error_code,
        run_id_chain=pipeline_run_chain_ids(session, run),
    )


def pipeline_run_chain_ids(session: Session, run: PipelineRun) -> list[str]:
    """沿 retry_of_run_id 回溯到首跑（首跑在前，当前 run 在最后）。"""
    chain: list[str] = [run.id]
    current = run
    seen = {run.id}
    while current.retry_of_run_id:
        parent = session.get(PipelineRun, current.retry_of_run_id)
        if parent is None or parent.id in seen:
            break
        chain.append(parent.id)
        seen.add(parent.id)
        current = parent
    chain.reverse()
    return chain


def due_pipeline_retry_runs(session: Session, *, now: datetime | None = None) -> list[PipelineRun]:
    current = _ensure_aware(now or utc_now())
    runs = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.pipeline_type == DAILY_PIPELINE_TYPE,
            PipelineRun.status == "failed",
            PipelineRun.next_retry_at.is_not(None),
        )
        .order_by(PipelineRun.next_retry_at),
    ).all()
    return [run for run in runs if _ensure_aware(run.next_retry_at) <= current]


def is_pipeline_run_superseded(session: Session, run: PipelineRun) -> bool:
    """同 day_key 已有 succeeded run 或已发布日报 → 自动重试必须让位（§6.2）。"""
    succeeded = session.scalar(
        select(PipelineRun.id).where(
            PipelineRun.workspace_code == run.workspace_code,
            PipelineRun.pipeline_type == DAILY_PIPELINE_TYPE,
            PipelineRun.day_key == run.day_key,
            PipelineRun.status == "succeeded",
        ),
    )
    if succeeded is not None:
        return True
    published = session.scalar(
        select(DailyReport.id).where(
            DailyReport.workspace_code == run.workspace_code,
            DailyReport.day_key == run.day_key,
            DailyReport.status == "published",
        ),
    )
    return published is not None


def create_pipeline_retry_run(
    session: Session,
    failed_run: PipelineRun,
    *,
    superseded: bool,
) -> PipelineRun:
    parameters = dict(failed_run.parameters_json or {})
    retry_policy = dict(parameters.get("retry") or default_schedule_policy()["retry"])
    request = pipeline_request_from_parameters(parameters)
    run = create_pipeline_run(
        session,
        request=request,
        trigger_type="retry",
        triggered_by="scheduler",
        status="skipped" if superseded else "queued",
        attempt=failed_run.attempt + 1,
        retry_of_run_id=failed_run.id,
        retry_policy={
            "max_attempts": int(retry_policy.get("max_attempts") or 0),
            "backoff_seconds": int(retry_policy.get("backoff_seconds") or 900),
        },
    )
    run.retry_reason = failed_run.error_code
    if superseded:
        run.skip_reason = "superseded"
        run.finished_at = utc_now()
    # 消费掉待重试标记，避免每个 tick 重复投递。
    failed_run.next_retry_at = None
    session.flush()
    return run


def list_recent_pipeline_runs(
    session: Session,
    workspace_code: str,
    *,
    limit: int = 5,
) -> list[PipelineRun]:
    return list(
        session.scalars(
            select(PipelineRun)
            .where(
                PipelineRun.workspace_code == workspace_code,
                PipelineRun.pipeline_type == DAILY_PIPELINE_TYPE,
            )
            .order_by(desc(PipelineRun.created_at), desc(PipelineRun.id))
            .limit(limit),
        ).all(),
    )


def pending_pipeline_retry(session: Session, workspace_code: str) -> PipelineRun | None:
    runs = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.workspace_code == workspace_code,
            PipelineRun.pipeline_type == DAILY_PIPELINE_TYPE,
            PipelineRun.status == "failed",
            PipelineRun.next_retry_at.is_not(None),
        )
        .order_by(PipelineRun.next_retry_at),
    ).all()
    return runs[0] if runs else None


def has_scheduler_dispatched_run(
    session: Session,
    *,
    workspace_code: str,
    day_key: str,
) -> bool:
    """§4 幂等键兜底：同 (workspace, day_key) 的 scheduler 触发 run 已存在则不再投。"""
    existing = session.scalar(
        select(PipelineRun.id).where(
            PipelineRun.workspace_code == workspace_code,
            PipelineRun.pipeline_type == DAILY_PIPELINE_TYPE,
            PipelineRun.day_key == day_key,
            PipelineRun.trigger_type == "scheduler",
        ),
    )
    return existing is not None


def upsert_scheduler_heartbeat(
    session: Session,
    *,
    scheduler_instance: str,
    job_kind: str,
    workspace_code: str = "",
    last_tick_at: datetime,
    last_enqueued_at: datetime | None = None,
    last_enqueued_job_id: str | None = None,
    next_run_at: datetime | None = None,
    detail_json: dict[str, Any] | None = None,
) -> SchedulerHeartbeat:
    """心跳行 upsert（唯一键 scheduler_instance+job_kind+workspace_code，§3.1）。

    detail_json 只放最近投递参数摘要（workspace/day_key/attempt），不含密钥。
    """
    heartbeat = session.scalar(
        select(SchedulerHeartbeat).where(
            SchedulerHeartbeat.scheduler_instance == scheduler_instance,
            SchedulerHeartbeat.job_kind == job_kind,
            SchedulerHeartbeat.workspace_code == (workspace_code or ""),
        ),
    )
    if heartbeat is None:
        heartbeat = SchedulerHeartbeat(
            scheduler_instance=scheduler_instance,
            job_kind=job_kind,
            workspace_code=workspace_code or "",
            last_tick_at=last_tick_at,
        )
        session.add(heartbeat)
    heartbeat.last_tick_at = last_tick_at
    if last_enqueued_at is not None:
        heartbeat.last_enqueued_at = last_enqueued_at
    if last_enqueued_job_id is not None:
        heartbeat.last_enqueued_job_id = last_enqueued_job_id
    if next_run_at is not None:
        heartbeat.next_run_at = next_run_at
    if detail_json is not None:
        heartbeat.detail_json = detail_json
    session.flush()
    return heartbeat


def latest_heartbeat_at(session: Session) -> datetime | None:
    values = session.scalars(select(SchedulerHeartbeat.last_tick_at)).all()
    aware = [_ensure_aware(value) for value in values if value is not None]
    return max(aware) if aware else None


def _ensure_aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# 供路由/调度器复用的公开别名（sqlite 读回的 datetime 可能缺 tzinfo）。
ensure_aware = _ensure_aware


def run_weekly_report_draft_job(workspace_code: str, week_key: str) -> dict[str, Any]:
    """周报节拍 job（§8.2）：幂等重建本周草稿，不自动发布。"""
    from app.core.database import get_session_factory
    from app.reports.weekly import (
        PublishedWeeklyReportError,
        WeeklyReportDraftRequest,
        create_weekly_report_draft,
    )

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for weekly report draft jobs.")
    with session_factory() as session:
        try:
            report = create_weekly_report_draft(
                session,
                WeeklyReportDraftRequest(workspace_code=workspace_code, week_key=week_key),
            )
        except PublishedWeeklyReportError as exc:
            return {
                "status": "skipped",
                "reason": "published_report_conflict",
                "workspace_code": workspace_code,
                "week_key": week_key,
                "detail": str(exc),
            }
        session.commit()
        return {
            "status": "succeeded",
            "workspace_code": workspace_code,
            "week_key": week_key,
            "weekly_report_id": report.id,
            "weekly_report_status": report.status,
        }
