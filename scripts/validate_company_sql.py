#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREVIEW_GLOB = REPO_ROOT / "outputs/sql/previews/*.sql"
DEFAULT_BASELINE = (
    REPO_ROOT
    / "outputs/sql/previews/planning_intel_2026-05-05_company_sql_preview.sql"
)

EXPECTED_COLUMNS = {
    "ai_journal": ["source_url", "source_title", "content", "created_at"],
    "ai_journal_focus": ["journal_id", "focus_id"],
    "ai_journal_analysis": [
        "journal_id",
        "category",
        "title",
        "summary",
        "key_points",
        "content_json",
        "source_url",
        "created_at",
    ],
    "t_news_data_info": [
        "catalog_id",
        "journal_id",
        "data",
        "adoption_status",
        "category",
        "title",
        "summary",
        "key_points",
        "content_json",
        "source_url",
    ],
}

TABLE_ORDER = [
    "ai_journal",
    "ai_journal_focus",
    "ai_journal_analysis",
    "t_news_data_info",
]

CONTENT_JSON_FIELDS = [
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact",
]

DISALLOWED_CONTENT_JSON_FIELDS = {
    "source",
    "recommendationReason",
    "news_item_id",
    "raw_item_id",
    "data_source_id",
}

AI_SQL_CATEGORIES = {
    "AI Infra",
    "AI 应用",
    "测评技术",
    "大厂动态",
    "模型",
    "算法",
    "推理加速",
    "训练技术",
    "智能体",
    "基础竞争力",
}

DATETIME_LITERAL_RE = re.compile(r"^'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'$")
HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
INSERT_LINE_RE = re.compile(r"^INSERT (?:IGNORE INTO|INTO) .+;$", re.MULTILINE)


@dataclass
class ValidationIssue:
    path: Path
    item_index: int | None
    field: str
    message: str

    def render(self) -> str:
        item = "-" if self.item_index is None else str(self.item_index)
        return f"{self.path}: item={item} field={self.field}: {self.message}"


@dataclass
class ParsedStatement:
    table: str
    columns: list[str]
    raw: str
    values: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate InfoWatchtower company SQL previews against the 2026-05-05 "
            "legacy-compatible baseline."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="SQL files to validate. Defaults to outputs/sql/previews/*.sql.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Baseline SQL file used to lock column order. Defaults to the 2026-05-05 preview.",
    )
    parser.add_argument(
        "--fix-headers",
        action="store_true",
        help="Rewrite SQL file headers to the canonical InfoWatchtower title block.",
    )
    args = parser.parse_args()

    files = args.files or sorted(Path(REPO_ROOT / "outputs/sql/previews").glob("*.sql"))
    files = [path if path.is_absolute() else REPO_ROOT / path for path in files]
    baseline = args.baseline if args.baseline.is_absolute() else REPO_ROOT / args.baseline

    issues: list[ValidationIssue] = []
    if not baseline.exists():
        issues.append(ValidationIssue(baseline, None, "baseline", "baseline file does not exist"))
    else:
        baseline_schema = extract_schema(baseline)
        for table, expected_columns in EXPECTED_COLUMNS.items():
            if baseline_schema.get(table) != expected_columns:
                issues.append(
                    ValidationIssue(
                        baseline,
                        None,
                        f"{table}.columns",
                        f"baseline columns {baseline_schema.get(table)} != expected {expected_columns}",
                    ),
                )

    if issues:
        print_issues(issues)
        return 1

    fixed_headers: list[Path] = []
    all_stats: dict[Path, dict[str, int]] = {}
    for path in files:
        if not path.exists():
            issues.append(ValidationIssue(path, None, "file", "file does not exist"))
            continue
        if path.suffix.lower() != ".sql":
            continue
        if args.fix_headers and normalize_header(path, baseline):
            fixed_headers.append(path)
        file_issues, stats = validate_file(path)
        issues.extend(file_issues)
        all_stats[path] = stats

    if fixed_headers:
        for path in fixed_headers:
            print(f"fixed header: {relative(path)}")

    if issues:
        print_issues(issues)
        return 1

    for path, stats in all_stats.items():
        print(
            f"ok: {relative(path)} "
            f"items={stats['items']} statements={stats['statements']} "
            f"analysis={stats['ai_journal_analysis']}"
        )
    return 0


