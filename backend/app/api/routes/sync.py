from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.api.routes.auth import require_capability, require_super_admin
from app.auth.service import write_audit
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.models.common import utc_now
from app.models.identity import User
from app.models.sync import SyncConflict, SyncCursor, SyncInbox, SyncRun
from app.schemas.operations import SyncRunRead
from app.schemas.sync import (
    SyncConflictRead,
    SyncConflictResolve,
    SyncCursorHealthRead,
    SyncHealthAlertRead,
    SyncHealthRead,
    SyncHealthRunRead,
    SyncHealthStatus,
    SyncHealthThresholdsRead,
)
from app.sync.feed import InvalidFeedCursorError, UnknownFeedObjectTypeError, feed_manifest, feed_page
from app.sync.apply import apply_sync_conflict_resolution
from app.sync.pull import DEFAULT_PULL_LIMIT, run_sync_pull
from app.sync.retry import failed_inbox_retry_summary, retry_failed_sync_inbox
from app.sync.records import SYNC_FEED_OBJECT_TYPES

router = APIRouter(prefix="/api/sync", tags=["sync"])
SYNC_PUBLISHER_CAPABILITY = Depends(require_capability("sync_publisher"))
SYNC_CONSUMER_CAPABILITY = Depends(require_capability("sync_consumer"))


def _sync_feed_consumers(settings: Settings) -> list[tuple[str, str]]:
    """解析 SYNC_SERVICE_TOKENS 为 (consumer_name, token) 列表。

    条目支持两种形式（逗号分隔，可混用）：
    - "name:token"：命名消费者，name 进审计日志，轮换/追责按名定位；
    - 纯 "token"：兼容旧配置，消费者名按条目位置记为 token-<序号>。
    注意：exports 侧的 require_sync_token（app/api/routes/auth.py）仍按整条比对，
    命名条目目前只对 feed/manifest 生效。
    """
    consumers: list[tuple[str, str]] = []
    for index, entry in enumerate(settings.sync_service_tokens.split(",")):
        entry = entry.strip()
        if not entry:
            continue
        name, separator, token = entry.partition(":")
        if separator and name.strip() and token.strip():
            consumers.append((name.strip(), token.strip()))
        else:
            consumers.append((f"token-{index + 1}", entry))
    return consumers


