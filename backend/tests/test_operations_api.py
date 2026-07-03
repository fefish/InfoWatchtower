import io
import json
import zipfile
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import (
    DataSource,
    EntityMilestone,
    HistoricalFeedbackItem,
    HistoricalJobRun,
    HistoricalReport,
    RawItem,
    SyncConflict,
    SyncInbox,
    SyncOutbox,
    TrackedEntity,
)
from tests.test_auth import make_client


def test_operations_pages_have_real_crud_and_lists(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    requirement = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "跟踪 Agent 工程能力变化",
            "description": "整理日报中可转化为内部工具能力的信号。",
            "priority": "high",
        },
    )
    assert requirement.status_code == 200
    requirement_id = requirement.json()["id"]

    patched = client.patch(f"/api/requirements/{requirement_id}", json={"status": "done"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"

    listed_requirements = client.get("/api/requirements", params={"workspace_code": "planning_intel"})
    assert listed_requirements.status_code == 200
    assert listed_requirements.json()[0]["id"] == requirement_id

    task = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "requirement_id": requirement_id,
            "title": "补充一周 Agent 案例",
        },
    )
    assert task.status_code == 200
    assert task.json()["requirement_id"] == requirement_id

    sync_run = client.post("/api/sync-runs", json={})
    assert sync_run.status_code == 200
    assert sync_run.json()["package_id"].startswith("sync_")

    audit_logs = client.get("/api/audit-logs")
    assert audit_logs.status_code == 200
    actions = {item["action"] for item in audit_logs.json()}
    assert "requirement.create" in actions
    assert "topic_task.create" in actions
    assert "sync_package.export" in actions


