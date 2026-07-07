from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import AdapterRegistry, RawItemInput, SourceFetchContext, create_default_registry
from app.models.common import utc_now
from app.models.content import DataSource, RawItem


@dataclass(frozen=True)
class SourceFetchResult:
    data_source_id: str
    source_type: str
    fetched: int
    created: int
    updated: int


class SourceNotFoundError(ValueError):
    pass


class SourceFetchError(RuntimeError):
    pass


MAX_RAW_ENTRY_KEY_LENGTH = 255
RAW_ENTRY_KEY_HASH_LENGTH = 16


async def fetch_source_to_raw_items(
    session: Session,
    data_source_id: str,
    registry: AdapterRegistry | None = None,
    fetched_at: datetime | None = None,
) -> SourceFetchResult:
    data_source = session.get(DataSource, data_source_id)
    if data_source is None:
        raise SourceNotFoundError(f"Data source not found: {data_source_id}")

    fetched_at = fetched_at or utc_now()
    data_source.last_fetch_at = fetched_at

    try:
        raw_inputs = await fetch_source_raw_inputs(data_source, registry)
    except Exception as exc:
        data_source.last_error = _error_message(exc)
        session.flush()
        raise SourceFetchError(data_source.last_error) from exc

    created, updated = upsert_raw_inputs(session, data_source, raw_inputs, fetched_at)
    return SourceFetchResult(
        data_source_id=data_source.id,
        source_type=data_source.source_type,
        fetched=len(raw_inputs),
        created=created,
        updated=updated,
    )


async def fetch_source_raw_inputs(
    data_source: DataSource,
    registry: AdapterRegistry | None = None,
    context: SourceFetchContext | None = None,
) -> list[RawItemInput]:
    registry = registry or create_default_registry()
    adapter = registry.get(data_source.source_type)
    fetch_with_context = getattr(adapter, "fetch_with_context", None)
    if context is not None and callable(fetch_with_context):
        return await fetch_with_context(data_source, context)
    return await adapter.fetch(data_source)


def upsert_raw_inputs(
    session: Session,
    data_source: DataSource,
    raw_inputs: list[RawItemInput],
    fetched_at: datetime,
) -> tuple[int, int]:
    created = 0
    updated = 0
    # 同批内按规范化 entry_key 去重：真实列表页会把同一篇文章链接多次（如轮播位+列表位
    # 指向同一 URL）。_upsert_raw_item 的存在性检查只能看到已 flush 的行，批内重复会在
    # flush 时撞 uq_raw_items_source_entry。后出现者覆盖先出现者，与"同 entry_key 重抓
    # 刷新"的既有语义一致。
    deduped: dict[str, RawItemInput] = {}
    for raw_input in raw_inputs:
        deduped[normalize_raw_entry_key(raw_input.entry_key)] = raw_input
    for raw_input in deduped.values():
        if _upsert_raw_item(session, data_source, raw_input, fetched_at):
            created += 1
        else:
            updated += 1

    data_source.last_success_at = fetched_at
    data_source.last_error = ""
    session.flush()
    return created, updated


def _upsert_raw_item(
    session: Session,
    data_source: DataSource,
    raw_input: RawItemInput,
    fetched_at: datetime,
) -> bool:
    entry_key = normalize_raw_entry_key(raw_input.entry_key)
    raw_item = session.scalar(
        select(RawItem).where(
            RawItem.data_source_id == data_source.id,
            RawItem.entry_key == entry_key,
        ),
    )
    created = raw_item is None
    if raw_item is None:
        raw_item = RawItem(
            data_source=data_source,
            workspace_code=data_source.workspace_code,
            domain_code=data_source.domain_code,
            visibility_scope=data_source.visibility_scope,
            sync_policy=data_source.sync_policy,
            source_type=data_source.source_type,
            source_name=data_source.name,
            entry_key=entry_key,
            fetched_at=fetched_at,
        )
        session.add(raw_item)

    raw_item.source_type = data_source.source_type
    raw_item.source_name = data_source.name
    raw_item.source_title = raw_input.source_title
    raw_item.source_url = raw_input.source_url
    raw_item.raw_content = raw_input.raw_content
    raw_item.raw_payload_json = raw_input.raw_payload_json
    raw_item.published_at = raw_input.published_at
    raw_item.fetched_at = fetched_at
    return created


def normalize_raw_entry_key(entry_key: str) -> str:
    value = str(entry_key or "").strip()
    if len(value) <= MAX_RAW_ENTRY_KEY_LENGTH:
        return value
    digest = sha1(value.encode("utf-8")).hexdigest()[:RAW_ENTRY_KEY_HASH_LENGTH]
    prefix_length = MAX_RAW_ENTRY_KEY_LENGTH - RAW_ENTRY_KEY_HASH_LENGTH - 1
    return f"{value[:prefix_length]}#{digest}"


def _error_message(exc: Exception) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    return message[:1000]
