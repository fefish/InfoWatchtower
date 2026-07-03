from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.fetch import normalize_raw_entry_key
from app.models.common import utc_now
from app.models.content import DataSource, RawItem
from app.models.legacy import (
    EntityMilestone,
    HistoricalFeedbackItem,
    HistoricalJobRun,
    HistoricalReport,
    TrackedEntity,
)

LEGACY_SYSTEM = "tech_insight_loop"
LEGACY_ARTICLE_TABLE = "articles"
LEGACY_REPORT_TABLE = "reports"
LEGACY_ENTITY_TABLE = "ai_entities"
LEGACY_MILESTONE_TABLE = "entity_milestones"
LEGACY_FEEDBACK_TABLE = "feedback"
LEGACY_QUALITY_FEEDBACK_TABLE = "article_quality_feedback"
LEGACY_JOB_TABLE = "jobs"
LEGACY_SOURCE_TYPE = "legacy_tech_insight_loop"
LEGACY_ARCHIVE_SOURCE_NAME = "Tech Insight Loop Legacy Archive"
LEGACY_WORKSPACE_CODE = "legacy_tech_insight_loop"
NUL_TEXT_REPLACEMENT = "\\u0000"
SUPPORTED_REPORT_TYPES = {"daily", "weekly"}


@dataclass(frozen=True)
class LegacyImportRequest:
    sqlite_path: Path
    workspace_code: str = LEGACY_WORKSPACE_CODE
    domain_code: str = "ai"
    article_limit: int | None = None
    report_limit: int | None = None


@dataclass(frozen=True)
class LegacyImportResult:
    articles_total: int
    articles_created: int
    articles_updated: int
    articles_skipped: int
    reports_total: int
    reports_created: int
    reports_updated: int
    reports_skipped: int
    report_refs_total: int
    report_refs_resolved: int
    report_refs_unresolved: int

    def to_dict(self) -> dict[str, int]:
        return {
            "articles_total": self.articles_total,
            "articles_created": self.articles_created,
            "articles_updated": self.articles_updated,
            "articles_skipped": self.articles_skipped,
            "reports_total": self.reports_total,
            "reports_created": self.reports_created,
            "reports_updated": self.reports_updated,
            "reports_skipped": self.reports_skipped,
            "report_refs_total": self.report_refs_total,
            "report_refs_resolved": self.report_refs_resolved,
            "report_refs_unresolved": self.report_refs_unresolved,
        }


@dataclass(frozen=True)
class EntityImportRequest:
    sqlite_path: Path
    workspace_code: str = LEGACY_WORKSPACE_CODE
    domain_code: str = "ai"
    entity_limit: int | None = None
    milestone_limit: int | None = None


@dataclass(frozen=True)
class EntityImportResult:
    entities_total: int
    entities_created: int
    entities_updated: int
    entities_skipped: int
    milestones_total: int
    milestones_created: int
    milestones_updated: int
    milestones_skipped: int
    article_refs_total: int
    article_refs_resolved: int
    article_refs_unresolved: int
    report_refs_total: int
    report_refs_resolved: int
    report_refs_unresolved: int

    def to_dict(self) -> dict[str, int]:
        return {
            "entities_total": self.entities_total,
            "entities_created": self.entities_created,
            "entities_updated": self.entities_updated,
            "entities_skipped": self.entities_skipped,
            "milestones_total": self.milestones_total,
            "milestones_created": self.milestones_created,
            "milestones_updated": self.milestones_updated,
            "milestones_skipped": self.milestones_skipped,
            "article_refs_total": self.article_refs_total,
            "article_refs_resolved": self.article_refs_resolved,
            "article_refs_unresolved": self.article_refs_unresolved,
            "report_refs_total": self.report_refs_total,
            "report_refs_resolved": self.report_refs_resolved,
            "report_refs_unresolved": self.report_refs_unresolved,
        }


@dataclass(frozen=True)
class QualityArchiveImportRequest:
    sqlite_path: Path
    workspace_code: str = LEGACY_WORKSPACE_CODE
    domain_code: str = "ai"
    feedback_limit: int | None = None
    quality_feedback_limit: int | None = None
    job_limit: int | None = None


