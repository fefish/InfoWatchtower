#!/usr/bin/env python3
"""Execute or verify Tech Insight Loop legacy imports against the configured database.

This command is the operational wrapper for real database import acceptance:

- default mode is no-write and prints usage guidance;
- --check-only reads current DB coverage and unresolved refs without importing;
- --execute runs the historical article/report import and entity milestone import;
- --include-quality-archive also imports feedback and old job summaries as archives;
- full import requires --confirm-full-import so an operator cannot do it by accident.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_SQLITE_PATH = ROOT / "references/参考工具/data/insight_loop.sqlite3"
DEFAULT_OUTPUT_JSON = ROOT / "outputs/tech_insight_loop/tech_insight_loop_import_execution_report.json"
DEFAULT_OUTPUT_MD = ROOT / "outputs/tech_insight_loop/tech_insight_loop_import_execution_report.md"
DEFAULT_WORKSPACE_CODE = "legacy_tech_insight_loop"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", type=Path, default=DEFAULT_SQLITE_PATH)
    parser.add_argument("--workspace-code", default=DEFAULT_WORKSPACE_CODE)
    parser.add_argument("--domain-code", default="ai")
    parser.add_argument("--article-limit", type=int, default=None)
    parser.add_argument("--report-limit", type=int, default=None)
    parser.add_argument("--entity-limit", type=int, default=None)
    parser.add_argument("--milestone-limit", type=int, default=None)
    parser.add_argument("--feedback-limit", type=int, default=None)
    parser.add_argument("--quality-feedback-limit", type=int, default=None)
    parser.add_argument("--job-limit", type=int, default=None)
    parser.add_argument("--gap-limit", type=int, default=20)
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--skip-entities", action="store_true")
    parser.add_argument("--include-quality-archive", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--confirm-full-import", action="store_true")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()

    if args.execute and args.check_only:
        raise SystemExit("--execute and --check-only are mutually exclusive.")
    if not args.execute and not args.check_only:
        print(
            "no-write mode: use --check-only to inspect current DB coverage, or use --execute "
            "with small limits first, for example:\n"
            "  python3 scripts/tech_insight_loop_import_verify.py --execute "
            "--article-limit 20 --report-limit 5 --entity-limit 5 --milestone-limit 20",
        )
        return 0
    if args.execute:
        _validate_execute_limits(args)

    from app.core.database import get_session_factory
    from app.ingestion.tech_insight_loop_import_audit import (
        build_legacy_import_summary,
        list_legacy_import_gap_items,
    )
    from app.ingestion.tech_insight_loop_legacy import (
        EntityImportRequest,
        LegacyImportRequest,
        QualityArchiveImportRequest,
        import_tech_insight_loop_entities,
        import_tech_insight_loop_legacy_history,
        import_tech_insight_loop_quality_archive,
    )

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for import verification.")

    history_result = None
    entity_result = None
    quality_archive_result = None
    session = session_factory()
    try:
        if args.execute and not args.skip_history:
            history_result = import_tech_insight_loop_legacy_history(
                session,
                LegacyImportRequest(
                    sqlite_path=args.sqlite_path,
                    workspace_code=args.workspace_code,
                    domain_code=args.domain_code,
                    article_limit=args.article_limit,
                    report_limit=args.report_limit,
                ),
            ).to_dict()
        if args.execute and not args.skip_entities:
            entity_result = import_tech_insight_loop_entities(
                session,
                EntityImportRequest(
                    sqlite_path=args.sqlite_path,
                    workspace_code=args.workspace_code,
                    domain_code=args.domain_code,
                    entity_limit=args.entity_limit,
                    milestone_limit=args.milestone_limit,
                ),
            ).to_dict()
        if args.execute and args.include_quality_archive:
            quality_archive_result = import_tech_insight_loop_quality_archive(
                session,
                QualityArchiveImportRequest(
                    sqlite_path=args.sqlite_path,
                    workspace_code=args.workspace_code,
                    domain_code=args.domain_code,
                    feedback_limit=args.feedback_limit,
                    quality_feedback_limit=args.quality_feedback_limit,
                    job_limit=args.job_limit,
                ),
            ).to_dict()
        if args.execute:
            session.commit()

        summary = build_legacy_import_summary(session, workspace_code=args.workspace_code)
        gaps = list_legacy_import_gap_items(
            session,
            workspace_code=args.workspace_code,
            kind="all",
            limit=args.gap_limit,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    report = {
        "mode": "execute" if args.execute else "check_only",
        "workspace_code": args.workspace_code,
        "domain_code": args.domain_code,
        "sqlite_path": str(args.sqlite_path),
        "limits": {
            "article_limit": args.article_limit,
            "report_limit": args.report_limit,
            "entity_limit": args.entity_limit,
            "milestone_limit": args.milestone_limit,
            "feedback_limit": args.feedback_limit,
            "quality_feedback_limit": args.quality_feedback_limit,
            "job_limit": args.job_limit,
            "gap_limit": args.gap_limit,
        },
        "skips": {
            "history": args.skip_history,
            "entities": args.skip_entities,
            "quality_archive": not args.include_quality_archive,
        },
        "history_import_result": history_result,
        "entity_import_result": entity_result,
        "quality_archive_import_result": quality_archive_result,
        "summary": summary.to_dict(),
        "gap_preview": [item.to_dict() for item in gaps],
        "guardrails": {
            "writes_current_daily_reports": False,
            "writes_current_weekly_reports": False,
            "writes_generated_news": False,
            "writes_standard_company_sql": False,
            "archive_workspace_code": args.workspace_code,
        },
    }

    _write_json(args.output_json, report)
    _write_markdown(args.output_md, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


def _validate_execute_limits(args: argparse.Namespace) -> None:
    if args.confirm_full_import:
        return
    missing_limits = []
    if not args.skip_history:
        if args.article_limit is None:
            missing_limits.append("--article-limit")
        if args.report_limit is None:
            missing_limits.append("--report-limit")
    if not args.skip_entities:
        if args.entity_limit is None:
            missing_limits.append("--entity-limit")
        if args.milestone_limit is None:
            missing_limits.append("--milestone-limit")
    if args.include_quality_archive:
        if args.feedback_limit is None:
            missing_limits.append("--feedback-limit")
        if args.quality_feedback_limit is None:
            missing_limits.append("--quality-feedback-limit")
        if args.job_limit is None:
            missing_limits.append("--job-limit")
    if missing_limits:
        raise SystemExit(
            "refusing unbounded --execute without --confirm-full-import; "
            f"provide limits first ({', '.join(missing_limits)}) or pass --confirm-full-import.",
        )


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Tech Insight Loop Import Execution Report",
        "",
        f"- Mode: `{report['mode']}`",
        f"- Workspace: `{report['workspace_code']}`",
        f"- SQLite: `{report['sqlite_path']}`",
        "",
        "## Import Results",
        "",
        "```json",
        json.dumps(
            {
                "history_import_result": report["history_import_result"],
                "entity_import_result": report["entity_import_result"],
                "quality_archive_import_result": report["quality_archive_import_result"],
                "limits": report["limits"],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        "```",
        "",
        "## Coverage",
        "",
        "| Metric | Actual | Expected | Missing | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for metric in summary["metrics"]:
        lines.append(
            f"| {metric['label']} | {metric['actual']} | {metric['expected']} | "
            f"{metric['missing']} | {metric['status']} |",
        )
    lines.extend(
        [
            "",
            "## Reference Resolution",
            "",
            f"- Historical report refs: {summary['report_refs']['resolved']}/"
            f"{summary['report_refs']['total']} resolved; "
            f"{summary['report_refs']['unresolved']} unresolved.",
            f"- Milestone article refs: {summary['milestone_article_refs']['resolved']}/"
            f"{summary['milestone_article_refs']['total']} resolved; "
            f"{summary['milestone_article_refs']['unresolved']} unresolved.",
            f"- Milestone report refs: {summary['milestone_report_refs']['resolved']}/"
            f"{summary['milestone_report_refs']['total']} resolved; "
            f"{summary['milestone_report_refs']['unresolved']} unresolved.",
            f"- Feedback article refs: {summary['feedback_article_refs']['resolved']}/"
            f"{summary['feedback_article_refs']['total']} resolved; "
            f"{summary['feedback_article_refs']['unresolved']} unresolved.",
            f"- Gap items: {summary['gap_item_count']}; unresolved refs: "
            f"{summary['total_unresolved_refs']}.",
            "",
            "## Gap Preview",
            "",
        ],
    )
    gaps = report["gap_preview"]
    if not gaps:
        lines.append("No unresolved reference gaps in the preview window.")
    else:
        for item in gaps:
            lines.append(
                f"- `{item['kind']}` `{item['legacy_id']}` {item['title']}: "
                f"{item['unresolved_count']} unresolved `{item['ref_type']}` refs.",
            )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This wrapper does not write current daily reports, weekly reports, generated news, or company SQL.",
            "- Imported assets remain under the archive workspace unless a later explicit migration changes that.",
            "",
        ],
    )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
