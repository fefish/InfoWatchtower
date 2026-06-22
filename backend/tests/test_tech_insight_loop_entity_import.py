from __future__ import annotations

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
    EntityImportRequest,
    LegacyImportRequest,
    import_tech_insight_loop_entities,
    import_tech_insight_loop_legacy_history,
)
from app.models import EntityMilestone, HistoricalReport, RawItem, TrackedEntity


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_import_tech_insight_loop_entities_is_idempotent_and_preserves_lineage(tmp_path: Path):
    legacy_db = tmp_path / "legacy.sqlite3"
    create_legacy_fixture(legacy_db)
    session = make_session()

    history = import_tech_insight_loop_legacy_history(
        session,
        LegacyImportRequest(sqlite_path=legacy_db),
    )
    assert history.articles_created == 2
    assert history.reports_created == 1

    first = import_tech_insight_loop_entities(
        session,
        EntityImportRequest(sqlite_path=legacy_db),
    )
    session.commit()

    assert first.to_dict() == {
        "entities_total": 2,
        "entities_created": 1,
        "entities_updated": 0,
        "entities_skipped": 1,
        "milestones_total": 3,
        "milestones_created": 2,
        "milestones_updated": 0,
        "milestones_skipped": 1,
        "article_refs_total": 2,
        "article_refs_resolved": 1,
        "article_refs_unresolved": 1,
        "report_refs_total": 1,
        "report_refs_resolved": 1,
        "report_refs_unresolved": 0,
    }

    entity = session.scalar(select(TrackedEntity).where(TrackedEntity.legacy_id == "301"))
    assert entity is not None
    assert entity.name == "OpenAI"
    assert entity.aliases_json == ["GPT", "ChatGPT"]
    assert entity.metadata_json["legacy_import"]["company_sql_eligible"] is False
    assert entity.metadata_json["influence_breakdown"]["technical_influence"] == 95.0

    linked = session.scalar(select(EntityMilestone).where(EntityMilestone.legacy_id == "401"))
    assert linked is not None
    assert linked.raw_item_id is not None
    assert linked.historical_report_id is not None
    assert linked.importance_level == "high"
    assert linked.metadata_json["legacy_refs"]["article_ref_resolved"] is True
    assert linked.metadata_json["legacy_refs"]["report_ref_resolved"] is True
    assert linked.metadata_json["legacy_import"]["recommendation_eligible"] is False

    unresolved = session.scalar(select(EntityMilestone).where(EntityMilestone.legacy_id == "402"))
    assert unresolved is not None
    assert unresolved.raw_item_id is None
    assert unresolved.historical_report_id is None
    assert unresolved.metadata_json["legacy_refs"]["article_ref_resolved"] is False
    assert unresolved.metadata_json["legacy_refs"]["report_ref_resolved"] is None

    summary = build_legacy_import_summary(session)
    metrics = {item.key: item for item in summary.metrics}
    assert metrics["articles"].actual == 2
    assert metrics["historical_reports"].actual == 1
    assert metrics["tracked_entities"].actual == 1
    assert metrics["entity_milestones"].actual == 2
    assert summary.milestone_article_refs.total == 2
    assert summary.milestone_article_refs.resolved == 1
    assert summary.milestone_article_refs.unresolved == 1
    assert summary.milestone_report_refs.total == 1
    assert summary.milestone_report_refs.resolved == 1
    assert summary.milestone_report_refs.unresolved == 0

    gaps = list_legacy_import_gap_items(session, kind="entity_milestones")
    assert len(gaps) == 1
    assert gaps[0].legacy_id == "402"
    assert gaps[0].ref_type == "article_id"

    second = import_tech_insight_loop_entities(
        session,
        EntityImportRequest(sqlite_path=legacy_db),
    )
    session.commit()

    assert second.entities_created == 0
    assert second.entities_updated == 1
    assert second.milestones_created == 0
    assert second.milestones_updated == 2
    assert session.scalar(select(func.count(TrackedEntity.id))) == 1
    assert session.scalar(select(func.count(EntityMilestone.id))) == 2
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
            CREATE TABLE ai_entities (
                id INTEGER PRIMARY KEY,
                name TEXT,
                entity_type TEXT,
                rank TEXT,
                aliases_json TEXT,
                market_influence REAL,
                technical_influence REAL,
                ecosystem_influence REAL,
                academic_influence REAL,
                open_source_influence REAL,
                commercial_influence REAL,
                business_relevance REAL,
                recent_growth REAL,
                influence_score REAL,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE entity_milestones (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER,
                article_id INTEGER,
                report_id INTEGER,
                event_time TEXT,
                event_type TEXT,
                event_title TEXT,
                event_content TEXT,
                impact TEXT,
                source_url TEXT,
                source_name TEXT,
                board TEXT,
                selected_for_timeline INTEGER,
                confidence REAL,
                model_payload_json TEXT,
                created_at TEXT,
                updated_at TEXT,
                event_brief TEXT,
                impact_brief TEXT,
                importance_score REAL,
                importance_level TEXT,
                summary_model_status TEXT,
                summary_model_payload_json TEXT,
                summary_model_error TEXT,
                deleted_at TEXT,
                timeline_brief TEXT,
                event_dedupe_key TEXT
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
                    '2026-05-01T23:59:59+00:00', 'body', '已生成', '[101]',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO ai_entities
            VALUES (301, 'OpenAI', 'AI模型厂商', 'A', '["GPT", "ChatGPT"]',
                    95, 95, 90, 85, 80, 75, 72, 50, 95, 'note',
                    '2026-05-01T00:00:00+00:00', '2026-05-01T00:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO ai_entities
            VALUES (302, '', 'AI模型厂商', 'B', '[]',
                    0, 0, 0, 0, 0, 0, 0, 0, 0, '',
                    '2026-05-01T00:00:00+00:00', '2026-05-01T00:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO entity_milestones
            VALUES (401, 301, 101, 201, '2026-05-01T10:00:00+00:00',
                    'release', 'Released thing', 'event content', 'impact',
                    'https://example.com/a', 'Example', 'AI模型', 1, 88,
                    '{"ok": true}', '2026-05-01T13:00:00+00:00',
                    '2026-05-01T13:00:00+00:00', 'brief', 'impact brief',
                    90, 'high', 'model_ok', '{"summary": true}', '',
                    '', 'timeline', '2026-05-01|release|openai')
            """,
        )
        conn.execute(
            """
            INSERT INTO entity_milestones
            VALUES (402, 301, 999, NULL, '2026-05-02T10:00:00+00:00',
                    'release', 'Missing source', 'event content', 'impact',
                    'https://example.com/missing', 'Example', 'AI模型', 1, 66,
                    '', '2026-05-02T13:00:00+00:00',
                    '2026-05-02T13:00:00+00:00', '', '', 60, 'medium',
                    '', '', '', '', '', '2026-05-02|release|missing')
            """,
        )
        conn.execute(
            """
            INSERT INTO entity_milestones
            VALUES (403, 999, 101, NULL, '2026-05-03T10:00:00+00:00',
                    'release', 'Missing entity', '', '',
                    'https://example.com/c', 'Example', 'AI模型', 1, 44,
                    '', '2026-05-03T13:00:00+00:00',
                    '2026-05-03T13:00:00+00:00', '', '', 40, 'low',
                    '', '', '', '', '', '2026-05-03|release|missing-entity')
            """,
        )
        conn.commit()
    finally:
        conn.close()
