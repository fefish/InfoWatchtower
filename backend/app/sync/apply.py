"""同步记录应用层（consumer 侧幂等落库）。

被两条通道复用：手工同步包导入（operations 路由）与 api_pull 定时拉取（sync.pull）。
幂等语义（docs/deployment/deployment-topology.md §3.5）：
- event_id 级：sync_inbox 里状态为 applied/skipped/conflict 的事件跳过；failed 允许重放重试
  （外键顺序失败可自愈）；本实例 outbox 里已有的事件视为自产事件跳过（防回环）。
  feed 的 event_id 是 (object_type, global_id, revision) 确定性哈希，因此 conflict 终态
  意味着同一对象同一版本的冲突只判定一次，处置走 sync_conflicts 闭环，不依赖重拉。
- 对象级：按 global_id upsert；revision/content_hash 冲突写 sync_conflicts 不覆盖本地；
  同一对象同一时刻最多一条 open 冲突（重复判定只刷新既有 open 记录，不重复通知）。
红线：同步只搬运数据，不改变公司 SQL 出口合同与任何主链路不变式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.sync import SyncRun

from app.models.common import utc_now
from app.models.content import DataSource, GeneratedNews, NewsItem, RawItem
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.sync.records import (
    SYNC_FEED_OBJECT_TYPES,
    contains_secret_key,
    datetime_value,
    dict_value,
    float_value,
    hash_json,
    int_value,
    optional_str,
)

SYNC_APPLY_OBJECT_TYPES = set(SYNC_FEED_OBJECT_TYPES)
SYNC_MANUAL_MERGE_OBJECT_TYPES = {"data_sources", "daily_reports", "weekly_reports"}
_SYNC_FORCE_CONFLICT_RESOLUTION = "__sync_force_conflict_resolution"

# 幂等跳过的 inbox 终态；failed 不在其中 → 重放可重试（规格 §3.5 前置缺陷修复）。
# conflict 也是终态：冲突已完整落库 sync_conflicts（含 incoming 快照），重放同一
# event_id 不需要也不应该再判一次冲突；处置通过 /api/sync/conflicts 闭环。
INBOX_SETTLED_STATUSES = {"applied", "skipped", "conflict"}


@dataclass
class SyncApplyOutcome:
    received: int = 0
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)


def apply_sync_records(
    session: Session,
    run: "SyncRun",
    records: list[dict[str, Any]],
    *,
    source_instance_id: str,
) -> SyncApplyOutcome:
    """把一批 envelope 记录幂等落库，维护 sync_inbox 台账，返回计数汇总。"""
    from app.models.sync import SyncInbox, SyncOutbox

    outcome = SyncApplyOutcome(received=len(records))
    for record in records:
        event_id = str(record.get("event_id") or "")
        if not event_id:
            outcome.failed += 1
            outcome.errors.append("record without event_id")
            continue

        own_event = session.scalar(select(SyncOutbox).where(SyncOutbox.event_id == event_id))
        if own_event is not None:
            outcome.skipped += 1
            continue
        inbox_existing = session.scalar(select(SyncInbox).where(SyncInbox.event_id == event_id))
        if inbox_existing is not None and inbox_existing.status in INBOX_SETTLED_STATUSES:
            outcome.skipped += 1
            continue

        object_type = str(record.get("object_type") or "")
        object_id = str(record.get("object_global_id") or record.get("object_id") or "")
        record_payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        try:
            apply_status, error_message = apply_sync_record(session, run, record)
        except ValueError as exc:
            apply_status = "failed"
            error_message = str(exc)

        if apply_status == "applied":
            outcome.applied += 1
            # API 会话工厂是 autoflush=False：立刻 flush，让同批后续记录的
            # 外键解析（data_source/raw_item/news_item 的 global_id SELECT）
            # 能看到本条刚落库的对象，依赖序排好的包一轮 apply 即净
            session.flush()
        elif apply_status == "conflict":
            outcome.conflicts += 1
            outcome.errors.append(error_message or f"conflict applying {event_id}")
        elif apply_status == "skipped":
            outcome.skipped += 1
        else:
            outcome.failed += 1
            outcome.errors.append(error_message or f"failed applying {event_id}")

        payload_hash = str(record.get("content_hash") or hash_json(record_payload))
        attempted_at = utc_now()
        error_text = error_message or ""
        if inbox_existing is not None:
            inbox_existing.status = apply_status
            inbox_existing.payload_hash = payload_hash
            inbox_existing.source_instance_id = source_instance_id
            inbox_existing.object_type = object_type
            inbox_existing.object_id = object_id
            inbox_existing.record_json = record
            inbox_existing.error_message = error_text
            inbox_existing.attempt_count = int(inbox_existing.attempt_count or 0) + 1
            inbox_existing.last_attempt_at = attempted_at
        else:
            session.add(
                SyncInbox(
                    event_id=event_id,
                    source_instance_id=source_instance_id,
                    object_type=object_type,
                    object_id=object_id,
                    payload_hash=payload_hash,
                    record_json=record,
                    status=apply_status,
                    error_message=error_text,
                    attempt_count=1,
                    last_attempt_at=attempted_at,
                ),
            )
    return outcome


def apply_sync_record(session: Session, run: "SyncRun", record: dict[str, Any]) -> tuple[str, str | None]:
    object_type = str(record.get("object_type") or "")
    operation = str(record.get("operation") or "upsert")
    if object_type not in SYNC_APPLY_OBJECT_TYPES:
        return "failed", f"unsupported object_type: {object_type}"
    if operation not in {"upsert", "create", "update"}:
        return "failed", f"unsupported operation for {object_type}: {operation}"

    payload = record.get("payload")
    if not isinstance(payload, dict):
        return "failed", f"{object_type} payload must be an object"
    if contains_secret_key(payload):
        return "failed", f"{object_type} payload contains secret-like fields"
    if str(record.get("visibility_scope") or payload.get("visibility_scope") or "") == "restricted":
        return "skipped", f"{object_type} has restricted visibility"

    if object_type == "data_sources":
        return _apply_data_source_record(session, run, record, payload)
    if object_type == "raw_items":
        return _apply_raw_item_record(session, run, record, payload)
    if object_type == "news_items":
        return _apply_news_item_record(session, run, record, payload)
    if object_type == "generated_news":
        return _apply_generated_news_record(session, run, record, payload)
    if object_type == "daily_reports":
        return _apply_daily_report_record(session, run, record, payload)
    if object_type == "weekly_reports":
        return _apply_weekly_report_record(session, run, record, payload)
    return "failed", f"unsupported object_type: {object_type}"


def apply_sync_conflict_resolution(
    session: Session,
    conflict: Any,
    *,
    strategy: str,
    merged_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply an open sync conflict through the same object handlers used by feed/package import."""
    if strategy not in {"use_incoming", "manual_merge"}:
        return {}
    if conflict.object_type not in SYNC_APPLY_OBJECT_TYPES:
        raise ValueError(f"unsupported object_type for conflict resolution: {conflict.object_type}")
    if conflict.sync_run is None:
        raise ValueError("sync conflict has no sync_run")

    incoming = dict(conflict.incoming_value_json or {})
    if strategy == "manual_merge":
        if conflict.object_type not in SYNC_MANUAL_MERGE_OBJECT_TYPES:
            raise ValueError(f"manual_merge is not supported for {conflict.object_type}")
        if not isinstance(merged_json, dict) or not merged_json:
            raise ValueError("manual_merge requires merged_json")
        payload = {**incoming, **merged_json}
        revision = max(int(conflict.local_revision or 0), int(conflict.incoming_revision or 0)) + 1
    else:
        payload = incoming
        revision = max(1, int(conflict.incoming_revision or 1))

    payload["global_id"] = str(payload.get("global_id") or conflict.object_id)
    payload[_SYNC_FORCE_CONFLICT_RESOLUTION] = True
    hash_payload = {
        key: value
        for key, value in payload.items()
        if key not in {_SYNC_FORCE_CONFLICT_RESOLUTION, "content_hash"}
    }
    content_hash = (
        str(incoming.get("content_hash") or hash_json(hash_payload))
        if strategy == "use_incoming"
        else hash_json(hash_payload)
    )
    record = {
        "event_id": f"conflict-resolution:{conflict.id}:{strategy}",
        "object_type": conflict.object_type,
        "object_id": conflict.object_id,
        "object_global_id": conflict.object_id,
        "operation": "upsert",
        "revision": revision,
        "content_hash": content_hash,
        "visibility_scope": payload.get("visibility_scope") or "public",
        "sync_policy": payload.get("sync_policy") or "public_to_intranet",
        "workspace_code": payload.get("workspace_code"),
        "domain_code": payload.get("domain_code"),
        "payload": payload,
    }
    apply_status, error_message = apply_sync_record(session, conflict.sync_run, record)
    if apply_status != "applied":
        raise ValueError(error_message or f"conflict resolution apply returned {apply_status}")
    return {
        "apply_status": apply_status,
        "applied_revision": revision,
        "applied_content_hash": content_hash,
        "object_type": conflict.object_type,
        "object_id": conflict.object_id,
    }


