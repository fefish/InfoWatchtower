from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import AdapterRegistry, RawItemInput, create_default_registry
from app.adapters.page import _extract_links, _fetch_article
from app.ingestion.fetch import fetch_source_raw_inputs, upsert_raw_inputs
from app.models.common import utc_now
from app.models.content import DataSource, IngestionRun
from app.models.workspace import Workspace, WorkspaceSourceLink

DEFAULT_INGESTION_SOURCE_TYPES = [
    "rss",
    "paper_rss",
    "page_manual",
    "page_monitor",
    "wiseflow",
]
DEFAULT_BACKFILL_SOURCE_TYPES = ["rss", "paper_rss"]
DEFAULT_INGESTION_CONCURRENCY = 8
DEFAULT_SOURCE_TIMEOUT_SECONDS = 25.0
SUPPORTED_BACKFILL_MODES = {"rss_window", "paper_api", "archive_page", "sitemap", "manual_import"}


@dataclass(frozen=True)
class WorkspaceIngestionRequest:
    workspace_code: str
    source_types: list[str]
    limit: int | None = None
    concurrency: int = DEFAULT_INGESTION_CONCURRENCY
    source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS


@dataclass(frozen=True)
class HistoricalBackfillRequest:
    workspace_code: str
    target_day_start: str
    target_day_end: str
    source_types: list[str]
    limit: int | None = None
    concurrency: int = DEFAULT_INGESTION_CONCURRENCY
    source_timeout_seconds: float = DEFAULT_SOURCE_TIMEOUT_SECONDS
    backfill_mode: str = "rss_window"
    source_scope: str = "source_type"
    retry_policy: str = "manual_run_no_retry"
    include_undated: bool = False
    manual_items: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class SourceFetchOutcome:
    source: DataSource
    raw_inputs: list[RawItemInput]
    error: str = ""


class WorkspaceNotFoundError(ValueError):
    pass


class InvalidBackfillRangeError(ValueError):
    pass


async def run_workspace_ingestion(
    session: Session,
    request: WorkspaceIngestionRequest,
    registry: AdapterRegistry | None = None,
    started_at: datetime | None = None,
) -> IngestionRun:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == request.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {request.workspace_code}")

    started_at = started_at or utc_now()
    source_types = _normalize_source_types(request.source_types)
    sources = _workspace_sources(
        session=session,
        workspace=workspace,
        source_types=source_types,
        limit=request.limit,
    )
    registry = registry or create_default_registry()

    run = IngestionRun(
        run_key=_run_key(workspace.code, started_at),
        workspace_code=workspace.code,
        domain_code=workspace.default_domain_code,
        run_type="workspace_fetch",
        status="running",
        started_at=started_at,
        params_json={
            "workspace_code": workspace.code,
            "source_types": source_types,
            "limit": request.limit,
            "concurrency": _normalize_concurrency(request.concurrency),
            "source_timeout_seconds": _normalize_timeout(request.source_timeout_seconds),
        },
    )
    session.add(run)
    session.flush()

    source_summaries = []
    totals = {
        "source_succeeded": 0,
        "source_failed": 0,
        "items_fetched": 0,
        "raw_created": 0,
        "raw_updated": 0,
    }
    outcomes = await _fetch_sources_concurrently(
        sources=sources,
        registry=registry,
        concurrency=_normalize_concurrency(request.concurrency),
        source_timeout_seconds=_normalize_timeout(request.source_timeout_seconds),
    )
    for outcome in outcomes:
        source = outcome.source
        source.last_fetch_at = started_at
        if outcome.error:
            source.last_error = outcome.error
            totals["source_failed"] += 1
            source_summaries.append(
                {
                    "data_source_id": source.id,
                    "name": source.name,
                    "source_type": source.source_type,
                    "status": "failed",
                    "error": outcome.error,
                    "fetched": 0,
                    "created": 0,
                    "updated": 0,
                },
            )
            continue

        created, updated = upsert_raw_inputs(session, source, outcome.raw_inputs, started_at)
        totals["source_succeeded"] += 1
        totals["items_fetched"] += len(outcome.raw_inputs)
        totals["raw_created"] += created
        totals["raw_updated"] += updated
        source_summaries.append(
            {
                "data_source_id": source.id,
                "name": source.name,
                "source_type": source.source_type,
                "status": "completed",
                "fetched": len(outcome.raw_inputs),
                "created": created,
                "updated": updated,
            },
        )

    run.source_total = len(sources)
    run.source_succeeded = totals["source_succeeded"]
    run.source_failed = totals["source_failed"]
    run.items_fetched = totals["items_fetched"]
    run.raw_created = totals["raw_created"]
    run.raw_updated = totals["raw_updated"]
    run.status = _run_status(run.source_total, run.source_succeeded, run.source_failed)
    run.completed_at = utc_now()
    run.summary_json = {
        "sources": source_summaries,
        "source_types": source_types,
    }
    session.flush()
    return run


