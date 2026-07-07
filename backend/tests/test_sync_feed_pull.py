from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.models.content import DataSource
from app.models.feedback import ActivityEvent
from app.models.sync import SyncConflict, SyncCursor, SyncInbox, SyncRun
from app.sync.apply import apply_sync_records
from app.sync.feed import decode_cursor, encode_cursor, feed_manifest, feed_page
from app.sync.pull import run_sync_pull
from app.sync.retry import failed_inbox_retry_summary, retry_failed_sync_inbox


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeFeedClient:
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, path: str, params: dict | None = None):
        if path == "/api/sync/feed/manifest":
            return FakeResponse(
                {
                    "instance_id": "extranet-test",
                    "object_types": ["data_sources"],
                    "watermarks": {},
                    "server_time": "2026-07-05T00:00:00+00:00",
                },
            )
        object_type = (params or {}).get("object_type")
        cursor = (params or {}).get("cursor")
        if object_type == "data_sources" and not cursor:
            return FakeResponse(
                {
                    "object_type": "data_sources",
                    "records": [
                        {
                            "event_id": "evt-feed-source-1",
                            "object_type": "data_sources",
                            "object_id": "source-remote-1",
                            "object_global_id": "source-remote-1",
                            "operation": "upsert",
                            "revision": 1,
                            "content_hash": "hash-source-1",
                            "visibility_scope": "public",
                            "sync_policy": "public_to_intranet",
                            "workspace_code": "shared",
                            "domain_code": "ai",
                            "payload": {
                                "global_id": "source-remote-1",
                                "origin_instance_id": "extranet-test",
                                "workspace_code": "shared",
                                "domain_code": "ai",
                                "visibility_scope": "public",
                                "sync_policy": "public_to_intranet",
                                "source_type": "rss",
                                "name": "远端源",
                                "url": "https://example.com/remote.xml",
                                "enabled": True,
                                "default_focus_id": 1,
                                "backfill_days": 30,
                            },
                        },
                    ],
                    "next_cursor": "cursor-1",
                    "has_more": False,
                },
            )
        return FakeResponse(
            {
                "object_type": object_type,
                "records": [],
                "next_cursor": None,
                "has_more": False,
            },
        )


def test_sync_pull_applies_feed_records_and_advances_cursor(monkeypatch, tmp_path):
    database_path = tmp_path / "sync_pull.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DEPLOY_MODE", "intranet")
    monkeypatch.setenv("AUTH_MODE", "intranet_header")
    monkeypatch.setenv("SYNC_REMOTE_BASE_URL", "https://extranet.example.com")
    monkeypatch.setenv("SYNC_REMOTE_TOKEN", "pull-token")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    monkeypatch.setattr("app.sync.pull.httpx.Client", FakeFeedClient)
    with Session() as session:
        first = run_sync_pull(session, get_settings())
        first_status = first.status
        first_counts = dict(first.counts_json)
        session.commit()

    assert first_status == "completed"
    assert first_counts["applied"] == 1

    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "source-remote-1"))
        cursor = session.get(SyncCursor, "data_sources")
        assert source is not None
        assert source.name == "远端源"
        assert cursor is not None
        assert cursor.cursor == "cursor-1"

        second = run_sync_pull(session, get_settings())
        second_status = second.status
        second_counts = dict(second.counts_json)
        session.commit()
    assert second_status == "completed"
    assert second_counts["received"] == 0