def print_issues(issues: Iterable[ValidationIssue]) -> None:
    print("company SQL validation failed:", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue.render()}", file=sys.stderr)


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def validate_file(path: Path) -> tuple[list[ValidationIssue], dict[str, int]]:
    sql_text = path.read_text(encoding="utf-8")
    body_start = find_body_start(sql_text)
    body_text = sql_text[body_start:] if body_start is not None else sql_text
    issues: list[ValidationIssue] = []

    if not sql_text.startswith("-- InfoWatchtower Company SQL Preview\n"):
        issues.append(
            ValidationIssue(path, None, "header", "header is not canonical; run with --fix-headers"),
        )
    if "STR_TO_DATE(" in body_text:
        issues.append(ValidationIssue(path, None, "created_at", "STR_TO_DATE is forbidden"))
    if re.search(r"^-- ===== .*\.sql =====$", body_text, re.MULTILINE):
        issues.append(
            ValidationIssue(path, None, "section_header", "section header must not contain file paths"),
        )
    if re.search(r"^-- ===== (\d{4}-\d{2}-\d{2}) \1 ", body_text, re.MULTILINE):
        issues.append(
            ValidationIssue(path, None, "section_header", "section header repeats the date"),
        )
    if re.search(r"\bcreated_at\b[^;\n]*\bNULL\b|\bNULL\b[^;\n]*\bcreated_at\b", body_text):
        issues.append(ValidationIssue(path, None, "created_at", "created_at must not be NULL"))
    if re.search(r"<\s*/?\s*(span|p|script|style|div|br|a)\b", body_text, re.IGNORECASE):
        issues.append(ValidationIssue(path, None, "html", "exported SQL contains HTML tags"))

    insert_lines = INSERT_LINE_RE.findall(body_text)
    if not insert_lines:
        issues.append(ValidationIssue(path, None, "statements", "no INSERT statements found"))
        return issues, empty_stats()
    if len(insert_lines) % 4 != 0:
        issues.append(
            ValidationIssue(path, None, "statements", "statement count is not a multiple of 4"),
        )

    stats = empty_stats()
    stats["statements"] = len(insert_lines)
    stats["items"] = len(insert_lines) // 4

    for item_index, offset in enumerate(range(0, len(insert_lines), 4), start=1):
        item_statements = insert_lines[offset : offset + 4]
        if len(item_statements) < 4:
            break
        parsed = [parse_statement(statement) for statement in item_statements]
        for parsed_statement in parsed:
            if parsed_statement.table:
                stats[parsed_statement.table] += 1
        issues.extend(validate_item(path, item_index, parsed))

    return issues, stats


def empty_stats() -> dict[str, int]:
    stats = {table: 0 for table in TABLE_ORDER}
    stats["items"] = 0
    stats["statements"] = 0
    return stats