async def run_historical_backfill(
    session: Session,
    request: HistoricalBackfillRequest,
    registry: AdapterRegistry | None = None,
    started_at: datetime | None = None,
) -> IngestionRun:
    workspace = session.scalar(
        select(Workspace).where(
            Workspace.code == request.workspace_code,
            Workspace.enabled.is_(True),
        ),
    )
    if workspace is None:
        raise WorkspaceNotFoundError(f"Workspace not found: {request.workspace_code}")

    target_day_start = _parse_day_key(request.target_day_start, "target_day_start")
    target_day_end = _parse_day_key(request.target_day_end, "target_day_end")
    if target_day_end < target_day_start:
        raise InvalidBackfillRangeError(
            "target_day_end must be greater than or equal to target_day_start",
        )

    started_at = started_at or utc_now()
    source_types = _normalize_source_types(request.source_types)
    concurrency = _normalize_concurrency(request.concurrency)
    source_timeout_seconds = _normalize_timeout(request.source_timeout_seconds)
    sources = _workspace_sources(
        session=session,
        workspace=workspace,
        source_types=source_types,
        limit=request.limit,
    )
    registry = registry or create_default_registry()
    backfill_mode = _normalize_backfill_mode(request.backfill_mode)

    run = IngestionRun(
        run_key=_backfill_run_key(
            workspace.code,
            request.target_day_start,
            request.target_day_end,
            started_at,
        ),
        workspace_code=workspace.code,
        domain_code=workspace.default_domain_code,
        run_type="historical_backfill",
        status="running",
        started_at=started_at,
        params_json={
            "workspace_code": workspace.code,
            "target_day_start": request.target_day_start,
            "target_day_end": request.target_day_end,
            "source_types": source_types,
            "limit": request.limit,
            "concurrency": concurrency,
            "source_timeout_seconds": source_timeout_seconds,
            "backfill_mode": backfill_mode,
            "source_scope": request.source_scope,
            "retry_policy": request.retry_policy,
            "include_undated": request.include_undated,
            "manual_items": len(request.manual_items or []),
        },
    )
    session.add(run)
    session.flush()

    source_summaries = []
    totals = {
        "source_succeeded": 0,
        "source_failed": 0,
        "items_fetched": 0,
        "items_in_target_range": 0,
        "items_out_of_target_range": 0,
        "items_missing_published_at": 0,
        "raw_created": 0,
        "raw_updated": 0,
    }
    outcomes = await _fetch_backfill_sources(
        sources=sources,
        registry=registry,
        concurrency=concurrency,
        source_timeout_seconds=source_timeout_seconds,
        backfill_mode=backfill_mode,
        manual_items=request.manual_items or [],
    )
    for outcome in outcomes:
        source = outcome.source
        source.last_fetch_at = started_at
        if outcome.error:
            source.last_error = outcome.error
            totals["source_failed"] += 1
            source_summaries.append(
                {
                    "data_source_id": source.id,
                    "name": source.name,
                    "source_type": source.source_type,
                    "status": "failed",
                    "error": outcome.error,
                    "fetched": 0,
                    "in_target_range": 0,
                    "out_of_target_range": 0,
                    "missing_published_at": 0,
                    "created": 0,
                    "updated": 0,
                },
            )
            continue

        filtered_inputs, date_stats = _filter_backfill_inputs(
            outcome.raw_inputs,
            target_day_start=target_day_start,
            target_day_end=target_day_end,
            include_undated=request.include_undated,
        )
        created, updated = upsert_raw_inputs(session, source, filtered_inputs, started_at)
        totals["source_succeeded"] += 1
        totals["items_fetched"] += len(outcome.raw_inputs)
        totals["items_in_target_range"] += date_stats["in_target_range"]
        totals["items_out_of_target_range"] += date_stats["out_of_target_range"]
        totals["items_missing_published_at"] += date_stats["missing_published_at"]
        totals["raw_created"] += created
        totals["raw_updated"] += updated
        source_summaries.append(
            {
                "data_source_id": source.id,
                "name": source.name,
                "source_type": source.source_type,
                "status": "completed",
                "fetched": len(outcome.raw_inputs),
                "in_target_range": date_stats["in_target_range"],
                "out_of_target_range": date_stats["out_of_target_range"],
                "missing_published_at": date_stats["missing_published_at"],
                "created": created,
                "updated": updated,
            },
        )

    run.source_total = len(sources)
    run.source_succeeded = totals["source_succeeded"]
    run.source_failed = totals["source_failed"]
    run.items_fetched = totals["items_fetched"]
    run.raw_created = totals["raw_created"]
    run.raw_updated = totals["raw_updated"]
    run.status = _run_status(run.source_total, run.source_succeeded, run.source_failed)
    run.completed_at = utc_now()
    run.summary_json = {
        "sources": source_summaries,
        "source_types": source_types,
        "target_day_start": request.target_day_start,
        "target_day_end": request.target_day_end,
        "backfill_mode": backfill_mode,
        "source_scope": request.source_scope,
        "retry_policy": request.retry_policy,
        "include_undated": request.include_undated,
        "items_in_target_range": totals["items_in_target_range"],
        "items_out_of_target_range": totals["items_out_of_target_range"],
        "items_missing_published_at": totals["items_missing_published_at"],
    }
    session.flush()
    return run