def _apply_data_source_record(
    session: Session,
    run: "SyncRun",
    record: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str | None]:
    global_id = _record_global_id(record, payload)
    incoming_revision = _record_revision(record, payload)
    incoming_hash = _record_content_hash(record, payload)
    source = session.scalar(select(DataSource).where(DataSource.global_id == global_id))
    if source is not None:
        conflict = _maybe_record_sync_conflict(
            session,
            run,
            object_type="data_sources",
            object_id=global_id,
            local_revision=source.revision,
            incoming_revision=incoming_revision,
            local_hash=source.content_hash,
            incoming_hash=incoming_hash,
            local_json=_data_source_snapshot(source),
            incoming_json=payload,
        )
        if conflict:
            return "conflict", conflict
    else:
        source = DataSource(
            global_id=global_id,
            origin_instance_id=str(payload.get("origin_instance_id") or "remote"),
            source_type=str(payload.get("source_type") or "rss"),
            name=str(payload.get("name") or payload.get("source_name") or global_id),
        )
        session.add(source)

    source.workspace_code = str(payload.get("workspace_code") or record.get("workspace_code") or "shared")
    source.domain_code = str(payload.get("domain_code") or record.get("domain_code") or source.domain_code or "ai")
    source.visibility_scope = str(payload.get("visibility_scope") or record.get("visibility_scope") or "public")
    source.sync_policy = str(payload.get("sync_policy") or record.get("sync_policy") or "public_to_intranet")
    source.source_type = str(payload.get("source_type") or source.source_type)
    source.name = str(payload.get("name") or source.name)
    source.url = optional_str(payload.get("url"))
    source.enabled = bool(payload.get("enabled", source.enabled))
    source.default_focus_id = int_value(payload.get("default_focus_id"), source.default_focus_id)
    source.backfill_days = int_value(payload.get("backfill_days"), source.backfill_days)
    source.credential_ref = optional_str(payload.get("credential_ref"))
    source.fetch_config = dict_value(payload.get("fetch_config"))
    source.paper_config = dict_value(payload.get("paper_config"))
    source.metadata_json = dict_value(payload.get("metadata_json") or payload.get("metadata"))
    source.last_fetch_at = datetime_value(payload.get("last_fetch_at"))
    source.last_success_at = datetime_value(payload.get("last_success_at"))
    source.last_error = str(payload.get("last_error") or "")
    source.source_score = float_value(payload.get("source_score"), source.source_score)
    source.revision = incoming_revision
    source.content_hash = incoming_hash
    return "applied", None


