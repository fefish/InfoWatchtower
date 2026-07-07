from pathlib import Path
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.content import IngestionRun, NewsItem, RawItem


def make_client(monkeypatch, tmp_path):
    database_path = tmp_path / "sources.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_MODE", "public_password")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    monkeypatch.setenv(
        "LEGACY_SEED_ROOT",
        str(Path(__file__).resolve().parents[2] / "config" / "seeds" / "legacy"),
    )
    monkeypatch.setenv(
        "TECH_INSIGHT_LOOP_SOURCE_CSV",
        str(
            Path(__file__).resolve().parents[2]
            / "config"
            / "seeds"
            / "tech_insight_loop"
            / "sources_full_zh.csv",
        ),
    )
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app())


def test_super_admin_imports_and_lists_legacy_sources(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    preview = client.get("/api/sources/import-preview", params={"catalog": "legacy"})
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["catalog"] == "legacy"
    assert preview_payload["total"] == 361
    assert preview_payload["would_create"] == 294
    assert preview_payload["would_update"] == 67
    assert preview_payload["samples"]

    imported = client.post("/api/sources/import-legacy-seeds")
    assert imported.status_code == 200
    assert imported.json() == {"created": 294, "updated": 67, "total": 361}

    after_preview = client.get("/api/sources/import-preview", params={"catalog": "legacy"})
    assert after_preview.status_code == 200
    assert after_preview.json()["would_create"] == 0

    sources = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert sources.status_code == 200
    payload = sources.json()
    assert len(payload) == 294
    assert sum(1 for item in payload if item["workspace_link_enabled"]) == 294
    assert "workspace_label_set_codes" not in payload[0]
    assert "workspace_default_label_paths" not in payload[0]
    assert {item["source_type"] for item in payload} == {
        "page_manual",
        "page_monitor",
        "paper_rss",
        "rss",
        "wiseflow",
    }

    ai_tool_sources = client.get("/api/sources", params={"workspace_code": "ai_tools"})
    assert ai_tool_sources.status_code == 200
    ai_tool_payload = ai_tool_sources.json()
    assert len(ai_tool_payload) == 294
    assert sum(1 for item in ai_tool_payload if item["workspace_link_enabled"]) == 294

    updated = client.patch(
        f"/api/sources/{payload[0]['id']}/workspace-link",
        json={
            "workspace_code": "planning_intel",
            "enabled": True,
            "source_weight": 1.5,
            "daily_limit": 3,
        },
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["workspace_source_weight"] == 1.5
    assert updated_payload["workspace_daily_limit"] == 3
    assert "workspace_label_set_codes" not in updated_payload
    assert "workspace_default_label_paths" not in updated_payload

    repeated = client.post("/api/sources/import-legacy-seeds")
    assert repeated.status_code == 200
    assert repeated.json() == {"created": 0, "updated": 361, "total": 361}


def test_super_admin_imports_tech_insight_loop_sources(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post("/api/sources/import-tech-insight-loop")
    assert imported.status_code == 200
    assert imported.json() == {
        "created": 363,
        "updated": 23,
        "total": 386,
        "fetchable": 355,
        "metadata_only": 31,
    }

    sources = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert sources.status_code == 200
    payload = sources.json()
    assert len(payload) == 363
    assert sum(1 for item in payload if item["workspace_link_enabled"]) == 332
    assert any(
        item["name"] == "机器之心"
        and item["metadata_only"] is True
        and item["needs_entry"] is True
        and item["workspace_link_enabled"] is False
        and item["source_tier"] == "P0"
        and item["source_channel_type"]
        and isinstance(item["expert_routes"], list)
        for item in payload
    )

    repeated = client.post("/api/sources/import-tech-insight-loop")
    assert repeated.status_code == 200
    assert repeated.json() == {
        "created": 0,
        "updated": 386,
        "total": 386,
        "fetchable": 355,
        "metadata_only": 31,
    }


def test_super_admin_creates_and_edits_custom_source(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "自建测试 RSS",
            "source_type": "rss",
            "url": "https://example.com/custom.rss",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["created"] is True
    source = payload["source"]
    assert source["source_type"] == "rss"
    assert source["url"] == "https://example.com/custom.rss"
    assert source["backfill_days"] == 7
    assert source["workspace_link_enabled"] is True

    bad_type = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "非法类型",
            "source_type": "csv",
            "url": "https://example.com/bad.csv",
        },
    )
    assert bad_type.status_code == 400

    bad_url = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "非法地址",
            "source_type": "rss",
            "url": "ftp://example.com/bad.rss",
        },
    )
    assert bad_url.status_code == 400

    conflict = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "重复地址",
            "source_type": "rss",
            "url": "https://example.com/custom.rss",
            "reuse_existing": False,
        },
    )
    assert conflict.status_code == 409

    patched = client.patch(
        f"/api/sources/{source['id']}",
        params={"workspace_code": "planning_intel"},
        json={"name": "自建测试 RSS v2", "backfill_days": 14},
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload["name"] == "自建测试 RSS v2"
    assert patched_payload["backfill_days"] == 14
    assert patched_payload["workspace_link_enabled"] is True

    empty = client.patch(f"/api/sources/{source['id']}", json={})
    assert empty.status_code == 400


def test_super_admin_creates_custom_paper_api_source(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "arXiv AI API",
            "source_type": "paper_api",
            "url": "https://export.arxiv.org/api/query?search_query=cat:cs.AI",
            "backfill_days": 30,
        },
    )

    assert created.status_code == 201
    source = created.json()["source"]
    assert source["source_type"] == "paper_api"
    assert source["url"] == "https://export.arxiv.org/api/query?search_query=cat:cs.AI"
    assert source["workspace_link_enabled"] is True
    assert source["backfill_days"] == 30


