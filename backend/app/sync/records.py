"""同步记录（envelope/payload）构造与通用值处理。

envelope 与手工同步包 records.jsonl 同构（config/contracts/sync_strategy.json
required_envelope_fields）；payload 字段集合与 apply 侧读取的键一一对应。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.models.content import DataSource, GeneratedNews, NewsItem, RawItem
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.core.privacy import contains_secret_like_key

# 外键依赖决定的应用顺序（docs/deployment/deployment-topology.md §3.4），consumer 必须按序拉取
SYNC_FEED_OBJECT_TYPES: tuple[str, ...] = (
    "data_sources",
    "raw_items",
    "news_items",
    "generated_news",
    "daily_reports",
    "weekly_reports",
)

EXPORTABLE_SYNC_POLICIES = {"public_to_intranet", "manual_only", "two_way_config"}


def sort_records_by_dependency(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 SYNC_FEED_OBJECT_TYPES 的外键依赖序稳定排序一批 envelope 记录。

    api_pull 通道天然按类型顺序拉取；手工包/重放通道的记录可能乱序，先排序
    可以让依赖对象先落库，一轮 apply 即净，而不是 failed 后等 retry 多轮收敛。
    未知 object_type 保持原相对顺序排在最后（apply 侧会显式判 failed）。
    """
    order = {object_type: index for index, object_type in enumerate(SYNC_FEED_OBJECT_TYPES)}
    return sorted(
        records,
        key=lambda record: order.get(str(record.get("object_type") or ""), len(order)),
    )