def _apply_raw_item_record(
    session: Session,
    run: "SyncRun",
    record: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str | None]:
    global_id = _record_global_id(record, payload)
    incoming_revision = _record_revision(record, payload)
    incoming_hash = _record_content_hash(record, payload)
    raw_item = session.scalar(select(RawItem).where(RawItem.global_id == global_id))
    data_source = _resolve_data_source(session, payload)
    if data_source is None:
        return "failed", "raw_items payload cannot resolve data source"

    if raw_item is not None:
        conflict = _maybe_record_sync_conflict(
            session,
            run,
            object_type="raw_items",
            object_id=global_id,
            local_revision=raw_item.revision,
            incoming_revision=incoming_revision,
            local_hash=raw_item.content_hash,
            incoming_hash=incoming_hash,
            local_json=_raw_item_snapshot(raw_item),
            incoming_json=payload,
        )
        if conflict:
            return "conflict", conflict
    else:
        raw_item = RawItem(
            global_id=global_id,
            origin_instance_id=str(payload.get("origin_instance_id") or "remote"),
            data_source=data_source,
            source_type=str(payload.get("source_type") or data_source.source_type),
            source_name=str(payload.get("source_name") or data_source.name),
            entry_key=str(payload.get("entry_key") or global_id)[:255],
            fetched_at=datetime_value(payload.get("fetched_at")) or utc_now(),
        )
        session.add(raw_item)

    raw_item.data_source = data_source
    raw_item.workspace_code = str(payload.get("workspace_code") or record.get("workspace_code") or "planning_intel")
    raw_item.domain_code = str(payload.get("domain_code") or record.get("domain_code") or data_source.domain_code)
    raw_item.visibility_scope = str(payload.get("visibility_scope") or record.get("visibility_scope") or "public")
    raw_item.sync_policy = str(payload.get("sync_policy") or record.get("sync_policy") or "public_to_intranet")
    raw_item.source_type = str(payload.get("source_type") or data_source.source_type)
    raw_item.source_name = str(payload.get("source_name") or data_source.name)
    raw_item.entry_key = str(payload.get("entry_key") or raw_item.entry_key)[:255]
    raw_item.source_title = str(payload.get("source_title") or "")
    raw_item.source_url = optional_str(payload.get("source_url"))
    raw_item.raw_content = str(payload.get("raw_content") or "")
    raw_item.fetched_at = datetime_value(payload.get("fetched_at")) or raw_item.fetched_at or utc_now()
    raw_item.published_at = datetime_value(payload.get("published_at"))
    raw_item.raw_payload_json = dict_value(payload.get("raw_payload_json"))
    raw_item.revision = incoming_revision
    raw_item.content_hash = incoming_hash
    return "applied", None