@dataclass(frozen=True)
class QualityArchiveImportResult:
    feedback_total: int
    feedback_created: int
    feedback_updated: int
    feedback_skipped: int
    quality_feedback_total: int
    quality_feedback_created: int
    quality_feedback_updated: int
    quality_feedback_skipped: int
    feedback_article_refs_total: int
    feedback_article_refs_resolved: int
    feedback_article_refs_unresolved: int
    jobs_total: int
    jobs_created: int
    jobs_updated: int
    jobs_skipped: int

    def to_dict(self) -> dict[str, int]:
        return {
            "feedback_total": self.feedback_total,
            "feedback_created": self.feedback_created,
            "feedback_updated": self.feedback_updated,
            "feedback_skipped": self.feedback_skipped,
            "quality_feedback_total": self.quality_feedback_total,
            "quality_feedback_created": self.quality_feedback_created,
            "quality_feedback_updated": self.quality_feedback_updated,
            "quality_feedback_skipped": self.quality_feedback_skipped,
            "feedback_article_refs_total": self.feedback_article_refs_total,
            "feedback_article_refs_resolved": self.feedback_article_refs_resolved,
            "feedback_article_refs_unresolved": self.feedback_article_refs_unresolved,
            "jobs_total": self.jobs_total,
            "jobs_created": self.jobs_created,
            "jobs_updated": self.jobs_updated,
            "jobs_skipped": self.jobs_skipped,
        }


def import_tech_insight_loop_legacy_history(
    session: Session,
    request: LegacyImportRequest,
) -> LegacyImportResult:
    sqlite_path = request.sqlite_path.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    with connect_readonly(sqlite_path) as conn:
        article_rows = fetch_rows(conn, LEGACY_ARTICLE_TABLE, limit=request.article_limit)
        report_rows = fetch_rows(conn, LEGACY_REPORT_TABLE, limit=request.report_limit)

    archive_source = ensure_archive_data_source(session, request)
    article_result = import_article_rows(session, archive_source, article_rows, request)
    report_result = import_report_rows(session, report_rows, article_result["article_ref_to_raw_id"], request)
    session.flush()
    return LegacyImportResult(
        articles_total=article_result["total"],
        articles_created=article_result["created"],
        articles_updated=article_result["updated"],
        articles_skipped=article_result["skipped"],
        reports_total=report_result["total"],
        reports_created=report_result["created"],
        reports_updated=report_result["updated"],
        reports_skipped=report_result["skipped"],
        report_refs_total=report_result["refs_total"],
        report_refs_resolved=report_result["refs_resolved"],
        report_refs_unresolved=report_result["refs_unresolved"],
    )


def import_tech_insight_loop_entities(
    session: Session,
    request: EntityImportRequest,
) -> EntityImportResult:
    sqlite_path = request.sqlite_path.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    with connect_readonly(sqlite_path) as conn:
        entity_rows = fetch_rows(conn, LEGACY_ENTITY_TABLE, limit=request.entity_limit)
        milestone_rows = fetch_rows(conn, LEGACY_MILESTONE_TABLE, limit=request.milestone_limit)
        legacy_article_identity_by_id = fetch_legacy_article_identity_by_id(conn)

    entity_result = import_entity_rows(session, entity_rows, request)
    milestone_result = import_milestone_rows(
        session,
        milestone_rows,
        entity_result["legacy_entity_id_to_tracked_entity_id"],
        legacy_article_identity_by_id,
        request,
    )
    session.flush()
    return EntityImportResult(
        entities_total=entity_result["total"],
        entities_created=entity_result["created"],
        entities_updated=entity_result["updated"],
        entities_skipped=entity_result["skipped"],
        milestones_total=milestone_result["total"],
        milestones_created=milestone_result["created"],
        milestones_updated=milestone_result["updated"],
        milestones_skipped=milestone_result["skipped"],
        article_refs_total=milestone_result["article_refs_total"],
        article_refs_resolved=milestone_result["article_refs_resolved"],
        article_refs_unresolved=milestone_result["article_refs_unresolved"],
        report_refs_total=milestone_result["report_refs_total"],
        report_refs_resolved=milestone_result["report_refs_resolved"],
        report_refs_unresolved=milestone_result["report_refs_unresolved"],
    )