def test_failed_sync_inbox_retry_replays_stored_record(monkeypatch, tmp_path):
    database_path = tmp_path / "sync_inbox_retry.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DEPLOY_MODE", "intranet")
    monkeypatch.setenv("AUTH_MODE", "intranet_header")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    record = {
        "event_id": "evt-inbox-failed-source-1",
        "object_type": "data_sources",
        "object_id": "source-inbox-retry-1",
        "object_global_id": "source-inbox-retry-1",
        "operation": "upsert",
        "revision": 1,
        "content_hash": "hash-inbox-retry-1",
        "visibility_scope": "public",
        "sync_policy": "public_to_intranet",
        "workspace_code": "shared",
        "domain_code": "ai",
        "payload": {
            "global_id": "source-inbox-retry-1",
            "origin_instance_id": "extranet-test",
            "workspace_code": "shared",
            "domain_code": "ai",
            "visibility_scope": "public",
            "sync_policy": "public_to_intranet",
            "source_type": "rss",
            "name": "失败后重试源",
            "url": "https://example.com/retry.xml",
            "enabled": True,
            "default_focus_id": 1,
            "backfill_days": 14,
        },
    }

    with Session() as session:
        session.add(
            SyncInbox(
                event_id="evt-inbox-failed-source-1",
                source_instance_id="extranet-test",
                object_type="data_sources",
                object_id="source-inbox-retry-1",
                payload_hash="hash-inbox-retry-1",
                record_json=record,
                status="failed",
                error_message="dependency missing",
                attempt_count=1,
            ),
        )
        run = retry_failed_sync_inbox(session, get_settings())
        run_status = run.status
        run_counts = dict(run.counts_json)
        session.commit()

    assert run_status == "completed"
    assert run_counts["selected_failed_inbox"] == 1
    assert run_counts["applied"] == 1

    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "source-inbox-retry-1"))
        inbox = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-inbox-failed-source-1"))
        assert source is not None
        assert source.name == "失败后重试源"
        assert source.url == "https://example.com/retry.xml"
        assert inbox is not None
        assert inbox.status == "applied"
        assert inbox.error_message == ""
        assert inbox.attempt_count == 2
        assert inbox.record_json["event_id"] == "evt-inbox-failed-source-1"


def test_failed_sync_inbox_auto_retry_only_replays_due_records(monkeypatch, tmp_path):
    database_path = tmp_path / "sync_inbox_auto_retry.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DEPLOY_MODE", "intranet")
    monkeypatch.setenv("AUTH_MODE", "intranet_header")
    monkeypatch.setenv("SYNC_FAILED_INBOX_RETRY_BASE_SECONDS", "300")
    monkeypatch.setenv("SYNC_FAILED_INBOX_RETRY_MAX_ATTEMPTS", "5")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)

    def record(source_id: str) -> dict:
        return {
            "event_id": f"evt-{source_id}",
            "object_type": "data_sources",
            "object_id": source_id,
            "object_global_id": source_id,
            "operation": "upsert",
            "revision": 1,
            "content_hash": f"hash-{source_id}",
            "visibility_scope": "public",
            "sync_policy": "public_to_intranet",
            "payload": {
                "global_id": source_id,
                "origin_instance_id": "extranet-test",
                "workspace_code": "shared",
                "domain_code": "ai",
                "visibility_scope": "public",
                "sync_policy": "public_to_intranet",
                "source_type": "rss",
                "name": f"重试源 {source_id}",
                "url": f"https://example.com/{source_id}.xml",
                "enabled": True,
                "default_focus_id": 1,
                "backfill_days": 14,
            },
        }

    with Session() as session:
        session.add_all(
            [
                SyncInbox(
                    event_id="evt-due-source",
                    source_instance_id="extranet-test",
                    object_type="data_sources",
                    object_id="due-source",
                    payload_hash="hash-due-source",
                    record_json=record("due-source"),
                    status="failed",
                    error_message="temporary dependency missing",
                    attempt_count=1,
                    last_attempt_at=now - timedelta(seconds=301),
                ),
                SyncInbox(
                    event_id="evt-not-due-source",
                    source_instance_id="extranet-test",
                    object_type="data_sources",
                    object_id="not-due-source",
                    payload_hash="hash-not-due-source",
                    record_json=record("not-due-source"),
                    status="failed",
                    error_message="recent failure",
                    attempt_count=1,
                    last_attempt_at=now - timedelta(seconds=60),
                ),
                SyncInbox(
                    event_id="evt-exhausted-source",
                    source_instance_id="extranet-test",
                    object_type="data_sources",
                    object_id="exhausted-source",
                    payload_hash="hash-exhausted-source",
                    record_json=record("exhausted-source"),
                    status="failed",
                    error_message="too many attempts",
                    attempt_count=5,
                    last_attempt_at=now - timedelta(seconds=3600),
                ),
            ],
        )
        summary = failed_inbox_retry_summary(session, get_settings(), now=now)
        assert summary["due_count"] == 1
        assert summary["blocked_count"] == 1
        assert summary["next_retry_at"] is not None

        run = retry_failed_sync_inbox(
            session,
            get_settings(),
            due_only=True,
            direction="inbox_auto_retry",
            package_prefix="inbox_auto_retry",
        )
        run_direction = run.direction
        run_counts = dict(run.counts_json)
        session.commit()

    assert run_direction == "inbox_auto_retry"
    assert run_counts["selected_failed_inbox"] == 1
    assert run_counts["retry_mode"] == "auto_backoff"
    assert run_counts["applied"] == 1

    with Session() as session:
        due = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-due-source"))
        not_due = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-not-due-source"))
        exhausted = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-exhausted-source"))
        assert due is not None and due.status == "applied"
        assert not_due is not None and not_due.status == "failed" and not_due.attempt_count == 1
        assert exhausted is not None and exhausted.status == "failed" and exhausted.attempt_count == 5