def _apply_news_item_record(
    session: Session,
    run: "SyncRun",
    record: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str | None]:
    global_id = _record_global_id(record, payload)
    incoming_revision = _record_revision(record, payload)
    incoming_hash = _record_content_hash(record, payload)
    news_item = session.scalar(select(NewsItem).where(NewsItem.global_id == global_id))
    raw_item = _resolve_raw_item(session, payload)
    data_source = _resolve_data_source(session, payload) or (raw_item.data_source if raw_item else None)
    if raw_item is None or data_source is None:
        return "failed", "news_items payload cannot resolve raw item and data source"

    if news_item is not None:
        conflict = _maybe_record_sync_conflict(
            session,
            run,
            object_type="news_items",
            object_id=global_id,
            local_revision=news_item.revision,
            incoming_revision=incoming_revision,
            local_hash=news_item.content_hash,
            incoming_hash=incoming_hash,
            local_json=_news_item_snapshot(news_item),
            incoming_json=payload,
        )
        if conflict:
            return "conflict", conflict
    else:
        news_item = NewsItem(
            global_id=global_id,
            origin_instance_id=str(payload.get("origin_instance_id") or "remote"),
            raw_item=raw_item,
            data_source=data_source,
            source_type=str(payload.get("source_type") or raw_item.source_type),
            source_name=str(payload.get("source_name") or raw_item.source_name),
            source_title=str(payload.get("source_title") or raw_item.source_title),
            dedupe_key=str(payload.get("dedupe_key") or f"sync:{global_id}")[:512],
        )
        session.add(news_item)

    news_item.raw_item = raw_item
    news_item.data_source = data_source
    news_item.workspace_code = str(payload.get("workspace_code") or record.get("workspace_code") or raw_item.workspace_code)
    news_item.domain_code = str(payload.get("domain_code") or record.get("domain_code") or raw_item.domain_code)
    news_item.visibility_scope = str(payload.get("visibility_scope") or record.get("visibility_scope") or raw_item.visibility_scope)
    news_item.sync_policy = str(payload.get("sync_policy") or record.get("sync_policy") or raw_item.sync_policy)
    news_item.source_type = str(payload.get("source_type") or raw_item.source_type)
    news_item.source_name = str(payload.get("source_name") or raw_item.source_name)
    news_item.source_url = optional_str(payload.get("source_url") or raw_item.source_url)
    news_item.canonical_url = optional_str(payload.get("canonical_url"))
    news_item.source_title = str(payload.get("source_title") or raw_item.source_title)
    news_item.normalized_title = str(payload.get("normalized_title") or news_item.source_title)
    news_item.summary = str(payload.get("summary") or "")
    news_item.content = str(payload.get("content") or raw_item.raw_content or news_item.summary or news_item.source_title)
    news_item.author = str(payload.get("author") or "")
    news_item.published_at = datetime_value(payload.get("published_at")) or raw_item.published_at
    news_item.focus_id = int_value(payload.get("focus_id"), news_item.focus_id)
    news_item.dedupe_key = str(payload.get("dedupe_key") or news_item.dedupe_key)[:512]
    news_item.active = bool(payload.get("active", news_item.active))
    news_item.normalization_status = str(payload.get("normalization_status") or "normalized")
    news_item.normalization_notes = str(payload.get("normalization_notes") or "")
    news_item.revision = incoming_revision
    news_item.content_hash = incoming_hash
    return "applied", None


