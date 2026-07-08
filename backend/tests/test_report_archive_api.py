"""历史报告库统一归档 API：已发布日报/周报 + legacy 报告合并、月份/关键词过滤、统计。"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.main import create_app
from app.models import (
    DailyReport,
    DailyReportItem,
    DataSource,
    GeneratedNews,
    HistoricalReport,
    NewsItem,
    RawItem,
    WeeklyReport,
    WeeklyReportItem,
)
from tests.test_auth import make_client
from tests.test_operations_api import _create_local_user

WS = "planning_intel"


def _chain(session, *, key: str, title: str, source_name: str):
    source = DataSource(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        source_type="rss",
        name=source_name,
        url=f"https://example.com/{key}.xml",
    )
    raw = RawItem(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        data_source=source,
        source_type="rss",
        source_name=source_name,
        entry_key=key,
        source_title=title,
        source_url=f"https://example.com/{key}",
        raw_content="raw",
        fetched_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        raw_payload_json={"title": title},
    )
    news = NewsItem(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        raw_item=raw,
        data_source=source,
        source_type="rss",
        source_name=source_name,
        source_url=raw.source_url,
        canonical_url=raw.source_url,
        source_title=title,
        normalized_title=title,
        summary="摘要",
        content="正文",
        published_at=datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
        dedupe_key=key,
    )
    generated = GeneratedNews(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        news_item=news,
        category="智能体",
        title=title,
        summary="摘要",
        source_url=raw.source_url,
        generation_status="ready",
        generated_by="minimax",
    )
    session.add_all([source, raw, news, generated])
    return generated


def _seed_archive(session):
    daily = DailyReport(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="workspace",
        sync_policy="public_to_intranet",
        day_key="2026-07-05",
        title="2026-07-05 AI 情报日报",
        summary="今日头条：Agent 平台化。",
        status="published",
        published_at=datetime(2026, 7, 5, 12, tzinfo=timezone.utc),
    )
    for index, (adoption, headline, source_name) in enumerate(
        [(2, True, "机器之心"), (2, False, "机器之心"), (2, False, "量子位"), (0, False, "36氪")],
    ):
        generated = _chain(session, key=f"daily-{index}", title=f"日报条目 {index}", source_name=source_name)
        session.add(
            DailyReportItem(
                workspace_code=WS,
                domain_code="ai",
                visibility_scope="workspace",
                sync_policy="public_to_intranet",
                daily_report=daily,
                generated_news=generated,
                adoption_status=adoption,
                is_headline=headline,
                sort_order=index,
            ),
        )
    draft_daily = DailyReport(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="workspace",
        sync_policy="public_to_intranet",
        day_key="2026-07-06",
        title="2026-07-06 草稿日报",
        summary="未发布，不应出现在归档。",
        status="draft",
    )
    weekly = WeeklyReport(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="workspace",
        sync_policy="public_to_intranet",
        week_key="2026-W27",
        title="2026-W27 AI 情报周报",
        summary="本周聚焦企业 Agent。",
        status="published",
        published_at=datetime(2026, 7, 6, 12, tzinfo=timezone.utc),
    )
    weekly_generated = _chain(session, key="weekly-0", title="周报条目", source_name="机器之心")
    session.add(
        WeeklyReportItem(
            workspace_code=WS,
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            weekly_report=weekly,
            generated_news=weekly_generated,
            adoption_status=2,
            sort_order=0,
        ),
    )
    legacy = HistoricalReport(
        workspace_code=WS,
        domain_code="ai",
        visibility_scope="workspace",
        sync_policy="manual_only",
        legacy_id="legacy-report-1",
        report_type="daily",
        title="旧系统 2025-06-10 日报",
        status="published_imported",
        period_start_at=datetime(2025, 6, 10, tzinfo=timezone.utc),
        period_end_at=datetime(2025, 6, 10, 23, tzinfo=timezone.utc),
        content="旧系统正文，包含 GPT-5 发布信息。",
        source_refs_json={"resolved": [{"id": 1}, {"id": 2}], "unresolved": [{"id": 3}]},
    )
    session.add_all([daily, draft_daily, weekly, legacy])
    session.commit()
    return daily, weekly, legacy


def test_report_archive_merges_published_and_legacy_with_stats(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        daily, weekly, legacy = _seed_archive(session)
        daily_id, weekly_id, legacy_id = daily.id, weekly.id, legacy.id

    listed = client.get("/api/report-archive", params={"workspace_code": WS})
    assert listed.status_code == 200
    entries = listed.json()
    assert [entry["id"] for entry in entries] == [weekly_id, daily_id, legacy_id]

    weekly_entry, daily_entry, legacy_entry = entries
    assert daily_entry["origin"] == "published"
    assert daily_entry["report_type"] == "daily"
    assert daily_entry["date_key"] == "2026-07-05"
    assert daily_entry["month"] == "2026-07"
    assert daily_entry["item_count"] == 4
    assert daily_entry["adopted_count"] == 3
    assert daily_entry["headline_count"] == 1
    assert daily_entry["adoption_rate"] == 0.75
    assert daily_entry["detail_kind"] == "daily_report"
    assert daily_entry["top_sources"][0] == {"name": "机器之心", "count": 2}
    assert {source["name"] for source in daily_entry["top_sources"]} == {"机器之心", "量子位"}

    assert weekly_entry["report_type"] == "weekly"
    assert weekly_entry["date_key"] == "2026-W27"
    assert weekly_entry["month"] == "2026-06"  # 2026-W27 周一是 2026-06-29
    assert weekly_entry["adopted_count"] == 1

    assert legacy_entry["origin"] == "legacy"
    assert legacy_entry["month"] == "2025-06"
    assert legacy_entry["item_count"] == 3
    assert legacy_entry["detail_kind"] == "historical_report"

    # 草稿日报不进归档
    assert all(entry["date_key"] != "2026-07-06" for entry in entries)

    # 月份过滤
    july = client.get("/api/report-archive", params={"workspace_code": WS, "month": "2026-07"})
    assert [entry["id"] for entry in july.json()] == [daily_id]

    # 关键词过滤命中 legacy 正文
    keyword = client.get("/api/report-archive", params={"workspace_code": WS, "q": "GPT-5"})
    assert [entry["id"] for entry in keyword.json()] == [legacy_id]

    # 来源过滤
    published_only = client.get("/api/report-archive", params={"workspace_code": WS, "origin": "published"})
    assert {entry["id"] for entry in published_only.json()} == {daily_id, weekly_id}

    summary = client.get("/api/report-archive/summary", params={"workspace_code": WS})
    assert summary.status_code == 200
    body = summary.json()
    assert body["total"] == 3
    assert body["published_daily"] == 1
    assert body["published_weekly"] == 1
    assert body["legacy_reports"] == 1
    assert body["total_items"] == 5
    assert body["total_adopted"] == 4
    assert 0 < body["average_adoption_rate"] <= 1
    months = {bucket["month"]: bucket["count"] for bucket in body["months"]}
    assert months == {"2026-07": 1, "2026-06": 1, "2025-06": 1}
    assert [bucket["month"] for bucket in body["months"]] == ["2026-07", "2026-06", "2025-06"]
    # 来源 Top：已发布采信条目聚合（daily 机器之心×2/量子位×1 + weekly 机器之心×1）
    assert body["top_sources"] == [
        {"name": "机器之心", "count": 3},
        {"name": "量子位", "count": 1},
    ]


def test_report_archive_summary_supports_report_type_and_origin_filters(monkeypatch, tmp_path):
    """archive-knowledge-design §5.1 后续增量 1：summary 跳月桶按 report_type/origin 精确计数。"""

    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        _seed_archive(session)

    daily_only = client.get(
        "/api/report-archive/summary", params={"workspace_code": WS, "report_type": "daily"},
    ).json()
    # legacy 报告 report_type=daily，也计入 daily 桶
    assert daily_only["total"] == 2
    assert daily_only["published_daily"] == 1
    assert daily_only["published_weekly"] == 0
    assert daily_only["legacy_reports"] == 1
    assert {bucket["month"]: bucket["count"] for bucket in daily_only["months"]} == {
        "2026-07": 1,
        "2025-06": 1,
    }
    assert daily_only["total_items"] == 4
    assert daily_only["total_adopted"] == 3
    assert daily_only["top_sources"] == [
        {"name": "机器之心", "count": 2},
        {"name": "量子位", "count": 1},
    ]

    weekly_only = client.get(
        "/api/report-archive/summary", params={"workspace_code": WS, "report_type": "weekly"},
    ).json()
    assert weekly_only["total"] == 1
    assert weekly_only["published_weekly"] == 1
    assert weekly_only["legacy_reports"] == 0
    assert {bucket["month"] for bucket in weekly_only["months"]} == {"2026-06"}
    assert weekly_only["total_items"] == 1
    assert weekly_only["top_sources"] == [{"name": "机器之心", "count": 1}]

    legacy_only = client.get(
        "/api/report-archive/summary", params={"workspace_code": WS, "origin": "legacy"},
    ).json()
    assert legacy_only["total"] == 1
    assert legacy_only["published_daily"] == 0
    assert legacy_only["published_weekly"] == 0
    assert legacy_only["legacy_reports"] == 1
    assert {bucket["month"] for bucket in legacy_only["months"]} == {"2025-06"}
    # legacy 无采信/来源数据：不给占位统计
    assert legacy_only["total_items"] == 0
    assert legacy_only["total_adopted"] == 0
    assert legacy_only["average_adoption_rate"] == 0.0
    assert legacy_only["top_sources"] == []
    assert legacy_only["latest_published_at"] is None

    published_only = client.get(
        "/api/report-archive/summary", params={"workspace_code": WS, "origin": "published"},
    ).json()
    assert published_only["total"] == 2
    assert published_only["legacy_reports"] == 0
    assert {bucket["month"] for bucket in published_only["months"]} == {"2026-07", "2026-06"}

    bad_type = client.get(
        "/api/report-archive/summary", params={"workspace_code": WS, "report_type": "monthly"},
    )
    assert bad_type.status_code == 422


def test_report_archive_sql_aggregation_path_matches_in_memory(monkeypatch, tmp_path):
    """archive-knowledge-design §5.1 后续增量 2：超阈值走 SQL 聚合降级路径，API 输出与内存路径一致。"""

    from app.archive import report_archive

    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        _seed_archive(session)

    baseline_cases = [
        ("/api/report-archive", {"workspace_code": WS}),
        ("/api/report-archive", {"workspace_code": WS, "month": "2026-07"}),
        ("/api/report-archive", {"workspace_code": WS, "q": "GPT-5"}),
        ("/api/report-archive", {"workspace_code": WS, "origin": "published"}),
        ("/api/report-archive", {"workspace_code": WS, "report_type": "daily"}),
        ("/api/report-archive", {"workspace_code": WS, "offset": 1, "limit": 1}),
        ("/api/report-archive/summary", {"workspace_code": WS}),
        ("/api/report-archive/summary", {"workspace_code": WS, "report_type": "daily"}),
        ("/api/report-archive/summary", {"workspace_code": WS, "origin": "legacy"}),
    ]
    baselines = []
    for path, params in baseline_cases:
        response = client.get(path, params=params)
        assert response.status_code == 200
        baselines.append(response.json())

    # 阈值压到 -1 强制走 SQL 聚合路径
    monkeypatch.setattr(report_archive, "SQL_AGGREGATION_THRESHOLD", -1)
    for (path, params), baseline in zip(baseline_cases, baselines):
        response = client.get(path, params=params)
        assert response.status_code == 200
        assert response.json() == baseline, f"SQL 聚合路径输出与内存路径不一致: {path} {params}"


def test_report_archive_requires_workspace_membership(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        _seed_archive(session)
    viewer = _create_local_user(engine, "archive-viewer", "password-123", workspace_role="viewer")
    outsider = _create_local_user(engine, "archive-outsider", "password-123", workspace_role=None)

    viewer_client = TestClient(create_app())
    assert viewer_client.post(
        "/api/auth/login",
        json={"username": viewer.username, "password": "password-123"},
    ).status_code == 200
    listed = viewer_client.get("/api/report-archive", params={"workspace_code": WS})
    assert listed.status_code == 200
    assert len(listed.json()) == 3
    assert viewer_client.get("/api/report-archive/summary", params={"workspace_code": WS}).status_code == 200

    outsider_client = TestClient(create_app())
    assert outsider_client.post(
        "/api/auth/login",
        json={"username": outsider.username, "password": "password-123"},
    ).status_code == 200
    assert outsider_client.get("/api/report-archive", params={"workspace_code": WS}).status_code == 403
    assert outsider_client.get("/api/report-archive/summary", params={"workspace_code": WS}).status_code == 403
