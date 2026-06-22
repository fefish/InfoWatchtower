from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/tech_insight_loop_inventory.py"
DRY_RUN_SCRIPT_PATH = ROOT / "scripts/tech_insight_loop_legacy_dry_run.py"


def load_inventory_module():
    spec = importlib.util.spec_from_file_location("tech_insight_loop_inventory", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dry_run_module():
    spec = importlib.util.spec_from_file_location(
        "tech_insight_loop_legacy_dry_run",
        DRY_RUN_SCRIPT_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_inventory_reports_counts_quality_and_mapping_preview(tmp_path: Path):
    module = load_inventory_module()
    db_path = tmp_path / "legacy.sqlite3"
    create_legacy_fixture(db_path)

    inventory = module.build_inventory(db_path, preview_limit=2)

    assert inventory["core_counts"]["sources"]["actual"] == 1
    assert inventory["core_counts"]["articles"]["actual"] == 2
    assert inventory["core_counts"]["reports"]["actual"] == 1
    assert inventory["core_counts"]["ai_entities"]["actual"] == 1
    assert inventory["core_counts"]["entity_milestones"]["actual"] == 2
    assert inventory["guardrails"] == [
        "read_only_inventory_only",
        "do_not_run_legacy_app_py",
        "do_not_copy_sqlite_tables_to_main_db",
        "historical_assets_do_not_auto_enter_recommendation",
        "historical_assets_do_not_enter_company_sql",
        "company_sql_contract_unchanged",
    ]

    article_dates = inventory["quality"]["date_fields"]["articles"]["publish_time"]
    assert article_dates["parsed"] == 1
    assert article_dates["failed"] == 1
    assert article_dates["failed_samples"] == ["not-a-date"]

    article_json = inventory["quality"]["json_fields"]["articles"]["tags_json"]
    assert article_json["valid"] == 1
    assert article_json["invalid"] == 1

    report_refs = inventory["quality"]["relationships"]["reports_source_article_ids"]
    assert report_refs == {
        "reports_checked": 1,
        "invalid_json": 0,
        "total_refs": 3,
        "unresolved_refs": 1,
        "invalid_samples": [],
    }

    milestone_checks = inventory["quality"]["relationships"]["entity_milestones"]
    assert milestone_checks["missing_entity_refs"] == 0
    assert milestone_checks["missing_article_refs"] == 1
    assert milestone_checks["missing_report_refs"] == 0

    article_preview = inventory["mapping_previews"]["articles"][0]
    assert article_preview["target_type"] == "raw_items + optional archived news_items"
    assert article_preview["target_key"] == "tech_insight_loop:articles:ART-1"
    assert "do not enter company SQL" in article_preview["guardrails"]
    assert article_preview["target_fields"]["raw_payload_json_path"] == "legacy_tech_insight_loop"


def test_write_inventory_outputs_creates_json_and_markdown(tmp_path: Path):
    module = load_inventory_module()
    db_path = tmp_path / "legacy.sqlite3"
    output_dir = tmp_path / "inventory"
    create_legacy_fixture(db_path)

    inventory = module.build_inventory(db_path, preview_limit=1)
    outputs = module.write_inventory_outputs(inventory, output_dir)

    json_path = Path(outputs["json"])
    markdown_path = Path(outputs["markdown"])
    assert json_path.exists()
    assert markdown_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["core_counts"]["articles"]["actual"] == 2
    assert "Tech Insight Loop 只读资产盘点" in markdown_path.read_text(encoding="utf-8")


def test_legacy_dry_run_plans_articles_reports_and_reference_gaps(tmp_path: Path):
    module = load_dry_run_module()
    db_path = tmp_path / "legacy.sqlite3"
    create_legacy_fixture(db_path)
    add_unsupported_report(db_path)

    dry_run = module.build_dry_run(db_path, preview_limit=2)

    assert dry_run["mode"] == "dry_run_only"
    assert dry_run["guardrails"] == [
        "do_not_write_legacy_sqlite",
        "do_not_write_infowatchtower_database",
        "do_not_run_legacy_app_py",
        "do_not_create_recommendation_runs",
        "do_not_create_sql_ready_generated_news",
        "do_not_export_historical_assets_to_company_sql",
    ]

    articles = dry_run["articles"]
    assert articles["total"] == 2
    assert articles["importable"] == 2
    assert articles["skipped"] == 0
    assert articles["company_sql_eligible"] is False
    assert articles["source_refs"] == {"resolved_source_id": 2}
    assert articles["mapping"]["legacy_row_id_to_target_key_count"] == 2
    assert articles["previews"][0]["target_status"] == "historical_imported"
    assert articles["previews"][0]["target_fields"]["raw_payload_json_path"] == (
        "legacy_tech_insight_loop"
    )

    reports = dry_run["reports"]
    assert reports["total"] == 2
    assert reports["importable"] == 1
    assert reports["skipped"] == 1
    assert reports["skip_reason_counts"] == {"unsupported_report_type": 1}
    assert reports["reference_totals"] == {
        "reports_checked": 2,
        "total_refs": 3,
        "resolved_refs": 2,
        "unresolved_refs": 1,
        "invalid_source_article_ids_json": 0,
    }
    assert reports["reference_gap_samples"][0]["unresolved_refs"] == ["999"]
    assert reports["previews"][0]["target_type"] == "historical_reports"
    assert reports["previews"][0]["target_status"] == "published_imported"


def test_write_legacy_dry_run_outputs_strips_internal_maps(tmp_path: Path):
    module = load_dry_run_module()
    db_path = tmp_path / "legacy.sqlite3"
    output_dir = tmp_path / "dry-run"
    create_legacy_fixture(db_path)

    dry_run = module.build_dry_run(db_path, preview_limit=1)
    outputs = module.write_dry_run_outputs(dry_run, output_dir)

    json_path = Path(outputs["json"])
    markdown_path = Path(outputs["markdown"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert json_path.exists()
    assert markdown_path.exists()
    assert "_row_id_to_target" not in payload["articles"]
    assert "_article_id_to_target" not in payload["articles"]
    assert payload["reports"]["reference_totals"]["unresolved_refs"] == 1
    assert "Tech Insight Loop 历史导入 Dry Run" in markdown_path.read_text(encoding="utf-8")


def create_legacy_fixture(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY,
                source_id TEXT,
                name TEXT,
                original_url TEXT,
                rss_url TEXT,
                created_at TEXT,
                updated_at TEXT
            );
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
                board TEXT,
                tags_json TEXT,
                entities_json TEXT,
                report_status TEXT,
                admission_level TEXT,
                info_pool TEXT,
                created_at TEXT,
                updated_at TEXT
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
                influence_score REAL,
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
                source_url TEXT,
                source_name TEXT,
                importance_level TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE feedback (
                id INTEGER PRIMARY KEY,
                created_at TEXT
            );
            CREATE TABLE article_quality_feedback (
                id INTEGER PRIMARY KEY,
                created_at TEXT
            );
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                status TEXT,
                details_json TEXT,
                started_at TEXT,
                updated_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO sources
            VALUES (1, 'SRC-1', 'Example', 'https://example.com', 'https://example.com/rss',
                    '2026-05-01T00:00:00+00:00', '2026-05-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO articles
            VALUES (101, 'ART-1', 'SRC-1', 'Example', 'Good title', 'https://example.com/a',
                    'https://example.com/a', '2026-05-01T10:00:00+00:00',
                    '2026-05-01T11:00:00+00:00', 'summary', 'content', 'AI模型',
                    '["tag"]', '[]', '已入日报', 'P1', '核心洞察池',
                    '2026-05-01T11:00:00+00:00', '2026-05-01T11:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO articles
            VALUES (102, 'ART-2', 'SRC-1', 'Example', 'Bad title', 'https://example.com/b',
                    'https://example.com/b', 'not-a-date',
                    '2026-05-01T12:00:00+00:00', 'summary', 'content', 'AI模型',
                    '{bad json', '[]', '未入报', 'R', '归档池',
                    '2026-05-01T12:00:00+00:00', '2026-05-01T12:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO reports
            VALUES (201, 'daily', 'Daily', '2026-05-01', '2026-05-01', 'body', '已生成',
                    '[101, "ART-2", 999]',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO ai_entities
            VALUES (301, 'OpenAI', 'AI模型厂商', 'A', '["OpenAI"]', 90,
                    '2026-05-01T00:00:00+00:00', '2026-05-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO entity_milestones
            VALUES (401, 301, 101, 201, '2026-05-01T10:00:00+00:00',
                    'release', 'Released thing', 'https://example.com/a', 'Example', 'high',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO entity_milestones
            VALUES (402, 301, 999, 201, '2026-05-01T10:00:00+00:00',
                    'release', 'Broken link', 'https://example.com/missing', 'Example', 'medium',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """
        )
        conn.execute("INSERT INTO feedback VALUES (1, '2026-05-01T00:00:00+00:00')")
        conn.execute(
            "INSERT INTO article_quality_feedback VALUES (1, '2026-05-01T00:00:00+00:00')"
        )
        conn.execute(
            """
            INSERT INTO jobs
            VALUES (1, 'done', '{"ok": true}', '2026-05-01T00:00:00+00:00',
                    '2026-05-01T00:00:00+00:00')
            """
        )
        conn.commit()
    finally:
        conn.close()


def add_unsupported_report(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO reports
            VALUES (202, 'brief', 'Brief', '2026-05-01', '2026-05-01', 'body', '草稿',
                    '[]',
                    '2026-05-01T13:00:00+00:00', '2026-05-01T13:00:00+00:00')
            """
        )
        conn.commit()
    finally:
        conn.close()