async def _fetch_sources_concurrently(
    *,
    sources: list[DataSource],
    registry: AdapterRegistry,
    concurrency: int,
    source_timeout_seconds: float,
) -> list[SourceFetchOutcome]:
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(source: DataSource) -> SourceFetchOutcome:
        async with semaphore:
            try:
                raw_inputs = await asyncio.wait_for(
                    fetch_source_raw_inputs(source, registry),
                    timeout=source_timeout_seconds,
                )
            except Exception as exc:
                return SourceFetchOutcome(source=source, raw_inputs=[], error=_fetch_error(exc))
            return SourceFetchOutcome(source=source, raw_inputs=raw_inputs)

    if not sources:
        return []
    return list(await asyncio.gather(*(fetch_one(source) for source in sources)))


async def _fetch_backfill_sources(
    *,
    sources: list[DataSource],
    registry: AdapterRegistry,
    concurrency: int,
    source_timeout_seconds: float,
    backfill_mode: str,
    manual_items: list[dict[str, Any]],
) -> list[SourceFetchOutcome]:
    if backfill_mode == "manual_import":
        return _manual_import_outcomes(sources=sources, manual_items=manual_items)
    if backfill_mode == "sitemap":
        return await _fetch_sitemap_sources_concurrently(
            sources=sources,
            concurrency=concurrency,
            source_timeout_seconds=source_timeout_seconds,
        )
    if backfill_mode == "archive_page":
        return await _fetch_archive_sources_concurrently(
            sources=sources,
            concurrency=concurrency,
            source_timeout_seconds=source_timeout_seconds,
        )
    return await _fetch_sources_concurrently(
        sources=sources,
        registry=registry,
        concurrency=concurrency,
        source_timeout_seconds=source_timeout_seconds,
    )


async def _fetch_sitemap_sources_concurrently(
    *,
    sources: list[DataSource],
    concurrency: int,
    source_timeout_seconds: float,
) -> list[SourceFetchOutcome]:
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(source: DataSource) -> SourceFetchOutcome:
        async with semaphore:
            try:
                raw_inputs = await asyncio.wait_for(
                    _fetch_sitemap_source(source),
                    timeout=source_timeout_seconds,
                )
            except Exception as exc:
                return SourceFetchOutcome(source=source, raw_inputs=[], error=_fetch_error(exc))
            return SourceFetchOutcome(source=source, raw_inputs=raw_inputs)

    if not sources:
        return []
    return list(await asyncio.gather(*(fetch_one(source) for source in sources)))