def import_tech_insight_loop_quality_archive(
    session: Session,
    request: QualityArchiveImportRequest,
) -> QualityArchiveImportResult:
    sqlite_path = request.sqlite_path.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    with connect_readonly(sqlite_path) as conn:
        feedback_rows = fetch_rows(conn, LEGACY_FEEDBACK_TABLE, limit=request.feedback_limit)
        quality_feedback_rows = fetch_rows(
            conn,
            LEGACY_QUALITY_FEEDBACK_TABLE,
            limit=request.quality_feedback_limit,
        )
        job_rows = fetch_rows(conn, LEGACY_JOB_TABLE, limit=request.job_limit)
        legacy_article_identity_by_id = fetch_legacy_article_identity_by_id(conn)

    feedback_result = import_feedback_rows(
        session,
        feedback_rows,
        legacy_article_identity_by_id,
        request,
        legacy_table=LEGACY_FEEDBACK_TABLE,
        feedback_kind="feedback",
    )
    quality_feedback_result = import_feedback_rows(
        session,
        quality_feedback_rows,
        legacy_article_identity_by_id,
        request,
        legacy_table=LEGACY_QUALITY_FEEDBACK_TABLE,
        feedback_kind="quality_feedback",
    )
    job_result = import_job_rows(session, job_rows, request)
    session.flush()
    return QualityArchiveImportResult(
        feedback_total=feedback_result["total"],
        feedback_created=feedback_result["created"],
        feedback_updated=feedback_result["updated"],
        feedback_skipped=feedback_result["skipped"],
        quality_feedback_total=quality_feedback_result["total"],
        quality_feedback_created=quality_feedback_result["created"],
        quality_feedback_updated=quality_feedback_result["updated"],
        quality_feedback_skipped=quality_feedback_result["skipped"],
        feedback_article_refs_total=feedback_result["article_refs_total"]
        + quality_feedback_result["article_refs_total"],
        feedback_article_refs_resolved=feedback_result["article_refs_resolved"]
        + quality_feedback_result["article_refs_resolved"],
        feedback_article_refs_unresolved=feedback_result["article_refs_unresolved"]
        + quality_feedback_result["article_refs_unresolved"],
        jobs_total=job_result["total"],
        jobs_created=job_result["created"],
        jobs_updated=job_result["updated"],
        jobs_skipped=job_result["skipped"],
    )


def connect_readonly(sqlite_path: Path) -> sqlite3.Connection:
    uri = f"{sqlite_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_rows(conn: sqlite3.Connection, table: str, limit: int | None = None) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM {quote_identifier(table)} ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (max(limit, 0),)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def fetch_legacy_article_identity_by_id(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT id, article_id FROM articles ORDER BY id").fetchall()
    mapping = {}
    for row in rows:
        row_id = str(row["id"])
        mapping[row_id] = clean_text(row["article_id"]) or row_id
    return mapping


def ensure_archive_data_source(session: Session, request: LegacyImportRequest) -> DataSource:
    existing = session.scalar(
        select(DataSource).where(
            DataSource.source_type == LEGACY_SOURCE_TYPE,
            DataSource.name == LEGACY_ARCHIVE_SOURCE_NAME,
        ),
    )
    if existing is not None:
        existing.enabled = False
        existing.workspace_code = request.workspace_code
        existing.domain_code = request.domain_code
        existing.metadata_json = {
            **(existing.metadata_json or {}),
            "origin": LEGACY_SYSTEM,
            "legacy_archive": True,
            "scheduler_enabled": False,
            "recommendation_eligible": False,
            "company_sql_eligible": False,
        }
        return existing

    data_source = DataSource(
        workspace_code=request.workspace_code,
        domain_code=request.domain_code,
        visibility_scope="public",
        sync_policy="public_to_intranet",
        source_type=LEGACY_SOURCE_TYPE,
        name=LEGACY_ARCHIVE_SOURCE_NAME,
        url=None,
        enabled=False,
        fetch_config={"adapter": "none", "scheduler_enabled": False},
        metadata_json={
            "origin": LEGACY_SYSTEM,
            "legacy_archive": True,
            "scheduler_enabled": False,
            "recommendation_eligible": False,
            "company_sql_eligible": False,
        },
        source_score=0,
        global_id="til:archive-source",
        content_hash=stable_hash({"source": LEGACY_ARCHIVE_SOURCE_NAME}),
    )
    session.add(data_source)
    session.flush()
    return data_source