def _intranet_pull_env(monkeypatch, database_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("DEPLOY_MODE", "intranet")
    monkeypatch.setenv("AUTH_MODE", "intranet_header")
    monkeypatch.setenv("SYNC_REMOTE_BASE_URL", "https://extranet.example.com")
    monkeypatch.setenv("SYNC_REMOTE_TOKEN", "pull-token")
    get_settings.cache_clear()
    get_engine.cache_clear()


def _conflict_record() -> dict:
    return {
        "event_id": "evt-conflict-source-r2",
        "object_type": "data_sources",
        "object_id": "source-conflict-1",
        "object_global_id": "source-conflict-1",
        "operation": "upsert",
        "revision": 2,
        "content_hash": "hash-incoming-v2",
        "visibility_scope": "public",
        "sync_policy": "public_to_intranet",
        "workspace_code": "shared",
        "domain_code": "ai",
        "payload": {
            "global_id": "source-conflict-1",
            "origin_instance_id": "extranet-test",
            "workspace_code": "shared",
            "domain_code": "ai",
            "visibility_scope": "public",
            "sync_policy": "public_to_intranet",
            "source_type": "rss",
            "name": "远端冲突版本",
            "url": "https://example.com/conflict-remote.xml",
        },
    }


class ConflictFeedClient:
    """每次都下发同一条冲突记录，模拟定时 pull 反复拉到同一 feed 页。"""

    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, path: str, params: dict | None = None):
        if path == "/api/sync/feed/manifest":
            return FakeResponse(
                {
                    "instance_id": "extranet-test",
                    "object_types": ["data_sources"],
                    "watermarks": {},
                    "server_time": "2026-07-07T00:00:00+00:00",
                },
            )
        object_type = (params or {}).get("object_type")
        if object_type == "data_sources":
            return FakeResponse(
                {
                    "object_type": "data_sources",
                    "records": [_conflict_record()],
                    "next_cursor": "cursor-conflict-1",
                    "has_more": False,
                },
            )
        return FakeResponse(
            {"object_type": object_type, "records": [], "next_cursor": None, "has_more": False},
        )


def test_sync_pull_conflict_advances_cursor_and_does_not_duplicate_conflicts(monkeypatch, tmp_path):
    database_path = tmp_path / "sync_pull_conflict.sqlite"
    _intranet_pull_env(monkeypatch, database_path)

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add(
            DataSource(
                global_id="source-conflict-1",
                origin_instance_id="intranet-test",
                revision=2,
                content_hash="hash-local-v2",
                workspace_code="shared",
                domain_code="ai",
                visibility_scope="public",
                sync_policy="public_to_intranet",
                source_type="rss",
                name="本地已确认版本",
                url="https://example.com/conflict-local.xml",
            ),
        )
        session.commit()

    monkeypatch.setattr("app.sync.pull.httpx.Client", ConflictFeedClient)
    with Session() as session:
        first = run_sync_pull(session, get_settings())
        first_status = first.status
        first_counts = dict(first.counts_json)
        session.commit()

    # 冲突不卡水位：run 记为冲突完成，cursor 照常推进且水位状态不是 failed
    assert first_status == "completed_with_conflicts"
    assert first_counts["conflicts"] == 1
    with Session() as session:
        cursor = session.get(SyncCursor, "data_sources")
        assert cursor is not None
        assert cursor.cursor == "cursor-conflict-1"
        assert cursor.last_status == "ok"
        assert cursor.last_error == ""
        conflicts = session.scalars(select(SyncConflict)).all()
        assert len(conflicts) == 1
        assert conflicts[0].status == "open"
        assert conflicts[0].resolution_json["seen_count"] == 1
        inbox = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-conflict-source-r2"))
        assert inbox is not None
        assert inbox.status == "conflict"
        # 本地版本不被覆盖
        source = session.scalar(select(DataSource).where(DataSource.global_id == "source-conflict-1"))
        assert source is not None and source.name == "本地已确认版本"
        events = session.scalars(
            select(ActivityEvent).where(ActivityEvent.event_type == "sync_conflict.created"),
        ).all()
        assert len(events) == 1

    # 第二轮拉到同一页：conflict 是 inbox 终态，同一 event_id 幂等跳过，
    # 不重复新增 open 冲突、不重复发通知
    with Session() as session:
        second = run_sync_pull(session, get_settings())
        second_status = second.status
        second_counts = dict(second.counts_json)
        session.commit()

    assert second_status == "completed"
    assert second_counts["conflicts"] == 0
    assert second_counts["skipped"] >= 1
    with Session() as session:
        conflicts = session.scalars(select(SyncConflict)).all()
        assert len(conflicts) == 1
        events = session.scalars(
            select(ActivityEvent).where(ActivityEvent.event_type == "sync_conflict.created"),
        ).all()
        assert len(events) == 1

    # 换一个 event_id 重放同一对象（手工包场景）：只刷新既有 open 冲突，不新增行
    with Session() as session:
        run = SyncRun(
            package_id="manual-replay-conflict",
            source_instance_id="extranet-test",
            target_instance_id="intranet-test",
            direction="import",
            status="running",
            counts_json={},
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.flush()
        outcome = apply_sync_records(
            session,
            run,
            [{**_conflict_record(), "event_id": "evt-conflict-source-r2-replay"}],
            source_instance_id="extranet-test",
        )
        assert outcome.conflicts == 1
        session.commit()

    with Session() as session:
        conflicts = session.scalars(select(SyncConflict)).all()
        assert len(conflicts) == 1
        assert conflicts[0].status == "open"
        assert conflicts[0].resolution_json["seen_count"] == 2
        events = session.scalars(
            select(ActivityEvent).where(ActivityEvent.event_type == "sync_conflict.created"),
        ).all()
        assert len(events) == 1


class BrokenManifestClient:
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, path: str, params: dict | None = None):
        raise httpx.ConnectError("connection refused")


