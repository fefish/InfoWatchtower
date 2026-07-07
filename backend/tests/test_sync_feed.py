"""feed 发布端直测（多环境同步验收 §5.7 与部署形态能力门）。

覆盖 test_deployment_modes.py 之外的 feed 边界：
- keyset (updated_at, id) 多页翻页（含同 updated_at 不同 id 的 tie-break）
- 同一 cursor 重放返回相同结果、非法 cursor 400
- 密钥红线：含 secret 字段的 payload 不下发但游标照常前进
- 非 publisher 形态 403 capability_disabled
- feed 访问审计与 name:token 消费者身份
- 手工包导入按对象依赖序排序，一轮 apply 即净
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_engine
from app.models.content import DataSource, GeneratedNews, NewsItem, RawItem
from app.models.feedback import AuditLog
from app.sync.feed import InvalidFeedCursorError, decode_cursor, feed_page
from app.sync.records import sort_records_by_dependency
from tests.test_deployment_modes import intranet_env, make_client


def _data_source(global_id: str, updated_at: datetime, *, object_id: str | None = None, **overrides) -> DataSource:
    fields = {
        "global_id": global_id,
        "origin_instance_id": "extranet-test",
        "revision": 1,
        "content_hash": f"hash-{global_id}",
        "workspace_code": "shared",
        "domain_code": "ai",
        "visibility_scope": "public",
        "sync_policy": "public_to_intranet",
        "source_type": "rss",
        "name": global_id,
        "url": f"https://example.com/{global_id}.xml",
        "updated_at": updated_at,
    }
    fields.update(overrides)
    if object_id is not None:
        fields["id"] = object_id
    return DataSource(**fields)


def _feed_db(tmp_path):
    database_path = tmp_path / "sync_feed.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_feed_page_multi_page_keyset_pagination_covers_tie_break(tmp_path):
    Session = _feed_db(tmp_path)
    t0 = datetime(2026, 7, 7, 10, 0, 0, 111111)
    with Session() as session:
        session.add_all(
            [
                _data_source("s1", t0, object_id="id-a"),
                _data_source("s2", t0 + timedelta(seconds=1), object_id="id-b"),
                # 同一 updated_at、不同 id：驱动 (updated_at, id) 复合游标的 tie-break
                _data_source("s3", t0 + timedelta(seconds=2), object_id="id-c"),
                _data_source("s4", t0 + timedelta(seconds=2), object_id="id-d"),
                _data_source("s5", t0 + timedelta(seconds=3), object_id="id-e"),
            ],
        )
        session.commit()

    with Session() as session:
        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            page = feed_page(session, "data_sources", cursor=cursor, limit=2)
            pages += 1
            seen.extend(record["object_global_id"] for record in page.records)
            if not page.has_more or not page.next_cursor:
                break
            cursor = page.next_cursor
            assert pages < 10, "keyset 翻页未收敛"

        # 每行恰好出现一次，顺序与 (updated_at, id) 一致，无漏发无重复
        assert seen == ["s1", "s2", "s3", "s4", "s5"]
        assert pages == 3

        # 落在 tie 中间的游标：s3 之后必须继续给 s4，不能跳过同 updated_at 的行
        first_two = feed_page(session, "data_sources", limit=3)
        assert [record["object_global_id"] for record in first_two.records] == ["s1", "s2", "s3"]
        after_tie = feed_page(session, "data_sources", cursor=first_two.next_cursor, limit=3)
        assert [record["object_global_id"] for record in after_tie.records] == ["s4", "s5"]


def test_feed_page_same_cursor_replays_identical_results(tmp_path):
    Session = _feed_db(tmp_path)
    t0 = datetime(2026, 7, 7, 10, 0, 0, 111111)
    with Session() as session:
        session.add_all(
            [
                _data_source("s1", t0, object_id="id-a"),
                _data_source("s2", t0 + timedelta(seconds=1), object_id="id-b"),
                _data_source("s3", t0 + timedelta(seconds=2), object_id="id-c"),
            ],
        )
        session.commit()

    with Session() as session:
        page1 = feed_page(session, "data_sources", limit=1)
        replay1 = feed_page(session, "data_sources", limit=1)
        assert page1.records == replay1.records
        assert page1.next_cursor == replay1.next_cursor

        page2 = feed_page(session, "data_sources", cursor=page1.next_cursor, limit=1)
        replay2 = feed_page(session, "data_sources", cursor=page1.next_cursor, limit=1)
        assert page2.records == replay2.records
        assert [record["object_global_id"] for record in page2.records] == ["s2"]
        # 同一对象同一版本重放产生相同 event_id（consumer inbox 幂等的前提）
        assert page2.records[0]["event_id"] == replay2.records[0]["event_id"]


def test_feed_page_rejects_invalid_cursor(tmp_path):
    Session = _feed_db(tmp_path)
    with Session() as session:
        with pytest.raises(InvalidFeedCursorError):
            feed_page(session, "data_sources", cursor="not-base64-@@@")
        with pytest.raises(InvalidFeedCursorError):
            # 合法 base64 但缺 "|id" 结构
            feed_page(session, "data_sources", cursor="aGVsbG8=")
    with pytest.raises(InvalidFeedCursorError):
        decode_cursor("aGVsbG8=")


def test_extranet_feed_returns_400_for_invalid_cursor(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="extranet",
        SYNC_SERVICE_TOKENS="feed-token",
    )
    response = client.get(
        "/api/sync/feed",
        params={"object_type": "data_sources", "cursor": "not-base64-@@@"},
        headers={"Authorization": "Bearer feed-token"},
    )
    assert response.status_code == 400
    assert "invalid feed cursor" in response.json()["detail"]


def test_extranet_feed_blocks_secret_payload_but_cursor_advances(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="extranet",
        SYNC_SERVICE_TOKENS="feed-token",
    )
    engine = get_engine()
    assert engine is not None
    Session = sessionmaker(bind=engine)
    t0 = datetime(2026, 7, 7, 10, 0, 0, 111111)
    with Session() as session:
        session.add_all(
            [
                _data_source(
                    "source-with-secret",
                    t0,
                    object_id="id-secret",
                    credential_ref="vault://feed-secret",
                    fetch_config={"api_token": "super-secret-token-value"},
                ),
                _data_source("source-clean", t0 + timedelta(seconds=1), object_id="id-clean"),
            ],
        )
        session.commit()

    headers = {"Authorization": "Bearer feed-token"}
    page1 = client.get(
        "/api/sync/feed",
        params={"object_type": "data_sources", "limit": 1},
        headers=headers,
    )
    assert page1.status_code == 200
    payload1 = page1.json()
    # 含密钥 payload 的行不下发，但游标照常前进（不会卡在该行反复重试）
    assert payload1["records"] == []
    assert payload1["next_cursor"]
    assert payload1["has_more"] is True
    assert "super-secret-token-value" not in page1.text

    page2 = client.get(
        "/api/sync/feed",
        params={"object_type": "data_sources", "limit": 1, "cursor": payload1["next_cursor"]},
        headers=headers,
    )
    assert page2.status_code == 200
    payload2 = page2.json()
    assert [record["object_global_id"] for record in payload2["records"]] == ["source-clean"]
    assert "super-secret-token-value" not in page2.text


@pytest.mark.parametrize(
    ("mode", "extra_env"),
    [
        ("cloud", {"DEPLOY_MODE": "cloud", "AUTH_MODE": "public_password"}),
        ("intranet", intranet_env()),
        ("standalone", {}),
    ],
)
def test_non_publisher_modes_gate_feed_with_403_capability_disabled(monkeypatch, tmp_path, mode, extra_env):
    env = {"SYNC_SERVICE_TOKENS": "feed-token", **extra_env}
    if mode == "intranet":
        env["DEPLOY_MODE"] = "intranet"
    client = make_client(monkeypatch, tmp_path, **env)
    headers = {"Authorization": "Bearer feed-token"}

    feed = client.get(
        "/api/sync/feed",
        params={"object_type": "data_sources"},
        headers=headers,
    )
    assert feed.status_code == 403, mode
    assert feed.json()["detail"] == {
        "code": "capability_disabled",
        "capability": "sync_publisher",
    }, mode

    manifest = client.get("/api/sync/feed/manifest", headers=headers)
    assert manifest.status_code == 403, mode
    assert manifest.json()["detail"] == {
        "code": "capability_disabled",
        "capability": "sync_publisher",
    }, mode


def test_feed_access_writes_audit_with_consumer_identity(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="extranet",
        SYNC_SERVICE_TOKENS="intranet-a:token-aaa, plain-token",
    )
    engine = get_engine()
    assert engine is not None
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(_data_source("source-audit-1", datetime(2026, 7, 7, 10, 0, 0, 111111)))
        session.commit()

    # 命名 token：consumer 身份进审计
    manifest = client.get(
        "/api/sync/feed/manifest",
        headers={"Authorization": "Bearer token-aaa"},
    )
    assert manifest.status_code == 200
    named = client.get(
        "/api/sync/feed",
        params={"object_type": "data_sources"},
        headers={"Authorization": "Bearer token-aaa"},
    )
    assert named.status_code == 200

    # 纯 token 兼容：按位置命名 token-2
    plain = client.get(
        "/api/sync/feed",
        params={"object_type": "data_sources"},
        headers={"Authorization": "Bearer plain-token"},
    )
    assert plain.status_code == 200

    # 名字本身或整条 name:token 都不是合法凭据
    assert (
        client.get(
            "/api/sync/feed",
            params={"object_type": "data_sources"},
            headers={"Authorization": "Bearer intranet-a"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/sync/feed",
            params={"object_type": "data_sources"},
            headers={"Authorization": "Bearer intranet-a:token-aaa"},
        ).status_code
        == 401
    )

    with Session() as session:
        manifest_logs = session.scalars(
            select(AuditLog).where(AuditLog.action == "sync_feed.manifest"),
        ).all()
        assert len(manifest_logs) == 1
        assert manifest_logs[0].detail_json["consumer"] == "intranet-a"

        read_logs = session.scalars(
            select(AuditLog).where(AuditLog.action == "sync_feed.read").order_by(AuditLog.created_at),
        ).all()
        assert [log.detail_json["consumer"] for log in read_logs] == ["intranet-a", "token-2"]
        for log in read_logs:
            assert log.object_type == "sync_feed"
            assert log.object_id == "data_sources"
            assert log.detail_json["record_count"] == 1
            assert log.detail_json["cursor"] == ""
            assert log.detail_json["next_cursor"]
        # 审计里不落 token 明文
        assert all("token-aaa" not in str(log.detail_json) for log in manifest_logs + read_logs)


def _import_records_out_of_order() -> list[dict]:
    """构造依赖逆序的手工包记录：generated_news → news_items → raw_items → data_sources。"""

    def envelope(event_id: str, object_type: str, global_id: str, payload: dict) -> dict:
        return {
            "event_id": event_id,
            "object_type": object_type,
            "object_id": global_id,
            "object_global_id": global_id,
            "operation": "upsert",
            "revision": 1,
            "content_hash": f"hash-{global_id}",
            "visibility_scope": "public",
            "sync_policy": "public_to_intranet",
            "workspace_code": "planning_intel",
            "domain_code": "ai",
            "payload": {
                "global_id": global_id,
                "origin_instance_id": "extranet-test",
                "workspace_code": "planning_intel",
                "domain_code": "ai",
                "visibility_scope": "public",
                "sync_policy": "public_to_intranet",
                **payload,
            },
        }

    return [
        envelope(
            "evt-disorder-gen-1",
            "generated_news",
            "gen-disorder-1",
            {
                "news_item_global_id": "news-disorder-1",
                "category": "行业动态",
                "title": "乱序包成稿",
                "summary": "依赖排序后一次导入即净",
                "generated_by": "llm_v2",
                "generation_status": "ready",
            },
        ),
        envelope(
            "evt-disorder-news-1",
            "news_items",
            "news-disorder-1",
            {
                "raw_item_global_id": "raw-disorder-1",
                "data_source_global_id": "ds-disorder-1",
                "source_type": "rss",
                "source_name": "乱序源",
                "source_title": "乱序新闻",
                "normalized_title": "乱序新闻",
                "content": "正文",
                "dedupe_key": "disorder-news-1",
            },
        ),
        envelope(
            "evt-disorder-raw-1",
            "raw_items",
            "raw-disorder-1",
            {
                "data_source_global_id": "ds-disorder-1",
                "source_type": "rss",
                "source_name": "乱序源",
                "entry_key": "disorder-entry-1",
                "source_title": "乱序新闻",
                "raw_content": "原始内容",
                "fetched_at": "2026-07-07T10:00:00+00:00",
            },
        ),
        envelope(
            "evt-disorder-ds-1",
            "data_sources",
            "ds-disorder-1",
            {
                "workspace_code": "shared",
                "source_type": "rss",
                "name": "乱序源",
                "url": "https://example.com/disorder.xml",
                "enabled": True,
            },
        ),
    ]


def test_sort_records_by_dependency_is_stable():
    records = _import_records_out_of_order()
    ordered = sort_records_by_dependency(records)
    assert [record["object_type"] for record in ordered] == [
        "data_sources",
        "raw_items",
        "news_items",
        "generated_news",
    ]
    # 稳定排序：同类型保持原相对顺序，未知类型排在最后
    mixed = [
        {"object_type": "news_items", "event_id": "n1"},
        {"object_type": "unknown_type", "event_id": "u1"},
        {"object_type": "news_items", "event_id": "n2"},
        {"object_type": "data_sources", "event_id": "d1"},
    ]
    assert [record["event_id"] for record in sort_records_by_dependency(mixed)] == ["d1", "n1", "n2", "u1"]


def test_import_sync_package_applies_out_of_order_records_in_one_pass(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    imported = client.post(
        "/api/sync/packages/import",
        json={
            "package_manifest": {
                "package_id": "disorder-package-001",
                "source_instance_id": "extranet-test",
                "target_instance_id": "local",
                "records_sha256": "",
            },
            "records": _import_records_out_of_order(),
        },
    )
    assert imported.status_code == 200
    payload = imported.json()
    # 依赖序排序后一轮即净：不再是首轮 failed 等 retry 自愈
    assert payload["status"] == "completed"
    assert payload["applied"] == 4
    assert payload["failed"] == 0
    assert payload["conflicts"] == 0
    assert payload["errors"] == []

    engine = get_engine()
    assert engine is not None
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "ds-disorder-1"))
        raw_item = session.scalar(select(RawItem).where(RawItem.global_id == "raw-disorder-1"))
        news_item = session.scalar(select(NewsItem).where(NewsItem.global_id == "news-disorder-1"))
        generated = session.scalar(select(GeneratedNews).where(GeneratedNews.global_id == "gen-disorder-1"))
        assert source is not None
        assert raw_item is not None and raw_item.data_source.global_id == "ds-disorder-1"
        assert news_item is not None and news_item.raw_item.global_id == "raw-disorder-1"
        assert generated is not None and generated.news_item.global_id == "news-disorder-1"