def require_sync_feed_consumer(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    """feed 侧 service token 鉴权，返回消费者身份供审计使用。"""
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sync token")
    for consumer_name, token in _sync_feed_consumers(settings):
        if hmac.compare_digest(token, presented):
            return consumer_name
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sync token")


@router.get(
    "/feed/manifest",
    dependencies=[SYNC_PUBLISHER_CAPABILITY],
)
def get_sync_feed_manifest(
    consumer: str = Depends(require_sync_feed_consumer),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    manifest = feed_manifest(session, settings.effective_instance_id)
    # feed 访问审计：记录哪个内网消费者在何时读取了 manifest（追责/轮换依据）
    write_audit(session, None, "sync_feed.manifest", "sync_feed", "manifest", {"consumer": consumer})
    session.commit()
    return manifest


@router.get("/feed", dependencies=[SYNC_PUBLISHER_CAPABILITY])
def get_sync_feed(
    object_type: str = Query(...),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    consumer: str = Depends(require_sync_feed_consumer),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        page = feed_page(session, object_type, cursor=cursor, limit=limit)
    except UnknownFeedObjectTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InvalidFeedCursorError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    response: dict[str, object] = {
        "object_type": page.object_type,
        "records": page.records,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
        "server_time": utc_now().isoformat(),
    }
    # feed 访问审计：消费者身份 + 拉取范围（cursor 是不透明水位，不含密钥）
    write_audit(
        session,
        None,
        "sync_feed.read",
        "sync_feed",
        page.object_type,
        {
            "consumer": consumer,
            "object_type": page.object_type,
            "cursor": cursor or "",
            "next_cursor": page.next_cursor or "",
            "record_count": len(page.records),
            "has_more": page.has_more,
        },
    )
    session.commit()
    return response


@router.post(
    "/pull-runs",
    response_model=SyncRunRead,
    dependencies=[SYNC_CONSUMER_CAPABILITY],
)
def create_sync_pull_run(
    limit: int = Query(default=DEFAULT_PULL_LIMIT, ge=1, le=500),
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SyncRunRead:
    run = run_sync_pull(session, settings, limit=limit)
    write_audit(
        session,
        current_user,
        "sync_pull.run",
        "sync_run",
        run.id,
        {"package_id": run.package_id, "status": run.status, "counts": run.counts_json},
    )
    session.commit()
    session.refresh(run)
    return SyncRunRead(
        id=run.id,
        package_id=run.package_id,
        source_instance_id=run.source_instance_id,
        target_instance_id=run.target_instance_id,
        direction=run.direction,
        status=run.status,
        counts_json=run.counts_json or {},
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


@router.get("/health", response_model=SyncHealthRead)
def get_sync_health(
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SyncHealthRead:
    return _build_sync_health(session, settings)


@router.post("/inbox/retry-failed", response_model=SyncRunRead)
def retry_failed_sync_inbox_records(
    object_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SyncRunRead:
    if object_type and object_type not in SYNC_FEED_OBJECT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unsupported object_type: {object_type}")
    run = retry_failed_sync_inbox(session, settings, object_type=object_type, limit=limit)
    write_audit(
        session,
        current_user,
        "sync_inbox.retry_failed",
        "sync_run",
        run.id,
        {
            "package_id": run.package_id,
            "status": run.status,
            "object_type": object_type or "",
            "limit": limit,
            "counts": run.counts_json,
        },
    )
    session.commit()
    session.refresh(run)
    return SyncRunRead(
        id=run.id,
        package_id=run.package_id,
        source_instance_id=run.source_instance_id,
        target_instance_id=run.target_instance_id,
        direction=run.direction,
        status=run.status,
        counts_json=run.counts_json or {},
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


@router.get("/conflicts", response_model=list[SyncConflictRead])
def list_sync_conflicts(
    status_filter: str = Query(default="open", alias="status"),
    object_type: str | None = Query(default=None),
    sync_run_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> list[SyncConflictRead]:
    statement = (
        select(SyncConflict)
        .options(selectinload(SyncConflict.sync_run))
        .order_by(SyncConflict.created_at.desc(), SyncConflict.id.desc())
        .limit(limit)
    )
    if status_filter != "all":
        statement = statement.where(SyncConflict.status == status_filter)
    if object_type:
        statement = statement.where(SyncConflict.object_type == object_type)
    if sync_run_id:
        statement = statement.where(SyncConflict.sync_run_id == sync_run_id)
    conflicts = session.scalars(statement).all()
    return [_sync_conflict_to_read(session, conflict) for conflict in conflicts]


@router.get("/conflicts/{conflict_id}", response_model=SyncConflictRead)
def get_sync_conflict(
    conflict_id: str,
    _: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> SyncConflictRead:
    return _sync_conflict_to_read(session, _load_sync_conflict(session, conflict_id))


@router.post("/conflicts/{conflict_id}/resolve", response_model=SyncConflictRead)
def resolve_sync_conflict(
    conflict_id: str,
    payload: SyncConflictResolve,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> SyncConflictRead:
    conflict = _load_sync_conflict(session, conflict_id)
    if conflict.status != "open":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sync conflict is not open")

    apply_result: dict[str, object] = {}
    if payload.strategy in {"use_incoming", "manual_merge"}:
        try:
            apply_result = apply_sync_conflict_resolution(
                session,
                conflict,
                strategy=payload.strategy,
                merged_json=payload.merged_json,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    now = utc_now()
    conflict.status = "resolved" if payload.strategy == "keep_local" else payload.strategy
    conflict.resolved_by_user_id = current_user.id
    conflict.resolved_at = now
    conflict.resolution_json = {
        **(conflict.resolution_json or {}),
        "strategy": payload.strategy,
        "reason": payload.reason,
        "merged_json": payload.merged_json,
        "apply_result": apply_result,
        "resolved_at": now.isoformat(),
    }
    write_audit(
        session,
        current_user,
        "sync_conflict.resolve",
        "sync_conflict",
        conflict.id,
        {
            "strategy": payload.strategy,
            "object_type": conflict.object_type,
            "object_id": conflict.object_id,
            "sync_run_id": conflict.sync_run_id,
        },
    )
    session.commit()
    session.refresh(conflict)
    return _sync_conflict_to_read(session, conflict)


def _build_sync_health(session: Session, settings: Settings) -> SyncHealthRead:
    now = utc_now()
    pull_interval = max(60, int(settings.sync_pull_interval_seconds or 60))
    warning_after_seconds = pull_interval * 2
    critical_after_seconds = pull_interval * 6
    thresholds = SyncHealthThresholdsRead(
        warning_after_seconds=warning_after_seconds,
        critical_after_seconds=critical_after_seconds,
        pull_interval_seconds=pull_interval,
    )
    sync_role = _sync_role(settings)
    cursor_rows = {
        cursor.object_type: cursor
        for cursor in session.scalars(select(SyncCursor).order_by(SyncCursor.object_type)).all()
    }
    expected_object_types = list(SYNC_FEED_OBJECT_TYPES) if settings.capability_sync_consumer else list(cursor_rows)
    cursors: list[SyncCursorHealthRead] = []
    alerts: list[SyncHealthAlertRead] = []
    missing_object_types = [object_type for object_type in expected_object_types if object_type not in cursor_rows]

    for object_type in expected_object_types:
        cursor = cursor_rows.get(object_type)
        if cursor is None:
            continue
        cursor_health = _cursor_health(
            cursor,
            now=now,
            warning_after_seconds=warning_after_seconds,
            critical_after_seconds=critical_after_seconds,
        )
        cursors.append(cursor_health)
        if cursor_health.status == "critical":
            alerts.append(
                SyncHealthAlertRead(
                    severity="critical",
                    code="cursor_failed_or_critical_lag",
                    object_type=cursor_health.object_type,
                    message=f"{cursor_health.object_type} 同步水位失败或严重滞后",
                ),
            )
        elif cursor_health.status == "warning":
            alerts.append(
                SyncHealthAlertRead(
                    severity="warning",
                    code="cursor_stale",
                    object_type=cursor_health.object_type,
                    message=f"{cursor_health.object_type} 同步水位已超过告警阈值",
                ),
            )
        elif cursor_health.status == "inactive":
            alerts.append(
                SyncHealthAlertRead(
                    severity="warning",
                    code="cursor_inactive",
                    object_type=cursor_health.object_type,
                    message=f"{cursor_health.object_type} 还没有成功拉取记录",
                ),
            )

    for object_type in sorted(set(cursor_rows) - set(expected_object_types)):
        cursors.append(
            _cursor_health(
                cursor_rows[object_type],
                now=now,
                warning_after_seconds=warning_after_seconds,
                critical_after_seconds=critical_after_seconds,
            ),
        )

    if missing_object_types:
        alerts.append(
            SyncHealthAlertRead(
                severity="warning",
                code="missing_cursors",
                message=f"{len(missing_object_types)} 类同步对象还没有拉取水位",
            ),
        )

    recent_runs = session.scalars(select(SyncRun).order_by(SyncRun.created_at.desc()).limit(10)).all()
    last_run = recent_runs[0] if recent_runs else None
    recent_failed_run_count = sum(1 for run in recent_runs if _sync_run_is_failed(run))
    recent_conflict_run_count = sum(1 for run in recent_runs if _sync_run_has_conflicts(run))
    if recent_failed_run_count:
        alerts.append(
            SyncHealthAlertRead(
                severity="critical",
                code="recent_failed_runs",
                message=f"最近 10 次同步运行中有 {recent_failed_run_count} 次失败或部分失败",
            ),
        )
    if recent_conflict_run_count:
        alerts.append(
            SyncHealthAlertRead(
                severity="warning",
                code="recent_conflict_runs",
                message=f"最近 10 次同步运行中有 {recent_conflict_run_count} 次产生冲突",
            ),
        )

    open_conflict_count = (
        session.scalar(select(func.count()).select_from(SyncConflict).where(SyncConflict.status == "open")) or 0
    )
    if open_conflict_count:
        alerts.append(
            SyncHealthAlertRead(
                severity="warning",
                code="open_conflicts",
                message=f"当前还有 {open_conflict_count} 个 open 同步冲突待处置",
            ),
        )

    failed_inbox_rows = session.execute(
        select(SyncInbox.object_type, func.count())
        .where(SyncInbox.status == "failed")
        .group_by(SyncInbox.object_type),
    ).all()
    failed_inbox_by_object_type = {str(object_type or "unknown"): int(count or 0) for object_type, count in failed_inbox_rows}
    failed_inbox_count = sum(failed_inbox_by_object_type.values())
    retry_summary = failed_inbox_retry_summary(session, settings, now=now)
    failed_inbox_retry_due_count = int(retry_summary["due_count"] or 0)
    failed_inbox_retry_blocked_count = int(retry_summary["blocked_count"] or 0)
    failed_inbox_next_retry_at = retry_summary["next_retry_at"]
    failed_inbox_retry_policy = dict(retry_summary["policy"] or {})
    if failed_inbox_count:
        alerts.append(
            SyncHealthAlertRead(
                severity="critical",
                code="failed_inbox_records",
                message=f"当前还有 {failed_inbox_count} 条 failed sync_inbox 记录可重试",
            ),
        )
    if failed_inbox_retry_blocked_count:
        alerts.append(
            SyncHealthAlertRead(
                severity="critical",
                code="failed_inbox_retry_blocked",
                message=f"{failed_inbox_retry_blocked_count} 条 failed sync_inbox 已达到自动重试上限，需要人工检查",
            ),
        )

    stale_cursor_count = sum(1 for cursor in cursors if cursor.status == "warning")
    failed_cursor_count = sum(1 for cursor in cursors if cursor.status == "critical")
    status_value = _overall_sync_health_status(
        alerts,
        sync_role=sync_role,
        cursor_count=len(cursors),
        recent_run_count=len(recent_runs),
        open_conflict_count=int(open_conflict_count),
    )
    return SyncHealthRead(
        status=status_value,
        generated_at=now,
        sync_role=sync_role,
        summary=_sync_health_summary(status_value, alerts),
        thresholds=thresholds,
        cursor_count=len(cursors),
        missing_cursor_count=len(missing_object_types),
        stale_cursor_count=stale_cursor_count,
        failed_cursor_count=failed_cursor_count,
        failed_inbox_count=failed_inbox_count,
        failed_inbox_by_object_type=failed_inbox_by_object_type,
        failed_inbox_retry_due_count=failed_inbox_retry_due_count,
        failed_inbox_retry_blocked_count=failed_inbox_retry_blocked_count,
        failed_inbox_next_retry_at=failed_inbox_next_retry_at,
        failed_inbox_retry_policy=failed_inbox_retry_policy,
        open_conflict_count=int(open_conflict_count),
        recent_failed_run_count=recent_failed_run_count,
        last_run=_sync_health_run_to_read(last_run) if last_run is not None else None,
        cursors=cursors,
        alerts=alerts,
    )


def _cursor_health(
    cursor: SyncCursor,
    *,
    now: datetime,
    warning_after_seconds: int,
    critical_after_seconds: int,
) -> SyncCursorHealthRead:
    warnings: list[str] = []
    age_seconds = _age_seconds(now, cursor.last_pulled_at)
    status_value: SyncHealthStatus = "ok"
    if cursor.last_status == "failed" or cursor.last_error:
        status_value = "critical"
        warnings.append(cursor.last_error or "last_status=failed")
    elif age_seconds is None:
        status_value = "inactive"
        warnings.append("no successful pull recorded")
    elif age_seconds > critical_after_seconds:
        status_value = "critical"
        warnings.append(f"cursor age {age_seconds}s exceeds critical threshold")
    elif age_seconds > warning_after_seconds:
        status_value = "warning"
        warnings.append(f"cursor age {age_seconds}s exceeds warning threshold")

    return SyncCursorHealthRead(
        object_type=cursor.object_type,
        cursor=cursor.cursor or "",
        last_pulled_at=cursor.last_pulled_at,
        last_status=cursor.last_status or "",
        last_error=cursor.last_error or "",
        age_seconds=age_seconds,
        status=status_value,
        warnings=warnings,
    )


def _sync_role(settings: Settings) -> str:
    if settings.capability_sync_publisher and settings.capability_sync_consumer:
        return "publisher_consumer"
    if settings.capability_sync_publisher:
        return "publisher"
    if settings.capability_sync_consumer:
        return "consumer"
    return "none"


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now - value).total_seconds()))


def _sync_run_is_failed(run: SyncRun) -> bool:
    counts = run.counts_json or {}
    failed_count = counts.get("failed")
    return run.status in {"failed", "error", "completed_with_errors"} or (
        isinstance(failed_count, (int, float)) and failed_count > 0
    )


def _sync_run_has_conflicts(run: SyncRun) -> bool:
    counts = run.counts_json or {}
    conflict_count = counts.get("conflicts")
    return run.status == "completed_with_conflicts" or (
        isinstance(conflict_count, (int, float)) and conflict_count > 0
    )


def _overall_sync_health_status(
    alerts: list[SyncHealthAlertRead],
    *,
    sync_role: str,
    cursor_count: int,
    recent_run_count: int,
    open_conflict_count: int,
) -> SyncHealthStatus:
    if any(alert.severity == "critical" for alert in alerts):
        return "critical"
    if any(alert.severity == "warning" for alert in alerts):
        return "warning"
    if sync_role == "none" and cursor_count == 0 and recent_run_count == 0 and open_conflict_count == 0:
        return "inactive"
    return "ok"


def _sync_health_summary(status_value: SyncHealthStatus, alerts: list[SyncHealthAlertRead]) -> str:
    if status_value == "ok":
        return "同步运行正常"
    if status_value == "inactive":
        return "当前实例未启用同步角色"
    critical_count = sum(1 for alert in alerts if alert.severity == "critical")
    warning_count = sum(1 for alert in alerts if alert.severity == "warning")
    if critical_count:
        return f"同步存在 {critical_count} 个严重告警、{warning_count} 个提醒"
    return f"同步存在 {warning_count} 个提醒"


def _sync_health_run_to_read(run: SyncRun) -> SyncHealthRunRead:
    return SyncHealthRunRead(
        id=run.id,
        package_id=run.package_id,
        source_instance_id=run.source_instance_id,
        target_instance_id=run.target_instance_id,
        direction=run.direction,
        status=run.status,
        counts_json=run.counts_json or {},
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


def _load_sync_conflict(session: Session, conflict_id: str) -> SyncConflict:
    conflict = session.scalar(
        select(SyncConflict)
        .options(selectinload(SyncConflict.sync_run))
        .where(SyncConflict.id == conflict_id),
    )
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync conflict not found")
    return conflict


def _sync_conflict_to_read(session: Session, conflict: SyncConflict) -> SyncConflictRead:
    resolved_by_name = None
    if conflict.resolved_by_user_id:
        user = session.get(User, conflict.resolved_by_user_id)
        resolved_by_name = user.display_name if user else None
    run = conflict.sync_run
    return SyncConflictRead(
        id=conflict.id,
        sync_run_id=conflict.sync_run_id,
        package_id=run.package_id if run else None,
        source_instance_id=run.source_instance_id if run else None,
        target_instance_id=run.target_instance_id if run else None,
        direction=run.direction if run else None,
        object_type=conflict.object_type,
        object_id=conflict.object_id,
        local_revision=conflict.local_revision,
        incoming_revision=conflict.incoming_revision,
        field_name=conflict.field_name,
        local_value_json=conflict.local_value_json or {},
        incoming_value_json=conflict.incoming_value_json or {},
        conflict_reason=conflict.conflict_reason or (conflict.resolution_json or {}).get("reason", ""),
        status=conflict.status,
        resolution_json=conflict.resolution_json or {},
        resolved_by_user_id=conflict.resolved_by_user_id,
        resolved_by_name=resolved_by_name,
        resolved_at=conflict.resolved_at,
        created_at=conflict.created_at,
        updated_at=conflict.updated_at,
    )