def _apply_generated_news_record(
    session: Session,
    run: "SyncRun",
    record: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str | None]:
    global_id = _record_global_id(record, payload)
    incoming_revision = _record_revision(record, payload)
    incoming_hash = _record_content_hash(record, payload)
    news_item = _resolve_news_item(session, payload)
    if news_item is None:
        return "failed", "generated_news payload cannot resolve news item"

    generated = session.scalar(select(GeneratedNews).where(GeneratedNews.global_id == global_id))
    if generated is not None:
        conflict = _maybe_record_sync_conflict(
            session,
            run,
            object_type="generated_news",
            object_id=global_id,
            local_revision=generated.revision,
            incoming_revision=incoming_revision,
            local_hash=generated.content_hash,
            incoming_hash=incoming_hash,
            local_json=_generated_news_snapshot(generated),
            incoming_json=payload,
        )
        if conflict:
            return "conflict", conflict
    else:
        # recommendation_item 留空：intranet 消费成稿，不复算推荐链
        generated = GeneratedNews(
            global_id=global_id,
            origin_instance_id=str(payload.get("origin_instance_id") or "remote"),
            news_item=news_item,
            title=str(payload.get("title") or ""),
        )
        session.add(generated)

    generated.news_item = news_item
    generated.workspace_code = str(payload.get("workspace_code") or record.get("workspace_code") or news_item.workspace_code)
    generated.domain_code = str(payload.get("domain_code") or record.get("domain_code") or news_item.domain_code)
    generated.visibility_scope = str(payload.get("visibility_scope") or record.get("visibility_scope") or "public")
    generated.sync_policy = str(payload.get("sync_policy") or record.get("sync_policy") or "public_to_intranet")
    generated.category = str(payload.get("category") or generated.category)
    generated.title = str(payload.get("title") or generated.title)
    generated.summary = str(payload.get("summary") or "")
    generated.key_points = str(payload.get("key_points") or "")
    generated.content_json = dict_value(payload.get("content_json"))
    generated.insight_json = dict_value(payload.get("insight_json"))
    generated.source_url = optional_str(payload.get("source_url"))
    generated.generated_by = str(payload.get("generated_by") or generated.generated_by)
    generated.generation_status = str(payload.get("generation_status") or generated.generation_status)
    generated.revision = incoming_revision
    generated.content_hash = incoming_hash
    return "applied", None


def _apply_daily_report_record(
    session: Session,
    run: "SyncRun",
    record: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str | None]:
    global_id = _record_global_id(record, payload)
    incoming_revision = _record_revision(record, payload)
    incoming_hash = _record_content_hash(record, payload)
    workspace_code = str(payload.get("workspace_code") or record.get("workspace_code") or "planning_intel")
    domain_code = str(payload.get("domain_code") or record.get("domain_code") or "ai")
    day_key = str(payload.get("day_key") or "")
    if not day_key:
        return "failed", "daily_reports payload is missing day_key"

    report = session.scalar(select(DailyReport).where(DailyReport.global_id == global_id))
    if report is not None:
        conflict = _maybe_record_sync_conflict(
            session,
            run,
            object_type="daily_reports",
            object_id=global_id,
            local_revision=report.revision,
            incoming_revision=incoming_revision,
            local_hash=report.content_hash,
            incoming_hash=incoming_hash,
            local_json=_report_snapshot(report, key_field="day_key", key_value=report.day_key),
            incoming_json=payload,
        )
        if conflict:
            return "conflict", conflict
    else:
        # 唯一键 (workspace, domain, day_key) 被本地不同来源的报告占用 → 冲突，不静默吞并
        occupied = session.scalar(
            select(DailyReport).where(
                DailyReport.workspace_code == workspace_code,
                DailyReport.domain_code == domain_code,
                DailyReport.day_key == day_key,
            ),
        )
        if occupied is not None:
            _record_conflict(
                session,
                run,
                object_type="daily_reports",
                object_id=global_id,
                local_revision=occupied.revision,
                incoming_revision=incoming_revision,
                local_json=_report_snapshot(occupied, key_field="day_key", key_value=occupied.day_key),
                incoming_json=payload,
                reason="local report with different global_id occupies the same day_key",
            )
            return "conflict", f"daily_reports:{global_id} conflict: day_key occupied by local report"
        report = DailyReport(
            global_id=global_id,
            origin_instance_id=str(payload.get("origin_instance_id") or "remote"),
            day_key=day_key,
            title=str(payload.get("title") or day_key),
        )
        session.add(report)

    # 先整体解析 items 的成稿外键，避免半应用状态（父对象已改、子项失败）
    incoming_items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    resolved: list[tuple[dict[str, Any], GeneratedNews]] = []
    for item_payload in incoming_items:
        generated = _resolve_generated_news(session, item_payload)
        if generated is None:
            return (
                "failed",
                "daily_reports item cannot resolve generated_news "
                f"{item_payload.get('generated_news_global_id')!r}",
            )
        resolved.append((item_payload, generated))

    report.workspace_code = workspace_code
    report.domain_code = domain_code
    report.visibility_scope = str(payload.get("visibility_scope") or record.get("visibility_scope") or "public")
    report.sync_policy = str(payload.get("sync_policy") or record.get("sync_policy") or "public_to_intranet")
    report.day_key = day_key
    report.title = str(payload.get("title") or report.title)
    report.summary = str(payload.get("summary") or "")
    report.status = str(payload.get("status") or report.status)
    report.published_at = datetime_value(payload.get("published_at"))
    report.revision = incoming_revision
    report.content_hash = incoming_hash
    session.flush()

    # items 随父整体 upsert（按 global_id 对齐）。不删除本地多余项：
    # intranet 的评论/点赞挂在 daily_report_items 上，删除会孤儿化交互数据。
    for item_payload, generated in resolved:
        item_global_id = str(item_payload.get("global_id") or "")
        if not item_global_id:
            continue
        item = session.scalar(select(DailyReportItem).where(DailyReportItem.global_id == item_global_id))
        if item is None:
            item = DailyReportItem(
                global_id=item_global_id,
                origin_instance_id=str(item_payload.get("origin_instance_id") or "remote"),
                daily_report=report,
                generated_news=generated,
            )
            session.add(item)
        item.daily_report = report
        item.generated_news = generated
        item.workspace_code = report.workspace_code
        item.domain_code = report.domain_code
        item.visibility_scope = str(item_payload.get("visibility_scope") or report.visibility_scope)
        item.sync_policy = str(item_payload.get("sync_policy") or report.sync_policy)
        item.adoption_status = int_value(item_payload.get("adoption_status"), 0)
        item.is_headline = bool(item_payload.get("is_headline", False))
        item.sort_order = int_value(item_payload.get("sort_order"), 0)
        item.editor_title = optional_str(item_payload.get("editor_title"))
        item.editor_summary = optional_str(item_payload.get("editor_summary"))
        item.editor_key_points = optional_str(item_payload.get("editor_key_points"))
        editor_content = item_payload.get("editor_content_json")
        item.editor_content_json = editor_content if isinstance(editor_content, dict) else None
        item.editor_notes = str(item_payload.get("editor_notes") or "")
        item.revision = int_value(item_payload.get("revision"), 1)
        item.content_hash = str(item_payload.get("content_hash") or "")
    return "applied", None