def test_source_detail_exposes_safe_raw_run_trend_and_errors(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "name": "详情测试 RSS",
            "source_type": "rss",
            "url": "https://example.com/detail.rss",
        },
    )
    assert created.status_code == 201
    source_id = created.json()["source"]["id"]

    Session = sessionmaker(bind=get_engine())
    with Session() as session:
        raw = RawItem(
            data_source_id=source_id,
            workspace_code="shared",
            domain_code="ai",
            source_type="rss",
            source_name="详情测试 RSS",
            entry_key="detail:1",
            source_title="详情页最近 raw 标题",
            source_url="https://example.com/detail-1",
            raw_content="这是一条用于源详情页展示的 raw 内容。" * 10,
            fetched_at=datetime(2026, 7, 5, 8, tzinfo=UTC),
            published_at=datetime(2026, 7, 5, 7, tzinfo=UTC),
            raw_payload_json={"token": "must-not-leak"},
        )
        session.add(raw)
        session.flush()
        session.add(
            NewsItem(
                raw_item_id=raw.id,
                data_source_id=source_id,
                workspace_code="planning_intel",
                domain_code="ai",
                source_type="rss",
                source_name="详情测试 RSS",
                source_url=raw.source_url,
                canonical_url=raw.source_url,
                source_title=raw.source_title,
                normalized_title="详情页最近 raw 标题",
                summary="summary",
                content="content",
                published_at=raw.published_at,
                dedupe_key="detail-dedupe",
            ),
        )
        session.add(
            IngestionRun(
                workspace_code="planning_intel",
                domain_code="ai",
                run_key="detail-run",
                run_type="workspace_fetch",
                status="partial",
                completed_at=datetime(2026, 7, 5, 8, 5, tzinfo=UTC),
                summary_json={
                    "sources": [
                        {
                            "data_source_id": source_id,
                            "source_type": "rss",
                            "status": "failed",
                            "fetched": 0,
                            "created": 0,
                            "updated": 0,
                            "error": "TimeoutError",
                        }
                    ]
                },
            ),
        )
        session.commit()

    detail = client.get(f"/api/sources/{source_id}", params={"workspace_code": "planning_intel"})

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["source"]["id"] == source_id
    assert payload["raw_count"] == 1
    assert payload["news_count"] == 1
    assert payload["recent_raw_items"][0]["source_title"] == "详情页最近 raw 标题"
    assert payload["recent_raw_items"][0]["raw_content_excerpt"].endswith("...")
    assert payload["recent_runs"][0]["run_key"] == "detail-run"
    assert payload["error_logs"][0]["error"] == "TimeoutError"
    assert payload["raw_trend"] == [{"day_key": "2026-07-05", "raw_count": 1}]
    assert "raw_payload_json" not in payload["recent_raw_items"][0]
    assert "must-not-leak" not in detail.text

    viewer_invite = client.post(
        "/api/auth/invites",
        json={
            "role_code": "viewer",
            "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
            "expires_in_days": 7,
        },
    )
    assert viewer_invite.status_code == 200
    viewer = TestClient(create_app())
    accepted = viewer.post(
        f"/api/auth/invites/{viewer_invite.json()['code']}/accept",
        json={
            "username": "source-detail-viewer",
            "display_name": "源详情 Viewer",
            "password": "strong-password",
        },
    )
    assert accepted.status_code == 200

    viewer_detail = viewer.get(f"/api/sources/{source_id}", params={"workspace_code": "planning_intel"})
    assert viewer_detail.status_code == 200
    assert viewer_detail.json()["source"]["id"] == source_id

    global_detail = viewer.get(f"/api/sources/{source_id}")
    assert global_detail.status_code == 403