def validate_item(path: Path, item_index: int, statements: list[ParsedStatement]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    tables = [statement.table for statement in statements]
    if tables != TABLE_ORDER:
        issues.append(
            ValidationIssue(path, item_index, "table_order", f"{tables} != {TABLE_ORDER}"),
        )
        return issues

    for statement in statements:
        expected_columns = EXPECTED_COLUMNS[statement.table]
        if statement.columns != expected_columns:
            issues.append(
                ValidationIssue(
                    path,
                    item_index,
                    f"{statement.table}.columns",
                    f"{statement.columns} != {expected_columns}",
                ),
            )

    journal, focus, analysis, data_info = statements
    if len(journal.values) != 4:
        issues.append(ValidationIssue(path, item_index, "ai_journal.values", "expected 4 values"))
        return issues

    source_url = unquote_sql_literal(journal.values[0])
    source_title = unquote_sql_literal(journal.values[1])
    raw_content = unquote_sql_literal(journal.values[2])
    created_at = journal.values[3].strip()

    issues.extend(require_non_empty(path, item_index, "ai_journal.source_url", source_url))
    issues.extend(require_non_empty(path, item_index, "ai_journal.source_title", source_title))
    issues.extend(require_non_empty(path, item_index, "ai_journal.content", raw_content))
    issues.extend(require_no_html(path, item_index, "ai_journal.source_title", source_title))
    issues.extend(require_no_html(path, item_index, "ai_journal.content", raw_content))
    issues.extend(require_datetime(path, item_index, "ai_journal.created_at", created_at))

    focus_id = parse_focus_statement(focus)
    if focus_id is None:
        issues.append(ValidationIssue(path, item_index, "ai_journal_focus.focus_id", "invalid focus SELECT"))
    elif focus_id < 0:
        issues.append(ValidationIssue(path, item_index, "ai_journal_focus.focus_id", "must be >= 0"))
    focus_url = parse_where_source_url(focus.raw)
    if focus_url != source_url:
        issues.append(
            ValidationIssue(path, item_index, "ai_journal_focus.source_url", "does not match ai_journal.source_url"),
        )

    analysis_values = parse_select_values(analysis, expected_prefix="id")
    if len(analysis_values) != 7:
        issues.append(
            ValidationIssue(path, item_index, "ai_journal_analysis.values", "expected 7 SELECT values after id"),
        )
        return issues
    category = unquote_sql_literal(analysis_values[0])
    title = unquote_sql_literal(analysis_values[1])
    summary = unquote_sql_literal(analysis_values[2])
    key_points = unquote_sql_literal(analysis_values[3])
    content_json_text = unquote_sql_literal(analysis_values[4])
    analysis_url = unquote_sql_literal(analysis_values[5])
    analysis_created_at = analysis_values[6].strip()

    issues.extend(require_category(path, item_index, "ai_journal_analysis.category", category))
    for field, value in [
        ("ai_journal_analysis.title", title),
        ("ai_journal_analysis.summary", summary),
        ("ai_journal_analysis.key_points", key_points),
        ("ai_journal_analysis.content_json", content_json_text),
        ("ai_journal_analysis.source_url", analysis_url),
    ]:
        issues.extend(require_non_empty(path, item_index, field, value))
        if field != "ai_journal_analysis.content_json":
            issues.extend(require_no_html(path, item_index, field, value))
    if analysis_url != source_url:
        issues.append(
            ValidationIssue(path, item_index, "ai_journal_analysis.source_url", "does not match ai_journal.source_url"),
        )
    if analysis_created_at != created_at:
        issues.append(
            ValidationIssue(path, item_index, "ai_journal_analysis.created_at", "does not match ai_journal.created_at"),
        )
    issues.extend(require_datetime(path, item_index, "ai_journal_analysis.created_at", analysis_created_at))
    issues.extend(validate_content_json(path, item_index, "ai_journal_analysis.content_json", content_json_text))
    if parse_where_source_url(analysis.raw) != source_url:
        issues.append(
            ValidationIssue(path, item_index, "ai_journal_analysis.where_source_url", "does not match ai_journal.source_url"),
        )

    data_values = parse_select_values(data_info, expected_prefix=None)
    if len(data_values) != 10:
        issues.append(
            ValidationIssue(path, item_index, "t_news_data_info.values", "expected 10 SELECT values"),
        )
        return issues
    if data_values[0].strip().upper() != "NULL":
        issues.append(ValidationIssue(path, item_index, "t_news_data_info.catalog_id", "must be NULL"))
    if data_values[1].strip() != "id":
        issues.append(ValidationIssue(path, item_index, "t_news_data_info.journal_id", "must SELECT id"))
    if data_values[2].strip().upper() != "NULL":
        issues.append(ValidationIssue(path, item_index, "t_news_data_info.data", "must be NULL"))
    if data_values[3].strip() != "2":
        issues.append(ValidationIssue(path, item_index, "t_news_data_info.adoption_status", "must be 2"))

    data_category = unquote_sql_literal(data_values[4])
    data_title = unquote_sql_literal(data_values[5])
    data_summary = unquote_sql_literal(data_values[6])
    data_key_points = unquote_sql_literal(data_values[7])
    data_content_json = unquote_sql_literal(data_values[8])
    data_source_url = unquote_sql_literal(data_values[9])
    for field, expected, actual in [
        ("category", category, data_category),
        ("title", title, data_title),
        ("summary", summary, data_summary),
        ("key_points", key_points, data_key_points),
        ("content_json", content_json_text, data_content_json),
        ("source_url", source_url, data_source_url),
    ]:
        if actual != expected:
            issues.append(
                ValidationIssue(
                    path,
                    item_index,
                    f"t_news_data_info.{field}",
                    f"does not match ai_journal_analysis.{field}",
                ),
            )
    if parse_where_source_url(data_info.raw) != source_url:
        issues.append(
            ValidationIssue(path, item_index, "t_news_data_info.where_source_url", "does not match ai_journal.source_url"),
        )

    return issues


def parse_statement(statement: str) -> ParsedStatement:
    for table in TABLE_ORDER:
        if f"INTO {table} " in statement:
            columns = parse_columns(statement)
            if table == "ai_journal":
                values = parse_journal_values(statement)
            else:
                values = parse_select_values(parse_statement_shell(table, columns, statement), None)
            return ParsedStatement(table=table, columns=columns, raw=statement, values=values)
    return ParsedStatement(table="", columns=[], raw=statement, values=[])


def parse_statement_shell(table: str, columns: list[str], statement: str) -> ParsedStatement:
    return ParsedStatement(table=table, columns=columns, raw=statement, values=[])


def parse_columns(statement: str) -> list[str]:
    match = re.search(r"\(([^)]*)\)", statement)
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",")]