def _apply_weekly_report_record(
    session: Session,
    run: "SyncRun",
    record: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, str | None]:
    global_id = _record_global_id(record, payload)
    incoming_revision = _record_revision(record, payload)
    incoming_hash = _record_content_hash(record, payload)
    workspace_code = str(payload.get("workspace_code") or record.get("workspace_code") or "planning_intel")
    domain_code = str(payload.get("domain_code") or record.get("domain_code") or "ai")
    week_key = str(payload.get("week_key") or "")
    if not week_key:
        return "failed", "weekly_reports payload is missing week_key"

    report = session.scalar(select(WeeklyReport).where(WeeklyReport.global_id == global_id))
    if report is not None:
        conflict = _maybe_record_sync_conflict(
            session,
            run,
            object_type="weekly_reports",
            object_id=global_id,
            local_revision=report.revision,
            incoming_revision=incoming_revision,
            local_hash=report.content_hash,
            incoming_hash=incoming_hash,
            local_json=_report_snapshot(report, key_field="week_key", key_value=report.week_key),
            incoming_json=payload,
        )
        if conflict:
            return "conflict", conflict
    else:
        occupied = session.scalar(
            select(WeeklyReport).where(
                WeeklyReport.workspace_code == workspace_code,
                WeeklyReport.domain_code == domain_code,
                WeeklyReport.week_key == week_key,
            ),
        )
        if occupied is not None:
            _record_conflict(
                session,
                run,
                object_type="weekly_reports",
                object_id=global_id,
                local_revision=occupied.revision,
                incoming_revision=incoming_revision,
                local_json=_report_snapshot(occupied, key_field="week_key", key_value=occupied.week_key),
                incoming_json=payload,
                reason="local report with different global_id occupies the same week_key",
            )
            return "conflict", f"weekly_reports:{global_id} conflict: week_key occupied by local report"
        report = WeeklyReport(
            global_id=global_id,
            origin_instance_id=str(payload.get("origin_instance_id") or "remote"),
            week_key=week_key,
            title=str(payload.get("title") or week_key),
        )
        session.add(report)

    incoming_items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    resolved: list[tuple[dict[str, Any], GeneratedNews | None, DailyReportItem | None]] = []
    for item_payload in incoming_items:
        generated = None
        if item_payload.get("generated_news_global_id"):
            generated = _resolve_generated_news(session, item_payload)
            if generated is None:
                return (
                    "failed",
                    "weekly_reports item cannot resolve generated_news "
                    f"{item_payload.get('generated_news_global_id')!r}",
                )
        daily_item = None
        daily_item_global_id = optional_str(item_payload.get("daily_report_item_global_id"))
        if daily_item_global_id:
            daily_item = session.scalar(
                select(DailyReportItem).where(DailyReportItem.global_id == daily_item_global_id),
            )
            if daily_item is None:
                return (
                    "failed",
                    f"weekly_reports item cannot resolve daily_report_item {daily_item_global_id!r}",
                )
        resolved.append((item_payload, generated, daily_item))

    report.workspace_code = workspace_code
    report.domain_code = domain_code
    report.visibility_scope = str(payload.get("visibility_scope") or record.get("visibility_scope") or "public")
    report.sync_policy = str(payload.get("sync_policy") or record.get("sync_policy") or "public_to_intranet")
    report.week_key = week_key
    report.title = str(payload.get("title") or report.title)
    report.summary = str(payload.get("summary") or "")
    report.status = str(payload.get("status") or report.status)
    report.published_at = datetime_value(payload.get("published_at"))
    report.revision = incoming_revision
    report.content_hash = incoming_hash
    session.flush()

    for item_payload, generated, daily_item in resolved:
        item_global_id = str(item_payload.get("global_id") or "")
        if not item_global_id:
            continue
        item = session.scalar(select(WeeklyReportItem).where(WeeklyReportItem.global_id == item_global_id))
        if item is None:
            item = WeeklyReportItem(
                global_id=item_global_id,
                origin_instance_id=str(item_payload.get("origin_instance_id") or "remote"),
                weekly_report=report,
            )
            session.add(item)
        item.weekly_report = report
        item.generated_news = generated
        item.daily_report_item = daily_item
        item.workspace_code = report.workspace_code
        item.domain_code = report.domain_code
        item.visibility_scope = str(item_payload.get("visibility_scope") or report.visibility_scope)
        item.sync_policy = str(item_payload.get("sync_policy") or report.sync_policy)
        item.adoption_status = int_value(item_payload.get("adoption_status"), 0)
        item.sort_order = int_value(item_payload.get("sort_order"), 0)
        item.editor_title = optional_str(item_payload.get("editor_title"))
        item.editor_summary = optional_str(item_payload.get("editor_summary"))
        editor_content = item_payload.get("editor_content_json")
        item.editor_content_json = editor_content if isinstance(editor_content, dict) else None
        item.revision = int_value(item_payload.get("revision"), 1)
        item.content_hash = str(item_payload.get("content_hash") or "")
    return "applied", None


