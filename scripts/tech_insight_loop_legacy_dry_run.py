#!/usr/bin/env python3
"""Dry-run Tech Insight Loop historical article/report import.

This command prepares the next migration batch without writing to the legacy
SQLite database or to the InfoWatchtower application database. It resolves
legacy article identities, report source references, and target archive states
so the real importer can be reviewed before it mutates anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tech_insight_loop_inventory import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SQLITE_PATH,
    clean_text,
    connect_readonly,
    parse_datetime_value,
    parse_json_list,
    quote_identifier,
    sha256_file,
)

ARTICLE_IMPORT_STATUS = "historical_imported"
REPORT_PUBLISHED_STATUS = "published_imported"
REPORT_DRAFT_STATUS = "imported"
SUPPORTED_REPORT_TYPES = {"daily", "weekly"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help="Path to Tech Insight Loop SQLite database.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for JSON and Markdown dry-run reports.",
    )
    parser.add_argument("--preview-limit", type=int, default=5)
    parser.add_argument("--no-write", action="store_true", help="Print JSON summary only.")
    args = parser.parse_args()

    dry_run = build_dry_run(args.sqlite_path, preview_limit=args.preview_limit)
    if args.no_write:
        print(json.dumps(dry_run, ensure_ascii=False, indent=2))
        return 0

    outputs = write_dry_run_outputs(dry_run, args.output_dir)
    print(f"wrote {outputs['json']}")
    print(f"wrote {outputs['markdown']}")
    return 0


def build_dry_run(sqlite_path: Path, preview_limit: int = 5) -> dict[str, Any]:
    sqlite_path = sqlite_path.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    with connect_readonly(sqlite_path) as conn:
        source_ids = load_source_ids(conn)
        article_rows = fetch_rows(conn, "articles")
        report_rows = fetch_rows(conn, "reports")
        article_plan = build_article_plan(article_rows, source_ids, preview_limit)
        report_plan = build_report_plan(report_rows, article_plan, preview_limit)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "sqlite_path": str(sqlite_path),
            "sqlite_sha256": sha256_file(sqlite_path),
            "sqlite_size_bytes": sqlite_path.stat().st_size,
        },
        "mode": "dry_run_only",
        "guardrails": [
            "do_not_write_legacy_sqlite",
            "do_not_write_infowatchtower_database",
            "do_not_run_legacy_app_py",
            "do_not_create_recommendation_runs",
            "do_not_create_sql_ready_generated_news",
            "do_not_export_historical_assets_to_company_sql",
        ],
        "articles": article_plan,
        "reports": report_plan,
        "next_import_order": [
            "create_or_resolve_history_source_placeholder",
            "import_articles_to_raw_items_with_legacy_payload",
            "optionally_create_archived_news_items_from_model_fields",
            "import_daily_weekly_reports_as_historical_reports",
            "write_report_article_reference_gaps",
        ],
    }


def build_article_plan(
    rows: list[dict[str, Any]],
    source_ids: set[str],
    preview_limit: int,
) -> dict[str, Any]:
    importable = []
    skipped = []
    duplicate_identity_count = 0
    identities_seen: set[str] = set()
    source_ref_counts = Counter()
    date_quality = {
        "publish_time_missing": 0,
        "publish_time_failed": 0,
        "crawled_at_missing": 0,
        "crawled_at_failed": 0,
    }
    model_archive_candidates = 0

    row_id_to_target: dict[str, str] = {}
    article_id_to_target: dict[str, str] = {}

    for row in rows:
        legacy_row_id = str(row.get("id"))
        article_id = clean_text(row.get("article_id"))
        identity = article_id or legacy_row_id
        skip_reasons = article_skip_reasons(row, identity)
        if identity in identities_seen:
            duplicate_identity_count += 1
            skip_reasons.append("duplicate_identity")

        source_id = clean_text(row.get("source_id"))
        if not source_id:
            source_ref_counts["missing_source_id"] += 1
        elif source_id not in source_ids:
            source_ref_counts["unresolved_source_id"] += 1
        else:
            source_ref_counts["resolved_source_id"] += 1

        update_datetime_quality(date_quality, "publish_time", row.get("publish_time"))
        update_datetime_quality(date_quality, "crawled_at", row.get("crawled_at"))

        if has_model_archive_candidate(row):
            model_archive_candidates += 1

        if skip_reasons:
            skipped.append(
                {
                    "legacy_row_id": legacy_row_id,
                    "article_id": article_id,
                    "target_key": target_key("articles", identity),
                    "reasons": skip_reasons,
                }
            )
            continue

        identities_seen.add(identity)
        target = target_key("articles", identity)
        row_id_to_target[legacy_row_id] = target
        if article_id:
            article_id_to_target[article_id] = target
        importable.append(article_preview(row, identity, source_id))

    return {
        "total": len(rows),
        "importable": len(importable),
        "skipped": len(skipped),
        "default_status": ARTICLE_IMPORT_STATUS,
        "raw_payload_json_path": "legacy_tech_insight_loop",
        "recommendation_eligible": False,
        "company_sql_eligible": False,
        "duplicate_identity_count": duplicate_identity_count,
        "source_refs": dict(source_ref_counts),
        "date_quality": date_quality,
        "model_archive_candidates": model_archive_candidates,
        "skip_reason_counts": count_reasons(skipped),
        "mapping": {
            "legacy_row_id_to_target_key_count": len(row_id_to_target),
            "legacy_article_id_to_target_key_count": len(article_id_to_target),
        },
        "previews": importable[: max(preview_limit, 0)],
        "_row_id_to_target": row_id_to_target,
        "_article_id_to_target": article_id_to_target,
    }


def build_report_plan(
    rows: list[dict[str, Any]],
    article_plan: dict[str, Any],
    preview_limit: int,
) -> dict[str, Any]:
    row_id_to_target = article_plan["_row_id_to_target"]
    article_id_to_target = article_plan["_article_id_to_target"]
    importable = []
    skipped = []
    status_counts = Counter()
    type_counts = Counter()
    reference_totals = {
        "reports_checked": 0,
        "total_refs": 0,
        "resolved_refs": 0,
        "unresolved_refs": 0,
        "invalid_source_article_ids_json": 0,
    }
    reference_gap_samples = []

    for row in rows:
        report_type = clean_text(row.get("report_type"))
        status = clean_text(row.get("status"))
        type_counts[report_type or ""] += 1
        status_counts[status or ""] += 1
        identity = str(row.get("id"))
        skip_reasons = report_skip_reasons(row, report_type)
        refs, invalid_json = parse_report_refs(row.get("source_article_ids_json"))
        resolved_refs = []
        unresolved_refs = []
        if invalid_json:
            reference_totals["invalid_source_article_ids_json"] += 1
        for ref in refs:
            ref_text = str(ref)
            target = row_id_to_target.get(ref_text) or article_id_to_target.get(ref_text)
            if target:
                resolved_refs.append({"legacy_ref": ref_text, "target_key": target})
            else:
                unresolved_refs.append(ref_text)
        reference_totals["reports_checked"] += 1
        reference_totals["total_refs"] += len(refs)
        reference_totals["resolved_refs"] += len(resolved_refs)
        reference_totals["unresolved_refs"] += len(unresolved_refs)
        if unresolved_refs and len(reference_gap_samples) < 10:
            reference_gap_samples.append(
                {
                    "legacy_report_id": identity,
                    "title": clean_text(row.get("title")),
                    "unresolved_refs": unresolved_refs[:10],
                }
            )

        if skip_reasons:
            skipped.append(
                {
                    "legacy_report_id": identity,
                    "target_key": target_key("reports", identity),
                    "report_type": report_type,
                    "status": status,
                    "reasons": skip_reasons,
                }
            )
            continue

        importable.append(
            report_preview(
                row,
                identity,
                report_type,
                resolved_refs,
                unresolved_refs,
                invalid_json=invalid_json,
            )
        )

    return {
        "total": len(rows),
        "importable": len(importable),
        "skipped": len(skipped),
        "supported_report_types": sorted(SUPPORTED_REPORT_TYPES),
        "target_statuses": {
            "published_like": REPORT_PUBLISHED_STATUS,
            "draft_or_other": REPORT_DRAFT_STATUS,
        },
        "type_counts": dict(type_counts),
        "status_counts": dict(status_counts),
        "reference_totals": reference_totals,
        "reference_gap_samples": reference_gap_samples,
        "skip_reason_counts": count_reasons(skipped),
        "previews": importable[: max(preview_limit, 0)],
    }


def load_source_ids(conn: Any) -> set[str]:
    if not table_exists(conn, "sources"):
        return set()
    return {
        clean_text(row["source_id"])
        for row in conn.execute("SELECT source_id FROM sources WHERE source_id IS NOT NULL")
        if clean_text(row["source_id"])
    }


def fetch_rows(conn: Any, table: str) -> list[dict[str, Any]]:
    if not table_exists(conn, table):
        return []
    rows = conn.execute(f"SELECT * FROM {quote_identifier(table)} ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def table_exists(conn: Any, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def article_skip_reasons(row: dict[str, Any], identity: str) -> list[str]:
    reasons = []
    if not identity:
        reasons.append("missing_identity")
    if not clean_text(row.get("title")):
        reasons.append("missing_title")
    if not (clean_text(row.get("normalized_url")) or clean_text(row.get("url"))):
        reasons.append("missing_url")
    return reasons


def report_skip_reasons(row: dict[str, Any], report_type: str) -> list[str]:
    reasons = []
    if not clean_text(row.get("title")):
        reasons.append("missing_title")
    if not clean_text(row.get("content")):
        reasons.append("missing_content")
    if report_type not in SUPPORTED_REPORT_TYPES:
        reasons.append("unsupported_report_type")
    return reasons


def article_preview(row: dict[str, Any], identity: str, source_id: str) -> dict[str, Any]:
    publish_time = parse_optional_datetime(row.get("publish_time"))
    crawled_at = parse_optional_datetime(row.get("crawled_at"))
    return {
        "legacy_table": "articles",
        "legacy_row_id": str(row.get("id")),
        "legacy_article_id": clean_text(row.get("article_id")),
        "target_key": target_key("articles", identity),
        "target_type": "raw_items",
        "target_status": ARTICLE_IMPORT_STATUS,
        "entry_key": f"legacy-tech-insight-loop:{identity}",
        "source_lookup": {
            "legacy_source_id": source_id,
            "source_name": clean_text(row.get("source_name")),
        },
        "target_fields": {
            "source_title": clean_text(row.get("title")),
            "source_url": clean_text(row.get("url")) or clean_text(row.get("normalized_url")),
            "source_name": clean_text(row.get("source_name")),
            "published_at": publish_time,
            "fetched_at": crawled_at,
            "source_type": "legacy_tech_insight_loop",
            "raw_payload_json_path": "legacy_tech_insight_loop",
        },
        "archive_news_candidate": has_model_archive_candidate(row),
        "original_scoring": {
            "admission_level": clean_text(row.get("admission_level")),
            "info_pool": clean_text(row.get("info_pool")),
            "quality_status": clean_text(row.get("quality_status")),
            "report_status": clean_text(row.get("report_status")),
        },
    }


def report_preview(
    row: dict[str, Any],
    identity: str,
    report_type: str,
    resolved_refs: list[dict[str, str]],
    unresolved_refs: list[str],
    invalid_json: bool,
) -> dict[str, Any]:
    period_start = parse_optional_datetime(row.get("period_start"))
    period_end = parse_optional_datetime(row.get("period_end"))
    return {
        "legacy_table": "reports",
        "legacy_report_id": identity,
        "target_key": target_key("reports", identity),
        "target_type": "historical_reports",
        "target_status": map_report_status(row.get("status")),
        "target_fields": {
            "title": clean_text(row.get("title")),
            "summary": "",
            "period_start": period_start,
            "period_end": period_end,
            "day_key": period_start[:10] if report_type == "daily" and period_start else "",
            "week_key": week_key_from_period_start(period_start) if report_type == "weekly" else "",
            "content_storage": "historical_reports.content",
        },
        "source_article_refs": {
            "invalid_json": invalid_json,
            "total": len(resolved_refs) + len(unresolved_refs),
            "resolved": len(resolved_refs),
            "unresolved": len(unresolved_refs),
            "resolved_preview": resolved_refs[:10],
            "unresolved_preview": unresolved_refs[:10],
        },
    }


def parse_report_refs(value: Any) -> tuple[list[Any], bool]:
    text = clean_text(value)
    if not text:
        return [], False
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [], True
    if not isinstance(parsed, list):
        return [], True
    return parsed, False


def update_datetime_quality(stats: dict[str, int], field: str, value: Any) -> None:
    text = clean_text(value)
    if not text:
        stats[f"{field}_missing"] += 1
    elif parse_datetime_value(text) is None:
        stats[f"{field}_failed"] += 1


def parse_optional_datetime(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parsed = parse_datetime_value(text)
    return parsed.isoformat() if parsed else ""


def has_model_archive_candidate(row: dict[str, Any]) -> bool:
    return any(
        clean_text(row.get(field))
        for field in ("model_title", "model_summary", "model_effect", "model_payload_json")
    )


def map_report_status(value: Any) -> str:
    status = clean_text(value)
    if status in {"已生成", "published", "completed"}:
        return REPORT_PUBLISHED_STATUS
    return REPORT_DRAFT_STATUS


def week_key_from_period_start(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def target_key(table: str, identity: str) -> str:
    return f"tech_insight_loop:{table}:{identity}"


def count_reasons(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        counts.update(item.get("reasons", []))
    return dict(counts)


def strip_internal_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_internal_keys(item)
            for key, item in value.items()
            if not key.startswith("_")
        }
    if isinstance(value, list):
        return [strip_internal_keys(item) for item in value]
    return value


def write_dry_run_outputs(dry_run: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    public_dry_run = strip_internal_keys(dry_run)
    json_path = output_dir / "tech_insight_loop_legacy_dry_run.json"
    markdown_path = output_dir / "tech_insight_loop_legacy_dry_run.md"
    json_path.write_text(
        json.dumps(public_dry_run, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(public_dry_run), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def render_markdown(dry_run: dict[str, Any]) -> str:
    article = dry_run["articles"]
    report = dry_run["reports"]
    lines = [
        "# Tech Insight Loop 历史导入 Dry Run",
        "",
        f"- 生成时间：`{dry_run['generated_at']}`",
        f"- SQLite：`{dry_run['input']['sqlite_path']}`",
        f"- SHA256：`{dry_run['input']['sqlite_sha256']}`",
        "",
        "## 禁区",
        "",
    ]
    for guardrail in dry_run["guardrails"]:
        lines.append(f"- `{guardrail}`")
    lines.extend(
        [
            "",
            "## Articles",
            "",
            f"- 总数：{article['total']}",
            f"- 可导入：{article['importable']}",
            f"- 跳过：{article['skipped']}",
            f"- 可生成历史 news 草稿候选：{article['model_archive_candidates']}",
            "",
            "## Reports",
            "",
            f"- 总数：{report['total']}",
            f"- 可导入：{report['importable']}",
            f"- 跳过：{report['skipped']}",
            f"- 引用总数：{report['reference_totals']['total_refs']}",
            f"- 已解析引用：{report['reference_totals']['resolved_refs']}",
            f"- 未解析引用：{report['reference_totals']['unresolved_refs']}",
            "",
            "## 下一步",
            "",
        ]
    )
    for step in dry_run["next_import_order"]:
        lines.append(f"- `{step}`")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
