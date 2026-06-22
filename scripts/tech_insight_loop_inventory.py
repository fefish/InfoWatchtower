#!/usr/bin/env python3
"""Read-only inventory for Tech Insight Loop legacy assets.

The script inspects the legacy SQLite database and writes a repeatable inventory
report plus migration-preview metadata. It never writes to the legacy database or
to the InfoWatchtower application database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = ROOT / "references/参考工具/data/insight_loop.sqlite3"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/tech_insight_loop"

CORE_EXPECTED_COUNTS: dict[str, int] = {
    "sources": 386,
    "articles": 14834,
    "reports": 66,
    "ai_entities": 23,
    "entity_milestones": 275,
    "feedback": 4,
    "article_quality_feedback": 4,
    "jobs": 257,
}

TARGET_MAPPINGS: dict[str, dict[str, Any]] = {
    "sources": {
        "target": "data_sources",
        "identity_column": "source_id",
        "status": "implemented_in_first_round",
        "rule": "Already imported through /api/sources/import-tech-insight-loop.",
    },
    "articles": {
        "target": "raw_items + optional archived news_items",
        "identity_column": "article_id",
        "status": "next_import_batch",
        "guardrails": [
            "store full legacy row in raw_items.raw_payload_json.legacy_tech_insight_loop",
            "do not auto-create ready generated_news",
            "do not auto-enter recommendation_runs",
            "do not enter company SQL",
        ],
    },
    "reports": {
        "target": "historical_reports archive; optional daily/weekly views later",
        "identity_column": "id",
        "status": "next_import_batch",
        "guardrails": [
            "use imported or published_imported status",
            "preserve source_article_ids_json lineage",
            "do not export through standard company SQL",
        ],
    },
    "ai_entities": {
        "target": "tracked_entities",
        "identity_column": "id",
        "status": "requires_new_model",
        "guardrails": ["entity records are timeline metadata, not news categories"],
    },
    "entity_milestones": {
        "target": "entity_milestones",
        "identity_column": "id",
        "status": "requires_new_model",
        "guardrails": [
            "preserve source URL and legacy article/report references",
            "editing milestones must not mutate raw/news/report source records",
        ],
    },
    "feedback": {
        "target": "historical feedback archive",
        "identity_column": "id",
        "status": "later_quality_batch",
    },
    "article_quality_feedback": {
        "target": "historical quality feedback archive",
        "identity_column": "id",
        "status": "later_quality_batch",
    },
    "jobs": {
        "target": "ingestion_runs archive summary",
        "identity_column": "id",
        "status": "later_quality_batch",
        "guardrails": ["migrate statistics and failure reasons only, not old task state machine"],
    },
}

DATE_COLUMNS = {
    "publish_time",
    "crawled_at",
    "created_at",
    "updated_at",
    "model_processed_at",
    "scorer_updated_at",
    "entity_milestone_processed_at",
    "event_time",
    "period_start",
    "period_end",
    "deleted_at",
    "started_at",
    "completed_at",
}

URL_COLUMNS = {"url", "normalized_url", "source_url", "source_website_url"}
URL_RE = re.compile(r"^(https?://|wx://|rsshub://)", re.IGNORECASE)


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
        help="Directory for JSON and Markdown inventory reports.",
    )
    parser.add_argument("--preview-limit", type=int, default=5)
    parser.add_argument("--no-write", action="store_true", help="Print JSON summary only.")
    args = parser.parse_args()

    inventory = build_inventory(args.sqlite_path, preview_limit=args.preview_limit)
    if args.no_write:
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return 0

    outputs = write_inventory_outputs(inventory, args.output_dir)
    print(f"wrote {outputs['json']}")
    print(f"wrote {outputs['markdown']}")
    return 0


def build_inventory(sqlite_path: Path, preview_limit: int = 5) -> dict[str, Any]:
    sqlite_path = sqlite_path.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    with connect_readonly(sqlite_path) as conn:
        tables = list_tables(conn)
        table_stats = {
            table: inspect_table(conn, table)
            for table in tables
        }
        core_counts = build_core_counts(table_stats)
        date_quality = inspect_date_quality(conn, table_stats)
        url_quality = inspect_url_quality(conn, table_stats)
        json_quality = inspect_json_quality(conn, table_stats)
        relationship_checks = inspect_relationships(conn, table_stats)
        mapping_previews = build_mapping_previews(conn, table_stats, preview_limit)
        report_breakdown = grouped_counts(conn, "reports", ["report_type", "status"])
        article_breakdown = grouped_counts(
            conn,
            "articles",
            ["quality_status", "report_status", "admission_level", "info_pool"],
        )
        entity_breakdown = grouped_counts(conn, "ai_entities", ["entity_type", "rank"])
        milestone_breakdown = grouped_counts(
            conn,
            "entity_milestones",
            ["importance_level", "event_type"],
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "input": {
            "sqlite_path": str(sqlite_path),
            "sqlite_sha256": sha256_file(sqlite_path),
            "sqlite_size_bytes": sqlite_path.stat().st_size,
        },
        "guardrails": [
            "read_only_inventory_only",
            "do_not_run_legacy_app_py",
            "do_not_copy_sqlite_tables_to_main_db",
            "historical_assets_do_not_auto_enter_recommendation",
            "historical_assets_do_not_enter_company_sql",
            "company_sql_contract_unchanged",
        ],
        "core_counts": core_counts,
        "tables": table_stats,
        "quality": {
            "date_fields": date_quality,
            "url_fields": url_quality,
            "json_fields": json_quality,
            "relationships": relationship_checks,
        },
        "breakdowns": {
            "reports": report_breakdown,
            "articles": article_breakdown,
            "ai_entities": entity_breakdown,
            "entity_milestones": milestone_breakdown,
        },
        "target_mappings": TARGET_MAPPINGS,
        "mapping_previews": mapping_previews,
        "next_batches": [
            "articles_to_raw_items_archive",
            "reports_to_imported_daily_weekly_reports",
            "ai_entities_and_entity_milestones_models",
            "quality_feedback_and_job_history_archive",
        ],
    }


def connect_readonly(sqlite_path: Path) -> sqlite3.Connection:
    uri = f"{sqlite_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def inspect_table(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    columns = []
    quoted = quote_identifier(table)
    row_count = int(conn.execute(f"SELECT COUNT(*) AS c FROM {quoted}").fetchone()["c"])
    for row in conn.execute(f"PRAGMA table_info({quoted})").fetchall():
        column = str(row["name"])
        columns.append(
            {
                "name": column,
                "type": str(row["type"] or ""),
                "not_null": bool(row["notnull"]),
                "primary_key": bool(row["pk"]),
                "default": row["dflt_value"],
                "stats": column_stats(conn, table, column),
            }
        )
    return {"row_count": row_count, "columns": columns}


def column_stats(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    q_table = quote_identifier(table)
    q_col = quote_identifier(column)
    row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN {q_col} IS NULL THEN 1 ELSE 0 END) AS null_count,
            SUM(CASE WHEN {q_col} IS NOT NULL AND TRIM(CAST({q_col} AS TEXT)) = '' THEN 1 ELSE 0 END)
                AS blank_count,
            COUNT(DISTINCT {q_col}) AS distinct_count
        FROM {q_table}
        """
    ).fetchone()
    return {
        "null_count": int(row["null_count"] or 0),
        "blank_count": int(row["blank_count"] or 0),
        "distinct_count": int(row["distinct_count"] or 0),
    }