def test_sync_pull_manifest_transport_failure_persists_failed_run(monkeypatch, tmp_path):
    database_path = tmp_path / "sync_pull_manifest_down.sqlite"
    _intranet_pull_env(monkeypatch, database_path)

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    monkeypatch.setattr("app.sync.pull.httpx.Client", BrokenManifestClient)
    with Session() as session:
        run = run_sync_pull(session, get_settings())
        run_status = run.status
        run_counts = dict(run.counts_json)
        session.commit()

    # 传输失败不裸抛：落成 status=failed 的 run，错误摘要可查
    assert run_status == "failed"
    assert any("manifest" in error and "connection refused" in error for error in run_counts["errors"])
    with Session() as session:
        persisted = session.scalars(select(SyncRun).where(SyncRun.direction == "api_pull")).all()
        assert len(persisted) == 1
        assert persisted[0].status == "failed"
        assert persisted[0].completed_at is not None


class BrokenFeedPageClient:
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, path: str, params: dict | None = None):
        if path == "/api/sync/feed/manifest":
            return FakeResponse(
                {
                    "instance_id": "extranet-test",
                    "object_types": ["data_sources"],
                    "watermarks": {},
                    "server_time": "2026-07-07T00:00:00+00:00",
                },
            )
        raise httpx.ReadTimeout("feed page timed out")


def test_sync_pull_feed_page_transport_failure_marks_cursor_failed(monkeypatch, tmp_path):
    database_path = tmp_path / "sync_pull_feed_down.sqlite"
    _intranet_pull_env(monkeypatch, database_path)

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    monkeypatch.setattr("app.sync.pull.httpx.Client", BrokenFeedPageClient)
    with Session() as session:
        run = run_sync_pull(session, get_settings())
        run_status = run.status
        run_counts = dict(run.counts_json)
        session.commit()

    assert run_status == "failed"
    assert run_counts["per_object"]["data_sources"]["transport_failed"] is True
    assert any("transport" in error for error in run_counts["errors"])
    with Session() as session:
        cursor = session.get(SyncCursor, "data_sources")
        assert cursor is not None
        assert cursor.last_status == "failed"
        assert "feed page timed out" in cursor.last_error
        # 首个类型传输失败即中断，后续类型不再拉取
        assert list(run_counts["per_object"]) == ["data_sources"]


def _make_real_feed_client(publisher_session_factory):
    """用 publisher 侧真实 feed_page 实现充当 httpx 客户端（跨库端到端）。"""

    class RealFeedClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, path: str, params: dict | None = None):
            with publisher_session_factory() as session:
                if path == "/api/sync/feed/manifest":
                    return FakeResponse(feed_manifest(session, "extranet-real"))
                page = feed_page(
                    session,
                    str((params or {}).get("object_type")),
                    cursor=(params or {}).get("cursor"),
                    limit=int((params or {}).get("limit") or 200),
                )
                return FakeResponse(
                    {
                        "object_type": page.object_type,
                        "records": page.records,
                        "next_cursor": page.next_cursor,
                        "has_more": page.has_more,
                    },
                )

    return RealFeedClient


