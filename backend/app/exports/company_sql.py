from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.common import utc_now
from app.models.content import GeneratedNews, NewsItem
from app.models.export import ExportJob, ExportJobItem
from app.models.reports import DailyReport, DailyReportItem

COMPANY_SQL_CONTENT_FIELDS = (
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact",
)


class DailyReportNotFoundError(ValueError):
    pass


class DailyReportNotPublishedError(ValueError):
    pass


@dataclass(frozen=True)
class CompanySqlExportResult:
    export_job: ExportJob
    sql_text: str
    item_count: int
    statement_count: int


@dataclass(frozen=True)
class CompanySqlStatement:
    table: str
    sql: str


def generate_company_sql_for_daily_report(
    session: Session,
    daily_report_id: str,
    requested_by_id: str | None = None,
) -> CompanySqlExportResult:
    report = _load_daily_report(session, daily_report_id)
    if report is None:
        raise DailyReportNotFoundError(f"Daily report not found: {daily_report_id}")
    if report.status != "published":
        raise DailyReportNotPublishedError(
            "Company SQL export only supports published daily reports.",
        )

    adopted_items = sorted(
        (item for item in report.items if item.adoption_status == 2),
        key=lambda item: (item.sort_order, item.created_at, item.id),
    )
    started_at = utc_now()
    export_job = ExportJob(
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        visibility_scope=report.visibility_scope,
        sync_policy=report.sync_policy,
        export_type="company_sql",
        status="running",
        requested_by_id=requested_by_id,
        params_json={
            "daily_report_id": report.id,
            "day_key": report.day_key,
            "workspace_code": report.workspace_code,
            "adoption_status": 2,
            "content_fields": list(COMPANY_SQL_CONTENT_FIELDS),
        },
        started_at=started_at,
    )
    session.add(export_job)
    session.flush()

    item_blocks: list[str] = []
    statement_count = 0
    for item in adopted_items:
        block, statements = _sql_block_for_item(item)
        item_blocks.append(block)
        for statement in statements:
            statement_count += 1
            session.add(
                ExportJobItem(
                    export_job=export_job,
                    daily_report_item=item,
                    generated_news=item.generated_news,
                    news_item=item.generated_news.news_item,
                    sql_sequence=statement_count,
                    sql_table=statement.table,
                    sql_text=statement.sql,
                    status="completed",
                ),
            )

    sql_text = _sql_header(started_at) + "".join(item_blocks)
    export_job.status = "completed"
    export_job.completed_at = utc_now()
    export_job.result_json = {
        "daily_report_id": report.id,
        "day_key": report.day_key,
        "item_count": len(adopted_items),
        "statement_count": statement_count,
        "sql_text": sql_text,
        "sql_tables": [
            "ai_journal",
            "ai_journal_focus",
            "ai_journal_analysis",
            "t_news_data_info",
        ],
    }
    session.flush()
    return CompanySqlExportResult(
        export_job=export_job,
        sql_text=sql_text,
        item_count=len(adopted_items),
        statement_count=statement_count,
    )


def _load_daily_report(session: Session, daily_report_id: str) -> DailyReport | None:
    return session.scalar(
        select(DailyReport)
        .options(
            selectinload(DailyReport.items)
            .selectinload(DailyReportItem.generated_news)
            .selectinload(GeneratedNews.news_item)
            .selectinload(NewsItem.raw_item),
        )
        .where(DailyReport.id == daily_report_id),
    )


def _sql_header(generated_at: datetime) -> str:
    return (
        f"-- 生成时间: {generated_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')}\n"
        "-- 规则: 使用 source_url 抽取正文，调用 MiniMax 生成长文分析，保留原始 created 时间。\n"
        "-- 输出模式: 单文件汇总输出。\n\n"
    )


def _sql_block_for_item(item: DailyReportItem) -> tuple[str, list[CompanySqlStatement]]:
    generated = item.generated_news
    news_item = generated.news_item
    raw_item = news_item.raw_item
    source_url = _first_text(raw_item.source_url, news_item.source_url, generated.source_url)
    source_title = _clean_export_text(
        _first_text(raw_item.source_title, news_item.source_title, "自动同步抓取"),
    )
    raw_content = _clean_export_text(_first_text(raw_item.raw_content, news_item.content))
    focus_id = _safe_int(news_item.focus_id)
    created_at = _mysql_datetime(raw_item.published_at or news_item.published_at)

    raw_url_val = escape_sql_string(source_url)
    raw_title_val = escape_sql_string(source_title)
    raw_content_val = escape_sql_string(raw_content)

    title_val = escape_sql_string(item.editor_title or generated.title or "无标题")
    summary_val = escape_sql_string(item.editor_summary or generated.summary or "")
    key_points_val = escape_sql_string(item.editor_key_points or generated.key_points or "")
    category_val = escape_sql_string(generated.category or "未分类")
    content_json_val = escape_sql_string(
        json.dumps(_company_content_json(item), ensure_ascii=False),
    )

    sql_journal = (
        "INSERT IGNORE INTO ai_journal (source_url, source_title, content, created_at) "
        f"VALUES ({raw_url_val}, {raw_title_val}, {raw_content_val}, {created_at});\n"
    )
    sql_focus = (
        "INSERT IGNORE INTO ai_journal_focus (journal_id, focus_id) "
        f"SELECT id, {focus_id} FROM ai_journal WHERE source_url = {raw_url_val} LIMIT 1;\n"
    )
    sql_analysis = (
        "INSERT INTO ai_journal_analysis "
        "(journal_id, category, title, summary, key_points, content_json, source_url, created_at) "
        f"SELECT id, {category_val}, {title_val}, {summary_val}, "
        f"{key_points_val}, {content_json_val}, {raw_url_val}, {created_at} "
        f"FROM ai_journal WHERE source_url = {raw_url_val} LIMIT 1;\n"
    )
    sql_data_info = (
        "INSERT INTO t_news_data_info "
        "(catalog_id, journal_id, data, adoption_status, category, title, summary, "
        "key_points, content_json, source_url) "
        f"SELECT NULL, id, NULL, {int(item.adoption_status)}, {category_val}, {title_val}, "
        f"{summary_val}, {key_points_val}, {content_json_val}, {raw_url_val} "
        f"FROM ai_journal WHERE source_url = {raw_url_val} LIMIT 1;\n"
    )
    statements = [
        CompanySqlStatement("ai_journal", sql_journal),
        CompanySqlStatement("ai_journal_focus", sql_focus),
        CompanySqlStatement("ai_journal_analysis", sql_analysis),
        CompanySqlStatement("t_news_data_info", sql_data_info),
    ]
    block = (
        f"-- [写入数据 Focus_ID: {focus_id}]\n"
        + "".join(statement.sql for statement in statements)
        + "\n"
    )
    return block, statements


def _company_content_json(item: DailyReportItem) -> dict[str, str]:
    generated_content = item.generated_news.content_json or {}
    editor_content = item.editor_content_json or {}
    merged = {**generated_content, **editor_content}
    return {
        field: _stringify_content_value(merged.get(field, ""))
        for field in COMPANY_SQL_CONTENT_FIELDS
    }


def _stringify_content_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _clean_export_text(value: Any) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _mysql_datetime(value: datetime | None) -> str:
    if value is None:
        return "NULL"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return f"'{value.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')}'"


def escape_sql_string(text: Any) -> str:
    if text is None:
        return "NULL"
    escaped_text = str(text).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped_text}'"