def import_article_rows(
    session: Session,
    archive_source: DataSource,
    rows: list[dict[str, Any]],
    request: LegacyImportRequest,
) -> dict[str, Any]:
    total = created = updated = skipped = 0
    article_ref_to_raw_id: dict[str, str] = {}
    now = utc_now()
    for row in rows:
        total += 1
        identity = article_identity(row)
        if not identity or not clean_text(row.get("title")):
            skipped += 1
            continue
        entry_key = normalize_raw_entry_key(f"{LEGACY_SOURCE_TYPE}:{identity}")
        raw_item = session.scalar(
            select(RawItem).where(
                RawItem.data_source_id == archive_source.id,
                RawItem.entry_key == entry_key,
            ),
        )
        if raw_item is None:
            raw_item = RawItem(
                data_source_id=archive_source.id,
                workspace_code=request.workspace_code,
                domain_code=request.domain_code,
                visibility_scope="public",
                sync_policy="public_to_intranet",
                source_type=LEGACY_SOURCE_TYPE,
                source_name=clean_text(row.get("source_name")) or LEGACY_ARCHIVE_SOURCE_NAME,
                entry_key=entry_key,
                fetched_at=parse_datetime(row.get("crawled_at")) or now,
                global_id=stable_global_id("til:article", identity),
            )
            session.add(raw_item)
            created += 1
        else:
            updated += 1

        raw_item.source_type = LEGACY_SOURCE_TYPE
        raw_item.source_name = clean_text(row.get("source_name")) or LEGACY_ARCHIVE_SOURCE_NAME
        raw_item.source_title = clean_text(row.get("title"))
        raw_item.source_url = clean_text(row.get("url")) or clean_text(row.get("normalized_url")) or None
        raw_item.raw_content = clean_text(row.get("raw_content"))
        raw_item.published_at = parse_datetime(row.get("publish_time"))
        raw_item.fetched_at = parse_datetime(row.get("crawled_at")) or raw_item.fetched_at or now
        raw_item.raw_payload_json = {
            "legacy_tech_insight_loop": sanitize_json_for_storage(row),
            "legacy_import": {
                "legacy_system": LEGACY_SYSTEM,
                "legacy_table": LEGACY_ARTICLE_TABLE,
                "legacy_row_id": str(row.get("id")),
                "legacy_article_id": clean_text(row.get("article_id")),
                "import_status": "historical_imported",
                "recommendation_eligible": False,
                "company_sql_eligible": False,
                "nul_sanitized_fields": nul_sanitized_fields(row),
            },
        }
        raw_item.content_hash = stable_hash(raw_item.raw_payload_json)
        raw_item.origin_instance_id = LEGACY_SYSTEM
        raw_item.workspace_code = request.workspace_code
        raw_item.domain_code = request.domain_code
        session.flush()

        article_ref_to_raw_id[str(row.get("id"))] = raw_item.id
        article_id = clean_text(row.get("article_id"))
        if article_id:
            article_ref_to_raw_id[article_id] = raw_item.id
    return {
        "total": total,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "article_ref_to_raw_id": article_ref_to_raw_id,
    }


def import_report_rows(
    session: Session,
    rows: list[dict[str, Any]],
    article_ref_to_raw_id: dict[str, str],
    request: LegacyImportRequest,
) -> dict[str, int]:
    total = created = updated = skipped = refs_total = refs_resolved = refs_unresolved = 0
    for row in rows:
        total += 1
        report_type = clean_text(row.get("report_type"))
        legacy_id = str(row.get("id"))
        if report_type not in SUPPORTED_REPORT_TYPES or not clean_text(row.get("content")):
            skipped += 1
            continue

        refs = parse_json_list(row.get("source_article_ids_json"))
        resolved_refs = []
        unresolved_refs = []
        for ref in refs:
            ref_text = str(ref)
            raw_item_id = article_ref_to_raw_id.get(ref_text)
            refs_total += 1
            if raw_item_id:
                refs_resolved += 1
                resolved_refs.append({"legacy_ref": ref_text, "raw_item_id": raw_item_id})
            else:
                refs_unresolved += 1
                unresolved_refs.append(ref_text)

        report = session.scalar(
            select(HistoricalReport).where(
                HistoricalReport.legacy_system == LEGACY_SYSTEM,
                HistoricalReport.legacy_table == LEGACY_REPORT_TABLE,
                HistoricalReport.legacy_id == legacy_id,
            ),
        )
        if report is None:
            report = HistoricalReport(
                legacy_system=LEGACY_SYSTEM,
                legacy_table=LEGACY_REPORT_TABLE,
                legacy_id=legacy_id,
                workspace_code=request.workspace_code,
                domain_code=request.domain_code,
                visibility_scope="public",
                sync_policy="public_to_intranet",
                global_id=stable_global_id("til:report", legacy_id),
            )
            session.add(report)
            created += 1
        else:
            updated += 1

        report.report_type = report_type
        report.title = clean_text(row.get("title"))
        report.status = map_report_status(row.get("status"))
        report.period_start_at = parse_datetime(row.get("period_start"))
        report.period_end_at = parse_datetime(row.get("period_end"))
        report.content = clean_text(row.get("content"))
        report.source_refs_json = {
            "legacy_source_article_ids": refs,
            "resolved": resolved_refs,
            "unresolved": unresolved_refs,
            "resolved_count": len(resolved_refs),
            "unresolved_count": len(unresolved_refs),
        }
        report.metadata_json = {
            "legacy_tech_insight_loop": sanitize_json_for_storage(row),
            "legacy_import": {
                "legacy_system": LEGACY_SYSTEM,
                "legacy_table": LEGACY_REPORT_TABLE,
                "legacy_id": legacy_id,
                "target": "historical_reports",
                "recommendation_eligible": False,
                "company_sql_eligible": False,
                "nul_sanitized_fields": nul_sanitized_fields(row),
            },
        }
        report.content_hash = stable_hash(
            {
                "legacy_id": legacy_id,
                "title": report.title,
                "content": report.content,
                "source_refs": report.source_refs_json,
            },
        )
        report.origin_instance_id = LEGACY_SYSTEM
        report.workspace_code = request.workspace_code
        report.domain_code = request.domain_code
    return {
        "total": total,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "refs_total": refs_total,
        "refs_resolved": refs_resolved,
        "refs_unresolved": refs_unresolved,
    }