def _publisher_data_source(global_id: str, name: str, updated_at: datetime) -> DataSource:
    return DataSource(
        global_id=global_id,
        origin_instance_id="extranet-real",
        revision=1,
        content_hash=f"hash-{global_id}",
        workspace_code="shared",
        domain_code="ai",
        visibility_scope="public",
        sync_policy="public_to_intranet",
        source_type="rss",
        name=name,
        url=f"https://example.com/{global_id}.xml",
        updated_at=updated_at,
    )


def test_sync_pull_lookback_replays_late_committed_rows(monkeypatch, tmp_path):
    """并发写入保护：publisher 长事务晚提交、时间戳落在已推进水位之前的行，
    由回看窗口重放捡回，不会被 keyset 严格大于过滤永久漏发。"""
    consumer_path = tmp_path / "sync_pull_consumer.sqlite"
    publisher_path = tmp_path / "sync_pull_publisher.sqlite"
    _intranet_pull_env(monkeypatch, consumer_path)

    consumer_engine = create_engine(f"sqlite:///{consumer_path}")
    publisher_engine = create_engine(f"sqlite:///{publisher_path}")
    Base.metadata.create_all(consumer_engine)
    Base.metadata.create_all(publisher_engine)
    ConsumerSession = sessionmaker(bind=consumer_engine)
    PublisherSession = sessionmaker(bind=publisher_engine)

    t0 = datetime(2026, 7, 7, 10, 0, 0, 111111)
    with PublisherSession() as session:
        session.add(_publisher_data_source("source-fresh-1", "先提交的新行", t0))
        session.commit()

    monkeypatch.setattr("app.sync.pull.httpx.Client", _make_real_feed_client(PublisherSession))
    with ConsumerSession() as session:
        first = run_sync_pull(session, get_settings())
        assert first.status == "completed"
        assert dict(first.counts_json)["applied"] == 1
        session.commit()

    with ConsumerSession() as session:
        cursor = session.get(SyncCursor, "data_sources")
        assert cursor is not None and cursor.cursor
        watermark, _ = decode_cursor(cursor.cursor)
        assert watermark == t0

    # 模拟长事务晚提交：行的 updated_at 落在已推进水位之前（60s < 回看窗口 300s）
    with PublisherSession() as session:
        session.add(_publisher_data_source("source-late-1", "晚提交的旧时间戳行", t0 - timedelta(seconds=60)))
        session.commit()

    with ConsumerSession() as session:
        second = run_sync_pull(session, get_settings())
        second_counts = dict(second.counts_json)
        assert second.status == "completed"
        session.commit()

    # 晚提交行被回看窗口捡回；已应用的行按 event_id 幂等跳过，不重复写
    assert second_counts["applied"] == 1
    assert second_counts["skipped"] >= 1
    with ConsumerSession() as session:
        late = session.scalar(select(DataSource).where(DataSource.global_id == "source-late-1"))
        assert late is not None
        assert late.name == "晚提交的旧时间戳行"
        assert len(session.scalars(select(DataSource)).all()) == 2
        # 水位重新推进回原高点（重放段的末行仍是最新行）
        cursor = session.get(SyncCursor, "data_sources")
        assert cursor is not None
        watermark, _ = decode_cursor(cursor.cursor)
        assert watermark == t0


def test_rewound_cursor_keeps_unparseable_cursor_as_is():
    from app.sync.pull import SYNC_PULL_REPLAY_LOOKBACK_SECONDS, _rewound_cursor

    original = encode_cursor(datetime(2026, 7, 7, 10, 0, 0), "row-id-1")
    rewound = _rewound_cursor(original, SYNC_PULL_REPLAY_LOOKBACK_SECONDS)
    updated_at, object_id = decode_cursor(rewound)
    assert updated_at == datetime(2026, 7, 7, 10, 0, 0) - timedelta(seconds=SYNC_PULL_REPLAY_LOOKBACK_SECONDS)
    assert object_id == "0"
    # 无法解析的游标（历史 fake 值等）原样返回，交给 publisher 判非法
    assert _rewound_cursor("cursor-1", 300) == "cursor-1"
