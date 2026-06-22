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
    LegacyImportRequest,
    QualityArchiveImportRequest,
    import_tech_insight_loop_legacy_history,
    import_tech_insight_loop_quality_archive,
)
from app.models import HistoricalFeedbackItem, HistoricalJobRun, RawItem


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_import_tech_insight_loop_quality_archive_is_idempotent(tmp_path: Path):
    legacy_db = tmp_path / "legacy.sqlite3"
    create_legacy_fixture(legacy_db)
    session = make_session()

    history = import_tech_insight_loop_legacy_history(
        session,
        LegacyImportRequest(sqlite_path=legacy_db),
    )
    assert history.articles_created == 1

    first = import_tech_insight_loop_quality_archive(
        session,
        QualityArchiveImportRequest(sqlite_path=legacy_db),
    )
    session.commit()

    assert first.to_dict() == {
        "feedback_total": 2,
        "feedback_created": 2,
        "feedback_updated": 0,
        "feedback_skipped": 0,
        "quality_feedback_total": 1,
        "quality_feedback_created": 1,
        "quality_feedback_updated": 0,
        "quality_feedback_skipped": 0,
        "feedback_article_refs_total": 3,
        "feedback_article_refs_resolved": 2,
        "feedback_article_refs_unresolved": 1,
        "jobs_total": 2,
        "jobs_created": 2,
        "jobs_updated": 0,
        "jobs_skipped": 0,
    }

    feedback = session.scalar(
        select(HistoricalFeedbackItem).where(
            HistoricalFeedbackItem.legacy_table == "feedback",
            HistoricalFeedbackItem.legacy_id == "501",
        ),
    )
    assert feedback is not None
    assert feedback.feedback_kind == "feedback"
    assert feedback.raw_item_id is not None
    assert feedback.metadata_json["legacy_import"]["mutates_current_feedback"] is False
    assert feedback.metadata_json["legacy_refs"]["article_ref_resolved"] is True

    quality = session.scalar(
        select(HistoricalFeedbackItem).where(
            HistoricalFeedbackItem.legacy_table == "article_quality_feedback",
            HistoricalFeedbackItem.legacy_id == "601",
        ),
    )
    assert quality is not None
    assert quality.feedback_kind == "quality_feedback"
    assert quality.reason == "和我们无关"
    assert quality.raw_item_id is not None

    unresolved = session.scalar(
        select(HistoricalFeedbackItem).where(
            HistoricalFeedbackItem.legacy_table == "feedback",
            HistoricalFeedbackItem.legacy_id == "502",
        ),
    )
    assert unresolved is not None
    assert unresolved.raw_item_id is None
    assert unresolved.metadata_json["legacy_refs"]["article_ref_resolved"] is False

    job = session.scalar(select(HistoricalJobRun).where(HistoricalJobRun.legacy_id == "701"))
    assert job is not None
    assert job.job_type == "rss_ingest"
    assert job.failed_count == 1
    assert job.details_json == {"source": "Example", "error": "timeout"}
    assert job.metadata_json["legacy_import"]["migrates_old_task_state_machine"] is False

    summary = build_legacy_import_summary(session)
    metrics = {item.key: item for item in summary.metrics}
    assert metrics["historical_feedback"].actual == 2
    assert metrics["historical_quality_feedback"].actual == 1
    assert metrics["historical_job_runs"].actual == 2
    assert summary.feedback_article_refs.total == 3
    assert summary.feedback_article_refs.resolved == 2
    assert summary.feedback_article_refs.unresolved == 1

    gaps = list_legacy_import_gap_items(session, kind="historical_feedback")
    assert len(gaps) == 1
    assert gaps[0].legacy_id == "502"
    assert gaps[0].ref_type == "article_id"

    second = import_tech_insight_loop_quality_archive(
        session,
        QualityArchiveImportRequest(sqlite_path=legacy_db),
    )
    session.commit()

    assert second.feedback_created == 0
    assert second.feedback_updated == 2
    assert second.quality_feedback_created == 0
    assert second.quality_feedback_updated == 1
    assert second.jobs_created == 0
    assert second.jobs_updated == 2
    assert session.scalar(select(func.count(HistoricalFeedbackItem.id))) == 3
    assert session.scalar(select(func.count(HistoricalJobRun.id))) == 2
    assert session.scalar(select(func.count(RawItem.id))) == 1


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
            CREATE TABLE feedback (
                id INTEGER PRIMARY KEY,
                article_id INTEGER,
                user_name TEXT,
                feedback_type TEXT,
                comment TEXT,
                created_at TEXT
            );
            CREATE TABLE article_quality_feedback (
                id INTEGER PRIMARY KEY,
                article_id INTEGER,
                user_name TEXT,
                feedback_type TEXT,
                reason TEXT,
                comment TEXT,
                created_at TEXT
            );
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                job_type TEXT,
                status TEXT,
                message TEXT,
                started_at TEXT,
                ended_at TEXT,
                total_sources INTEGER,
                processed_sources INTEGER,
                inserted_count INTEGER,
                failed_count INTEGER,
                details_json TEXT,
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
            """
            INSERT INTO reports
            VALUES (201, 'daily', 'Daily', '2026-05-01T00:00:00+00:00',
                    '2026-05-01T23:59:59+00:00', 'body', '已生成', '[101]',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO feedback
            VALUES (501, 101, '试点用户', '有价值', '可进入观察',
                    '2026-05-02T09:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO feedback
            VALUES (502, 999, '试点用户', '无价值', '找不到原素材',
                    '2026-05-02T10:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO article_quality_feedback
            VALUES (601, 101, '试点用户', '无价值', '和我们无关', '泛商业',
                    '2026-05-02T11:00:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO jobs
            VALUES (701, 'rss_ingest', 'finished_with_errors', 'inserted=1, failed=1',
                    '2026-05-02T08:00:00+00:00',
                    '2026-05-02T08:10:00+00:00',
                    2, 2, 1, 1, '{"source": "Example", "error": "timeout"}',
                    '2026-05-02T08:10:00+00:00')
            """,
        )
        conn.execute(
            """
            INSERT INTO jobs
            VALUES (702, 'rss_ingest', 'finished', 'inserted=2, failed=0',
                    '2026-05-03T08:00:00+00:00',
                    '2026-05-03T08:10:00+00:00',
                    2, 2, 2, 0, '',
                    '2026-05-03T08:10:00+00:00')
            """,
        )
        conn.commit()
    finally:
        conn.close()