def test_patch_url_fills_entry_for_metadata_only_source(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post("/api/sources/import-tech-insight-loop")
    assert imported.status_code == 200

    sources = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert sources.status_code == 200
    # CSV 里有两条「机器之心」（rss + wx://）；wx 行现在映射为 source_type=wechat，
    # 按 metadata_only 精确选中待补入口的治理记录，不依赖列表排序。
    target = next(
        item
        for item in sources.json()
        if item["name"] == "机器之心" and item["metadata_only"] is True
    )
    assert target["needs_entry"] is True
    assert target["metadata_only"] is True

    patched = client.patch(
        f"/api/sources/{target['id']}",
        params={"workspace_code": "planning_intel"},
        json={"url": "https://example.com/jiqizhixin.rss"},
    )
    assert patched.status_code == 200
    patched_payload = patched.json()
    assert patched_payload["url"] == "https://example.com/jiqizhixin.rss"
    assert patched_payload["needs_entry"] is False
    assert patched_payload["metadata_only"] is False
    assert patched_payload["fetch_entry_status"] == "manual_entry_added"

    reimported = client.post("/api/sources/import-tech-insight-loop")
    assert reimported.status_code == 200

    after_reimport = client.get("/api/sources", params={"workspace_code": "planning_intel"})
    assert after_reimport.status_code == 200
    survivor = next(item for item in after_reimport.json() if item["id"] == target["id"])
    assert survivor["url"] == "https://example.com/jiqizhixin.rss"
    assert survivor["needs_entry"] is False
    assert survivor["metadata_only"] is False
    assert survivor["fetch_entry_status"] == "manual_entry_added"


def test_ingestion_limit_zero_is_rejected_and_empty_selection_is_no_sources(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post("/api/sources/import-legacy-seeds")
    assert imported.status_code == 200

    rejected = client.post(
        "/api/ingestion/runs",
        json={
            "workspace_code": "planning_intel",
            "source_types": ["rss", "paper_rss"],
            "limit": 0,
        },
    )
    assert rejected.status_code == 422

    created = client.post(
        "/api/ingestion/runs",
        json={
            "workspace_code": "planning_intel",
            "source_types": ["paper_api"],
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["workspace_code"] == "planning_intel"
    assert payload["status"] == "no_sources"
    assert payload["source_total"] == 0
    assert payload["params_json"]["source_types"] == ["paper_api"]
    assert payload["summary_json"]["hint"]

    listed = client.get("/api/ingestion/runs", params={"workspace_code": "planning_intel"})
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == payload["id"]

    detail = client.get(f"/api/ingestion/runs/{payload['id']}")
    assert detail.status_code == 200
    assert detail.json()["run_key"] == payload["run_key"]

    coverage = client.get(
        "/api/ingestion/coverage",
        params={
            "workspace_code": "planning_intel",
            "day_key": "2026-05-05",
            "run_id": payload["id"],
        },
    )
    assert coverage.status_code == 200
    coverage_payload = coverage.json()
    assert coverage_payload["run_id"] == payload["id"]
    assert coverage_payload["funnel"]["enabled_sources"] == 294
    assert coverage_payload["funnel"]["run_sources"] == 0
    assert coverage_payload["sources"]