def _maybe_record_sync_conflict(
    session: Session,
    run: "SyncRun",
    *,
    object_type: str,
    object_id: str,
    local_revision: int,
    incoming_revision: int,
    local_hash: str,
    incoming_hash: str,
    local_json: dict[str, Any],
    incoming_json: dict[str, Any],
) -> str | None:
    if incoming_json.get(_SYNC_FORCE_CONFLICT_RESOLUTION) is True:
        return None
    if local_revision > incoming_revision:
        reason = "incoming revision is older than local revision"
    elif local_revision == incoming_revision and local_hash and incoming_hash and local_hash != incoming_hash:
        reason = "same revision has different content hash"
    else:
        return None
    _record_conflict(
        session,
        run,
        object_type=object_type,
        object_id=object_id,
        local_revision=local_revision,
        incoming_revision=incoming_revision,
        local_json=local_json,
        incoming_json=incoming_json,
        reason=reason,
    )
    return f"{object_type}:{object_id} conflict: {reason}"


def _record_conflict(
    session: Session,
    run: "SyncRun",
    *,
    object_type: str,
    object_id: str,
    local_revision: int,
    incoming_revision: int,
    local_json: dict[str, Any],
    incoming_json: dict[str, Any],
    reason: str,
) -> None:
    from app.collaboration.notifications import record_sync_conflict_activity
    from app.models.sync import SyncConflict

    # 冲突幂等：同一对象同一时刻只保留一条 open 冲突。重复判定（不同 event_id、
    # 手工包重放或 incoming 换了新版本仍冲突）只刷新既有 open 记录的 incoming 快照
    # 和判定原因，不新增行、不重复发通知——避免定时 pull 每轮把 open_conflict_count
    # 和 important 通知无限刷高。
    existing = session.scalar(
        select(SyncConflict).where(
            SyncConflict.object_type == object_type,
            SyncConflict.object_id == object_id,
            SyncConflict.status == "open",
        ),
    )
    if existing is not None:
        existing.local_revision = local_revision
        existing.incoming_revision = incoming_revision
        existing.local_value_json = local_json
        existing.incoming_value_json = incoming_json
        existing.conflict_reason = reason
        resolution_json = dict(existing.resolution_json or {})
        existing.resolution_json = {
            **resolution_json,
            "reason": reason,
            "seen_count": int(resolution_json.get("seen_count") or 1) + 1,
            "last_seen_at": utc_now().isoformat(),
            "last_sync_run_id": run.id,
        }
        session.flush()
        return

    conflict = SyncConflict(
        sync_run=run,
        object_type=object_type,
        object_id=object_id,
        local_revision=local_revision,
        incoming_revision=incoming_revision,
        field_name="record",
        local_value_json=local_json,
        incoming_value_json=incoming_json,
        conflict_reason=reason,
        status="open",
        resolution_json={"reason": reason, "seen_count": 1},
    )
    session.add(conflict)
    session.flush()
    workspace_code = str(incoming_json.get("workspace_code") or local_json.get("workspace_code") or "planning_intel")
    domain_code = str(incoming_json.get("domain_code") or local_json.get("domain_code") or "ai")
    record_sync_conflict_activity(session, conflict=conflict, workspace_code=workspace_code, domain_code=domain_code)