def import_entity_rows(
    session: Session,
    rows: list[dict[str, Any]],
    request: EntityImportRequest,
) -> dict[str, Any]:
    total = created = updated = skipped = 0
    legacy_entity_id_to_tracked_entity_id: dict[str, str] = {}
    for row in rows:
        total += 1
        legacy_id = str(row.get("id"))
        name = clean_text(row.get("name"))
        if not legacy_id or not name:
            skipped += 1
            continue

        entity = session.scalar(
            select(TrackedEntity).where(
                TrackedEntity.legacy_system == LEGACY_SYSTEM,
                TrackedEntity.legacy_table == LEGACY_ENTITY_TABLE,
                TrackedEntity.legacy_id == legacy_id,
            ),
        )
        if entity is None:
            entity = TrackedEntity(
                legacy_system=LEGACY_SYSTEM,
                legacy_table=LEGACY_ENTITY_TABLE,
                legacy_id=legacy_id,
                workspace_code=request.workspace_code,
                domain_code=request.domain_code,
                visibility_scope="public",
                sync_policy="public_to_intranet",
                global_id=stable_global_id("til:entity", legacy_id),
            )
            session.add(entity)
            created += 1
        else:
            updated += 1

        aliases = parse_json_list(row.get("aliases_json"))
        entity.name = name
        entity.entity_type = clean_text(row.get("entity_type"))
        entity.rank = clean_text(row.get("rank"))
        entity.aliases_json = aliases
        entity.influence_score = as_float(row.get("influence_score"))
        entity.notes = clean_text(row.get("notes"))
        entity.metadata_json = {
            "legacy_tech_insight_loop": sanitize_json_for_storage(row),
            "legacy_import": {
                "legacy_system": LEGACY_SYSTEM,
                "legacy_table": LEGACY_ENTITY_TABLE,
                "legacy_id": legacy_id,
                "target": "tracked_entities",
                "recommendation_eligible": False,
                "company_sql_eligible": False,
                "nul_sanitized_fields": nul_sanitized_fields(row),
            },
            "influence_breakdown": {
                "market_influence": as_float(row.get("market_influence")),
                "technical_influence": as_float(row.get("technical_influence")),
                "ecosystem_influence": as_float(row.get("ecosystem_influence")),
                "academic_influence": as_float(row.get("academic_influence")),
                "open_source_influence": as_float(row.get("open_source_influence")),
                "commercial_influence": as_float(row.get("commercial_influence")),
                "business_relevance": as_float(row.get("business_relevance")),
                "recent_growth": as_float(row.get("recent_growth")),
            },
        }
        entity.content_hash = stable_hash(
            {
                "legacy_id": legacy_id,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "rank": entity.rank,
                "aliases": aliases,
                "influence_score": entity.influence_score,
            },
        )
        entity.origin_instance_id = LEGACY_SYSTEM
        entity.workspace_code = request.workspace_code
        entity.domain_code = request.domain_code
        session.flush()
        legacy_entity_id_to_tracked_entity_id[legacy_id] = entity.id
    return {
        "total": total,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "legacy_entity_id_to_tracked_entity_id": legacy_entity_id_to_tracked_entity_id,
    }