async def _fetch_archive_sources_concurrently(
    *,
    sources: list[DataSource],
    concurrency: int,
    source_timeout_seconds: float,
) -> list[SourceFetchOutcome]:
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(source: DataSource) -> SourceFetchOutcome:
        async with semaphore:
            try:
                raw_inputs = await asyncio.wait_for(
                    _fetch_archive_source(source),
                    timeout=source_timeout_seconds,
                )
            except Exception as exc:
                return SourceFetchOutcome(source=source, raw_inputs=[], error=_fetch_error(exc))
            return SourceFetchOutcome(source=source, raw_inputs=raw_inputs)

    if not sources:
        return []
    return list(await asyncio.gather(*(fetch_one(source) for source in sources)))


async def _fetch_sitemap_source(source: DataSource) -> list[RawItemInput]:
    config = source.fetch_config or {}
    sitemap_url = str(config.get("sitemap_url") or source.url or "").strip()
    if not sitemap_url:
        return []
    max_links = int(config.get("max_links") or config.get("sitemap_max_links") or 100)
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, trust_env=False) as client:
        response = await client.get(sitemap_url)
        response.raise_for_status()
    entries = _parse_sitemap_entries(response.text)[:max(0, max_links)]
    return [
        RawItemInput(
            entry_key=entry["loc"],
            source_title=_title_from_url(entry["loc"]),
            source_url=entry["loc"],
            raw_content=entry["loc"],
            published_at=_parse_optional_datetime(entry.get("lastmod")),
            raw_payload_json={
                "backfill_mode": "sitemap",
                "sitemap_url": sitemap_url,
                "loc": entry["loc"],
                "lastmod": entry.get("lastmod") or "",
            },
        )
        for entry in entries
        if entry.get("loc")
    ]


async def _fetch_archive_source(source: DataSource) -> list[RawItemInput]:
    config = source.fetch_config or {}
    archive_url = str(config.get("archive_url") or config.get("page_url") or source.url or "").strip()
    if not archive_url:
        return []
    max_links = int(config.get("max_links") or 20)
    href_contains = list(config.get("href_contains") or [])
    exclude_exact = set(config.get("exclude_exact") or [])
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, trust_env=False) as client:
        response = await client.get(archive_url)
        response.raise_for_status()
        links = _extract_links(
            html=response.text,
            base_url=str(response.url),
            href_contains=href_contains,
            exclude_exact=exclude_exact,
            max_links=max_links,
        )
        return [await _fetch_article(client, url, title_hint=title) for url, title in links]


def _manual_import_outcomes(
    *,
    sources: list[DataSource],
    manual_items: list[dict[str, Any]],
) -> list[SourceFetchOutcome]:
    source_by_id = {source.id: source for source in sources}
    grouped: dict[str, list[RawItemInput]] = {source.id: [] for source in sources}
    errors: dict[str, str] = {}
    for raw in manual_items:
        source_id = str(raw.get("data_source_id") or "").strip()
        source = source_by_id.get(source_id)
        if source is None:
            errors[source_id or "unknown"] = "manual_import item missing enabled data_source_id"
            continue
        source_url = str(raw.get("source_url") or raw.get("url") or "").strip() or None
        source_title = str(raw.get("source_title") or raw.get("title") or source_url or "手工补采条目")
        raw_content = str(raw.get("raw_content") or raw.get("content") or raw.get("summary") or source_title)
        entry_key = str(raw.get("entry_key") or source_url or source_title)
        grouped[source.id].append(
            RawItemInput(
                entry_key=entry_key,
                source_title=source_title,
                source_url=source_url,
                raw_content=raw_content,
                published_at=_parse_optional_datetime(raw.get("published_at")),
                raw_payload_json={
                    "backfill_mode": "manual_import",
                    "payload": raw,
                },
            ),
        )

    outcomes = [
        SourceFetchOutcome(source=source, raw_inputs=grouped.get(source.id, []))
        for source in sources
    ]
    if errors and not outcomes:
        return []
    return outcomes


