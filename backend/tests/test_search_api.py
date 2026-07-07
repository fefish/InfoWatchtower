from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models.content import DataSource
from app.models.export import ExportJob, ExportJobItem
from app.models.reports import DailyReportItem, ReportRendition
from app.models.sync import SyncConflict, SyncRun
from app.models.workspace import Workspace, WorkspaceSourceLink
from tests.test_account_lifecycle import _create_local_user, _create_report_bundle
from tests.test_auth import make_client


def test_search_returns_workspace_objects_and_routes(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    bundle = _create_report_bundle(engine)

    source = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "source_type": "rss",
            "name": "Searchable RSS",
            "url": "https://example.com/searchable.xml",
        },
    )
    assert source.status_code == 201
    source_id = source.json()["source"]["id"]

    report_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "Generated",
            "types": "daily_report_item,generated_news",
        },
    )
    assert report_search.status_code == 200
    report_payload = report_search.json()
    assert report_payload["query"] == "Generated"
    daily_item = next(item for item in report_payload["results"] if item["object_type"] == "daily_report_item")
    assert daily_item["object_id"] == bundle["daily_item_id"]
    assert daily_item["route"] == f"/daily-reports?item_id={bundle['daily_item_id']}"
    assert "title" in daily_item["matched_fields"]

    weekly_item_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "Generated",
            "types": "weekly_report_item",
        },
    )
    assert weekly_item_search.status_code == 200
    weekly_item = weekly_item_search.json()["results"][0]
    assert weekly_item["object_type"] == "weekly_report_item"
    assert weekly_item["object_id"] == bundle["weekly_item_id"]
    assert weekly_item["route"] == (
        f"/weekly-reports?report_id={bundle['weekly_report_id']}&item_id={bundle['weekly_item_id']}"
    )

    rendition_ids = _create_report_renditions(engine, bundle)
    daily_rendition_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "技术洞察日报",
            "types": "report_rendition",
        },
    )
    assert daily_rendition_search.status_code == 200
    daily_rendition = daily_rendition_search.json()["results"][0]
    assert daily_rendition["object_type"] == "report_rendition"
    assert daily_rendition["object_id"] == rendition_ids["daily_rendition_id"]
    assert daily_rendition["route"] == (
        f"/daily-reports?report_id={bundle['daily_report_id']}"
        f"&rendition_id={rendition_ids['daily_rendition_id']}&format_code=tech_insight_v1"
    )

    weekly_rendition_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "weekly_brief_v1",
            "types": "report_rendition",
        },
    )
    assert weekly_rendition_search.status_code == 200
    weekly_rendition = weekly_rendition_search.json()["results"][0]
    assert weekly_rendition["object_type"] == "report_rendition"
    assert weekly_rendition["object_id"] == rendition_ids["weekly_rendition_id"]
    assert weekly_rendition["route"] == (
        f"/weekly-reports?report_id={bundle['weekly_report_id']}"
        f"&rendition_id={rendition_ids['weekly_rendition_id']}&format_code=weekly_brief_v1"
    )

    source_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "Searchable",
            "types": "data_source",
        },
    )
    assert source_search.status_code == 200
    source_payload = source_search.json()
    assert source_payload["results"][0]["object_type"] == "data_source"
    assert source_payload["results"][0]["object_id"] == source_id
    assert source_payload["results"][0]["route"] == f"/sources/{source_id}"


def test_search_requires_workspace_membership(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    _create_report_bundle(engine)
    _create_local_user(engine, "outsider", "password-123", workspace_role=None)

    assert client.post("/api/auth/login", json={"username": "outsider", "password": "password-123"}).status_code == 200
    response = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "Generated",
        },
    )

    assert response.status_code == 403


def test_search_returns_export_jobs_and_super_admin_sync_conflicts(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    ids = _create_export_and_sync_objects(engine)

    export_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "company_sql",
            "types": "export_job",
        },
    )
    assert export_search.status_code == 200
    export_result = export_search.json()["results"][0]
    assert export_result["object_type"] == "export_job"
    assert export_result["object_id"] == ids["export_job_id"]
    assert export_result["route"] == f"/exports?export_job_id={ids['export_job_id']}"

    export_item_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "ai_journal",
            "types": "export_job_item",
        },
    )
    assert export_item_search.status_code == 200
    export_item_result = export_item_search.json()["results"][0]
    assert export_item_result["object_type"] == "export_job_item"
    assert export_item_result["object_id"] == ids["export_job_item_id"]
    assert export_item_result["route"] == (
        f"/exports?export_job_id={ids['export_job_id']}&export_job_item_id={ids['export_job_item_id']}"
    )

    sync_run_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "external-package-search-001",
            "types": "sync_run",
        },
    )
    assert sync_run_search.status_code == 200
    sync_run_result = sync_run_search.json()["results"][0]
    assert sync_run_result["object_type"] == "sync_run"
    assert sync_run_result["object_id"] == ids["sync_run_id"]
    assert sync_run_result["route"] == f"/sync?sync_run_id={ids['sync_run_id']}"

    conflict_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "global-source-import-002",
            "types": "sync_conflict",
        },
    )
    assert conflict_search.status_code == 200
    conflict_result = conflict_search.json()["results"][0]
    assert conflict_result["object_type"] == "sync_conflict"
    assert conflict_result["object_id"] == ids["sync_conflict_id"]
    assert conflict_result["route"] == f"/sync?conflict_id={ids['sync_conflict_id']}"


