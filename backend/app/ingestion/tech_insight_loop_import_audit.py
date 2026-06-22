from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import REPO_ROOT
from app.ingestion.tech_insight_loop_legacy import LEGACY_SOURCE_TYPE, LEGACY_WORKSPACE_CODE
from app.models.common import utc_now
from app.models.content import RawItem
from app.models.legacy import (
    EntityMilestone,
    HistoricalFeedbackItem,
    HistoricalJobRun,
    HistoricalReport,
    TrackedEntity,
)

LEGACY_IMPORT_CONTRACT_PATH = REPO_ROOT / "config" / "contracts" / "tech_insight_loop_legacy_import.json"


@dataclass(frozen=True)
class LegacyImportMetric:
    key: str
    label: str
    expected: int
    actual: int
    missing: int
    coverage_rate: float
    status: str


@dataclass(frozen=True)
class LegacyImportRefStats:
    total: int
    resolved: int
    unresolved: int


@dataclass(frozen=True)
class LegacyImportSummary:
    workspace_code: str
    generated_at: datetime
    expected_counts: dict[str, int]
    metrics: list[LegacyImportMetric]
    report_refs: LegacyImportRefStats
    milestone_article_refs: LegacyImportRefStats
    milestone_report_refs: LegacyImportRefStats
    feedback_article_refs: LegacyImportRefStats
    total_unresolved_refs: int
    gap_item_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LegacyImportGapItem:
    kind: str
    id: str
    legacy_id: str
    title: str
    ref_type: str
    unresolved_refs: list[Any]
    unresolved_count: int
    detail_path: str
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_legacy_import_summary(
    session: Session,
    *,
    workspace_code: str = LEGACY_WORKSPACE_CODE,
    contract_path: Path = LEGACY_IMPORT_CONTRACT_PATH,
) -> LegacyImportSummary:
    expected_counts = legacy_import_expected_counts(contract_path)
    raw_count = legacy_raw_count(session, workspace_code)
    reports = session.scalars(
        select(HistoricalReport).where(HistoricalReport.workspace_code == workspace_code),
    ).all()
    entities = session.scalars(
        select(TrackedEntity).where(TrackedEntity.workspace_code == workspace_code),
    ).all()
    milestones = session.scalars(
        select(EntityMilestone).where(EntityMilestone.workspace_code == workspace_code),
    ).all()
    feedback_items = session.scalars(
        select(HistoricalFeedbackItem).where(HistoricalFeedbackItem.workspace_code == workspace_code),
    ).all()
    job_count = historical_job_count(session, workspace_code)

    report_ref_stats = report_ref_stats_for(reports)
    milestone_article_stats, milestone_report_stats = milestone_ref_stats_for(milestones)
    feedback_article_stats = feedback_ref_stats_for(feedback_items)
    gap_count = sum(1 for report in reports if report_ref_counts(report)[1] > 0)
    gap_count += sum(1 for milestone in milestones if milestone_unresolved_ref_count(milestone) > 0)
    gap_count += sum(1 for item in feedback_items if feedback_unresolved_ref_count(item) > 0)
    total_unresolved_refs = (
        report_ref_stats.unresolved
        + milestone_article_stats.unresolved
        + milestone_report_stats.unresolved
        + feedback_article_stats.unresolved
    )

    return LegacyImportSummary(
        workspace_code=workspace_code,
        generated_at=utc_now(),
        expected_counts=expected_counts,
        metrics=[
            legacy_import_metric("articles", "历史素材 raw", expected_counts["articles"], raw_count),
            legacy_import_metric(
                "historical_reports",
                "历史日报/周报",
                expected_counts["importable_reports"],
                len(reports),
            ),
            legacy_import_metric("tracked_entities", "实体", expected_counts["ai_entities"], len(entities)),
            legacy_import_metric(
                "entity_milestones",
                "实体大事记",
                expected_counts["entity_milestones"],
                len(milestones),
            ),
            legacy_import_metric(
                "historical_feedback",
                "旧反馈",
                expected_counts["feedback"],
                historical_feedback_count(feedback_items, "feedback"),
            ),
            legacy_import_metric(
                "historical_quality_feedback",
                "旧质量反馈",
                expected_counts["article_quality_feedback"],
                historical_feedback_count(feedback_items, "quality_feedback"),
            ),
            legacy_import_metric("historical_job_runs", "旧任务记录", expected_counts["jobs"], job_count),
        ],
        report_refs=report_ref_stats,
        milestone_article_refs=milestone_article_stats,
        milestone_report_refs=milestone_report_stats,
        feedback_article_refs=feedback_article_stats,
        total_unresolved_refs=total_unresolved_refs,
        gap_item_count=gap_count,
    )