def hash_json(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def deterministic_event_id(object_type: str, global_id: str, revision: int) -> str:
    """同一对象同一版本重放幂等、新版本产生新 event_id（规格 §3.3）。"""
    return hashlib.sha256(f"{object_type}|{global_id}|{revision}".encode()).hexdigest()


def contains_secret_key(value: Any) -> bool:
    return contains_secret_like_key(value)


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _scope_fields(obj: Any) -> dict[str, Any]:
    return {
        "global_id": obj.global_id,
        "origin_instance_id": obj.origin_instance_id,
        "revision": obj.revision,
        "content_hash": obj.content_hash,
        "workspace_code": obj.workspace_code,
        "domain_code": obj.domain_code,
        "visibility_scope": obj.visibility_scope,
        "sync_policy": obj.sync_policy,
    }


def data_source_payload(source: DataSource) -> dict[str, Any]:
    return {
        **_scope_fields(source),
        "source_type": source.source_type,
        "name": source.name,
        "url": source.url,
        "enabled": source.enabled,
        "default_focus_id": source.default_focus_id,
        "backfill_days": source.backfill_days,
        "credential_ref": source.credential_ref,
        "fetch_config": source.fetch_config or {},
        "paper_config": source.paper_config or {},
        "metadata_json": source.metadata_json or {},
        "last_fetch_at": _iso(source.last_fetch_at),
        "last_success_at": _iso(source.last_success_at),
        "last_error": source.last_error or "",
        "source_score": source.source_score,
        "updated_at": _iso(source.updated_at),
    }


def raw_item_payload(raw_item: RawItem) -> dict[str, Any]:
    return {
        **_scope_fields(raw_item),
        "data_source_global_id": raw_item.data_source.global_id if raw_item.data_source else None,
        "source_type": raw_item.source_type,
        "source_name": raw_item.source_name,
        "entry_key": raw_item.entry_key,
        "source_title": raw_item.source_title,
        "source_url": raw_item.source_url,
        "raw_content": raw_item.raw_content or "",
        "fetched_at": _iso(raw_item.fetched_at),
        "published_at": _iso(raw_item.published_at),
        "raw_payload_json": raw_item.raw_payload_json or {},
        "updated_at": _iso(raw_item.updated_at),
    }


def news_item_payload(news_item: NewsItem) -> dict[str, Any]:
    return {
        **_scope_fields(news_item),
        "raw_item_global_id": news_item.raw_item.global_id if news_item.raw_item else None,
        "data_source_global_id": news_item.data_source.global_id if news_item.data_source else None,
        "source_type": news_item.source_type,
        "source_name": news_item.source_name,
        "source_url": news_item.source_url,
        "canonical_url": news_item.canonical_url,
        "source_title": news_item.source_title,
        "normalized_title": news_item.normalized_title,
        "summary": news_item.summary or "",
        "content": news_item.content or "",
        "author": news_item.author or "",
        "published_at": _iso(news_item.published_at),
        "focus_id": news_item.focus_id,
        "dedupe_key": news_item.dedupe_key,
        "active": news_item.active,
        "normalization_status": news_item.normalization_status,
        "normalization_notes": news_item.normalization_notes or "",
        "updated_at": _iso(news_item.updated_at),
    }


def generated_news_payload(generated: GeneratedNews) -> dict[str, Any]:
    # recommendation 链不下发：intranet 消费成稿，不复算推荐
    return {
        **_scope_fields(generated),
        "news_item_global_id": generated.news_item.global_id if generated.news_item else None,
        "category": generated.category,
        "title": generated.title,
        "summary": generated.summary or "",
        "key_points": generated.key_points or "",
        "content_json": generated.content_json or {},
        "insight_json": generated.insight_json or {},
        "source_url": generated.source_url,
        "generated_by": generated.generated_by,
        "generation_status": generated.generation_status,
        "updated_at": _iso(generated.updated_at),
    }


def _daily_report_item_payload(item: DailyReportItem) -> dict[str, Any]:
    return {
        **_scope_fields(item),
        "generated_news_global_id": item.generated_news.global_id if item.generated_news else None,
        "adoption_status": item.adoption_status,
        "is_headline": item.is_headline,
        "sort_order": item.sort_order,
        "editor_title": item.editor_title,
        "editor_summary": item.editor_summary,
        "editor_key_points": item.editor_key_points,
        "editor_content_json": item.editor_content_json,
        "editor_notes": item.editor_notes or "",
    }


def daily_report_payload(report: DailyReport) -> dict[str, Any]:
    items = sorted(report.items, key=lambda item: (item.sort_order, item.id))
    return {
        **_scope_fields(report),
        "day_key": report.day_key,
        "title": report.title,
        "summary": report.summary or "",
        "status": report.status,
        "published_at": _iso(report.published_at),
        "items": [_daily_report_item_payload(item) for item in items],
        "updated_at": _iso(report.updated_at),
    }


def _weekly_report_item_payload(item: WeeklyReportItem) -> dict[str, Any]:
    return {
        **_scope_fields(item),
        "daily_report_item_global_id": (
            item.daily_report_item.global_id if item.daily_report_item else None
        ),
        "generated_news_global_id": item.generated_news.global_id if item.generated_news else None,
        "adoption_status": item.adoption_status,
        "sort_order": item.sort_order,
        "editor_title": item.editor_title,
        "editor_summary": item.editor_summary,
        "editor_content_json": item.editor_content_json,
    }


def weekly_report_payload(report: WeeklyReport) -> dict[str, Any]:
    items = sorted(report.items, key=lambda item: (item.sort_order, item.id))
    return {
        **_scope_fields(report),
        "week_key": report.week_key,
        "title": report.title,
        "summary": report.summary or "",
        "status": report.status,
        "published_at": _iso(report.published_at),
        "items": [_weekly_report_item_payload(item) for item in items],
        "updated_at": _iso(report.updated_at),
    }


PAYLOAD_BUILDERS = {
    "data_sources": data_source_payload,
    "raw_items": raw_item_payload,
    "news_items": news_item_payload,
    "generated_news": generated_news_payload,
    "daily_reports": daily_report_payload,
    "weekly_reports": weekly_report_payload,
}


def feed_envelope(object_type: str, obj: Any, payload: dict[str, Any]) -> dict[str, Any]:
    revision = int(obj.revision or 1)
    return {
        "event_id": deterministic_event_id(object_type, obj.global_id, revision),
        "object_type": object_type,
        "object_id": obj.id,
        "object_global_id": obj.global_id,
        "operation": "upsert",
        "revision": revision,
        "content_hash": obj.content_hash or hash_json(payload),
        "visibility_scope": obj.visibility_scope,
        "sync_policy": obj.sync_policy,
        "workspace_code": obj.workspace_code,
        "domain_code": obj.domain_code,
        "payload": payload,
    }
