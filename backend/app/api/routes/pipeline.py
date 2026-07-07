from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import assert_workspace_member, get_current_user, require_capability
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.models.common import utc_now
from app.models.identity import User
from app.models.pipeline import PipelineRun
from app.models.workspace import Workspace, WorkspaceMembership
from app.pipeline.daily import DailyPipelineRequest
from app.pipeline.runs import (
    create_pipeline_run,
    ensure_aware,
    execute_pipeline_run,
    latest_heartbeat_at,
    list_recent_pipeline_runs,
    pending_pipeline_retry,
)
from app.pipeline.schedule_policy import resolve_workspace_schedule, scheduler_timezone
from app.schemas.pipeline import DailyPipelineRunCreate, DailyPipelineRunRead
from app.schemas.schedule_policy import (
    SchedulerStatusPendingRetryRead,
    SchedulerStatusRead,
    SchedulerStatusRunRead,
    SchedulerStatusWorkspaceRead,
)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)
SETTINGS = Depends(get_settings)
# 含采集阶段，intranet 形态整条本地管线关闭（消费远端成稿）
INGESTION_CAPABILITY = Depends(require_capability("ingestion"))

# 心跳超过 3 个 tick（180s）视为 scheduler 离线（pipeline-jobs-design §8.5）。
HEARTBEAT_STALE_SECONDS = 180


@router.post("/daily-runs", response_model=DailyPipelineRunRead, dependencies=[INGESTION_CAPABILITY])
async def create_daily_pipeline_run(
    payload: DailyPipelineRunCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> DailyPipelineRunRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    # 手动触发同样吃工作台 retry 策略（§6.2）；retry_max_attempts 请求级覆盖
    # （null=跟随工作台，0=本次不自动重试）。run 行先落库，失败也留痕。
    run = create_pipeline_run(
        session,
        request=DailyPipelineRequest(
            workspace_code=payload.workspace_code,
            day_key=payload.day_key,
            source_types=payload.source_types,
            ingestion_limit=payload.ingestion_limit,
            ingestion_concurrency=payload.ingestion_concurrency,
            ingestion_source_timeout_seconds=payload.ingestion_source_timeout_seconds,
            ingestion_max_items_per_source=payload.ingestion_max_items_per_source,
            recommendation_limit=payload.recommendation_limit,
            source_daily_limit=payload.source_daily_limit,
            generation_timeout_seconds=payload.generation_timeout_seconds,
            create_daily_draft=payload.create_daily_draft,
            run_ingestion=payload.run_ingestion,
        ),
        trigger_type="manual",
        triggered_by=current_user.id,
        retry_max_attempts_override=payload.retry_max_attempts,
    )
    session.commit()
    result_payload = await execute_pipeline_run(session, run)
    if result_payload.get("status") == "failed":
        error_code = str(result_payload.get("error_code") or "")
        if error_code == "published_report_conflict":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(result_payload.get("error_message") or ""),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": error_code,
                "message": str(result_payload.get("error_message") or ""),
                "pipeline_run_id": result_payload.get("pipeline_run_id"),
                "attempt": result_payload.get("attempt"),
                "next_retry_at": result_payload.get("next_retry_at"),
            },
        )
    return DailyPipelineRunRead(**result_payload)


@router.get("/scheduler/status", response_model=SchedulerStatusRead)
def get_scheduler_status(
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
    settings: Settings = SETTINGS,
) -> SchedulerStatusRead:
    """调度心跳与下次运行（§8.5）：只读 DB，不与 scheduler 进程通信。

    intranet 等禁采形态不 403：返回 capability_ingestion=false 供前端解释；
    workspaces 数组按调用者 membership 过滤（super_admin 全量）。
    """
    timezone = scheduler_timezone(settings)
    now = datetime.now(timezone)
    heartbeat_at = latest_heartbeat_at(session)
    heartbeat_stale = (
        heartbeat_at is None
        or (utc_now() - heartbeat_at) > timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    )
    workspaces = _visible_workspaces(session, current_user)
    workspace_reads: list[SchedulerStatusWorkspaceRead] = []
    for workspace in workspaces:
        resolved = resolve_workspace_schedule(settings, workspace, now=now)
        last_runs = [
            _run_to_status_read(run) for run in list_recent_pipeline_runs(session, workspace.code)
        ]
        pending = pending_pipeline_retry(session, workspace.code)
        workspace_reads.append(
            SchedulerStatusWorkspaceRead(
                workspace_code=workspace.code,
                effective_enabled=resolved.effective_enabled,
                effective_daily_time=resolved.effective_daily_time,
                effective_day_offset=resolved.effective_day_offset,
                policy_source=resolved.policy_source,
                next_run_at=resolved.next_run_at.isoformat() if resolved.next_run_at else None,
                weekly_enabled=resolved.weekly_enabled,
                last_runs=last_runs,
                pending_retry=_pending_retry_read(pending),
            ),
        )
    return SchedulerStatusRead(
        instance_enabled=bool(settings.ingestion_scheduler_enabled),
        deploy_mode=settings.deploy_mode,
        capability_ingestion=bool(settings.capability_ingestion),
        timezone=settings.ingestion_scheduler_timezone,
        heartbeat_at=heartbeat_at.isoformat() if heartbeat_at else None,
        heartbeat_stale=heartbeat_stale,
        workspaces=workspace_reads,
    )


def _visible_workspaces(session: Session, user: User) -> list[Workspace]:
    is_super_admin = any(role.code == "super_admin" for role in user.roles)
    if is_super_admin:
        return list(
            session.scalars(
                select(Workspace).where(Workspace.enabled.is_(True)).order_by(Workspace.code),
            ).all(),
        )
    return list(
        session.scalars(
            select(Workspace)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(
                Workspace.enabled.is_(True),
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.enabled.is_(True),
            )
            .order_by(Workspace.code),
        ).all(),
    )


def _run_to_status_read(run: PipelineRun) -> SchedulerStatusRunRead:
    return SchedulerStatusRunRead(
        run_id=run.id,
        day_key=run.day_key,
        status=run.status,
        trigger_type=run.trigger_type,
        attempt=run.attempt,
        error_code=run.error_code or "",
        skip_reason=run.skip_reason or "",
        finished_at=ensure_aware(run.finished_at).isoformat() if run.finished_at else None,
    )


def _pending_retry_read(run: PipelineRun | None) -> SchedulerStatusPendingRetryRead | None:
    if run is None:
        return None
    return SchedulerStatusPendingRetryRead(
        run_id=run.id,
        attempt=run.attempt,
        next_attempt=run.attempt + 1,
        next_retry_at=ensure_aware(run.next_retry_at).isoformat() if run.next_retry_at else None,
        error_code=run.error_code or "",
    )
