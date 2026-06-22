#!/usr/bin/env python3
"""Import Tech Insight Loop tracked entities and entity milestones.

This command is intentionally separate from historical article/report import:

- without --execute, it refuses to write and points to the inventory review;
- with --execute, it writes tracked_entities and entity_milestones only;
- imported milestones preserve legacy refs but do not mutate raw/news/reports.
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
    parser.add_argument("--entity-limit", type=int, default=None)
    parser.add_argument("--milestone-limit", type=int, default=None)
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
        EntityImportRequest,
        import_tech_insight_loop_entities,
    )

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL is required for --execute.")

    session = session_factory()
    try:
        result = import_tech_insight_loop_entities(
            session,
            EntityImportRequest(
                sqlite_path=args.sqlite_path,
                workspace_code=args.workspace_code,
                domain_code=args.domain_code,
                entity_limit=args.entity_limit,
                milestone_limit=args.milestone_limit,
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