def parse_journal_values(statement: str) -> list[str]:
    match = re.search(r"\bVALUES\s*\((.*)\);$", statement)
    if not match:
        return []
    return split_sql_values(match.group(1))


def parse_select_values(statement: ParsedStatement, expected_prefix: str | None) -> list[str]:
    match = re.search(r"\bSELECT\s+(.*?)\s+FROM\s+ai_journal\s+WHERE\b", statement.raw)
    if not match:
        return []
    values = split_sql_values(match.group(1))
    if expected_prefix is None:
        return values
    if not values or values[0].strip() != expected_prefix:
        return []
    return values[1:]


def parse_focus_statement(statement: ParsedStatement) -> int | None:
    match = re.search(r"\bSELECT\s+id,\s+(\d+)\s+FROM\s+ai_journal\b", statement.raw)
    if not match:
        return None
    return int(match.group(1))


def parse_where_source_url(statement: str) -> str | None:
    match = re.search(r"\bWHERE\s+source_url\s+=\s+('(?:''|\\.|[^'])*')\s+LIMIT\s+1;$", statement)
    if not match:
        return None
    return unquote_sql_literal(match.group(1))


def split_sql_values(values_text: str) -> list[str]:
    values: list[str] = []
    current: list[str] = []
    in_quote = False
    index = 0
    while index < len(values_text):
        char = values_text[index]
        if char == "'":
            current.append(char)
            if in_quote and index + 1 < len(values_text) and values_text[index + 1] == "'":
                current.append(values_text[index + 1])
                index += 2
                continue
            in_quote = not in_quote
            index += 1
            continue
        if char == "," and not in_quote:
            values.append("".join(current).strip())
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    values.append("".join(current).strip())
    return values


def unquote_sql_literal(value: str) -> str | None:
    value = value.strip()
    if value.upper() == "NULL":
        return None
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        inner = value[1:-1]
        return inner.replace("''", "'").replace("\\\\", "\\")
    return value


def require_non_empty(
    path: Path,
    item_index: int,
    field: str,
    value: str | None,
) -> list[ValidationIssue]:
    if value is None or not str(value).strip():
        return [ValidationIssue(path, item_index, field, "must be non-empty")]
    return []


def require_no_html(
    path: Path,
    item_index: int,
    field: str,
    value: str | None,
) -> list[ValidationIssue]:
    if value and HTML_TAG_RE.search(value):
        return [ValidationIssue(path, item_index, field, "must not contain HTML tags")]
    return []


def require_datetime(path: Path, item_index: int, field: str, value: str) -> list[ValidationIssue]:
    if value.upper() == "NULL":
        return [ValidationIssue(path, item_index, field, "must not be NULL")]
    if "STR_TO_DATE(" in value.upper() or "CAST(" in value.upper():
        return [ValidationIssue(path, item_index, field, "must be a plain quoted datetime literal")]
    if not DATETIME_LITERAL_RE.match(value):
        return [
            ValidationIssue(
                path,
                item_index,
                field,
                "must match quoted 'YYYY-MM-DD HH:MM:SS'",
            ),
        ]
    return []


def require_category(path: Path, item_index: int, field: str, value: str | None) -> list[ValidationIssue]:
    if value not in AI_SQL_CATEGORIES:
        return [ValidationIssue(path, item_index, field, f"{value!r} is not in AI SQL categories")]
    return []


def validate_content_json(
    path: Path,
    item_index: int,
    field: str,
    content_json_text: str | None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not content_json_text:
        return [ValidationIssue(path, item_index, field, "must be non-empty JSON object")]
    try:
        payload = json.loads(content_json_text)
    except json.JSONDecodeError as exc:
        return [ValidationIssue(path, item_index, field, f"invalid JSON: {exc}")]
    if not isinstance(payload, dict):
        return [ValidationIssue(path, item_index, field, "must be a JSON object")]
    payload_keys = set(payload)
    expected_keys = set(CONTENT_JSON_FIELDS)
    if payload_keys != expected_keys:
        issues.append(
            ValidationIssue(
                path,
                item_index,
                field,
                f"keys {sorted(payload_keys)} != {CONTENT_JSON_FIELDS}",
            ),
        )
    forbidden = payload_keys & DISALLOWED_CONTENT_JSON_FIELDS
    if forbidden:
        issues.append(
            ValidationIssue(path, item_index, field, f"contains forbidden keys: {sorted(forbidden)}"),
        )
    for key in CONTENT_JSON_FIELDS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(path, item_index, f"{field}.{key}", "must be non-empty string"))
        elif HTML_TAG_RE.search(value):
            issues.append(ValidationIssue(path, item_index, f"{field}.{key}", "must not contain HTML tags"))
    return issues