def list_legacy_import_gap_items(
    session: Session,
    *,
    workspace_code: str = LEGACY_WORKSPACE_CODE,
    kind: str = "all",
    limit: int = 50,
) -> list[LegacyImportGapItem]:
    gaps: list[LegacyImportGapItem] = []
    if kind in {"all", "historical_reports"}:
        reports = session.scalars(
            select(HistoricalReport)
            .where(HistoricalReport.workspace_code == workspace_code)
            .order_by(HistoricalReport.period_start_at.desc().nullslast(), HistoricalReport.created_at.desc()),
        ).all()
        for report in reports:
            item = historical_report_gap_item(report)
            if item is not None:
                gaps.append(item)
    if kind in {"all", "entity_milestones"}:
        milestones = session.scalars(
            select(EntityMilestone)
            .options(selectinload(EntityMilestone.tracked_entity))
            .where(EntityMilestone.workspace_code == workspace_code)
            .order_by(EntityMilestone.event_time.desc().nullslast(), EntityMilestone.created_at.desc()),
        ).all()
        for milestone in milestones:
            item = entity_milestone_gap_item(milestone)
            if item is not None:
                gaps.append(item)
    if kind in {"all", "historical_feedback"}:
        feedback_items = session.scalars(
            select(HistoricalFeedbackItem)
            .where(HistoricalFeedbackItem.workspace_code == workspace_code)
            .order_by(HistoricalFeedbackItem.feedback_at.desc().nullslast(), HistoricalFeedbackItem.created_at.desc()),
        ).all()
        for feedback_item in feedback_items:
            item = historical_feedback_gap_item(feedback_item)
            if item is not None:
                gaps.append(item)
    return gaps[: max(limit, 0)]


def legacy_import_expected_counts(contract_path: Path = LEGACY_IMPORT_CONTRACT_PATH) -> dict[str, int]:
    fallback = {
        "articles": 14834,
        "legacy_reports": 66,
        "importable_reports": 58,
        "ai_entities": 23,
        "entity_milestones": 275,
        "feedback": 4,
        "article_quality_feedback": 4,
        "jobs": 257,
    }
    if not contract_path.exists():
        return fallback
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    legacy_counts = contract.get("legacy_sqlite_expected_counts") or {}
    dry_run_counts = contract.get("dry_run_expected_importable_counts") or {}
    return {
        "articles": int_from_mapping(dry_run_counts, "articles", int_from_mapping(legacy_counts, "articles", 14834)),
        "legacy_reports": int_from_mapping(legacy_counts, "reports", 66),
        "importable_reports": int_from_mapping(dry_run_counts, "reports", 58),
        "ai_entities": int_from_mapping(legacy_counts, "ai_entities", 23),
        "entity_milestones": int_from_mapping(legacy_counts, "entity_milestones", 275),
        "feedback": int_from_mapping(legacy_counts, "feedback", 4),
        "article_quality_feedback": int_from_mapping(legacy_counts, "article_quality_feedback", 4),
        "jobs": int_from_mapping(legacy_counts, "jobs", 257),
    }