def _workspace_sources(
    session: Session,
    workspace: Workspace,
    source_types: list[str],
    limit: int | None,
) -> list[DataSource]:
    statement = (
        select(DataSource)
        .join(WorkspaceSourceLink, WorkspaceSourceLink.data_source_id == DataSource.id)
        .where(
            WorkspaceSourceLink.workspace_id == workspace.id,
            WorkspaceSourceLink.enabled.is_(True),
            DataSource.enabled.is_(True),
        )
        .order_by(DataSource.source_type, DataSource.name)
    )
    if source_types:
        statement = statement.where(DataSource.source_type.in_(source_types))
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement).all())


def _normalize_source_types(source_types: list[str]) -> list[str]:
    normalized: list[str] = []
    for source_type in source_types or DEFAULT_INGESTION_SOURCE_TYPES:
        value = source_type.strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized or list(DEFAULT_INGESTION_SOURCE_TYPES)


def _normalize_backfill_mode(value: str) -> str:
    normalized = (value or "rss_window").strip()
    if normalized not in SUPPORTED_BACKFILL_MODES:
        raise InvalidBackfillRangeError(
            f"backfill_mode must be one of: {', '.join(sorted(SUPPORTED_BACKFILL_MODES))}",
        )
    return normalized


def _normalize_concurrency(value: int) -> int:
    return min(max(int(value or DEFAULT_INGESTION_CONCURRENCY), 1), 32)


def _normalize_timeout(value: float) -> float:
    return min(max(float(value or DEFAULT_SOURCE_TIMEOUT_SECONDS), 3.0), 120.0)


def _parse_day_key(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidBackfillRangeError(f"{field_name} must use YYYY-MM-DD format") from exc


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re_match := _parse_iso_date_prefix(text):
        return re_match
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_iso_date_prefix(value: str) -> datetime | None:
    if len(value) == 10:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC)
    return None


def _parse_sitemap_entries(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text.encode("utf-8"))
    entries: list[dict[str, str]] = []
    for url_node in root.iter():
        if _strip_namespace(url_node.tag) != "url":
            continue
        entry = {"loc": "", "lastmod": ""}
        for child in list(url_node):
            tag = _strip_namespace(child.tag)
            if tag in entry:
                entry[tag] = (child.text or "").strip()
        if entry["loc"]:
            entries.append(entry)
    return entries


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _title_from_url(url: str) -> str:
    path = PurePosixPath(urlparse(url).path)
    candidate = path.stem or path.name or url
    return candidate.replace("-", " ").replace("_", " ").strip() or url


def _filter_backfill_inputs(
    raw_inputs: list[RawItemInput],
    *,
    target_day_start: date,
    target_day_end: date,
    include_undated: bool,
) -> tuple[list[RawItemInput], dict[str, int]]:
    filtered: list[RawItemInput] = []
    stats = {
        "in_target_range": 0,
        "out_of_target_range": 0,
        "missing_published_at": 0,
    }
    for raw_input in raw_inputs:
        item_day = _published_day(raw_input.published_at)
        if item_day is None:
            stats["missing_published_at"] += 1
            if include_undated:
                filtered.append(raw_input)
            continue
        if target_day_start <= item_day <= target_day_end:
            stats["in_target_range"] += 1
            filtered.append(raw_input)
        else:
            stats["out_of_target_range"] += 1
    return filtered, stats


def _published_day(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(UTC).date()


def _fetch_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        message = "TimeoutError: source fetch exceeded timeout"
    else:
        message = f"{exc.__class__.__name__}: {exc}"
    return message[:1000]


def _run_key(workspace_code: str, started_at: datetime) -> str:
    compact_time = started_at.strftime("%Y%m%d%H%M%S%f")
    return f"{workspace_code}:ingestion:{compact_time}"


def _backfill_run_key(
    workspace_code: str,
    target_day_start: str,
    target_day_end: str,
    started_at: datetime,
) -> str:
    compact_time = started_at.strftime("%Y%m%d%H%M%S%f")
    return f"{workspace_code}:backfill:{target_day_start}:{target_day_end}:{compact_time}"


def _run_status(source_total: int, source_succeeded: int, source_failed: int) -> str:
    if source_total == 0:
        return "completed"
    if source_failed == 0:
        return "completed"
    if source_succeeded > 0:
        return "partial"
    return "failed"
