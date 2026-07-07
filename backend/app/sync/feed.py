"""feed 下发（publisher 侧，业务表水位直查，docs/deployment/deployment-topology.md §3.3）。

不给主管线补 outbox 生产者：直接按 (updated_at, id) keyset 分页查询业务表，
同一 cursor 重复请求返回相同结果（无副作用、可重放）。
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.common import utc_now
from app.models.content import DataSource, GeneratedNews, NewsItem, RawItem
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.sync.records import (
    EXPORTABLE_SYNC_POLICIES,
    PAYLOAD_BUILDERS,
    SYNC_FEED_OBJECT_TYPES,
    contains_secret_key,
    feed_envelope,
)

DEFAULT_FEED_LIMIT = 200
MAX_FEED_LIMIT = 500

_FEED_MODELS = {
    "data_sources": DataSource,
    "raw_items": RawItem,
    "news_items": NewsItem,
    "generated_news": GeneratedNews,
    "daily_reports": DailyReport,
    "weekly_reports": WeeklyReport,
}

_FEED_LOAD_OPTIONS = {
    "raw_items": (selectinload(RawItem.data_source),),
    "news_items": (selectinload(NewsItem.raw_item), selectinload(NewsItem.data_source)),
    "generated_news": (selectinload(GeneratedNews.news_item),),
    "daily_reports": (
        selectinload(DailyReport.items).selectinload(DailyReportItem.generated_news),
    ),
    "weekly_reports": (
        selectinload(WeeklyReport.items).selectinload(WeeklyReportItem.generated_news),
        selectinload(WeeklyReport.items).selectinload(WeeklyReportItem.daily_report_item),
    ),
}


class InvalidFeedCursorError(ValueError):
    pass


class UnknownFeedObjectTypeError(ValueError):
    pass


@dataclass(frozen=True)
class FeedPage:
    object_type: str
    records: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool


def encode_cursor(updated_at: datetime, object_id: str) -> str:
    raw = f"{updated_at.isoformat()}|{object_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        updated_at_iso, _, object_id = raw.partition("|")
        updated_at = datetime.fromisoformat(updated_at_iso)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidFeedCursorError(f"invalid feed cursor: {cursor!r}") from exc
    if not object_id:
        raise InvalidFeedCursorError(f"invalid feed cursor: {cursor!r}")
    return updated_at, object_id


def _feed_model(object_type: str):
    model = _FEED_MODELS.get(object_type)
    if model is None:
        raise UnknownFeedObjectTypeError(
            f"object_type must be one of {', '.join(SYNC_FEED_OBJECT_TYPES)}; got {object_type!r}",
        )
    return model


def feed_page(
    session: Session,
    object_type: str,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_FEED_LIMIT,
) -> FeedPage:
    model = _feed_model(object_type)
    limit = max(1, min(int(limit or DEFAULT_FEED_LIMIT), MAX_FEED_LIMIT))

    statement = (
        select(model)
        .where(
            model.visibility_scope != "restricted",
            model.sync_policy.in_(EXPORTABLE_SYNC_POLICIES),
        )
        .order_by(model.updated_at, model.id)
        .limit(limit)
    )
    for option in _FEED_LOAD_OPTIONS.get(object_type, ()):
        statement = statement.options(option)
    if cursor:
        # 严格大于的 keyset 过滤本身有并发边界：updated_at 在 flush 时生成、
        # commit 后才可见，长事务晚提交的行会落在已下发的游标之前。
        # publisher 侧保持无状态可重放，不在这里加窗口；由 consumer 侧
        # （app/sync/pull.py 的回看窗口重放 + inbox event_id 幂等）补偿漏发。
        after_updated_at, after_id = decode_cursor(cursor)
        statement = statement.where(
            or_(
                model.updated_at > after_updated_at,
                and_(model.updated_at == after_updated_at, model.id > after_id),
            ),
        )

    rows = list(session.scalars(statement).all())
    build_payload = PAYLOAD_BUILDERS[object_type]
    records: list[dict[str, Any]] = []
    for row in rows:
        payload = build_payload(row)
        # 密钥红线：含 secret/token/password/cookie/.env 的 payload 不下发（游标照常前进）
        if contains_secret_key(payload):
            continue
        records.append(feed_envelope(object_type, row, payload))

    has_more = len(rows) == limit
    next_cursor = encode_cursor(rows[-1].updated_at, rows[-1].id) if rows else None
    return FeedPage(object_type=object_type, records=records, next_cursor=next_cursor, has_more=has_more)


def feed_manifest(session: Session, instance_id: str) -> dict[str, Any]:
    watermarks: dict[str, str | None] = {}
    for object_type in SYNC_FEED_OBJECT_TYPES:
        model = _FEED_MODELS[object_type]
        watermark = session.scalar(
            select(func.max(model.updated_at)).where(
                model.visibility_scope != "restricted",
                model.sync_policy.in_(EXPORTABLE_SYNC_POLICIES),
            ),
        )
        watermarks[object_type] = watermark.isoformat() if watermark is not None else None
    return {
        "instance_id": instance_id,
        "object_types": list(SYNC_FEED_OBJECT_TYPES),
        "watermarks": watermarks,
        "server_time": utc_now().isoformat(),
    }