def build_core_counts(table_stats: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for table, expected in CORE_EXPECTED_COUNTS.items():
        actual = table_stats.get(table, {}).get("row_count")
        counts[table] = {
            "expected": expected,
            "actual": actual,
            "status": "ok" if actual == expected else "mismatch",
        }
    return counts


def inspect_date_quality(
    conn: sqlite3.Connection,
    table_stats: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for table, stats in table_stats.items():
        for column in column_names(stats):
            if not is_date_column(column):
                continue
            values = fetch_column_values(conn, table, column)
            result.setdefault(table, {})[column] = parse_datetime_stats(values)
    return result


def inspect_url_quality(
    conn: sqlite3.Connection,
    table_stats: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for table, stats in table_stats.items():
        for column in column_names(stats):
            if not is_url_column(column):
                continue
            values = fetch_column_values(conn, table, column)
            missing = 0
            invalid = 0
            invalid_samples = []
            for value in values:
                text = clean_text(value)
                if not text:
                    missing += 1
                elif not URL_RE.search(text):
                    invalid += 1
                    if len(invalid_samples) < 5:
                        invalid_samples.append(text[:200])
            result.setdefault(table, {})[column] = {
                "total": len(values),
                "missing": missing,
                "invalid_non_empty": invalid,
                "invalid_samples": invalid_samples,
            }
    return result


def inspect_json_quality(
    conn: sqlite3.Connection,
    table_stats: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for table, stats in table_stats.items():
        for column in column_names(stats):
            if not is_json_column(column):
                continue
            values = fetch_column_values(conn, table, column)
            missing = 0
            valid = 0
            invalid = 0
            invalid_samples = []
            for value in values:
                text = clean_text(value)
                if not text:
                    missing += 1
                    continue
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    invalid += 1
                    if len(invalid_samples) < 5:
                        invalid_samples.append(text[:200])
                else:
                    valid += 1
            result.setdefault(table, {})[column] = {
                "total": len(values),
                "missing": missing,
                "valid": valid,
                "invalid": invalid,
                "invalid_samples": invalid_samples,
            }
    return result


def inspect_relationships(
    conn: sqlite3.Connection,
    table_stats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if {"entity_milestones", "ai_entities", "articles"}.issubset(table_stats):
        checks["entity_milestones"] = {
            "missing_entity_refs": scalar_count(
                conn,
                """
                SELECT COUNT(*)
                FROM entity_milestones em
                LEFT JOIN ai_entities e ON e.id = em.entity_id
                WHERE e.id IS NULL
                """,
            ),
            "missing_article_refs": scalar_count(
                conn,
                """
                SELECT COUNT(*)
                FROM entity_milestones em
                LEFT JOIN articles a ON a.id = em.article_id
                WHERE a.id IS NULL
                """,
            ),
        }
    if {"entity_milestones", "reports"}.issubset(table_stats):
        checks.setdefault("entity_milestones", {})["missing_report_refs"] = scalar_count(
            conn,
            """
            SELECT COUNT(*)
            FROM entity_milestones em
            LEFT JOIN reports r ON r.id = em.report_id
            WHERE em.report_id IS NOT NULL AND r.id IS NULL
            """,
        )
    if {"reports", "articles"}.issubset(table_stats):
        checks["reports_source_article_ids"] = inspect_report_article_refs(conn)
    return checks


def inspect_report_article_refs(conn: sqlite3.Connection) -> dict[str, Any]:
    article_ids = {
        str(row["article_id"])
        for row in conn.execute("SELECT article_id FROM articles WHERE article_id IS NOT NULL")
    }
    article_row_ids = {
        str(row["id"])
        for row in conn.execute("SELECT id FROM articles WHERE id IS NOT NULL")
    }
    rows = conn.execute("SELECT id, source_article_ids_json FROM reports").fetchall()
    invalid_json = 0
    total_refs = 0
    unresolved_refs = 0
    invalid_samples = []
    for row in rows:
        text = clean_text(row["source_article_ids_json"])
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            invalid_json += 1
            if len(invalid_samples) < 5:
                invalid_samples.append({"report_id": row["id"], "value": text[:200]})
            continue
        refs = parsed if isinstance(parsed, list) else []
        total_refs += len(refs)
        unresolved_refs += sum(
            1
            for ref in refs
            if str(ref) not in article_ids and str(ref) not in article_row_ids
        )
    return {
        "reports_checked": len(rows),
        "invalid_json": invalid_json,
        "total_refs": total_refs,
        "unresolved_refs": unresolved_refs,
        "invalid_samples": invalid_samples,
    }


def build_mapping_previews(
    conn: sqlite3.Connection,
    table_stats: dict[str, dict[str, Any]],
    preview_limit: int,
) -> dict[str, list[dict[str, Any]]]:
    previews: dict[str, list[dict[str, Any]]] = {}
    for table in TARGET_MAPPINGS:
        if table not in table_stats:
            continue
        rows = fetch_preview_rows(conn, table, preview_limit)
        previews[table] = [preview_row(table, row) for row in rows]
    return previews


def preview_row(table: str, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    if table == "articles":
        legacy_id = clean_text(data.get("article_id")) or str(data.get("id"))
        return {
            "legacy_table": table,
            "legacy_id": legacy_id,
            "target_type": "raw_items + optional archived news_items",
            "target_key": f"tech_insight_loop:articles:{legacy_id}",
            "target_fields": {
                "source_title": data.get("title"),
                "source_url": data.get("url"),
                "published_at": data.get("publish_time"),
                "source_name": data.get("source_name"),
                "board": data.get("board"),
                "admission_level": data.get("admission_level"),
                "report_status": data.get("report_status"),
                "raw_payload_json_path": "legacy_tech_insight_loop",
            },
            "guardrails": TARGET_MAPPINGS[table]["guardrails"],
        }
    if table == "reports":
        report_type = clean_text(data.get("report_type"))
        target_type = "historical_reports" if report_type in {"daily", "weekly"} else "later_archive"
        refs = parse_json_list(data.get("source_article_ids_json"))
        return {
            "legacy_table": table,
            "legacy_id": str(data.get("id")),
            "target_type": target_type,
            "target_key": f"tech_insight_loop:reports:{data.get('id')}",
            "target_fields": {
                "report_type": report_type,
                "title": data.get("title"),
                "period_start": data.get("period_start"),
                "period_end": data.get("period_end"),
                "target_status": "published_imported",
                "source_article_ref_count": len(refs),
            },
            "guardrails": TARGET_MAPPINGS[table]["guardrails"],
        }
    if table == "ai_entities":
        return {
            "legacy_table": table,
            "legacy_id": str(data.get("id")),
            "target_type": "tracked_entities",
            "target_key": f"tech_insight_loop:ai_entities:{data.get('id')}",
            "target_fields": {
                "name": data.get("name"),
                "entity_type": data.get("entity_type"),
                "rank": data.get("rank"),
                "influence_score": data.get("influence_score"),
            },
            "guardrails": TARGET_MAPPINGS[table]["guardrails"],
        }
    if table == "entity_milestones":
        return {
            "legacy_table": table,
            "legacy_id": str(data.get("id")),
            "target_type": "entity_milestones",
            "target_key": f"tech_insight_loop:entity_milestones:{data.get('id')}",
            "target_fields": {
                "legacy_entity_id": data.get("entity_id"),
                "legacy_article_row_id": data.get("article_id"),
                "legacy_report_id": data.get("report_id"),
                "event_time": data.get("event_time"),
                "event_title": data.get("event_title"),
                "importance_level": data.get("importance_level"),
                "source_url": data.get("source_url"),
            },
            "guardrails": TARGET_MAPPINGS[table]["guardrails"],
        }
    mapping = TARGET_MAPPINGS.get(table, {})
    identity = clean_text(data.get(mapping.get("identity_column", "id"))) or str(data.get("id"))
    return {
        "legacy_table": table,
        "legacy_id": identity,
        "target_type": mapping.get("target", "archive"),
        "target_key": f"tech_insight_loop:{table}:{identity}",
        "target_fields": compact_dict(data, limit=8),
        "guardrails": mapping.get("guardrails", []),
    }


def fetch_preview_rows(
    conn: sqlite3.Connection,
    table: str,
    preview_limit: int,
) -> list[sqlite3.Row]:
    order_col = "id"
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})")}
    if order_col not in columns:
        order_col = sorted(columns)[0]
    return conn.execute(
        f"""
        SELECT *
        FROM {quote_identifier(table)}
        ORDER BY {quote_identifier(order_col)}
        LIMIT ?
        """,
        (max(preview_limit, 0),),
    ).fetchall()


def grouped_counts(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
) -> dict[str, list[dict[str, Any]]]:
    existing_columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for column in columns:
        if column not in existing_columns:
            continue
        q_col = quote_identifier(column)
        rows = conn.execute(
            f"""
            SELECT {q_col} AS value, COUNT(*) AS count
            FROM {quote_identifier(table)}
            GROUP BY {q_col}
            ORDER BY count DESC, value
            LIMIT 50
            """
        ).fetchall()
        result[column] = [{"value": row["value"], "count": int(row["count"])} for row in rows]
    return result


def write_inventory_outputs(inventory: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "tech_insight_loop_inventory.json"
    markdown_path = output_dir / "tech_insight_loop_inventory.md"
    json_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(inventory), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def render_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# Tech Insight Loop 只读资产盘点",
        "",
        f"- 生成时间：`{inventory['generated_at']}`",
        f"- SQLite：`{inventory['input']['sqlite_path']}`",
        f"- SHA256：`{inventory['input']['sqlite_sha256']}`",
        f"- 大小：`{inventory['input']['sqlite_size_bytes']}` bytes",
        "",
        "## 核心数量",
        "",
        "| 表 | 预期 | 实际 | 状态 |",
        "| --- | ---: | ---: | --- |",
    ]
    for table, stats in inventory["core_counts"].items():
        lines.append(
            f"| `{table}` | {stats['expected']} | {stats['actual']} | {stats['status']} |"
        )

    lines.extend(["", "## 迁移边界", ""])
    for guardrail in inventory["guardrails"]:
        lines.append(f"- `{guardrail}`")

    lines.extend(["", "## 目标映射", ""])
    lines.extend(["| 旧表 | 目标 | 状态 |", "| --- | --- | --- |"])
    for table, mapping in inventory["target_mappings"].items():
        lines.append(f"| `{table}` | {mapping.get('target', '')} | {mapping.get('status', '')} |")

    lines.extend(["", "## 质量摘要", ""])
    lines.append("### 日期字段")
    lines.append("")
    lines.append("| 表.字段 | 总数 | 可解析 | 缺失 | 失败 |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for table, fields in inventory["quality"]["date_fields"].items():
        for column, stats in fields.items():
            lines.append(
                f"| `{table}.{column}` | {stats['total']} | {stats['parsed']} | "
                f"{stats['missing']} | {stats['failed']} |"
            )

    lines.extend(["", "### URL 字段", ""])
    lines.append("| 表.字段 | 总数 | 缺失 | 非空但格式异常 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for table, fields in inventory["quality"]["url_fields"].items():
        for column, stats in fields.items():
            lines.append(
                f"| `{table}.{column}` | {stats['total']} | {stats['missing']} | "
                f"{stats['invalid_non_empty']} |"
            )

    lines.extend(["", "### JSON 字段", ""])
    lines.append("| 表.字段 | 总数 | 有效 | 缺失 | 失败 |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for table, fields in inventory["quality"]["json_fields"].items():
        for column, stats in fields.items():
            lines.append(
                f"| `{table}.{column}` | {stats['total']} | {stats['valid']} | "
                f"{stats['missing']} | {stats['invalid']} |"
            )

    lines.extend(["", "## 关系检查", ""])
    lines.append("```json")
    lines.append(json.dumps(inventory["quality"]["relationships"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.extend(
        [
            "",
            "## 下一批次",
            "",
        ]
    )
    for item in inventory["next_batches"]:
        lines.append(f"- `{item}`")
    lines.append("")
    return "\n".join(lines)


def parse_datetime_stats(values: list[Any]) -> dict[str, Any]:
    missing = 0
    parsed = 0
    failed = 0
    failed_samples = []
    for value in values:
        text = clean_text(value)
        if not text:
            missing += 1
            continue
        if parse_datetime_value(text) is None:
            failed += 1
            if len(failed_samples) < 5:
                failed_samples.append(text[:200])
        else:
            parsed += 1
    return {
        "total": len(values),
        "parsed": parsed,
        "missing": missing,
        "failed": failed,
        "failed_samples": failed_samples,
    }


def parse_datetime_value(text: str) -> datetime | None:
    text = text.strip()
    if not text:
        return None
    candidates = [
        text,
        text.replace("Z", "+00:00"),
        text.replace("/", "-"),
    ]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def is_date_column(column: str) -> bool:
    return column in DATE_COLUMNS


def is_url_column(column: str) -> bool:
    return column in URL_COLUMNS or column.endswith("_url")


def is_json_column(column: str) -> bool:
    return column.endswith("_json") or column.endswith("_payload_json")


def column_names(table_stats: dict[str, Any]) -> list[str]:
    return [str(column["name"]) for column in table_stats.get("columns", [])]


def fetch_column_values(conn: sqlite3.Connection, table: str, column: str) -> list[Any]:
    rows = conn.execute(
        f"SELECT {quote_identifier(column)} AS value FROM {quote_identifier(table)}"
    ).fetchall()
    return [row["value"] for row in rows]


def scalar_count(conn: sqlite3.Connection, query: str) -> int:
    return int(conn.execute(query).fetchone()[0])


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_json_list(value: Any) -> list[Any]:
    text = clean_text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def compact_dict(data: dict[str, Any], limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(data)[:limit]:
        value = data[key]
        if isinstance(value, str) and len(value) > 200:
            value = value[:200] + "..."
        result[key] = value
    return result


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
