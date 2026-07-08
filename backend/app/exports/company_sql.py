from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.common import utc_now
from app.models.content import GeneratedNews, NewsItem
from app.models.export import ExportJob, ExportJobItem
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace
from app.workspaces.policy import (
    AI_SQL_CATEGORIES as CANONICAL_AI_SQL_CATEGORIES,
)
from app.workspaces.policy import (
    WorkspaceContentPolicy,
    policy_for_workspace,
)

COMPANY_SQL_CONTENT_FIELDS = (
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact",
)
# 非公司 SQL 口径工作台（news_format_code 非 company_sql_v1 或一级标签
# 不是 AI 十分类）的导出指引：不产出语义错误的兼容映射 SQL。
COMPANY_SQL_WORKSPACE_GUIDANCE = (
    "该工作台的标签策略不是公司 SQL 口径（需 news_format_code=company_sql_v1 "
    "且一级标签为 AI 十分类），无法生成标准公司 SQL；"
    "请调整工作台标签策略，或改用技术洞察版 Markdown/HTML 导出。"
)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
COMPANY_SQL_SOURCE_URL_MAX_LENGTH = 1024
COMPANY_SQL_TITLE_WARN_LENGTH = 255
COMPANY_SQL_SUMMARY_WARN_LENGTH = 2000
COMPANY_SQL_KEY_POINTS_WARN_LENGTH = 1000
HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


class DailyReportNotFoundError(ValueError):
    pass


class DailyReportNotPublishedError(ValueError):
    pass


class DailyReportGenerationNotReadyError(ValueError):
    pass


class CompanySqlWorkspaceNotSupportedError(ValueError):
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


@dataclass(frozen=True)
class CompanySqlPreflightIssue:
    level: str
    code: str
    message: str
    field: str | None = None
    daily_report_item_id: str | None = None


@dataclass(frozen=True)
class CompanySqlPreflightItem:
    daily_report_item_id: str
    generated_news_id: str
    news_item_id: str
    adoption_status: int
    status: str
    title: str
    source_url: str | None
    category: str | None
    errors: list[CompanySqlPreflightIssue]
    warnings: list[CompanySqlPreflightIssue]


