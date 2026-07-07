"""Consumer-side API pull for extranet -> intranet synchronization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.models.common import utc_now
from app.models.sync import SyncCursor, SyncRun
from app.sync.apply import apply_sync_records
from app.sync.feed import InvalidFeedCursorError, decode_cursor, encode_cursor
from app.sync.records import SYNC_FEED_OBJECT_TYPES

DEFAULT_PULL_LIMIT = 200

# keyset (updated_at, id) 水位的并发写入保护窗口（秒）。
# publisher 侧 updated_at 在 ORM flush 时生成、事务 commit 后才对 feed 可见：
# 长事务晚提交的行时间戳会落在 consumer 已推进的水位之前，feed 的严格大于过滤
# 将永久漏发（raw_items 是写一次的原始事实，漏发即静默丢数据）。
# 补偿方案：每轮 pull 对每类对象的第一页把已持久化水位回退 LOOKBACK 秒，
# 重放这段重叠区间；重复事件由 sync_inbox 的 event_id 幂等终态
# （applied/skipped/conflict）吸收，不会重复写数据。翻页游标不回退，
# 单轮内严格前进，不会死循环。窗口需覆盖 publisher 侧最长写事务时长加时钟偏差。
SYNC_PULL_REPLAY_LOOKBACK_SECONDS = 300

# 传输层异常集合：连接失败 / 4xx-5xx（raise_for_status）/ 响应不是合法 JSON 对象
_TRANSPORT_ERRORS = (httpx.HTTPError, RuntimeError, ValueError)


@dataclass
class ObjectPullStats:
    received: int = 0
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    conflicts: int = 0
    pages: int = 0
    transport_failed: bool = False
    errors: list[str] = field(default_factory=list)


def run_sync_pull(session: Session, settings: Settings, *, limit: int = DEFAULT_PULL_LIMIT) -> SyncRun:
    now = utc_now()
    remote_base_url = settings.sync_remote_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.sync_remote_token}"}

    run = SyncRun(
        package_id=f"api_pull_{now.strftime('%Y%m%d%H%M%S%f')}",
        source_instance_id="remote",
        target_instance_id=settings.effective_instance_id,
        direction="api_pull",
        status="running",
        counts_json={},
        started_at=now,
    )
    session.add(run)
    session.flush()

    per_object: dict[str, dict[str, Any]] = {}
    all_errors: list[str] = []
    remote_instance_id = "remote"
    transport_failed = False

    # 传输层失败（extranet 不可达、token 失效、5xx）不允许裸抛：
    # 异常会让路由/job 的事务整体回滚，running 状态的 run 也随之丢失，
    # 运维在 /api/sync/health 里就看不到任何失败记录。这里把失败落成
    # status=failed 的 SyncRun 后正常返回，由调用方提交。
    try:
        with httpx.Client(base_url=remote_base_url, headers=headers, timeout=30.0) as client:
            manifest = _get_json(client, "/api/sync/feed/manifest")
            remote_instance_id = str(manifest.get("instance_id") or "remote")
            run.source_instance_id = remote_instance_id

            for object_type in SYNC_FEED_OBJECT_TYPES:
                stats = _pull_object_type(
                    session=session,
                    run=run,
                    client=client,
                    object_type=object_type,
                    source_instance_id=remote_instance_id,
                    limit=limit,
                )
                per_object[object_type] = asdict(stats)
                all_errors.extend(f"{object_type}: {error}" for error in stats.errors)
                transport_failed = transport_failed or stats.transport_failed
                # failed（外键依赖缺失等）或传输失败按依赖序中断后续类型；
                # 冲突不再中断：冲突已落库 sync_conflicts + sync_inbox，可独立处置
                if stats.failed or stats.transport_failed:
                    break
    except _TRANSPORT_ERRORS as exc:
        transport_failed = True
        all_errors.append(f"manifest: {exc}")

    totals = _sum_stats(per_object)
    run.status = "failed" if transport_failed else _pull_status(totals)
    run.completed_at = utc_now()
    run.counts_json = {
        **totals,
        "remote_instance_id": remote_instance_id,
        "object_types": list(SYNC_FEED_OBJECT_TYPES),
        "per_object": per_object,
        "errors": all_errors,
    }
    session.flush()
    return run


def run_sync_pull_job(limit: int = DEFAULT_PULL_LIMIT) -> dict[str, Any]:
    settings = get_settings()
    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for sync pull jobs.")

    with session_factory() as session:
        run = run_sync_pull(session, settings, limit=limit)
        payload = {
            "id": run.id,
            "package_id": run.package_id,
            "direction": run.direction,
            "status": run.status,
            "counts_json": run.counts_json,
        }
        session.commit()
        return payload


def _pull_object_type(
    *,
    session: Session,
    run: SyncRun,
    client: httpx.Client,
    object_type: str,
    source_instance_id: str,
    limit: int,
) -> ObjectPullStats:
    cursor_row = session.get(SyncCursor, object_type)
    if cursor_row is None:
        cursor_row = SyncCursor(object_type=object_type, cursor="")
        session.add(cursor_row)
        session.flush()

    # 首页把持久化水位回退一个安全窗口重放（见 SYNC_PULL_REPLAY_LOOKBACK_SECONDS），
    # 吸收 publisher 侧长事务晚提交造成的水位前漏发行
    cursor = cursor_row.cursor or None
    if cursor:
        cursor = _rewound_cursor(cursor, SYNC_PULL_REPLAY_LOOKBACK_SECONDS)
    stats = ObjectPullStats()
    while True:
        params: dict[str, Any] = {"object_type": object_type, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        try:
            page = _get_json(client, "/api/sync/feed", params=params)
        except _TRANSPORT_ERRORS as exc:
            # feed 页传输失败：水位不动但要在 sync_cursors 上留下失败痕迹，
            # /api/sync/health 才能立刻转 critical，而不是等滞后阈值兜底
            stats.transport_failed = True
            stats.errors.append(f"transport: {exc}")
            cursor_row.last_status = "failed"
            cursor_row.last_error = str(exc)[:4000]
            session.flush()
            return stats
        records = page.get("records") if isinstance(page.get("records"), list) else []
        outcome = apply_sync_records(session, run, records, source_instance_id=source_instance_id)
        stats.pages += 1
        stats.received += outcome.received
        stats.applied += outcome.applied
        stats.skipped += outcome.skipped
        stats.failed += outcome.failed
        stats.conflicts += outcome.conflicts
        stats.errors.extend(outcome.errors)

        next_cursor = str(page.get("next_cursor") or "")
        if outcome.failed:
            # failed（外键依赖缺失等）不推进水位：等 retry 自愈或下一轮按序重拉
            cursor_row.last_status = "failed"
            cursor_row.last_error = "; ".join(outcome.errors)[:4000]
            session.flush()
            return stats

        # 冲突不卡水位：冲突记录已持久化在 sync_conflicts + sync_inbox（可追溯、
        # 可处置，不依赖重拉同一页），水位照常推进；同一冲突由 apply 侧按
        # (object_type, object_id, open) 幂等去重，不会每轮重复新增 open 记录
        if next_cursor:
            cursor_row.cursor = next_cursor
            cursor = next_cursor
        cursor_row.last_pulled_at = utc_now()
        cursor_row.last_status = "ok"
        cursor_row.last_error = ""
        session.flush()

        if not bool(page.get("has_more")) or not next_cursor:
            return stats


def _rewound_cursor(cursor: str, lookback_seconds: int) -> str:
    """把持久化的 keyset 游标回退 lookback 秒，返回重放起点游标。

    id 位取 "0" 哨兵（字典序小于任何 uuid hex id），使回退时间点之后的行全部
    重新纳入。游标无法解析时原样返回（publisher 会按非法游标拒绝，暴露问题）。
    """
    try:
        updated_at, _ = decode_cursor(cursor)
    except InvalidFeedCursorError:
        return cursor
    return encode_cursor(updated_at - timedelta(seconds=lookback_seconds), "0")


def _get_json(client: httpx.Client, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.get(path, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} returned non-object JSON")
    return payload


def _sum_stats(per_object: dict[str, dict[str, Any]]) -> dict[str, int]:
    totals = {"received": 0, "applied": 0, "skipped": 0, "failed": 0, "conflicts": 0, "pages": 0}
    for stats in per_object.values():
        for key in totals:
            totals[key] += int(stats.get(key) or 0)
    return totals


def _pull_status(totals: dict[str, int]) -> str:
    if totals["failed"]:
        return "completed_with_errors"
    if totals["conflicts"]:
        return "completed_with_conflicts"
    return "completed"
