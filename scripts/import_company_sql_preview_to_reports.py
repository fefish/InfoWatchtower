#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from validate_company_sql import (  # noqa: E402
    INSERT_LINE_RE,
    TABLE_ORDER,
    find_body_start,
    parse_focus_statement,
    parse_select_values,
    parse_statement,
    unquote_sql_literal,
    validate_file,
)

from app.auth.service import ensure_auth_seed  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import get_session_factory  # noqa: E402
from app.models.common import utc_now  # noqa: E402
from app.models.content import (  # noqa: E402
    DataSource,
    DedupeGroup,
    DedupeGroupItem,
    GeneratedNews,
    NewsItem,
    RawItem,
    RecommendationItem,
    RecommendationRun,
)
from app.models.reports import DailyReport, DailyReportItem, WeeklyReportItem  # noqa: E402
from app.reports.weekly import WeeklyReportDraftRequest, create_weekly_report_draft  # noqa: E402

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
PREVIEW_DATE_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_company_sql_preview\.sql$")


@dataclass(frozen=True)
class PreviewItem:
    source_url: str
    source_title: str
    raw_content: str
    created_at: datetime
    focus_id: int
    category: str
    title: str
    summary: str
    key_points: str
    content_json: dict[str, str]


@dataclass(frozen=True)
class ImportStats:
    files: int = 0
    days: int = 0
    items: int = 0
    daily_reports_created: int = 0
    daily_reports_updated: int = 0
    weekly_reports_created_or_updated: int = 0
    weekly_items_adopted: int = 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import validated InfoWatchtower company SQL preview files back into "
            "the local daily/weekly report tables for demo or recovery use."
        ),
    )
    parser.add_argument("files", nargs="+", type=Path, help="Single-day company SQL preview files.")
    parser.add_argument("--workspace-code", default="planning_intel")
    parser.add_argument("--domain-code", default="ai")
    parser.add_argument("--execute", action="store_true", help="Actually write to DATABASE_URL.")
    parser.add_argument("--create-weekly", action="store_true", help="Create weekly drafts from imported days.")
    parser.add_argument(
        "--publish-weekly",
        action="store_true",
        help="Mark generated weekly items adopted and publish the weekly reports.",
    )
    args = parser.parse_args()

    files = [_resolve_file(path) for path in args.files]
    parsed_by_day = parse_preview_files(files)
    if not parsed_by_day:
        print("No importable preview items found.")
        return 1

    for day_key, items in sorted(parsed_by_day.items()):
        print(f"preview {day_key}: {len(items)} items")

    if not args.execute:
        print("Dry run only. Re-run with --execute to write daily/weekly reports.")
        return 0

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is required when --execute is used.", file=sys.stderr)
        return 1

    session_factory = get_session_factory()
    if session_factory is None:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        return 1

    session = session_factory()
    try:
        ensure_auth_seed(session, get_settings())
        stats = import_previews(
            session=session,
            parsed_by_day=parsed_by_day,
            workspace_code=args.workspace_code,
            domain_code=args.domain_code,
            create_weekly=args.create_weekly,
            publish_weekly=args.publish_weekly,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(
        json.dumps(
            {
                "files": len(files),
                "days": len(parsed_by_day),
                "items": stats.items,
                "daily_reports_created": stats.daily_reports_created,
                "daily_reports_updated": stats.daily_reports_updated,
                "weekly_reports_created_or_updated": stats.weekly_reports_created_or_updated,
                "weekly_items_adopted": stats.weekly_items_adopted,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


def _resolve_file(path: Path) -> Path:
    resolved = path if path.is_absolute() else REPO_ROOT / path
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    return resolved


def parse_preview_files(files: list[Path]) -> dict[str, list[PreviewItem]]:
    parsed: dict[str, list[PreviewItem]] = {}
    for path in files:
        day_key = _day_key_from_path(path)
        issues, _stats = validate_file(path)
        if issues:
            rendered = "\n".join(f"- {issue.render()}" for issue in issues)
            raise ValueError(f"{path} failed SQL validation:\n{rendered}")
        parsed.setdefault(day_key, []).extend(parse_preview_file(path))
    return parsed


def _day_key_from_path(path: Path) -> str:
    if "_to_" in path.name:
        raise ValueError(
            f"{path.name} is a combined preview file. "
            "Pass single-day preview files to avoid duplicate report imports.",
        )
    match = PREVIEW_DATE_RE.search(path.name)
    if not match:
        raise ValueError(
            f"{path.name} is not a single-day preview file. "
            "Use files named *_YYYY-MM-DD_company_sql_preview.sql.",
        )
    return match.group(1)


def parse_preview_file(path: Path) -> list[PreviewItem]:
    sql_text = path.read_text(encoding="utf-8")
    body_start = find_body_start(sql_text)
    body_text = sql_text[body_start:] if body_start is not None else sql_text
    insert_lines = INSERT_LINE_RE.findall(body_text)
    items: list[PreviewItem] = []
    for offset in range(0, len(insert_lines), 4):
        statements = [parse_statement(statement) for statement in insert_lines[offset : offset + 4]]
        tables = [statement.table for statement in statements]
        if tables != TABLE_ORDER:
            raise ValueError(f"{path}: invalid statement order at item {offset // 4 + 1}: {tables}")

        journal, focus, analysis, _data_info = statements
        analysis_values = parse_select_values(analysis, expected_prefix="id")
        content_json = json.loads(unquote_sql_literal(analysis_values[4]))
        if not isinstance(content_json, dict):
            raise ValueError(f"{path}: content_json must be an object")
        items.append(
            PreviewItem(
                source_url=unquote_sql_literal(journal.values[0]),
                source_title=unquote_sql_literal(journal.values[1]),
                raw_content=unquote_sql_literal(journal.values[2]),
                created_at=_parse_sql_datetime(journal.values[3]),
                focus_id=parse_focus_statement(focus) or 1,
                category=unquote_sql_literal(analysis_values[0]),
                title=unquote_sql_literal(analysis_values[1]),
                summary=unquote_sql_literal(analysis_values[2]),
                key_points=unquote_sql_literal(analysis_values[3]),
                content_json={str(key): str(value) for key, value in content_json.items()},
            ),
        )
    return items


def _parse_sql_datetime(value: str) -> datetime:
    raw = value.strip().strip("'")
    parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=BEIJING_TZ).astimezone(timezone.utc)


def import_previews(
    *,
    session,
    parsed_by_day: dict[str, list[PreviewItem]],
    workspace_code: str,
    domain_code: str,
    create_weekly: bool,
    publish_weekly: bool,
) -> ImportStats:
    source = _ensure_preview_source(session, domain_code)
    daily_created = 0
    daily_updated = 0
    imported_days: set[str] = set()
    item_count = 0

    for day_key, items in sorted(parsed_by_day.items()):
        report, created = _ensure_daily_report(session, workspace_code, domain_code, day_key)
        if created:
            daily_created += 1
        else:
            daily_updated += 1
        for sort_order, item in enumerate(items, start=1):
            _upsert_daily_item(
                session=session,
                source=source,
                report=report,
                item=item,
                workspace_code=workspace_code,
                domain_code=domain_code,
                day_key=day_key,
                sort_order=sort_order,
            )
            item_count += 1
        imported_days.add(day_key)

    weekly_count = 0
    weekly_adopted = 0
    if create_weekly:
        for week_key in sorted({_iso_week_key(day_key) for day_key in imported_days}):
            weekly = create_weekly_report_draft(
                session,
                WeeklyReportDraftRequest(
                    workspace_code=workspace_code,
                    week_key=week_key,
                    limit=200,
                    include_unpublished_daily=False,
                ),
            )
            weekly_count += 1
            if publish_weekly:
                for weekly_item in weekly.items:
                    weekly_item.adoption_status = 2
                    weekly_adopted += 1
                weekly.status = "published"
                weekly.published_at = utc_now()
    return ImportStats(
        files=len(parsed_by_day),
        days=len(parsed_by_day),
        items=item_count,
        daily_reports_created=daily_created,
        daily_reports_updated=daily_updated,
        weekly_reports_created_or_updated=weekly_count,
        weekly_items_adopted=weekly_adopted,
    )


def _ensure_preview_source(session, domain_code: str) -> DataSource:
    from sqlalchemy import select

    source = session.scalar(
        select(DataSource).where(
            DataSource.source_type == "company_sql_preview",
            DataSource.name == "Company SQL Preview Import",
        ),
    )
    if source is not None:
        return source
    source = DataSource(
        workspace_code="shared",
        domain_code=domain_code,
        source_type="company_sql_preview",
        name="Company SQL Preview Import",
        url=None,
        enabled=False,
        default_focus_id=1,
        metadata_json={
            "origin": "company_sql_preview_import",
            "company_sql_contract_unchanged": True,
        },
    )
    session.add(source)
    session.flush()
    return source


def _ensure_daily_report(session, workspace_code: str, domain_code: str, day_key: str) -> tuple[DailyReport, bool]:
    from sqlalchemy import select

    report = session.scalar(
        select(DailyReport).where(
            DailyReport.workspace_code == workspace_code,
            DailyReport.domain_code == domain_code,
            DailyReport.day_key == day_key,
        ),
    )
    if report is not None:
        report.title = f"{day_key} 规划部情报工作台 日报"
        report.summary = "由已校验公司 SQL 预览回填的已发布日报。"
        report.status = "published"
        if report.published_at is None:
            report.published_at = utc_now()
        return report, False
    report = DailyReport(
        workspace_code=workspace_code,
        domain_code=domain_code,
        day_key=day_key,
        title=f"{day_key} 规划部情报工作台 日报",
        summary="由已校验公司 SQL 预览回填的已发布日报。",
        status="published",
        published_at=utc_now(),
    )
    session.add(report)
    session.flush()
    return report, True


def _upsert_daily_item(
    *,
    session,
    source: DataSource,
    report: DailyReport,
    item: PreviewItem,
    workspace_code: str,
    domain_code: str,
    day_key: str,
    sort_order: int,
) -> DailyReportItem:
    from sqlalchemy import select

    raw = _upsert_raw_item(session, source, item, workspace_code, domain_code)
    news = _upsert_news_item(session, raw, item, workspace_code, domain_code)
    group, group_item = _upsert_dedupe(session, news, item, workspace_code, domain_code)
    run = _ensure_recommendation_run(session, workspace_code, domain_code, day_key)
    recommendation = session.scalar(
        select(RecommendationItem).where(
            RecommendationItem.run_id == run.id,
            RecommendationItem.news_item_id == news.id,
        ),
    )
    if recommendation is None:
        recommendation = RecommendationItem(
            run=run,
            dedupe_group=group,
            dedupe_group_item=group_item,
            news_item=news,
            rank=sort_order,
            selected=True,
        )
        session.add(recommendation)
    recommendation.workspace_code = workspace_code
    recommendation.domain_code = domain_code
    recommendation.rank = sort_order
    recommendation.quality_score = 90.0
    recommendation.topic_score = 85.0
    recommendation.freshness_score = 80.0
    recommendation.source_score = source.source_score
    recommendation.final_score = 90.0
    recommendation.selected = True
    recommendation.admission_level = "P1"
    recommendation.admission_score = 90.0
    recommendation.admission_pool = "company_sql_preview"
    recommendation.recommendation_reason = "admission=P1; pool=company_sql_preview; imported from validated SQL preview."
    recommendation.scorer_breakdown_json = {"source": "company_sql_preview_import"}
    session.flush()

    generated = session.scalar(
        select(GeneratedNews).where(GeneratedNews.recommendation_item_id == recommendation.id),
    )
    if generated is None:
        generated = GeneratedNews(
            recommendation_item=recommendation,
            news_item=news,
            title=item.title,
        )
        session.add(generated)
    generated.workspace_code = workspace_code
    generated.domain_code = domain_code
    generated.category = item.category
    generated.title = item.title
    generated.summary = item.summary
    generated.key_points = item.key_points
    generated.content_json = {
        **item.content_json,
        "source": {
            "news_item_id": news.id,
            "raw_item_id": raw.id,
            "data_source_id": source.id,
            "imported_from": "company_sql_preview",
        },
    }
    generated.source_url = item.source_url
    generated.generated_by = "sql_preview_import"
    generated.generation_status = "ready"
    session.flush()

    daily_item = session.scalar(
        select(DailyReportItem).where(
            DailyReportItem.daily_report_id == report.id,
            DailyReportItem.generated_news_id == generated.id,
        ),
    )
    if daily_item is None:
        daily_item = DailyReportItem(daily_report=report, generated_news=generated)
        session.add(daily_item)
    daily_item.workspace_code = workspace_code
    daily_item.domain_code = domain_code
    daily_item.adoption_status = 2
    daily_item.sort_order = sort_order
    daily_item.editor_title = None
    daily_item.editor_summary = None
    daily_item.editor_key_points = None
    daily_item.editor_content_json = None
    daily_item.editor_notes = "imported_from=company_sql_preview"
    session.flush()
    return daily_item


def _upsert_raw_item(session, source: DataSource, item: PreviewItem, workspace_code: str, domain_code: str) -> RawItem:
    from sqlalchemy import select

    entry_key = _stable_key("sql-preview", item.source_url)
    raw = session.scalar(
        select(RawItem).where(
            RawItem.data_source_id == source.id,
            RawItem.entry_key == entry_key,
        ),
    )
    if raw is None:
        raw = RawItem(data_source=source, entry_key=entry_key)
        session.add(raw)
    raw.workspace_code = workspace_code
    raw.domain_code = domain_code
    raw.source_type = source.source_type
    raw.source_name = source.name
    raw.source_title = item.source_title
    raw.source_url = item.source_url
    raw.raw_content = item.raw_content
    raw.published_at = item.created_at
    raw.fetched_at = utc_now()
    raw.raw_payload_json = {
        "origin": "company_sql_preview",
        "source_url": item.source_url,
        "title": item.title,
        "content_json": item.content_json,
    }
    session.flush()
    return raw


def _upsert_news_item(session, raw: RawItem, item: PreviewItem, workspace_code: str, domain_code: str) -> NewsItem:
    from sqlalchemy import select

    news = session.scalar(
        select(NewsItem).where(
            NewsItem.workspace_code == workspace_code,
            NewsItem.source_url == item.source_url,
        ),
    )
    if news is None:
        news = NewsItem(raw_item=raw, data_source=raw.data_source, source_title=item.source_title)
        session.add(news)
    news.workspace_code = workspace_code
    news.domain_code = domain_code
    news.source_type = raw.source_type
    news.source_name = raw.source_name
    news.source_url = item.source_url
    news.canonical_url = item.source_url
    news.source_title = item.source_title
    news.normalized_title = item.title
    news.summary = item.summary
    news.content = raw.raw_content
    news.published_at = item.created_at
    news.focus_id = item.focus_id
    news.dedupe_key = _stable_key("dedupe", item.source_url)
    news.active = True
    news.normalization_status = "normalized"
    news.normalization_notes = "imported_from=company_sql_preview"
    session.flush()
    return news


def _upsert_dedupe(
    session,
    news: NewsItem,
    item: PreviewItem,
    workspace_code: str,
    domain_code: str,
) -> tuple[DedupeGroup, DedupeGroupItem]:
    from sqlalchemy import select

    dedupe_key = _stable_key("dedupe", item.source_url)
    group = session.scalar(
        select(DedupeGroup).where(
            DedupeGroup.workspace_code == workspace_code,
            DedupeGroup.dedupe_key == dedupe_key,
        ),
    )
    if group is None:
        group = DedupeGroup(workspace_code=workspace_code, domain_code=domain_code, dedupe_key=dedupe_key)
        session.add(group)
    group.domain_code = domain_code
    group.winner_news_item = news
    group.item_count = 1
    group.status = "active"
    session.flush()

    group_item = session.scalar(
        select(DedupeGroupItem).where(
            DedupeGroupItem.dedupe_group_id == group.id,
            DedupeGroupItem.news_item_id == news.id,
        ),
    )
    if group_item is None:
        group_item = DedupeGroupItem(dedupe_group=group, news_item=news)
        session.add(group_item)
    group_item.is_winner = True
    group_item.rank_score = 100.0
    group_item.duplicate_reason = "company_sql_preview_import"
    session.flush()
    return group, group_item


def _ensure_recommendation_run(session, workspace_code: str, domain_code: str, day_key: str) -> RecommendationRun:
    from sqlalchemy import select

    run_key = f"{workspace_code}:sql-preview:{day_key}"
    run = session.scalar(select(RecommendationRun).where(RecommendationRun.run_key == run_key))
    if run is None:
        run = RecommendationRun(
            workspace_code=workspace_code,
            domain_code=domain_code,
            run_key=run_key,
            started_at=utc_now(),
        )
        session.add(run)
    run.status = "completed"
    run.completed_at = utc_now()
    run.params_json = {"day_key": day_key, "source": "company_sql_preview_import"}
    session.flush()
    return run


def _stable_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _iso_week_key(day_key: str) -> str:
    day = datetime.strptime(day_key, "%Y-%m-%d").date()
    year, week, _weekday = day.isocalendar()
    return f"{year}-W{week:02d}"


if __name__ == "__main__":
    raise SystemExit(main())