def extract_schema(path: Path) -> dict[str, list[str]]:
    schema: dict[str, list[str]] = {}
    sql_text = path.read_text(encoding="utf-8")
    for line in INSERT_LINE_RE.findall(sql_text):
        parsed = parse_statement(line)
        if parsed.table and parsed.table not in schema:
            schema[parsed.table] = parsed.columns
    return schema


def normalize_header(path: Path, baseline: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    stats = {
        "items": len(re.findall(r"-- \[写入数据 Focus_ID:", original)),
        "statements": len(INSERT_LINE_RE.findall(original)),
    }
    body_start = find_body_start(original)
    body = original[body_start:].lstrip() if body_start is not None else original
    body = normalize_section_headers(body)
    generated_at = extract_existing_generated_at(original)
    header = canonical_header(path, baseline, generated_at, stats)
    normalized = header + body.rstrip() + "\n"
    if normalized == original:
        return False
    path.write_text(normalized, encoding="utf-8")
    return True


def find_body_start(sql_text: str) -> int | None:
    section_index = sql_text.find("-- =====")
    item_index = sql_text.find("-- [写入数据 Focus_ID:")
    indexes = [index for index in [section_index, item_index] if index >= 0]
    if not indexes:
        return None
    return min(indexes)


def normalize_section_headers(body: str) -> str:
    body = re.sub(
        r"^-- ===== (\d{4}-\d{2}-\d{2}) \1 (.*?) =====$",
        r"-- ===== \1 \2 =====",
        body,
        flags=re.MULTILINE,
    )

    def replace_path_header(match: re.Match[str]) -> str:
        raw_path = match.group(1)
        date_match = re.search(r"_(\d{4}-\d{2}-\d{2})_company_sql_preview\.sql$", raw_path)
        if not date_match:
            return match.group(0)
        return f"-- ===== {date_match.group(1)} 规划部情报工作台 日报 ====="

    return re.sub(r"^-- ===== (.*?\.sql) =====$", replace_path_header, body, flags=re.MULTILINE)


def extract_existing_generated_at(sql_text: str) -> str:
    match = re.search(r"^-- 生成时间:\s*(.+)$", sql_text, re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def canonical_header(path: Path, baseline: Path, generated_at: str, stats: dict[str, int]) -> str:
    workspace, date_range = parse_path_scope(path)
    baseline_relative = relative(baseline)
    return (
        "-- InfoWatchtower Company SQL Preview\n"
        f"-- 工作台: {workspace}\n"
        f"-- 日期范围: {date_range}\n"
        f"-- 生成时间: {generated_at}\n"
        "-- 导出规则: 已发布日报；仅 adoption_status = 2；generated_news.generation_status = ready；非 rule_v1 fallback。\n"
        "-- 表顺序: ai_journal -> ai_journal_focus -> ai_journal_analysis -> t_news_data_info\n"
        "-- 日期规则: created_at 使用 'YYYY-MM-DD HH:MM:SS'；缺失发布时间兜底为日报 day_key 09:00:00；禁止 NULL/STR_TO_DATE。\n"
        f"-- 校验基准: {baseline_relative}\n"
        f"-- 汇总: {stats['items']} 条新闻，{stats['statements']} 条 SQL 语句。\n\n"
    )


def parse_path_scope(path: Path) -> tuple[str, str]:
    match = re.match(
        r"(?P<workspace>.+?)_(?P<start>\d{4}-\d{2}-\d{2})(?:_to_(?P<end>\d{4}-\d{2}-\d{2}))?_company_sql_preview\.sql$",
        path.name,
    )
    if not match:
        return "unknown", "unknown"
    workspace = match.group("workspace")
    start = match.group("start")
    end = match.group("end")
    return workspace, f"{start} 至 {end}" if end else start


if __name__ == "__main__":
    raise SystemExit(main())