def import_milestone_rows(
    session: Session,
    rows: list[dict[str, Any]],
    legacy_entity_id_to_tracked_entity_id: dict[str, str],
    legacy_article_identity_by_id: dict[str, str],
    request: EntityImportRequest,
) -> dict[str, int]:
    total = created = updated = skipped = 0
    article_refs_total = article_refs_resolved = article_refs_unresolved = 0
    report_refs_total = report_refs_resolved = report_refs_unresolved = 0
    for row in rows:
        total += 1
        legacy_id = str(row.get("id"))
        legacy_entity_id = str(row.get("entity_id") or "")
        tracked_entity_id = legacy_entity_id_to_tracked_entity_id.get(legacy_entity_id)
        title = clean_text(row.get("event_title"))
        if not legacy_id or not tracked_entity_id or not title:
            skipped += 1
            continue

        legacy_article_id = clean_text(row.get("article_id")) or None
        article_identity = legacy_article_identity_by_id.get(legacy_article_id or "")
        raw_item_id = None
        if legacy_article_id:
            article_refs_total += 1
            raw_item_id = resolve_imported_raw_item_id(session, article_identity or legacy_article_id)
            if raw_item_id:
                article_refs_resolved += 1
            else:
                article_refs_unresolved += 1

        legacy_report_id = clean_text(row.get("report_id")) or None
        historical_report_id = None
        if legacy_report_id:
            report_refs_total += 1
            historical_report_id = resolve_imported_historical_report_id(session, legacy_report_id)
            if historical_report_id:
                report_refs_resolved += 1
            else:
                report_refs_unresolved += 1

        milestone = session.scalar(
            select(EntityMilestone).where(
                EntityMilestone.legacy_system == LEGACY_SYSTEM,
                EntityMilestone.legacy_table == LEGACY_MILESTONE_TABLE,
                EntityMilestone.legacy_id == legacy_id,
            ),
        )
        if milestone is None:
            milestone = EntityMilestone(
                legacy_system=LEGACY_SYSTEM,
                legacy_table=LEGACY_MILESTONE_TABLE,
                legacy_id=legacy_id,
                tracked_entity_id=tracked_entity_id,
                legacy_entity_id=legacy_entity_id,
                workspace_code=request.workspace_code,
                domain_code=request.domain_code,
                visibility_scope="public",
                sync_policy="public_to_intranet",
                global_id=stable_global_id("til:milestone", legacy_id),
            )
            session.add(milestone)
            created += 1
        else:
            updated += 1

        event_time = parse_datetime(row.get("event_time"))
        milestone.tracked_entity_id = tracked_entity_id
        milestone.legacy_entity_id = legacy_entity_id
        milestone.legacy_article_id = legacy_article_id
        milestone.legacy_report_id = legacy_report_id
        milestone.raw_item_id = raw_item_id
        milestone.historical_report_id = historical_report_id
        milestone.event_time = event_time
        milestone.event_type = clean_text(row.get("event_type"))
        milestone.title = title
        milestone.event_content = clean_text(row.get("event_content"))
        milestone.impact = clean_text(row.get("impact"))
        milestone.event_brief = clean_text(row.get("event_brief"))
        milestone.impact_brief = clean_text(row.get("impact_brief"))
        milestone.timeline_brief = clean_text(row.get("timeline_brief"))
        milestone.source_url = clean_text(row.get("source_url")) or None
        milestone.source_name = clean_text(row.get("source_name"))
        milestone.board = clean_text(row.get("board"))
        milestone.selected_for_timeline = as_bool(row.get("selected_for_timeline"), default=True)
        milestone.confidence_score = as_float(row.get("confidence"))
        milestone.importance_score = as_float(row.get("importance_score"))
        milestone.importance_level = clean_text(row.get("importance_level")) or "medium"
        milestone.event_dedupe_key = clean_text(row.get("event_dedupe_key"))
        milestone.metadata_json = {
            "legacy_tech_insight_loop": sanitize_json_for_storage(row),
            "legacy_import": {
                "legacy_system": LEGACY_SYSTEM,
                "legacy_table": LEGACY_MILESTONE_TABLE,
                "legacy_id": legacy_id,
                "target": "entity_milestones",
                "recommendation_eligible": False,
                "company_sql_eligible": False,
                "nul_sanitized_fields": nul_sanitized_fields(row),
            },
            "legacy_refs": {
                "entity_id": legacy_entity_id,
                "article_id": legacy_article_id,
                "article_identity": article_identity,
                "raw_item_id": raw_item_id,
                "report_id": legacy_report_id,
                "historical_report_id": historical_report_id,
                "article_ref_resolved": bool(raw_item_id) if legacy_article_id else None,
                "report_ref_resolved": bool(historical_report_id) if legacy_report_id else None,
            },
            "model_payload": parse_json_value(row.get("model_payload_json")),
            "summary_model_payload": parse_json_value(row.get("summary_model_payload_json")),
            "summary_model_status": clean_text(row.get("summary_model_status")),
            "summary_model_error": clean_text(row.get("summary_model_error")),
            "deleted_at": clean_text(row.get("deleted_at")),
        }
        milestone.content_hash = stable_hash(
            {
                "legacy_id": legacy_id,
                "tracked_entity_id": tracked_entity_id,
                "event_time": event_time.isoformat() if event_time else None,
                "title": milestone.title,
                "event_content": milestone.event_content,
                "impact": milestone.impact,
                "importance_level": milestone.importance_level,
                "event_dedupe_key": milestone.event_dedupe_key,
            },
        )
        milestone.origin_instance_id = LEGACY_SYSTEM
        milestone.workspace_code = request.workspace_code
        milestone.domain_code = request.domain_code
    return {
        "total": total,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "article_refs_total": article_refs_total,
        "article_refs_resolved": article_refs_resolved,
        "article_refs_unresolved": article_refs_unresolved,
        "report_refs_total": report_refs_total,
        "report_refs_resolved": report_refs_resolved,
        "report_refs_unresolved": report_refs_unresolved,
    }


