from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


MANUAL_IMPORT_FIELD_ALIASES = {
    "data_source_id": "data_source_id",
    "source_id": "data_source_id",
    "source_title": "source_title",
    "title": "source_title",
    "source_url": "source_url",
    "url": "source_url",
    "raw_content": "raw_content",
    "content": "raw_content",
    "summary": "raw_content",
    "published_at": "published_at",
    "entry_key": "entry_key",
}


@dataclass
class ManualImportError:
    row_number: int
    code: str
    message: str
    raw_text: str = ""


@dataclass
class ManualImportPreview:
    input_format: str
    total_rows: int = 0
    accepted_items: list[dict[str, Any]] = field(default_factory=list)
    errors: list[ManualImportError] = field(default_factory=list)
    error_report_csv: str = ""

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_items)

    @property
    def rejected_count(self) -> int:
        return len(self.errors)


def preview_manual_import(
    *,
    input_text: str,
    input_format: str,
    default_data_source_id: str,
    enabled_source_ids: set[str],
) -> ManualImportPreview:
    resolved_format = _resolve_input_format(input_text, input_format)
    rows, parse_errors = _parse_rows(input_text, resolved_format)
    accepted_items: list[dict[str, Any]] = []
    errors: list[ManualImportError] = list(parse_errors)
    for row_number, raw_row, raw_text in rows:
        normalized = _normalize_row(raw_row)
        if not str(normalized.get("data_source_id") or "").strip() and default_data_source_id:
            normalized["data_source_id"] = default_data_source_id
        row_errors = _validate_row(
            normalized,
            enabled_source_ids=enabled_source_ids,
            row_number=row_number,
            raw_text=raw_text,
        )
        if row_errors:
            errors.extend(row_errors)
            continue
        normalized["_manual_import_row_number"] = row_number
        normalized["_manual_import_original"] = raw_row
        accepted_items.append(normalized)

    preview = ManualImportPreview(
        input_format=resolved_format,
        total_rows=len(rows) + len(parse_errors),
        accepted_items=accepted_items,
        errors=errors,
    )
    preview.error_report_csv = _error_report_csv(preview)
    return preview


def _resolve_input_format(input_text: str, input_format: str) -> str:
    requested = (input_format or "auto").strip().lower()
    if requested in {"csv", "sql"}:
        return requested
    if requested != "auto":
        return "csv"
    stripped = input_text.lstrip()
    if re.match(r"(?is)^insert\s+into\s+", stripped):
        return "sql"
    return "csv"


def _parse_rows(input_text: str, input_format: str) -> tuple[list[tuple[int, dict[str, Any], str]], list[ManualImportError]]:
    if not input_text.strip():
        return [], [ManualImportError(row_number=0, code="empty_input", message="手工导入内容为空")]
    if input_format == "sql":
        return _parse_sql_insert_rows(input_text)
    return _parse_csv_rows(input_text)


def _parse_csv_rows(input_text: str) -> tuple[list[tuple[int, dict[str, Any], str]], list[ManualImportError]]:
    try:
        reader = csv.DictReader(io.StringIO(input_text))
        if not reader.fieldnames:
            return [], [ManualImportError(row_number=1, code="missing_header", message="CSV 第一行必须是表头")]
        rows: list[tuple[int, dict[str, Any], str]] = []
        raw_lines = input_text.splitlines()
        for index, row in enumerate(reader, start=2):
            if row is None or not any(str(value or "").strip() for value in row.values()):
                continue
            rows.append((index, {str(key or ""): value for key, value in row.items()}, raw_lines[index - 1] if index - 1 < len(raw_lines) else ""))
        if not rows:
            return [], [ManualImportError(row_number=2, code="no_rows", message="CSV 至少需要一行数据")]
        return rows, []
    except csv.Error as exc:
        return [], [ManualImportError(row_number=0, code="csv_parse_error", message=str(exc))]


