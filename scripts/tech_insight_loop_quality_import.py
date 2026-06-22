#!/usr/bin/env python3
"""Import Tech Insight Loop feedback and old job summaries as archive records.

This command is intentionally conservative:

- without --execute, it refuses to write and points to the inventory review;
- with --execute, it writes historical_feedback_items and historical_job_runs only;
- imported feedback is historical audit material, not current comments/ratings;
- imported jobs are statistics-only archive rows, not current ingestion_runs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_SQLITE_PATH = ROOT / "references/参考工具/data/insight_loop.sqlite3"
DEFAULT_WORKSPACE_CODE = "legacy_tech_insight_loop"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", type=Path, default=DEFAULT_SQLITE_PATH)
    parser.add_argument("--workspace-code", default=DEFAULT_WORKSPACE_CODE)
    parser.add_argument("--domain-code", default="ai")
    parser.add_argument("--feedback-limit", type=int, default=None)
    parser.add_argument("--quality-feedback-limit", type=int, default=None)
    parser.add_argument("--job-limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        print(
            "dry-run only: review `python3 scripts/tech_insight_loop_inventory.py "
            "--preview-limit 3`, then rerun this command with --execute.",
        )
        return 0

    from app.core.database import get_session_factory
    from app.ingestion.tech_insight_loop_legacy import (
        QualityArchiveImportRequest,
        import_tech_insight_loop_quality_archive,
    )

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for --execute.")

    session = session_factory()
    try:
        result = import_tech_insight_loop_quality_archive(
            session,
            QualityArchiveImportRequest(
                sqlite_path=args.sqlite_path,
                workspace_code=args.workspace_code,
                domain_code=args.domain_code,
                feedback_limit=args.feedback_limit,
                quality_feedback_limit=args.quality_feedback_limit,
                job_limit=args.job_limit,
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(result.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
