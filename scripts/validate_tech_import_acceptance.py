#!/usr/bin/env python3
"""Validate Tech Insight Loop production import acceptance reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_FALSE_GUARDRAILS = (
    "writes_current_daily_reports",
    "writes_current_weekly_reports",
    "writes_generated_news",
    "writes_standard_company_sql",
)


class AcceptanceError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_json", type=Path)
    parser.add_argument(
        "--accepted-gaps-json",
        type=Path,
        default=None,
        help="JSON file documenting accepted unresolved legacy refs.",
    )
    parser.add_argument(
        "--allow-execute-report",
        action="store_true",
        help="Allow a report emitted by --execute; default requires --check-only evidence.",
    )
    args = parser.parse_args(argv)

    try:
        result = validate_acceptance_report(
            args.report_json,
            accepted_gaps_path=args.accepted_gaps_json,
            require_check_only=not args.allow_execute_report,
        )
    except AcceptanceError as exc:
        print(json.dumps({"status": "failed", "errors": exc.errors}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({"status": "passed", **result}, ensure_ascii=False, indent=2))
    return 0


def validate_acceptance_report(
    report_path: Path,
    *,
    accepted_gaps_path: Path | None = None,
    require_check_only: bool = True,
) -> dict[str, Any]:
    report = _load_json_object(report_path)
    accepted_gaps = _load_accepted_gaps(accepted_gaps_path)
    errors: list[str] = []

    if require_check_only and report.get("mode") != "check_only":
        errors.append("report must be produced by tech_insight_loop_import_verify.py --check-only")

    summary = _dict_value(report.get("summary"))
    metrics = _list_value(summary.get("metrics"))
    incomplete_metrics = []
    for metric in metrics:
        item = _dict_value(metric)
        missing = _int_value(item.get("missing"))
        if item.get("status") != "complete" or missing > 0:
            incomplete_metrics.append(
                f"{item.get('key', 'unknown')} actual={item.get('actual')} "
                f"expected={item.get('expected')} missing={missing}",
            )
    if incomplete_metrics:
        errors.append("coverage is incomplete: " + "; ".join(incomplete_metrics))

    guardrails = _dict_value(report.get("guardrails"))
    for key in REQUIRED_FALSE_GUARDRAILS:
        if guardrails.get(key) is not False:
            errors.append(f"guardrail {key} must be false")

    gap_count = _int_value(summary.get("gap_item_count"))
    unresolved_refs = _int_value(summary.get("total_unresolved_refs"))
    gap_preview = [_dict_value(item) for item in _list_value(report.get("gap_preview"))]
    accepted_unresolved_refs = 0
    if gap_count > 0 or unresolved_refs > 0:
        if len(gap_preview) < gap_count:
            errors.append(
                "gap_preview does not contain every gap item; rerun "
                "tech_insight_loop_import_verify.py with a larger --gap-limit",
            )
        missing_acceptance = []
        accepted_by_key = _accepted_gap_counts_by_key(accepted_gaps)
        for gap in gap_preview:
            key = _gap_key(gap)
            unresolved_count = _int_value(gap.get("unresolved_count"))
            accepted_count = accepted_by_key.get(key, 0)
            if accepted_count < unresolved_count:
                missing_acceptance.append(
                    f"{key[0]}:{key[1]}:{key[2]} unresolved={unresolved_count} accepted={accepted_count}",
                )
            accepted_unresolved_refs += min(accepted_count, unresolved_count)
        if missing_acceptance:
            errors.append("unresolved gaps are not archived: " + "; ".join(missing_acceptance))
        if accepted_unresolved_refs < unresolved_refs:
            errors.append(
                f"accepted unresolved refs {accepted_unresolved_refs} < report total {unresolved_refs}",
            )

    if errors:
        raise AcceptanceError(errors)

    return {
        "report_json": str(report_path),
        "metrics_checked": len(metrics),
        "gap_items": gap_count,
        "unresolved_refs": unresolved_refs,
        "accepted_unresolved_refs": accepted_unresolved_refs,
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AcceptanceError([f"file not found: {path}"]) from exc
    except json.JSONDecodeError as exc:
        raise AcceptanceError([f"invalid JSON: {path}: {exc}"]) from exc
    if not isinstance(value, dict):
        raise AcceptanceError([f"expected JSON object: {path}"])
    return value


def _load_accepted_gaps(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    doc = _load_json_object(path)
    accepted = doc.get("accepted_gaps", doc.get("gaps", []))
    if not isinstance(accepted, list):
        raise AcceptanceError([f"accepted gaps must be a list: {path}"])
    return [_dict_value(item) for item in accepted]


def _accepted_gap_counts_by_key(items: list[dict[str, Any]]) -> dict[tuple[str, str, str], int]:
    counts: dict[tuple[str, str, str], int] = {}
    for item in items:
        key = _gap_key(item)
        count = _int_value(item.get("accepted_unresolved_count", item.get("unresolved_count")))
        if count <= 0:
            continue
        if not item.get("reason"):
            continue
        counts[key] = counts.get(key, 0) + count
    return counts


def _gap_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("kind") or ""),
        str(item.get("legacy_id") or ""),
        str(item.get("ref_type") or ""),
    )


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    return value if isinstance(value, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