def _resolve_data_source(session: Session, payload: dict[str, Any]) -> DataSource | None:
    data_source_global_id = optional_str(payload.get("data_source_global_id") or payload.get("data_source_id"))
    if data_source_global_id:
        source = session.scalar(select(DataSource).where(DataSource.global_id == data_source_global_id))
        if source is not None:
            return source
        source = session.get(DataSource, data_source_global_id)
        if source is not None:
            return source
    url = optional_str(payload.get("data_source_url") or payload.get("url"))
    if url:
        return session.scalar(select(DataSource).where(DataSource.url == url))
    return None


def _resolve_raw_item(session: Session, payload: dict[str, Any]) -> RawItem | None:
    raw_global_id = optional_str(payload.get("raw_item_global_id") or payload.get("raw_item_id"))
    if raw_global_id:
        raw_item = session.scalar(select(RawItem).where(RawItem.global_id == raw_global_id))
        if raw_item is not None:
            return raw_item
        raw_item = session.get(RawItem, raw_global_id)
        if raw_item is not None:
            return raw_item
    return None


def _resolve_news_item(session: Session, payload: dict[str, Any]) -> NewsItem | None:
    news_global_id = optional_str(payload.get("news_item_global_id") or payload.get("news_item_id"))
    if news_global_id:
        news_item = session.scalar(select(NewsItem).where(NewsItem.global_id == news_global_id))
        if news_item is not None:
            return news_item
        news_item = session.get(NewsItem, news_global_id)
        if news_item is not None:
            return news_item
    return None


def _resolve_generated_news(session: Session, payload: dict[str, Any]) -> GeneratedNews | None:
    generated_global_id = optional_str(
        payload.get("generated_news_global_id") or payload.get("generated_news_id"),
    )
    if generated_global_id:
        generated = session.scalar(
            select(GeneratedNews).where(GeneratedNews.global_id == generated_global_id),
        )
        if generated is not None:
            return generated
        generated = session.get(GeneratedNews, generated_global_id)
        if generated is not None:
            return generated
    return None


def _record_global_id(record: dict[str, Any], payload: dict[str, Any]) -> str:
    value = optional_str(record.get("object_global_id") or payload.get("global_id") or record.get("object_id"))
    if not value:
        raise ValueError("sync record is missing object_global_id")
    return value


def _record_revision(record: dict[str, Any], payload: dict[str, Any]) -> int:
    return max(1, int_value(record.get("revision") or payload.get("revision"), 1))


def _record_content_hash(record: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(record.get("content_hash") or payload.get("content_hash") or hash_json(payload))


def _data_source_snapshot(source: DataSource) -> dict[str, Any]:
    return {
        "global_id": source.global_id,
        "revision": source.revision,
        "content_hash": source.content_hash,
        "name": source.name,
        "url": source.url,
        "source_type": source.source_type,
    }


def _raw_item_snapshot(raw_item: RawItem) -> dict[str, Any]:
    return {
        "global_id": raw_item.global_id,
        "revision": raw_item.revision,
        "content_hash": raw_item.content_hash,
        "entry_key": raw_item.entry_key,
        "source_title": raw_item.source_title,
        "source_url": raw_item.source_url,
    }


def _news_item_snapshot(news_item: NewsItem) -> dict[str, Any]:
    return {
        "global_id": news_item.global_id,
        "revision": news_item.revision,
        "content_hash": news_item.content_hash,
        "dedupe_key": news_item.dedupe_key,
        "source_title": news_item.source_title,
        "source_url": news_item.source_url,
    }


def _generated_news_snapshot(generated: GeneratedNews) -> dict[str, Any]:
    return {
        "global_id": generated.global_id,
        "revision": generated.revision,
        "content_hash": generated.content_hash,
        "title": generated.title,
        "category": generated.category,
        "generation_status": generated.generation_status,
    }


def _report_snapshot(report: Any, *, key_field: str, key_value: str) -> dict[str, Any]:
    return {
        "global_id": report.global_id,
        "revision": report.revision,
        "content_hash": report.content_hash,
        key_field: key_value,
        "title": report.title,
        "status": report.status,
    }