def import_feedback_rows(
    session: Session,
    rows: list[dict[str, Any]],
    legacy_article_identity_by_id: dict[str, str],
    request: QualityArchiveImportRequest,
    *,
    legacy_table: str,
    feedback_kind: str,
) -> dict[str, int]:
    total = created = updated = skipped = 0
    article_refs_total = article_refs_resolved = article_refs_unresolved = 0
    for row in rows:
        total += 1
        legacy_id = str(row.get("id") or "")
        if not legacy_id:
            skipped += 1
            continue

        legacy_article_id = clean_text(row.get("article_id")) or None
        article_identity = legacy_article_identity_by_id.get(legacy_article_id or "")
        raw_item_id = None
        if legacy_article_id:
            article_refs_total += 1
            raw_item_id = resolve_imported_raw_item_id(session, article_identity or legacy_article_id)
            if raw_item_id:
                article_refs_resolved += 1
            else:
                article_refs_unresolved += 1

        item = session.scalar(
            select(HistoricalFeedbackItem).where(
                HistoricalFeedbackItem.legacy_system == LEGACY_SYSTEM,
                HistoricalFeedbackItem.legacy_table == legacy_table,
                HistoricalFeedbackItem.legacy_id == legacy_id,
            ),
        )
        if item is None:
            global_prefix = "til:qfb" if legacy_table == LEGACY_QUALITY_FEEDBACK_TABLE else "til:fb"
            item = HistoricalFeedbackItem(
                legacy_system=LEGACY_SYSTEM,
                legacy_table=legacy_table,
                legacy_id=legacy_id,
                workspace_code=request.workspace_code,
                domain_code=request.domain_code,
                visibility_scope="public",
                sync_policy="public_to_intranet",
                global_id=stable_global_id(global_prefix, legacy_id),
            )
            session.add(item)
            created += 1
        else:
            updated += 1

        item.legacy_article_id = legacy_article_id
        item.raw_item_id = raw_item_id
        item.feedback_kind = feedback_kind
        item.user_name = clean_text(row.get("user_name"))
        item.feedback_type = clean_text(row.get("feedback_type"))
        item.reason = clean_text(row.get("reason"))
        item.comment = clean_text(row.get("comment"))
        item.feedback_at = parse_datetime(row.get("created_at"))
        item.metadata_json = {
            "legacy_tech_insight_loop": sanitize_json_for_storage(row),
            "legacy_import": {
                "legacy_system": LEGACY_SYSTEM,
                "legacy_table": legacy_table,
                "legacy_id": legacy_id,
                "target": "historical_feedback_items",
                "recommendation_eligible": False,
                "company_sql_eligible": False,
                "mutates_current_feedback": False,
                "nul_sanitized_fields": nul_sanitized_fields(row),
            },
            "legacy_refs": {
                "article_id": legacy_article_id,
                "article_identity": article_identity,
                "raw_item_id": raw_item_id,
                "article_ref_resolved": bool(raw_item_id) if legacy_article_id else None,
            },
        }
        item.content_hash = stable_hash(
            {
                "legacy_table": legacy_table,
                "legacy_id": legacy_id,
                "legacy_article_id": legacy_article_id,
                "feedback_type": item.feedback_type,
                "reason": item.reason,
                "comment": item.comment,
            },
        )
        item.origin_instance_id = LEGACY_SYSTEM
        item.workspace_code = request.workspace_code
        item.domain_code = request.domain_code
    return {
        "total": total,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "article_refs_total": article_refs_total,
        "article_refs_resolved": article_refs_resolved,
        "article_refs_unresolved": article_refs_unresolved,
    }