def test_search_sync_objects_require_super_admin(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    _create_export_and_sync_objects(engine)
    _create_local_user(engine, "workspace-viewer", "password-123", workspace_role="viewer")

    assert client.post(
        "/api/auth/login",
        json={"username": "workspace-viewer", "password": "password-123"},
    ).status_code == 200
    response = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "global-source-import-002",
            "types": "sync_conflict",
        },
    )

    assert response.status_code == 403

    run_response = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "external-package-search-001",
            "types": "sync_run",
        },
    )

    assert run_response.status_code == 403


def test_search_suppresses_data_sources_when_ingestion_capability_is_disabled(monkeypatch, tmp_path):
    client, engine = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="intranet",
        AUTH_MODE="intranet_header",
        AUTH_AUTO_PROVISION="true",
        AUTH_DEFAULT_ROLE="viewer",
        AUTH_DEFAULT_WORKSPACE_CODES="planning_intel:viewer",
    )
    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        assert workspace is not None
        source = DataSource(
            workspace_code="shared",
            domain_code="ai",
            source_type="rss",
            name="Intranet Hidden RSS",
            url="https://example.com/hidden.xml",
        )
        session.add(
            WorkspaceSourceLink(
                workspace=workspace,
                data_source=source,
                domain_code="ai",
                enabled=True,
            ),
        )
        session.commit()

    headers = {
        "X-Employee-No": "E-search-001",
        "X-Employee-Name": "%E5%86%85%E7%BD%91%E6%90%9C%E7%B4%A2%E7%94%A8%E6%88%B7",
        "X-Department": "%E8%A7%84%E5%88%92%E9%83%A8",
    }
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    default_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "Hidden",
        },
        headers=headers,
    )
    assert default_search.status_code == 200
    assert all(item["object_type"] != "data_source" for item in default_search.json()["results"])

    data_source_search = client.get(
        "/api/search",
        params={
            "workspace_code": "planning_intel",
            "q": "Hidden",
            "types": "data_source",
        },
        headers=headers,
    )
    assert data_source_search.status_code == 200
    assert data_source_search.json()["results"] == []


def _create_export_and_sync_objects(engine) -> dict[str, str]:
    bundle = _create_report_bundle(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        daily_item = session.get(DailyReportItem, bundle["daily_item_id"])
        assert daily_item is not None
        generated = daily_item.generated_news
        assert generated is not None
        export_job = ExportJob(
            workspace_code="planning_intel",
            export_type="company_sql",
            status="completed",
            result_json={"item_count": 2, "statement_count": 8},
        )
        session.add(export_job)
        session.flush()
        export_item = ExportJobItem(
            export_job_id=export_job.id,
            daily_report_item_id=daily_item.id,
            generated_news_id=generated.id,
            news_item_id=generated.news_item_id,
            sql_sequence=1,
            sql_table="ai_journal",
            sql_text="INSERT INTO ai_journal (source_title) VALUES ('Generated');",
            status="completed",
        )
        session.add(export_item)
        sync_run = SyncRun(
            package_id="external-package-search-001",
            source_instance_id="extranet",
            target_instance_id="intranet",
            direction="import",
            status="completed_with_conflicts",
        )
        session.add(sync_run)
        session.flush()
        conflict = SyncConflict(
            sync_run_id=sync_run.id,
            object_type="data_sources",
            object_id="global-source-import-002",
            field_name="record",
            conflict_reason="same revision has different content hash",
            status="open",
            local_value_json={"name": "同步源"},
            incoming_value_json={"name": "冲突源"},
        )
        session.add(conflict)
        session.commit()
        return {
            "export_job_id": export_job.id,
            "export_job_item_id": export_item.id,
            "sync_run_id": sync_run.id,
            "sync_conflict_id": conflict.id,
        }


def _create_report_renditions(engine, bundle: dict[str, str]) -> dict[str, str]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        daily = ReportRendition(
            workspace_code="planning_intel",
            domain_code="ai",
            report_type="daily",
            report_id=bundle["daily_report_id"],
            format_code="tech_insight_v1",
            status="draft",
            title="2026-07-03 规划部 技术洞察日报",
            summary_json={"period_key": "2026-07-03", "item_total": 1, "source_total": 1},
            body_json={"format_code": "tech_insight_v1"},
            generated_by="rule_projection_v1",
        )
        weekly = ReportRendition(
            workspace_code="planning_intel",
            domain_code="ai",
            report_type="weekly",
            report_id=bundle["weekly_report_id"],
            format_code="weekly_brief_v1",
            status="draft",
            title="2026-W27 规划部 weekly_brief_v1",
            summary_json={"period_key": "2026-W27", "item_total": 1, "source_total": 1},
            body_json={"format_code": "weekly_brief_v1"},
            generated_by="rule_projection_v1",
        )
        session.add_all([daily, weekly])
        session.commit()
        return {
            "daily_rendition_id": daily.id,
            "weekly_rendition_id": weekly.id,
        }
