from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.ingestion.tech_insight_loop_import_audit import (
    build_legacy_import_summary,
    list_legacy_import_gap_items,
)
from app.ingestion.tech_insight_loop_legacy import (
    LEGACY_SOURCE_TYPE,
    LEGACY_WORKSPACE_CODE,
    LegacyImportRequest,
    import_tech_insight_loop_legacy_history,
)
from app.models import HistoricalReport
from app.models.content import DataSource, RawItem


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_import_tech_insight_loop_legacy_history_is_idempotent(tmp_path: Path):
    legacy_db = tmp_path / "legacy.sqlite3"
    create_legacy_fixture(legacy_db)
    session = make_session()

    first = import_tech_insight_loop_legacy_history(
        session,
        LegacyImportRequest(sqlite_path=legacy_db),
    )
    session.commit()

    assert first.to_dict() == {
        "articles_total": 2,
        "articles_created": 2,
        "articles_updated": 0,
        "articles_skipped": 0,
        "reports_total": 2,
        "reports_created": 1,
        "reports_updated": 0,
        "reports_skipped": 1,
        "report_refs_total": 3,
        "report_refs_resolved": 2,
        "report_refs_unresolved": 1,
    }

    archive_source = session.scalar(select(DataSource).where(DataSource.source_type == LEGACY_SOURCE_TYPE))
    assert archive_source is not None
    assert archive_source.enabled is False
    assert archive_source.workspace_code == LEGACY_WORKSPACE_CODE
    assert archive_source.metadata_json["company_sql_eligible"] is False

    raw_items = session.scalars(select(RawItem).order_by(RawItem.entry_key)).all()
    assert len(raw_items) == 2
    assert raw_items[0].workspace_code == LEGACY_WORKSPACE_CODE
    assert raw_items[0].source_name == "Example"
    assert raw_items[0].raw_payload_json["legacy_import"]["company_sql_eligible"] is False
    assert raw_items[0].raw_payload_json["legacy_tech_insight_loop"]["article_id"] == "ART-1"
    assert "\x00" not in raw_items[0].raw_content
    assert "\\u0000" in raw_items[0].raw_content
    assert "\x00" not in json.dumps(raw_items[0].raw_payload_json, ensure_ascii=False)
    assert raw_items[0].raw_payload_json["legacy_import"]["nul_sanitized_fields"] == [
        {"field": "raw_content", "nul_count": 1, "replacement": "\\u0000"},
        {"field": "model_payload_json", "nul_count": 1, "replacement": "\\u0000"},
    ]

    report = session.scalar(select(HistoricalReport))
    assert report is not None
    assert report.workspace_code == LEGACY_WORKSPACE_CODE
    assert report.report_type == "daily"
    assert report.status == "published_imported"
    assert report.source_refs_json["resolved_count"] == 2
    assert report.source_refs_json["unresolved"] == ["999"]
    assert report.metadata_json["legacy_import"]["company_sql_eligible"] is False

    summary = build_legacy_import_summary(session)
    metrics = {item.key: item for item in summary.metrics}
    assert metrics["articles"].actual == 2
    assert metrics["historical_reports"].actual == 1
    assert metrics["tracked_entities"].actual == 0
    assert metrics["entity_milestones"].actual == 0
    assert summary.report_refs.total == 3
    assert summary.report_refs.resolved == 2
    assert summary.report_refs.unresolved == 1

    gaps = list_legacy_import_gap_items(session, kind="historical_reports")
    assert len(gaps) == 1
    assert gaps[0].legacy_id == "201"
    assert gaps[0].unresolved_refs == ["999"]

    second = import_tech_insight_loop_legacy_history(
        session,
        LegacyImportRequest(sqlite_path=legacy_db),
    )
    session.commit()

    assert second.articles_created == 0
    assert second.articles_updated == 2
    assert second.reports_created == 0
    assert second.reports_updated == 1
    assert session.scalar(select(func.count(RawItem.id))) == 2
    assert session.scalar(select(func.count(HistoricalReport.id))) == 1


def create_legacy_fixture(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY,
                article_id TEXT,
                source_id TEXT,
                source_name TEXT,
                title TEXT,
                url TEXT,
                normalized_url TEXT,
                publish_time TEXT,
                crawled_at TEXT,
                summary TEXT,
                raw_content TEXT,
                model_title TEXT,
                model_summary TEXT,
                model_effect TEXT,
                model_payload_json TEXT
            );
            CREATE TABLE reports (
                id INTEGER PRIMARY KEY,
                report_type TEXT,
                title TEXT,
                period_start TEXT,
                period_end TEXT,
                content TEXT,
                status TEXT,
                source_article_ids_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO articles
            VALUES (101, 'ART-1', 'SRC-1', 'Example', 'Good title',
                    'https://example.com/a', 'https://example.com/a',
                    '2026-05-01T10:00:00+00:00',
                    '2026-05-01T11:00:00+00:00',
                    'summary', 'content', 'Model title', 'Model summary', 'Effect', '{}')
            """,
        )
        conn.execute(
            "UPDATE articles SET raw_content = ?, model_payload_json = ? WHERE id = 101",
            ("content\x00with-binary-marker", '{"note": "kept\x00as-marker"}'),
        )
        conn.execute(
            """
            INSERT INTO articles
            VALUES (102, 'ART-2', 'SRC-1', 'Example', 'Second title',
                    'https://example.com/b', 'https://example.com/b',
                    '2026-05-01T12:00:00+00:00',
                    '2026-05-01T13:00:00+00:00',
                    'summary', 'content', '', '', '', '')
            """,
        )
        conn.execute(
            """
            INSERT INTO reports
            VALUES (201, 'daily', 'Daily', '2026-05-01T00:00:00+00:00',
                    '2026-05-01T23:59:59+00:00', 'body', '已生成',
                    '[101, "ART-2", 999]',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO reports
            VALUES (202, 'brief', 'Brief', '2026-05-01T00:00:00+00:00',
                    '2026-05-01T23:59:59+00:00', 'body', '草稿', '[]',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """,
        )
        conn.commit()
    finally:
        conn.close()