def int_from_mapping(mapping: dict[str, object], key: str, default: int) -> int:
    value = mapping.get(key)
    return value if isinstance(value, int) else default


def legacy_raw_count(session: Session, workspace_code: str) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(RawItem)
        .where(
            RawItem.workspace_code == workspace_code,
            RawItem.source_type == LEGACY_SOURCE_TYPE,
        ),
    )
    return int(value or 0)


def historical_job_count(session: Session, workspace_code: str) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(HistoricalJobRun)
        .where(HistoricalJobRun.workspace_code == workspace_code),
    )
    return int(value or 0)


def legacy_import_metric(key: str, label: str, expected: int, actual: int) -> LegacyImportMetric:
    missing = max(expected - actual, 0)
    coverage_rate = round(actual / expected, 4) if expected else 1.0
    if expected and actual >= expected:
        status_text = "complete"
    elif actual > 0:
        status_text = "partial"
    else:
        status_text = "pending"
    return LegacyImportMetric(
        key=key,
        label=label,
        expected=expected,
        actual=actual,
        missing=missing,
        coverage_rate=coverage_rate,
        status=status_text,
    )


def report_ref_stats_for(reports: list[HistoricalReport]) -> LegacyImportRefStats:
    resolved = unresolved = 0
    for report in reports:
        report_resolved, report_unresolved = report_ref_counts(report)
        resolved += report_resolved
        unresolved += report_unresolved
    return LegacyImportRefStats(
        total=resolved + unresolved,
        resolved=resolved,
        unresolved=unresolved,
    )


def milestone_ref_stats_for(
    milestones: list[EntityMilestone],
) -> tuple[LegacyImportRefStats, LegacyImportRefStats]:
    article_total = article_resolved = article_unresolved = 0
    report_total = report_resolved = report_unresolved = 0
    for milestone in milestones:
        article_ref, report_ref = milestone_ref_flags(milestone)
        if milestone.legacy_article_id:
            article_total += 1
            if article_ref is True:
                article_resolved += 1
            elif article_ref is False:
                article_unresolved += 1
        if milestone.legacy_report_id:
            report_total += 1
            if report_ref is True:
                report_resolved += 1
            elif report_ref is False:
                report_unresolved += 1
    return (
        LegacyImportRefStats(
            total=article_total,
            resolved=article_resolved,
            unresolved=article_unresolved,
        ),
        LegacyImportRefStats(
            total=report_total,
            resolved=report_resolved,
            unresolved=report_unresolved,
        ),
    )


def feedback_ref_stats_for(feedback_items: list[HistoricalFeedbackItem]) -> LegacyImportRefStats:
    total = resolved = unresolved = 0
    for item in feedback_items:
        ref = feedback_ref_flag(item)
        if item.legacy_article_id:
            total += 1
            if ref is True:
                resolved += 1
            elif ref is False:
                unresolved += 1
    return LegacyImportRefStats(total=total, resolved=resolved, unresolved=unresolved)


def historical_feedback_count(feedback_items: list[HistoricalFeedbackItem], feedback_kind: str) -> int:
    return sum(1 for item in feedback_items if item.feedback_kind == feedback_kind)


def historical_report_gap_item(report: HistoricalReport) -> LegacyImportGapItem | None:
    resolved_count, unresolved_count = report_ref_counts(report)
    if unresolved_count <= 0:
        return None
    refs = report.source_refs_json or {}
    unresolved_refs = refs.get("unresolved") or []
    if not isinstance(unresolved_refs, list):
        unresolved_refs = []
    return LegacyImportGapItem(
        kind="historical_reports",
        id=report.id,
        legacy_id=report.legacy_id,
        title=report.title,
        ref_type="source_article_ids",
        unresolved_refs=unresolved_refs,
        unresolved_count=unresolved_count,
        detail_path=f"/historical-reports/{report.id}",
        context={
            "report_type": report.report_type,
            "status": report.status,
            "period_start_at": report.period_start_at,
            "resolved_ref_count": resolved_count,
        },
    )


