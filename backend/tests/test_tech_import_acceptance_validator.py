from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_tech_import_acceptance.py"


def test_tech_import_acceptance_validator_passes_complete_report(tmp_path: Path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report()), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(report_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["metrics_checked"] == 2


def test_tech_import_acceptance_validator_rejects_incomplete_coverage(tmp_path: Path):
    report = _report()
    report["summary"]["metrics"][0]["actual"] = 1
    report["summary"]["metrics"][0]["missing"] = 1
    report["summary"]["metrics"][0]["status"] = "partial"
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(report_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert "coverage is incomplete" in payload["errors"][0]


def test_tech_import_acceptance_validator_requires_archived_gaps(tmp_path: Path):
    report = _report()
    report["summary"]["gap_item_count"] = 1
    report["summary"]["total_unresolved_refs"] = 2
    report["gap_preview"] = [
        {
            "kind": "historical_reports",
            "legacy_id": "201",
            "ref_type": "source_article_ids",
            "unresolved_count": 2,
        },
    ]
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    failed = subprocess.run(
        [sys.executable, str(SCRIPT), str(report_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert failed.returncode == 1

    accepted_path = tmp_path / "accepted-gaps.json"
    accepted_path.write_text(
        json.dumps(
            {
                "accepted_gaps": [
                    {
                        "kind": "historical_reports",
                        "legacy_id": "201",
                        "ref_type": "source_article_ids",
                        "accepted_unresolved_count": 2,
                        "reason": "legacy source row is absent from the frozen SQLite asset.",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    passed = subprocess.run(
        [sys.executable, str(SCRIPT), str(report_path), "--accepted-gaps-json", str(accepted_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert passed.returncode == 0
    payload = json.loads(passed.stdout)
    assert payload["accepted_unresolved_refs"] == 2


def _report() -> dict:
    return {
        "mode": "check_only",
        "summary": {
            "metrics": [
                {"key": "articles", "expected": 2, "actual": 2, "missing": 0, "status": "complete"},
                {
                    "key": "historical_reports",
                    "expected": 1,
                    "actual": 1,
                    "missing": 0,
                    "status": "complete",
                },
            ],
            "gap_item_count": 0,
            "total_unresolved_refs": 0,
        },
        "gap_preview": [],
        "guardrails": {
            "writes_current_daily_reports": False,
            "writes_current_weekly_reports": False,
            "writes_generated_news": False,
            "writes_standard_company_sql": False,
        },
    }