def import_job_rows(
    session: Session,
    rows: list[dict[str, Any]],
    request: QualityArchiveImportRequest,
) -> dict[str, int]:
    total = created = updated = skipped = 0
    for row in rows:
        total += 1
        legacy_id = str(row.get("id") or "")
        if not legacy_id:
            skipped += 1
            continue

        job = session.scalar(
            select(HistoricalJobRun).where(
                HistoricalJobRun.legacy_system == LEGACY_SYSTEM,
                HistoricalJobRun.legacy_table == LEGACY_JOB_TABLE,
                HistoricalJobRun.legacy_id == legacy_id,
            ),
        )
        if job is None:
            job = HistoricalJobRun(
                legacy_system=LEGACY_SYSTEM,
                legacy_table=LEGACY_JOB_TABLE,
                legacy_id=legacy_id,
                workspace_code=request.workspace_code,
                domain_code=request.domain_code,
                visibility_scope="public",
                sync_policy="public_to_intranet",
                global_id=stable_global_id("til:job", legacy_id),
            )
            session.add(job)
            created += 1
        else:
            updated += 1

        details = parse_json_value(row.get("details_json"))
        job.job_type = clean_text(row.get("job_type"))
        job.status = clean_text(row.get("status"))
        job.message = clean_text(row.get("message"))
        job.started_at = parse_datetime(row.get("started_at"))
        job.ended_at = parse_datetime(row.get("ended_at"))
        job.legacy_updated_at = parse_datetime(row.get("updated_at"))
        job.total_sources = as_int(row.get("total_sources"))
        job.processed_sources = as_int(row.get("processed_sources"))
        job.inserted_count = as_int(row.get("inserted_count"))
        job.failed_count = as_int(row.get("failed_count"))
        job.details_json = details if isinstance(details, dict) else {"raw": details}
        job.metadata_json = {
            "legacy_tech_insight_loop": sanitize_json_for_storage(row),
            "legacy_import": {
                "legacy_system": LEGACY_SYSTEM,
                "legacy_table": LEGACY_JOB_TABLE,
                "legacy_id": legacy_id,
                "target": "historical_job_runs",
                "migrates_old_task_state_machine": False,
                "statistics_only": True,
                "nul_sanitized_fields": nul_sanitized_fields(row),
            },
        }
        job.content_hash = stable_hash(
            {
                "legacy_id": legacy_id,
                "job_type": job.job_type,
                "status": job.status,
                "message": job.message,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "ended_at": job.ended_at.isoformat() if job.ended_at else None,
                "counts": {
                    "total_sources": job.total_sources,
                    "processed_sources": job.processed_sources,
                    "inserted_count": job.inserted_count,
                    "failed_count": job.failed_count,
                },
                "details": job.details_json,
            },
        )
        job.origin_instance_id = LEGACY_SYSTEM
        job.workspace_code = request.workspace_code
        job.domain_code = request.domain_code
    return {
        "total": total,
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def article_identity(row: dict[str, Any]) -> str:
    return clean_text(row.get("article_id")) or str(row.get("id") or "")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return replace_nul(str(value)).strip()


def replace_nul(value: str) -> str:
    return value.replace("\x00", NUL_TEXT_REPLACEMENT)


def sanitize_json_for_storage(value: Any) -> Any:
    if isinstance(value, str):
        return replace_nul(value)
    if isinstance(value, list):
        return [sanitize_json_for_storage(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_for_storage(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_json_for_storage(item) for key, item in value.items()}
    return value


def nul_sanitized_fields(row: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for key, value in row.items():
        if isinstance(value, str):
            count = value.count("\x00")
            if count:
                fields.append({"field": key, "nul_count": count, "replacement": NUL_TEXT_REPLACEMENT})
    return fields


def parse_json_list(value: Any) -> list[Any]:
    text = clean_text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    parsed = sanitize_json_for_storage(parsed)
    return parsed if isinstance(parsed, list) else []


def parse_json_value(value: Any) -> Any:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    return sanitize_json_for_storage(parsed)


def parse_datetime(value: Any) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def map_report_status(value: Any) -> str:
    status = clean_text(value)
    if status in {"已生成", "published", "completed"}:
        return "published_imported"
    return "imported"


def as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = clean_text(value).lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def resolve_imported_raw_item_id(session: Session, article_identity_value: str) -> str | None:
    if not article_identity_value:
        return None
    return session.scalar(
        select(RawItem.id).where(RawItem.global_id == stable_global_id("til:article", article_identity_value)),
    )


def resolve_imported_historical_report_id(session: Session, legacy_report_id: str) -> str | None:
    if not legacy_report_id:
        return None
    return session.scalar(
        select(HistoricalReport.id).where(
            HistoricalReport.legacy_system == LEGACY_SYSTEM,
            HistoricalReport.legacy_table == LEGACY_REPORT_TABLE,
            HistoricalReport.legacy_id == legacy_report_id,
        ),
    )


def stable_global_id(prefix: str, identity: str) -> str:
    digest = sha1(identity.encode("utf-8")).hexdigest()[:40]
    return f"{prefix}:{digest}"


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return sha1(payload.encode("utf-8")).hexdigest()


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