def entity_milestone_gap_item(milestone: EntityMilestone) -> LegacyImportGapItem | None:
    unresolved_refs = []
    article_ref, report_ref = milestone_ref_flags(milestone)
    if milestone.legacy_article_id and article_ref is False:
        unresolved_refs.append({"ref_type": "article_id", "legacy_ref": milestone.legacy_article_id})
    if milestone.legacy_report_id and report_ref is False:
        unresolved_refs.append({"ref_type": "report_id", "legacy_ref": milestone.legacy_report_id})
    if not unresolved_refs:
        return None
    entity = milestone.tracked_entity
    ref_types = sorted({str(item["ref_type"]) for item in unresolved_refs})
    return LegacyImportGapItem(
        kind="entity_milestones",
        id=milestone.id,
        legacy_id=milestone.legacy_id,
        title=milestone.title,
        ref_type="/".join(ref_types),
        unresolved_refs=unresolved_refs,
        unresolved_count=len(unresolved_refs),
        detail_path=f"/entity-milestones/{milestone.id}",
        context={
            "entity_name": entity.name if entity else "",
            "entity_type": entity.entity_type if entity else "",
            "event_time": milestone.event_time,
            "event_type": milestone.event_type,
            "board": milestone.board,
        },
    )


def historical_feedback_gap_item(item: HistoricalFeedbackItem) -> LegacyImportGapItem | None:
    article_ref = feedback_ref_flag(item)
    if not item.legacy_article_id or article_ref is not False:
        return None
    return LegacyImportGapItem(
        kind="historical_feedback",
        id=item.id,
        legacy_id=item.legacy_id,
        title=f"{item.feedback_kind}: {item.feedback_type or 'unknown'}",
        ref_type="article_id",
        unresolved_refs=[{"ref_type": "article_id", "legacy_ref": item.legacy_article_id}],
        unresolved_count=1,
        detail_path="/historical-reports",
        context={
            "legacy_table": item.legacy_table,
            "feedback_kind": item.feedback_kind,
            "feedback_type": item.feedback_type,
            "reason": item.reason,
            "feedback_at": item.feedback_at,
        },
    )


def report_ref_counts(report: HistoricalReport) -> tuple[int, int]:
    refs = report.source_refs_json or {}
    resolved_count = refs.get("resolved_count")
    unresolved_count = refs.get("unresolved_count")
    if isinstance(resolved_count, int) and isinstance(unresolved_count, int):
        return resolved_count, unresolved_count
    resolved = refs.get("resolved") or []
    unresolved = refs.get("unresolved") or []
    return (
        len(resolved) if isinstance(resolved, list) else 0,
        len(unresolved) if isinstance(unresolved, list) else 0,
    )


def milestone_ref_flags(milestone: EntityMilestone) -> tuple[bool | None, bool | None]:
    refs = (milestone.metadata_json or {}).get("legacy_refs") or {}
    article_ref = refs.get("article_ref_resolved")
    report_ref = refs.get("report_ref_resolved")
    return (
        article_ref if isinstance(article_ref, bool) else None,
        report_ref if isinstance(report_ref, bool) else None,
    )


def milestone_unresolved_ref_count(milestone: EntityMilestone) -> int:
    article_ref, report_ref = milestone_ref_flags(milestone)
    total = 0
    if milestone.legacy_article_id and article_ref is False:
        total += 1
    if milestone.legacy_report_id and report_ref is False:
        total += 1
    return total


def feedback_ref_flag(item: HistoricalFeedbackItem) -> bool | None:
    refs = (item.metadata_json or {}).get("legacy_refs") or {}
    article_ref = refs.get("article_ref_resolved")
    return article_ref if isinstance(article_ref, bool) else None


def feedback_unresolved_ref_count(item: HistoricalFeedbackItem) -> int:
    return 1 if item.legacy_article_id and feedback_ref_flag(item) is False else 0