def _parse_sql_insert_rows(input_text: str) -> tuple[list[tuple[int, dict[str, Any], str]], list[ManualImportError]]:
    statements = list(
        re.finditer(
            r"(?is)insert\s+into\s+[\w\".]+\s*\((?P<columns>[^)]+)\)\s*values\s*(?P<values>.*?);",
            input_text if input_text.rstrip().endswith(";") else input_text.rstrip() + ";",
        ),
    )
    if not statements:
        return [], [
            ManualImportError(
                row_number=0,
                code="sql_parse_error",
                message="SQL v1 只支持带列名的 INSERT ... VALUES ...;",
            ),
        ]

    rows: list[tuple[int, dict[str, Any], str]] = []
    errors: list[ManualImportError] = []
    row_number = 1
    for statement in statements:
        columns = [_clean_sql_identifier(value) for value in statement.group("columns").split(",")]
        tuples = _split_sql_value_tuples(statement.group("values"))
        if not tuples:
            errors.append(ManualImportError(row_number=row_number, code="sql_no_values", message="INSERT 语句没有 VALUES 行"))
            continue
        for tuple_text in tuples:
            row_number += 1
            try:
                values = next(csv.reader([tuple_text], quotechar="'", escapechar="\\", doublequote=True, skipinitialspace=True))
            except csv.Error as exc:
                errors.append(
                    ManualImportError(
                        row_number=row_number,
                        code="sql_values_parse_error",
                        message=str(exc),
                        raw_text=tuple_text,
                    ),
                )
                continue
            if len(values) != len(columns):
                errors.append(
                    ManualImportError(
                        row_number=row_number,
                        code="sql_column_mismatch",
                        message=f"SQL VALUES 列数 {len(values)} 与列名数 {len(columns)} 不一致",
                        raw_text=tuple_text,
                    ),
                )
                continue
            rows.append((row_number, dict(zip(columns, [_sql_value(value) for value in values])), tuple_text))
    return rows, errors


def _split_sql_value_tuples(values_text: str) -> list[str]:
    tuples: list[str] = []
    depth = 0
    start: int | None = None
    quote: str | None = None
    index = 0
    while index < len(values_text):
        char = values_text[index]
        if quote:
            if char == quote:
                if index + 1 < len(values_text) and values_text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and start is not None:
                tuples.append(values_text[start:index].strip())
                start = None
        index += 1
    return tuples


def _clean_sql_identifier(value: str) -> str:
    return value.strip().strip('"').strip("`").strip().lower()


def _sql_value(value: str) -> str:
    stripped = value.strip()
    if stripped.upper() == "NULL":
        return ""
    return stripped


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        target = MANUAL_IMPORT_FIELD_ALIASES.get(_normalize_field_name(key), _normalize_field_name(key))
        text = str(value or "").strip()
        if text:
            normalized[target] = text
    return normalized


def _normalize_field_name(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _validate_row(
    row: dict[str, Any],
    *,
    enabled_source_ids: set[str],
    row_number: int,
    raw_text: str,
) -> list[ManualImportError]:
    errors: list[ManualImportError] = []
    source_id = str(row.get("data_source_id") or "").strip()
    if not source_id:
        errors.append(ManualImportError(row_number=row_number, code="missing_source", message="缺少 data_source_id", raw_text=raw_text))
    elif source_id not in enabled_source_ids:
        errors.append(
            ManualImportError(
                row_number=row_number,
                code="source_not_enabled",
                message=f"data_source_id 不属于当前工作台已启用源：{source_id}",
                raw_text=raw_text,
            ),
        )
    if not _row_has_content(row):
        errors.append(
            ManualImportError(
                row_number=row_number,
                code="empty_payload",
                message="至少需要标题、URL 或正文之一",
                raw_text=raw_text,
            ),
        )
    published_at = str(row.get("published_at") or "").strip()
    if published_at and not _valid_datetime(published_at):
        errors.append(
            ManualImportError(
                row_number=row_number,
                code="invalid_published_at",
                message="published_at 必须是 ISO 时间或可解析日期",
                raw_text=raw_text,
            ),
        )
    return errors


def _row_has_content(row: dict[str, Any]) -> bool:
    return any(str(row.get(key) or "").strip() for key in ("source_title", "source_url", "raw_content"))


def _valid_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _error_report_csv(preview: ManualImportPreview) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "row_number",
            "status",
            "data_source_id",
            "source_title",
            "source_url",
            "error_code",
            "error_message",
        ],
    )
    writer.writeheader()
    for item in preview.accepted_items:
        writer.writerow(
            {
                "row_number": item.get("_manual_import_row_number", ""),
                "status": "accepted",
                "data_source_id": item.get("data_source_id", ""),
                "source_title": item.get("source_title", ""),
                "source_url": item.get("source_url", ""),
                "error_code": "",
                "error_message": "",
            },
        )
    for error in preview.errors:
        writer.writerow(
            {
                "row_number": error.row_number,
                "status": "rejected",
                "data_source_id": "",
                "source_title": "",
                "source_url": "",
                "error_code": error.code,
                "error_message": error.message,
            },
        )
    return output.getvalue()