def test_sync_package_export_download_and_import_are_auditable(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            SyncOutbox(
                workspace_code="planning_intel",
                domain_code="ai",
                visibility_scope="public",
                sync_policy="public_to_intranet",
                event_id="evt-sync-001",
                object_type="news_items",
                object_id="news-001",
                operation="upsert",
                payload_json={"global_id": "global-news-001", "revision": 2, "title": "同步新闻"},
                payload_hash="",
                status="pending",
            ),
        )
        session.commit()

    exported = client.post(
        "/api/sync/packages/export",
        json={"source_instance_id": "public", "target_instance_id": "intranet", "limit": 10},
    )
    assert exported.status_code == 200
    export_payload = exported.json()
    package_id = export_payload["package_manifest"]["package_id"]
    assert export_payload["package_manifest"]["record_count"] == 1
    assert export_payload["records"][0]["event_id"] == "evt-sync-001"
    assert export_payload["records"][0]["object_global_id"] == "global-news-001"
    assert export_payload["sync_run"]["counts_json"]["exported"] == 1

    downloaded = client.get(f"/api/sync/packages/{package_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        records = [
            json.loads(line)
            for line in archive.read("records.jsonl").decode("utf-8").splitlines()
            if line.strip()
        ]
    assert manifest["package_id"] == package_id
    assert records[0]["event_id"] == "evt-sync-001"

    imported = client.post(
        "/api/sync/packages/import",
        json={
            "package_manifest": {
                **manifest,
                "package_id": "external-package-001",
                "source_instance_id": "public-other",
                "records_sha256": "",
            },
            "records": [
                {
                    "event_id": "evt-sync-import-001",
                    "object_type": "data_sources",
                    "object_id": "remote-source-001",
                    "object_global_id": "global-source-import-001",
                    "operation": "upsert",
                    "revision": 2,
                    "content_hash": "hash-source-v2",
                    "visibility_scope": "public",
                    "sync_policy": "public_to_intranet",
                    "workspace_code": "shared",
                    "domain_code": "ai",
                    "payload": {
                        "global_id": "global-source-import-001",
                        "workspace_code": "shared",
                        "domain_code": "ai",
                        "visibility_scope": "public",
                        "sync_policy": "public_to_intranet",
                        "source_type": "rss",
                        "name": "同步源",
                        "url": "https://example.com/feed.xml",
                        "enabled": True,
                        "default_focus_id": 1,
                        "backfill_days": 7,
                        "metadata_json": {"origin": "sync"},
                    },
                },
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["applied"] == 1
    assert imported.json()["conflicts"] == 0
    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "global-source-import-001"))
        assert source is not None
        assert source.name == "同步源"
        assert source.url == "https://example.com/feed.xml"
        inbox = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-sync-import-001"))
        assert inbox is not None
        assert inbox.status == "applied"

    repeated = client.post(
        "/api/sync/packages/import",
        json={
            "package_manifest": {
                **manifest,
                "package_id": "external-package-001",
                "source_instance_id": "public-other",
                "records_sha256": "",
            },
            "records": [
                {
                    "event_id": "evt-sync-import-001",
                    "object_type": "data_sources",
                    "object_id": "remote-source-001",
                    "object_global_id": "global-source-import-001",
                    "operation": "upsert",
                    "revision": 2,
                    "content_hash": "hash-source-v2",
                    "visibility_scope": "public",
                    "sync_policy": "public_to_intranet",
                    "workspace_code": "shared",
                    "domain_code": "ai",
                    "payload": {
                        "global_id": "global-source-import-001",
                        "source_type": "rss",
                        "name": "同步源",
                    },
                },
            ],
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["skipped"] == 1

    conflict = client.post(
        "/api/sync/packages/import",
        json={
            "package_manifest": {
                **manifest,
                "package_id": "external-package-002",
                "source_instance_id": "public-other",
                "records_sha256": "",
            },
            "records": [
                {
                    "event_id": "evt-sync-conflict-001",
                    "object_type": "data_sources",
                    "object_id": "remote-source-001",
                    "object_global_id": "global-source-import-001",
                    "operation": "upsert",
                    "revision": 2,
                    "content_hash": "hash-source-v2-conflicting",
                    "visibility_scope": "public",
                    "sync_policy": "public_to_intranet",
                    "workspace_code": "shared",
                    "domain_code": "ai",
                    "payload": {
                        "global_id": "global-source-import-001",
                        "source_type": "rss",
                        "name": "冲突源",
                        "url": "https://example.com/other.xml",
                    },
                },
            ],
        },
    )
    assert conflict.status_code == 200
    assert conflict.json()["status"] == "completed_with_conflicts"
    assert conflict.json()["conflicts"] == 1
    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "global-source-import-001"))
        assert source is not None
        assert source.name == "同步源"
        conflict_row = session.scalar(
            select(SyncConflict).where(SyncConflict.object_id == "global-source-import-001"),
        )
        assert conflict_row is not None
        assert conflict_row.status == "open"


def test_historical_reports_are_listed_and_read_only(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        first = HistoricalReport(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="reports",
            legacy_id="201",
            report_type="daily",
            title="技术洞察日报 2026-05-01",
            status="published_imported",
            period_start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            period_end_at=datetime(2026, 5, 1, 23, 59, 59, tzinfo=timezone.utc),
            content="body with Agent memory details",
            source_refs_json={
                "resolved": [{"legacy_ref": "101", "raw_item_id": "raw_101"}],
                "unresolved": ["999"],
                "resolved_count": 1,
                "unresolved_count": 1,
            },
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:report:test-201",
            origin_instance_id="tech_insight_loop",
        )
        second = HistoricalReport(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="reports",
            legacy_id="202",
            report_type="weekly",
            title="技术洞察周报 2026-W18",
            status="imported",
            period_start_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
            period_end_at=datetime(2026, 5, 10, 23, 59, 59, tzinfo=timezone.utc),
            content="weekly body",
            source_refs_json={"resolved": [], "unresolved": [], "resolved_count": 0, "unresolved_count": 0},
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:report:test-202",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([first, second])
        session.commit()
        first_id = first.id

    summary = client.get("/api/historical-reports/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["total"] == 2
    assert summary_payload["by_report_type"] == {"daily": 1, "weekly": 1}
    assert summary_payload["unresolved_report_count"] == 1
    assert summary_payload["unresolved_ref_count"] == 1

    unresolved = client.get(
        "/api/historical-reports",
        params={"workspace_code": "legacy_tech_insight_loop", "has_unresolved_refs": True},
    )
    assert unresolved.status_code == 200
    unresolved_payload = unresolved.json()
    assert len(unresolved_payload) == 1
    assert unresolved_payload[0]["legacy_id"] == "201"
    assert unresolved_payload[0]["unresolved_ref_count"] == 1
    assert "content" not in unresolved_payload[0]

    weekly = client.get(
        "/api/historical-reports",
        params={"workspace_code": "legacy_tech_insight_loop", "report_type": "weekly", "q": "周报"},
    )
    assert weekly.status_code == 200
    assert [item["legacy_id"] for item in weekly.json()] == ["202"]

    detail = client.get(f"/api/historical-reports/{first_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["content"] == "body with Agent memory details"
    assert detail_payload["source_refs_json"]["unresolved"] == ["999"]
    assert detail_payload["metadata_json"]["legacy_import"]["company_sql_eligible"] is False


def test_legacy_import_summary_and_gaps(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            name="Tech Insight Loop Legacy Archive",
            enabled=False,
            global_id="til:archive-source:test",
            content_hash="source-hash",
        )
        session.add(source)
        session.flush()
        raw = RawItem(
            data_source_id=source.id,
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            source_name="Legacy",
            entry_key="legacy-101",
            source_title="Legacy article",
            raw_content="raw",
            fetched_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            raw_payload_json={"legacy_tech_insight_loop": {"id": 101}},
            global_id="til:article:test-101",
            content_hash="raw-hash",
        )
        report = HistoricalReport(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="reports",
            legacy_id="201",
            report_type="daily",
            title="技术洞察日报 2026-05-01",
            status="published_imported",
            period_start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            period_end_at=datetime(2026, 5, 1, 23, 59, 59, tzinfo=timezone.utc),
            content="body",
            source_refs_json={
                "resolved": [{"legacy_ref": "101", "raw_item_id": raw.id}],
                "unresolved": ["999"],
                "resolved_count": 1,
                "unresolved_count": 1,
            },
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:report:test-201",
            origin_instance_id="tech_insight_loop",
        )
        entity = TrackedEntity(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="ai_entities",
            legacy_id="301",
            name="OpenAI",
            entity_type="AI模型厂商",
            rank="A",
            aliases_json=[],
            influence_score=95,
            global_id="til:entity:test-301",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([raw, report, entity])
        session.flush()
        milestone = EntityMilestone(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="entity_milestones",
            legacy_id="401",
            tracked_entity_id=entity.id,
            legacy_entity_id="301",
            legacy_article_id="999",
            legacy_report_id="201",
            historical_report_id=report.id,
            event_time=datetime(2026, 5, 1, 10, tzinfo=timezone.utc),
            event_type="产品/模型发布",
            title="OpenAI 发布新模型",
            source_name="Legacy",
            board="AI模型",
            importance_score=90,
            importance_level="high",
            event_dedupe_key="event-401",
            metadata_json={
                "legacy_refs": {
                    "article_id": "999",
                    "report_id": "201",
                    "article_ref_resolved": False,
                    "report_ref_resolved": True,
                },
            },
            global_id="til:milestone:test-401",
            origin_instance_id="tech_insight_loop",
        )
        session.add(milestone)
        session.commit()

    summary = client.get("/api/legacy-import/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["workspace_code"] == "legacy_tech_insight_loop"
    metrics = {item["key"]: item for item in payload["metrics"]}
    assert metrics["articles"]["actual"] == 1
    assert metrics["articles"]["expected"] == 14834
    assert metrics["articles"]["status"] == "partial"
    assert metrics["historical_reports"]["actual"] == 1
    assert metrics["tracked_entities"]["actual"] == 1
    assert metrics["entity_milestones"]["actual"] == 1
    assert payload["report_refs"] == {"total": 2, "resolved": 1, "unresolved": 1}
    assert payload["milestone_article_refs"] == {"total": 1, "resolved": 0, "unresolved": 1}
    assert payload["milestone_report_refs"] == {"total": 1, "resolved": 1, "unresolved": 0}
    assert payload["total_unresolved_refs"] == 2
    assert payload["gap_item_count"] == 2

    gaps = client.get("/api/legacy-import/gaps", params={"workspace_code": "legacy_tech_insight_loop"})
    assert gaps.status_code == 200
    gap_payload = gaps.json()
    assert {item["kind"] for item in gap_payload} == {"historical_reports", "entity_milestones"}
    report_gap = next(item for item in gap_payload if item["kind"] == "historical_reports")
    assert report_gap["legacy_id"] == "201"
    assert report_gap["unresolved_refs"] == ["999"]
    milestone_gap = next(item for item in gap_payload if item["kind"] == "entity_milestones")
    assert milestone_gap["legacy_id"] == "401"
    assert milestone_gap["unresolved_refs"] == [{"ref_type": "article_id", "legacy_ref": "999"}]


def test_quality_archive_summary_feedback_and_job_runs(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            name="Tech Insight Loop Legacy Archive",
            enabled=False,
            global_id="til:archive-source:quality",
            content_hash="source-hash-quality",
        )
        session.add(source)
        session.flush()
        raw = RawItem(
            data_source_id=source.id,
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            source_name="Legacy",
            entry_key="legacy-101",
            source_title="Legacy article",
            raw_content="raw",
            fetched_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            raw_payload_json={"legacy_tech_insight_loop": {"id": 101}},
            global_id="til:article:quality-101",
            content_hash="raw-hash-quality",
        )
        session.add(raw)
        session.flush()
        feedback = HistoricalFeedbackItem(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            legacy_system="tech_insight_loop",
            legacy_table="feedback",
            legacy_id="501",
            legacy_article_id="999",
            feedback_kind="feedback",
            user_name="analyst",
            feedback_type="not_relevant",
            reason="wrong board",
            comment="should not enter report",
            feedback_at=datetime(2026, 5, 2, 9, tzinfo=timezone.utc),
            metadata_json={
                "legacy_refs": {
                    "article_id": "999",
                    "article_ref_resolved": False,
                },
            },
            global_id="til:feedback:test-501",
            origin_instance_id="tech_insight_loop",
        )
        quality = HistoricalFeedbackItem(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            legacy_system="tech_insight_loop",
            legacy_table="article_quality_feedback",
            legacy_id="601",
            legacy_article_id="101",
            raw_item_id=raw.id,
            feedback_kind="quality_feedback",
            user_name="reviewer",
            feedback_type="low_quality",
            reason="source_noise",
            comment="marketing language",
            feedback_at=datetime(2026, 5, 3, 9, tzinfo=timezone.utc),
            metadata_json={
                "legacy_refs": {
                    "article_id": "101",
                    "article_ref_resolved": True,
                },
            },
            global_id="til:quality-feedback:test-601",
            origin_instance_id="tech_insight_loop",
        )
        job = HistoricalJobRun(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            legacy_system="tech_insight_loop",
            legacy_table="jobs",
            legacy_id="701",
            job_type="rss_fetch",
            status="failed",
            message="timeout",
            started_at=datetime(2026, 5, 4, 9, tzinfo=timezone.utc),
            ended_at=datetime(2026, 5, 4, 9, 1, tzinfo=timezone.utc),
            total_sources=10,
            processed_sources=8,
            inserted_count=6,
            failed_count=2,
            details_json={"failed_sources": ["source-a"]},
            global_id="til:job:test-701",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([feedback, quality, job])
        session.commit()

    summary = client.get("/api/quality-archive/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total_feedback"] == 1
    assert payload["total_quality_feedback"] == 1
    assert payload["total_job_runs"] == 1
    assert payload["unresolved_feedback_count"] == 1
    assert payload["unresolved_feedback_ref_count"] == 1
    assert payload["total_job_failures"] == 2
    assert payload["by_feedback_type"] == {"not_relevant": 1, "low_quality": 1}
    assert payload["by_quality_reason"] == {"source_noise": 1}
    assert payload["by_job_type"] == {"rss_fetch": 1}
    assert payload["by_job_status"] == {"failed": 1}

    unresolved_feedback = client.get(
        "/api/historical-feedback-items",
        params={"workspace_code": "legacy_tech_insight_loop", "has_unresolved_refs": True},
    )
    assert unresolved_feedback.status_code == 200
    unresolved_payload = unresolved_feedback.json()
    assert [item["legacy_id"] for item in unresolved_payload] == ["501"]
    assert unresolved_payload[0]["article_ref_resolved"] is False

    quality_feedback = client.get(
        "/api/historical-feedback-items",
        params={"workspace_code": "legacy_tech_insight_loop", "feedback_kind": "quality_feedback", "q": "marketing"},
    )
    assert quality_feedback.status_code == 200
    assert [item["legacy_id"] for item in quality_feedback.json()] == ["601"]
    assert quality_feedback.json()[0]["article_ref_resolved"] is True

    gaps = client.get(
        "/api/legacy-import/gaps",
        params={"workspace_code": "legacy_tech_insight_loop", "kind": "historical_feedback"},
    )
    assert gaps.status_code == 200
    assert gaps.json()[0]["kind"] == "historical_feedback"
    assert gaps.json()[0]["unresolved_refs"] == [{"ref_type": "article_id", "legacy_ref": "999"}]

    jobs = client.get(
        "/api/historical-job-runs",
        params={"workspace_code": "legacy_tech_insight_loop", "status": "failed", "q": "timeout"},
    )
    assert jobs.status_code == 200
    job_payload = jobs.json()
    assert [item["legacy_id"] for item in job_payload] == ["701"]
    assert job_payload[0]["details_json"] == {"failed_sources": ["source-a"]}


def test_entity_timeline_is_listed_and_read_only(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        entity = TrackedEntity(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="ai_entities",
            legacy_id="301",
            name="OpenAI",
            entity_type="AI模型厂商",
            rank="A",
            aliases_json=["GPT", "ChatGPT"],
            influence_score=95,
            notes="legacy entity",
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:entity:test-301",
            origin_instance_id="tech_insight_loop",
        )
        session.add(entity)
        session.flush()
        linked = EntityMilestone(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="entity_milestones",
            legacy_id="401",
            tracked_entity_id=entity.id,
            legacy_entity_id="301",
            legacy_article_id="101",
            legacy_report_id="201",
            raw_item_id=None,
            historical_report_id=None,
            event_time=datetime(2026, 5, 1, 10, tzinfo=timezone.utc),
            event_type="产品/模型发布",
            title="OpenAI 发布新模型",
            event_content="event content",
            impact="impact",
            event_brief="brief",
            impact_brief="impact brief",
            timeline_brief="timeline",
            source_url="https://example.com/openai",
            source_name="Example",
            board="AI模型",
            selected_for_timeline=True,
            confidence_score=88,
            importance_score=90,
            importance_level="high",
            event_dedupe_key="2026-05-01|release|openai",
            metadata_json={
                "legacy_refs": {
                    "article_id": "101",
                    "report_id": "201",
                    "article_ref_resolved": True,
                    "report_ref_resolved": True,
                },
                "legacy_import": {"recommendation_eligible": False},
            },
            global_id="til:milestone:test-401",
            origin_instance_id="tech_insight_loop",
        )
        unresolved = EntityMilestone(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="entity_milestones",
            legacy_id="402",
            tracked_entity_id=entity.id,
            legacy_entity_id="301",
            legacy_article_id="999",
            legacy_report_id=None,
            event_time=datetime(2026, 5, 2, 10, tzinfo=timezone.utc),
            event_type="战略变化",
            title="OpenAI 调整战略",
            event_content="strategy",
            impact="impact",
            source_url="https://example.com/openai-2",
            source_name="Example",
            board="AI安全、可信与治理",
            selected_for_timeline=True,
            confidence_score=70,
            importance_score=80,
            importance_level="medium",
            event_dedupe_key="2026-05-02|strategy|openai",
            metadata_json={
                "legacy_refs": {
                    "article_id": "999",
                    "article_ref_resolved": False,
                    "report_ref_resolved": None,
                },
                "legacy_import": {"recommendation_eligible": False},
            },
            global_id="til:milestone:test-402",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([linked, unresolved])
        session.commit()
        linked_id = linked.id

    summary = client.get("/api/entity-timeline/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["total_entities"] == 1
    assert summary_payload["total_milestones"] == 2
    assert summary_payload["unresolved_milestone_count"] == 1
    assert summary_payload["by_entity_type"] == {"AI模型厂商": 1}

    entities = client.get("/api/tracked-entities", params={"workspace_code": "legacy_tech_insight_loop", "q": "OpenAI"})
    assert entities.status_code == 200
    entity_payload = entities.json()[0]
    assert entity_payload["name"] == "OpenAI"
    assert entity_payload["milestone_count"] == 2
    assert entity_payload["aliases_json"] == ["GPT", "ChatGPT"]

    unresolved_response = client.get(
        "/api/entity-milestones",
        params={"workspace_code": "legacy_tech_insight_loop", "has_unresolved_refs": True},
    )
    assert unresolved_response.status_code == 200
    unresolved_payload = unresolved_response.json()
    assert [item["legacy_id"] for item in unresolved_payload] == ["402"]
    assert unresolved_payload[0]["article_ref_resolved"] is False

    event_type_response = client.get(
        "/api/entity-milestones",
        params={"workspace_code": "legacy_tech_insight_loop", "event_type": "产品/模型发布"},
    )
    assert event_type_response.status_code == 200
    assert [item["legacy_id"] for item in event_type_response.json()] == ["401"]

    detail = client.get(f"/api/entity-milestones/{linked_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["event_content"] == "event content"
    assert detail_payload["legacy_refs"]["article_ref_resolved"] is True
    assert detail_payload["metadata_json"]["legacy_import"]["recommendation_eligible"] is False