@dataclass(frozen=True)
class CompanySqlPreflightReport:
    daily_report_id: str
    workspace_code: str
    domain_code: str
    day_key: str
    report_status: str
    status: str
    eligible_count: int
    blocked_count: int
    skipped_count: int
    warning_count: int
    error_count: int
    errors: list[CompanySqlPreflightIssue]
    warnings: list[CompanySqlPreflightIssue]
    items: list[CompanySqlPreflightItem]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def run_company_sql_preflight(session: Session, daily_report_id: str) -> CompanySqlPreflightReport:
    report = _load_daily_report(session, daily_report_id)
    if report is None:
        raise DailyReportNotFoundError(f"Daily report not found: {daily_report_id}")

    report_errors: list[CompanySqlPreflightIssue] = []
    report_warnings: list[CompanySqlPreflightIssue] = []
    if report.status != "published":
        report_errors.append(
            CompanySqlPreflightIssue(
                level="error",
                code="report_not_published",
                field="daily_reports.status",
                message="公司 SQL 只能导出已发布日报。",
            ),
        )
    policy = _workspace_export_policy(session, report)
    if policy is not None and not policy.company_sql_capable:
        report_errors.append(
            CompanySqlPreflightIssue(
                level="error",
                code="workspace_not_company_sql",
                field="workspace.label_policy",
                message=COMPANY_SQL_WORKSPACE_GUIDANCE,
            ),
        )

    export_category_mode = _export_category_mode(session, report)
    items = [
        _preflight_item(item, export_category_mode, report.day_key)
        for item in sorted(report.items, key=lambda item: (item.sort_order, item.created_at, item.id))
    ]
    eligible_count = sum(1 for item in items if item.status == "eligible")
    blocked_count = sum(1 for item in items if item.status == "blocked")
    skipped_count = sum(1 for item in items if item.status == "skipped")
    error_count = len(report_errors) + sum(len(item.errors) for item in items)
    warning_count = len(report_warnings) + sum(len(item.warnings) for item in items)
    return CompanySqlPreflightReport(
        daily_report_id=report.id,
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        day_key=report.day_key,
        report_status=report.status,
        status="failed" if error_count else "passed",
        eligible_count=eligible_count,
        blocked_count=blocked_count,
        skipped_count=skipped_count,
        warning_count=warning_count,
        error_count=error_count,
        errors=report_errors,
        warnings=report_warnings,
        items=items,
    )


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
    policy = _workspace_export_policy(session, report)
    if policy is not None and not policy.company_sql_capable:
        raise CompanySqlWorkspaceNotSupportedError(
            f"Workspace {report.workspace_code} 不适配公司 SQL 导出：{COMPANY_SQL_WORKSPACE_GUIDANCE}",
        )
    preflight = run_company_sql_preflight(session, daily_report_id)
    if preflight.status != "passed":
        first_error = preflight.errors[0] if preflight.errors else next(
            (item.errors[0] for item in preflight.items if item.errors),
            None,
        )
        raise DailyReportGenerationNotReadyError(
            first_error.message if first_error else "Company SQL preflight failed.",
        )

    adopted_items = sorted(
        (item for item in report.items if item.adoption_status == 2),
        key=lambda item: (item.sort_order, item.created_at, item.id),
    )
    not_ready = [
        item
        for item in adopted_items
        if item.generated_news.generation_status != "ready"
        or item.generated_news.generated_by.startswith("rule_v1")
    ]
    if not_ready:
        raise DailyReportGenerationNotReadyError(
            "Company SQL export requires adopted items to be generated by the LLM and marked ready.",
        )

    started_at = utc_now()
    export_category_mode = _export_category_mode(session, report)
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
            "export_category_mode": export_category_mode,
        },
        started_at=started_at,
    )
    session.add(export_job)
    session.flush()

    item_blocks: list[str] = []
    statement_count = 0
    for item in adopted_items:
        block, statements = _sql_block_for_item(item, export_category_mode, report.day_key)
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

    sql_text = _sql_header(started_at, report, len(adopted_items), statement_count) + "".join(
        item_blocks,
    )
    sql_size_bytes = len(sql_text.encode("utf-8"))
    export_job.status = "completed"
    export_job.completed_at = utc_now()
    export_job.result_json = {
        "daily_report_id": report.id,
        "day_key": report.day_key,
        "item_count": len(adopted_items),
        "statement_count": statement_count,
        "preflight": preflight.to_json(),
        "sql_text": sql_text,
        "sql_size_bytes": sql_size_bytes,
        "download_strategy": "server_streaming",
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


def _preflight_item(
    item: DailyReportItem,
    export_category_mode: str,
    report_day_key: str,
) -> CompanySqlPreflightItem:
    generated = item.generated_news
    news_item = generated.news_item
    raw_item = news_item.raw_item
    title = _first_text(item.editor_title, generated.title)
    source_url = _first_text(raw_item.source_url, news_item.source_url, generated.source_url)
    export_category = _export_category(item, export_category_mode)
    errors: list[CompanySqlPreflightIssue] = []
    warnings: list[CompanySqlPreflightIssue] = []

    if item.adoption_status != 2:
        return CompanySqlPreflightItem(
            daily_report_item_id=item.id,
            generated_news_id=generated.id,
            news_item_id=news_item.id,
            adoption_status=item.adoption_status,
            status="skipped",
            title=title,
            source_url=source_url or None,
            category=export_category or None,
            errors=[],
            warnings=[],
        )

    def add_error(code: str, field: str, message: str) -> None:
        errors.append(
            CompanySqlPreflightIssue(
                level="error",
                code=code,
                field=field,
                message=message,
                daily_report_item_id=item.id,
            ),
        )

    def add_warning(code: str, field: str, message: str) -> None:
        warnings.append(
            CompanySqlPreflightIssue(
                level="warning",
                code=code,
                field=field,
                message=message,
                daily_report_item_id=item.id,
            ),
        )

    if generated.generated_by.startswith("rule_v1"):
        # 文案违例 #8（frontend-product-design §14.2）：preflight 提示透传到 /exports
        # 界面，改为业务话术；错误码 rule_fallback_blocked 与判定逻辑不变。
        add_error("rule_fallback_blocked", "generated_news.generated_by", "规则降级草稿（非 AI 生成确认稿）不能进入标准公司 SQL。")
    if generated.generation_status != "ready":
        add_error("generation_not_ready", "generated_news.generation_status", "采信条目生成稿必须为 ready。")
    if not source_url:
        add_error("source_url_missing", "source_url", "source_url 不能为空。")
    elif len(source_url) > COMPANY_SQL_SOURCE_URL_MAX_LENGTH:
        add_error("source_url_too_long", "source_url", f"source_url 超过 {COMPANY_SQL_SOURCE_URL_MAX_LENGTH} 字符。")

    if not title:
        add_error("title_missing", "title", "导出标题不能为空。")
    elif len(title) > COMPANY_SQL_TITLE_WARN_LENGTH:
        add_warning("title_long", "title", f"标题超过 {COMPANY_SQL_TITLE_WARN_LENGTH} 字符，导入前需复核。")
    summary = _first_text(item.editor_summary, generated.summary)
    if not summary:
        add_error("summary_missing", "summary", "导出摘要不能为空。")
    elif len(summary) > COMPANY_SQL_SUMMARY_WARN_LENGTH:
        add_warning("summary_long", "summary", f"摘要超过 {COMPANY_SQL_SUMMARY_WARN_LENGTH} 字符，导入前需复核。")
    key_points = _first_text(item.editor_key_points, generated.key_points)
    if not key_points:
        add_error("key_points_missing", "key_points", "导出关键点不能为空。")
    elif len(key_points) > COMPANY_SQL_KEY_POINTS_WARN_LENGTH:
        add_warning("key_points_long", "key_points", f"关键点超过 {COMPANY_SQL_KEY_POINTS_WARN_LENGTH} 字符，导入前需复核。")

    merged_content = {**(generated.content_json or {}), **(item.editor_content_json or {})}
    for field in COMPANY_SQL_CONTENT_FIELDS:
        if field not in merged_content:
            add_error("content_field_missing", f"content_json.{field}", f"content_json 缺少 {field}。")
            continue
        content_value = _stringify_content_value(merged_content.get(field))
        if HTML_TAG_RE.search(content_value):
            add_error("content_html_detected", f"content_json.{field}", f"content_json.{field} 含 HTML 标签。")

    if export_category not in AI_SQL_CATEGORIES:
        add_error("category_invalid", "generated_news.category", "category 必须是规划部 AI 十分类。")
    elif generated.category and generated.category not in AI_SQL_CATEGORIES:
        add_warning("category_remapped", "generated_news.category", "原始 category 非 AI 十分类，导出时将按兼容规则映射。")

    source_title_raw = _first_text(raw_item.source_title, news_item.source_title, "自动同步抓取")
    source_title_clean = _clean_export_text(source_title_raw)
    if not source_title_clean:
        add_error("source_title_empty_after_clean", "source_title", "source_title 清洗后为空。")
    elif _contains_html(source_title_raw):
        add_warning("source_title_html_cleaned", "source_title", "source_title 含 HTML，导出会清洗为纯文本。")
    raw_content_raw = _first_text(raw_item.raw_content, news_item.content)
    raw_content_clean = _clean_export_text(raw_content_raw)
    if not raw_content_clean:
        add_error("raw_content_empty_after_clean", "raw_content", "ai_journal.content 清洗后为空。")
    elif _contains_html(raw_content_raw):
        add_warning("raw_content_html_cleaned", "raw_content", "ai_journal.content 含 HTML，导出会清洗为纯文本。")

    source_datetime = raw_item.published_at or news_item.published_at or _report_day_fallback_datetime(report_day_key)
    if source_datetime is None:
        add_error("created_at_unrenderable", "created_at", "created_at 无法按北京时间字面量渲染。")

    return CompanySqlPreflightItem(
        daily_report_item_id=item.id,
        generated_news_id=generated.id,
        news_item_id=news_item.id,
        adoption_status=item.adoption_status,
        status="blocked" if errors else "eligible",
        title=title,
        source_url=source_url or None,
        category=export_category or None,
        errors=errors,
        warnings=warnings,
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


def _sql_header(
    generated_at: datetime,
    report: DailyReport,
    item_count: int,
    statement_count: int,
) -> str:
    return (
        "-- InfoWatchtower Company SQL Preview\n"
        f"-- 工作台: {report.workspace_code}\n"
        f"-- 日期范围: {report.day_key}\n"
        f"-- 生成时间: {generated_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')}\n"
        "-- 导出规则: 已发布日报；仅 adoption_status = 2；generated_news.generation_status = ready；非 rule_v1 fallback。\n"
        "-- 表顺序: ai_journal -> ai_journal_focus -> ai_journal_analysis -> t_news_data_info\n"
        "-- 日期规则: created_at 使用北京时间 'YYYY-MM-DD HH:MM:SS'；缺失发布时间兜底为日报 day_key 09:00:00；禁止 NULL/STR_TO_DATE。\n"
        "-- 校验基准: outputs/sql/previews/planning_intel_2026-05-05_company_sql_preview.sql\n"
        f"-- 汇总: {item_count} 条新闻，{statement_count} 条 SQL 语句。\n\n"
    )


def _sql_block_for_item(
    item: DailyReportItem,
    export_category_mode: str,
    report_day_key: str,
) -> tuple[str, list[CompanySqlStatement]]:
    generated = item.generated_news
    news_item = generated.news_item
    raw_item = news_item.raw_item
    source_url = _first_text(raw_item.source_url, news_item.source_url, generated.source_url)
    source_title = _clean_export_text(
        _first_text(raw_item.source_title, news_item.source_title, "自动同步抓取"),
    )
    raw_content = _clean_export_text(_first_text(raw_item.raw_content, news_item.content))
    focus_id = _safe_int(news_item.focus_id)
    created_at = _mysql_datetime(
        raw_item.published_at
        or news_item.published_at
        or _report_day_fallback_datetime(report_day_key),
    )

    raw_url_val = escape_sql_string(source_url)
    raw_title_val = escape_sql_string(source_title)
    raw_content_val = escape_sql_string(raw_content)

    title_val = escape_sql_string(item.editor_title or generated.title or "无标题")
    summary_val = escape_sql_string(item.editor_summary or generated.summary or "")
    key_points_val = escape_sql_string(item.editor_key_points or generated.key_points or "")
    category_val = escape_sql_string(_export_category(item, export_category_mode))
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


def _workspace_export_policy(session: Session, report: DailyReport) -> WorkspaceContentPolicy | None:
    workspace = session.scalar(select(Workspace).where(Workspace.code == report.workspace_code))
    if workspace is None:
        return None
    return policy_for_workspace(workspace)


def _export_category_mode(session: Session, report: DailyReport) -> str:
    """导出 category 口径来自工作台标签策略（与推荐层共用同一解析）。

    当前契约只允许 news_primary（API 写入侧同样锁死），其他值在
    _export_category 中显式拒绝，避免未来扩展第二种口径时静默失效。
    """
    policy = _workspace_export_policy(session, report)
    return policy.export_category_mode if policy is not None else "news_primary"


def _export_category(item: DailyReportItem, export_category_mode: str) -> str:
    if export_category_mode != "news_primary":
        raise ValueError(f"Unsupported export_category_mode: {export_category_mode}")
    generated = item.generated_news
    category = generated.category or ""
    if category in AI_SQL_CATEGORIES:
        return category
    content_json = generated.content_json or {}
    legacy_category = _first_text(
        content_json.get("legacy_ai_category"),
        content_json.get("sql_category"),
    )
    if legacy_category in AI_SQL_CATEGORIES:
        return legacy_category
    return _legacy_ai_category_for_item(item)


# 公司 SQL 契约锁死的一级分类集合（单一事实源在 app.workspaces.policy）。
AI_SQL_CATEGORIES = set(CANONICAL_AI_SQL_CATEGORIES)


def _legacy_ai_category_for_item(item: DailyReportItem) -> str:
    generated = item.generated_news
    text = " ".join(
        [
            generated.category or "",
            item.editor_title or generated.title or "",
            item.editor_summary or generated.summary or "",
            item.editor_key_points or generated.key_points or "",
            json.dumps(_company_content_json(item), ensure_ascii=False),
        ],
    ).lower()
    rules = [
        ("智能体", ("agent", "智能体", "mcp", "a2a", "rag")),
        ("推理加速", ("inference", "推理", "kv cache", "serving", "吞吐", "延迟")),
        ("训练技术", ("training", "训练", "fine-tuning", "finetune", "后训练")),
        ("测评技术", ("benchmark", "评测", "evaluation", "eval", "数据集")),
        ("AI Infra", ("infra", "infrastructure", "gpu", "hbm", "cxl", "集群", "数据中心")),
        ("模型", ("model", "模型", "llm", "多模态", "vlm", "vla")),
        ("算法", ("algorithm", "算法", "优化", "architecture", "架构")),
        ("大厂动态", ("openai", "google", "deepmind", "meta", "microsoft", "anthropic", "amazon")),
        ("AI 应用", ("应用", "assistant", "copilot", "workflow", "case")),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return "基础竞争力"


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


def _contains_html(value: Any) -> bool:
    return bool(value and HTML_TAG_RE.search(str(value)))


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
    return f"'{value.astimezone(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}'"


def _report_day_fallback_datetime(day_key: str) -> datetime | None:
    try:
        report_day = datetime.strptime(day_key, "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime.combine(report_day, time(hour=9), tzinfo=BEIJING_TZ)


def escape_sql_string(text: Any) -> str:
    if text is None:
        return "NULL"
    escaped_text = str(text).replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped_text}'"
