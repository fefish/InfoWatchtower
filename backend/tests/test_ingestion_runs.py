from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.adapters.base import AdapterRegistry, RawItemInput
from app.adapters.stubs import WiseflowReadInfoAdapter
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.ingestion.jobs import run_historical_backfill_job, run_workspace_ingestion_job
from app.ingestion import retry as ingestion_retry
from app.ingestion.runs import (
    HistoricalBackfillRequest,
    InvalidBackfillRangeError,
    WorkspaceIngestionRequest,
    run_historical_backfill,
    run_workspace_ingestion,
)
from app.api.routes import ingestion as ingestion_routes
from app.models.content import DataSource, IngestionRun, RawItem
from app.models.feedback import ActivityEvent, Notification
from app.models.workspace import Workspace, WorkspaceSourceLink
from tests.test_auth import make_client as make_auth_client


class FakeRssAdapter:
    source_type = "rss"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        return [
            RawItemInput(
                entry_key="entry:1",
                source_title="A scheduled item",
                source_url="https://example.com/a",
                raw_content="Body A",
                published_at=datetime(2026, 5, 5, 8, tzinfo=UTC),
                raw_payload_json={"source": data_source.name, "entry": 1},
            ),
            RawItemInput(
                entry_key="entry:2",
                source_title="Another scheduled item",
                source_url="https://example.com/b",
                raw_content="Body B",
                published_at=datetime(2026, 5, 5, 9, tzinfo=UTC),
                raw_payload_json={"source": data_source.name, "entry": 2},
            ),
        ]


class FakeBackfillRssAdapter:
    source_type = "rss"

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        return [
            RawItemInput(
                entry_key="entry:target",
                source_title="Target day item",
                source_url="https://example.com/target",
                raw_content="Target body",
                published_at=datetime(2026, 5, 10, 8, tzinfo=UTC),
                raw_payload_json={"source": data_source.name, "entry": "target"},
            ),
            RawItemInput(
                entry_key="entry:old",
                source_title="Old item",
                source_url="https://example.com/old",
                raw_content="Old body",
                published_at=datetime(2026, 5, 8, 8, tzinfo=UTC),
                raw_payload_json={"source": data_source.name, "entry": "old"},
            ),
            RawItemInput(
                entry_key="entry:undated",
                source_title="Undated item",
                source_url="https://example.com/undated",
                raw_content="Undated body",
                published_at=None,
                raw_payload_json={"source": data_source.name, "entry": "undated"},
            ),
        ]


class FakePaperApiAdapter:
    source_type = "paper_api"

    def __init__(self):
        self.contexts = []

    async def fetch(self, data_source: DataSource) -> list[RawItemInput]:
        raise AssertionError("paper_api backfill must pass SourceFetchContext")

    async def fetch_with_context(self, data_source: DataSource, context) -> list[RawItemInput]:
        self.contexts.append(context)
        return [
            RawItemInput(
                entry_key="arxiv:2605.12345v1",
                source_title="Paper API target item",
                source_url="https://arxiv.org/abs/2605.12345v1",
                raw_content="Paper body",
                published_at=datetime(2026, 5, 10, 8, tzinfo=UTC),
                raw_payload_json={
                    "provider": "arxiv",
                    "context_start": context.target_day_start.isoformat(),
                    "context_end": context.target_day_end.isoformat(),
                },
            ),
            RawItemInput(
                entry_key="arxiv:2605.oldv1",
                source_title="Paper API old item",
                source_url="https://arxiv.org/abs/2605.oldv1",
                raw_content="Old paper body",
                published_at=datetime(2026, 5, 8, 8, tzinfo=UTC),
                raw_payload_json={"provider": "arxiv"},
            ),
        ]


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_workspace_source(session):
    workspace = Workspace(
        code="planning_intel",
        name="规划部情报工作台",
        description="",
        default_domain_code="ai",
    )
    source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type="rss",
        name="Example RSS",
        url="https://example.com/rss.xml",
    )
    link = WorkspaceSourceLink(
        workspace=workspace,
        data_source=source,
        domain_code="ai",
        enabled=True,
    )
    session.add(link)
    session.commit()
    return source


def seed_workspace_source_with_type(session, *, source_type: str, name: str, url: str) -> DataSource:
    workspace = Workspace(
        code="planning_intel",
        name="规划部情报工作台",
        description="",
        default_domain_code="ai",
    )
    source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type=source_type,
        name=name,
        url=url,
    )
    link = WorkspaceSourceLink(
        workspace=workspace,
        data_source=source,
        domain_code="ai",
        enabled=True,
    )
    session.add(link)
    session.commit()
    return source


def add_workspace_source(session, *, name: str, url: str, source_type: str = "rss") -> DataSource:
    workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
    assert workspace is not None
    source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type=source_type,
        name=name,
        url=url,
    )
    link = WorkspaceSourceLink(
        workspace=workspace,
        data_source=source,
        domain_code="ai",
        enabled=True,
    )
    session.add(link)
    session.commit()
    return source


def seed_empty_workspace(session):
    workspace = Workspace(
        code="planning_intel",
        name="规划部情报工作台",
        description="",
        default_domain_code="ai",
    )
    session.add(workspace)
    session.commit()
    return workspace


@pytest.mark.asyncio
async def test_workspace_ingestion_run_fetches_enabled_sources_idempotently():
    session = make_session()
    source = seed_workspace_source(session)
    registry = AdapterRegistry()
    registry.register(FakeRssAdapter())

    request = WorkspaceIngestionRequest(
        workspace_code="planning_intel",
        source_types=["rss"],
    )
    started_at = datetime(2026, 5, 5, 10, tzinfo=UTC)

    first = await run_workspace_ingestion(session, request, registry, started_at)
    session.commit()

    assert first.status == "completed"
    assert first.source_total == 1
    assert first.source_succeeded == 1
    assert first.source_failed == 0
    assert first.items_fetched == 2
    assert first.raw_created == 2
    assert first.raw_updated == 0
    assert first.params_json["workspace_code"] == "planning_intel"
    assert first.params_json["concurrency"] == 8
    assert first.params_json["source_timeout_seconds"] == 25.0
    assert first.summary_json["sources"][0]["data_source_id"] == source.id
    assert session.scalar(select(func.count(RawItem.id))) == 2

    second = await run_workspace_ingestion(
        session,
        request,
        registry,
        started_at + timedelta(minutes=1),
    )
    session.commit()

    assert second.status == "completed"
    assert second.raw_created == 0
    assert second.raw_updated == 2
    assert session.scalar(select(func.count(IngestionRun.id))) == 2
    assert session.scalar(select(func.count(RawItem.id))) == 2


@pytest.mark.asyncio
async def test_workspace_ingestion_run_can_target_source_ids_for_failed_retry():
    session = make_session()
    skipped_source = seed_workspace_source(session)
    retry_source = add_workspace_source(
        session,
        name="Retry RSS",
        url="https://example.com/retry.xml",
    )
    registry = AdapterRegistry()
    registry.register(FakeRssAdapter())

    run = await run_workspace_ingestion(
        session,
        WorkspaceIngestionRequest(
            workspace_code="planning_intel",
            source_types=["rss"],
            source_ids=[retry_source.id],
        ),
        registry,
        datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    assert run.status == "completed"
    assert run.source_total == 1
    assert run.params_json["source_ids"] == [retry_source.id]
    assert run.summary_json["sources"][0]["data_source_id"] == retry_source.id
    assert skipped_source.id not in {source["data_source_id"] for source in run.summary_json["sources"]}
    assert set(session.scalars(select(RawItem.data_source_id)).all()) == {retry_source.id}


@pytest.mark.asyncio
async def test_workspace_ingestion_run_records_per_source_failures():
    session = make_session()
    seed_workspace_source(session)

    run = await run_workspace_ingestion(
        session,
        WorkspaceIngestionRequest(workspace_code="planning_intel", source_types=["rss"]),
        AdapterRegistry(),
        datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    assert run.status == "failed"
    assert run.source_total == 1
    assert run.source_succeeded == 0
    assert run.source_failed == 1
    assert run.summary_json["sources"][0]["status"] == "failed"
    assert "No adapter registered" in run.summary_json["sources"][0]["error"]


@pytest.mark.asyncio
async def test_workspace_ingestion_run_marks_unimplemented_stub_sources_as_skipped():
    session = make_session()
    seed_workspace_source_with_type(
        session,
        source_type="wiseflow",
        name="Wiseflow Legacy",
        url="https://example.com/read-info",
    )
    registry = AdapterRegistry()
    registry.register(WiseflowReadInfoAdapter())

    run = await run_workspace_ingestion(
        session,
        WorkspaceIngestionRequest(workspace_code="planning_intel", source_types=["wiseflow"]),
        registry,
        datetime(2026, 5, 5, 10, tzinfo=UTC),
    )
    session.commit()

    assert run.status == "skipped_unimplemented"
    assert run.source_total == 1
    assert run.source_succeeded == 0
    assert run.source_failed == 0
    assert run.items_fetched == 0
    assert run.raw_created == 0
    assert run.summary_json["source_skipped_unimplemented"] == 1
    assert run.summary_json["sources"][0]["status"] == "skipped_unimplemented"
    assert "AdapterNotImplementedError" in run.summary_json["sources"][0]["error"]
    assert session.scalar(select(func.count(RawItem.id))) == 0


@pytest.mark.asyncio
async def test_historical_backfill_persists_only_target_range_by_default():
    session = make_session()
    seed_workspace_source(session)
    registry = AdapterRegistry()
    registry.register(FakeBackfillRssAdapter())

    run = await run_historical_backfill(
        session,
        HistoricalBackfillRequest(
            workspace_code="planning_intel",
            target_day_start="2026-05-10",
            target_day_end="2026-05-10",
            source_types=["rss"],
        ),
        registry,
        datetime(2026, 5, 14, 10, tzinfo=UTC),
    )
    session.commit()

    assert run.run_type == "historical_backfill"
    assert run.status == "completed"
    assert run.items_fetched == 3
    assert run.raw_created == 1
    assert run.params_json["target_day_start"] == "2026-05-10"
    assert run.params_json["backfill_mode"] == "rss_window"
    assert run.summary_json["items_in_target_range"] == 1
    assert run.summary_json["items_out_of_target_range"] == 1
    assert run.summary_json["items_missing_published_at"] == 1
    assert session.scalar(select(func.count(RawItem.id))) == 1
    raw_item = session.scalar(select(RawItem))
    assert raw_item is not None
    assert raw_item.entry_key == "entry:target"


@pytest.mark.asyncio
async def test_historical_backfill_can_include_undated_items_for_manual_repair():
    session = make_session()
    seed_workspace_source(session)
    registry = AdapterRegistry()
    registry.register(FakeBackfillRssAdapter())

    run = await run_historical_backfill(
        session,
        HistoricalBackfillRequest(
            workspace_code="planning_intel",
            target_day_start="2026-05-10",
            target_day_end="2026-05-10",
            source_types=["rss"],
            include_undated=True,
        ),
        registry,
        datetime(2026, 5, 14, 10, tzinfo=UTC),
    )
    session.commit()

    assert run.raw_created == 2
    assert run.summary_json["items_missing_published_at"] == 1
    entry_keys = set(session.scalars(select(RawItem.entry_key)).all())
    assert entry_keys == {"entry:target", "entry:undated"}


@pytest.mark.asyncio
async def test_historical_backfill_passes_target_window_to_paper_api_adapter():
    session = make_session()
    seed_workspace_source_with_type(
        session,
        source_type="paper_api",
        name="arXiv API",
        url="https://export.arxiv.org/api/query?search_query=cat:cs.AI",
    )
    adapter = FakePaperApiAdapter()
    registry = AdapterRegistry()
    registry.register(adapter)

    run = await run_historical_backfill(
        session,
        HistoricalBackfillRequest(
            workspace_code="planning_intel",
            target_day_start="2026-05-10",
            target_day_end="2026-05-10",
            source_types=["paper_api"],
            backfill_mode="paper_api",
        ),
        registry,
        datetime(2026, 5, 14, 10, tzinfo=UTC),
    )
    session.commit()

    assert run.status == "completed"
    assert run.items_fetched == 2
    assert run.raw_created == 1
    assert run.summary_json["items_in_target_range"] == 1
    assert adapter.contexts[0].mode == "paper_api"
    assert adapter.contexts[0].target_day_start.isoformat() == "2026-05-10"
    assert session.scalar(select(RawItem.entry_key)) == "arxiv:2605.12345v1"


@pytest.mark.asyncio
async def test_manual_import_backfill_requires_manual_items():
    session = make_session()
    seed_workspace_source(session)

    with pytest.raises(InvalidBackfillRangeError, match="requires at least one manual item"):
        await run_historical_backfill(
            session,
            HistoricalBackfillRequest(
                workspace_code="planning_intel",
                target_day_start="2026-05-10",
                target_day_end="2026-05-10",
                source_types=["rss"],
                backfill_mode="manual_import",
                manual_items=[],
            ),
            AdapterRegistry(),
            datetime(2026, 5, 14, 10, tzinfo=UTC),
        )

    assert session.scalar(select(func.count(IngestionRun.id))) == 0
    assert session.scalar(select(func.count(RawItem.id))) == 0


@pytest.mark.asyncio
async def test_manual_import_backfill_validates_source_and_payload():
    session = make_session()
    source = seed_workspace_source(session)

    with pytest.raises(InvalidBackfillRangeError, match="must include data_source_id"):
        await run_historical_backfill(
            session,
            HistoricalBackfillRequest(
                workspace_code="planning_intel",
                target_day_start="2026-05-10",
                target_day_end="2026-05-10",
                source_types=["rss"],
                backfill_mode="manual_import",
                manual_items=[{"title": "No source"}],
            ),
            AdapterRegistry(),
            datetime(2026, 5, 14, 10, tzinfo=UTC),
        )

    with pytest.raises(InvalidBackfillRangeError, match="must belong to enabled sources"):
        await run_historical_backfill(
            session,
            HistoricalBackfillRequest(
                workspace_code="planning_intel",
                target_day_start="2026-05-10",
                target_day_end="2026-05-10",
                source_types=["rss"],
                backfill_mode="manual_import",
                manual_items=[{"data_source_id": "unknown-source", "title": "Wrong source"}],
            ),
            AdapterRegistry(),
            datetime(2026, 5, 14, 10, tzinfo=UTC),
        )

    with pytest.raises(InvalidBackfillRangeError, match="at least one of title"):
        await run_historical_backfill(
            session,
            HistoricalBackfillRequest(
                workspace_code="planning_intel",
                target_day_start="2026-05-10",
                target_day_end="2026-05-10",
                source_types=["rss"],
                backfill_mode="manual_import",
                manual_items=[{"data_source_id": source.id}],
            ),
            AdapterRegistry(),
            datetime(2026, 5, 14, 10, tzinfo=UTC),
        )

    assert session.scalar(select(func.count(IngestionRun.id))) == 0
    assert session.scalar(select(func.count(RawItem.id))) == 0


@pytest.mark.asyncio
async def test_manual_import_backfill_persists_raw_items_with_payload_lineage():
    session = make_session()
    source = seed_workspace_source(session)

    run = await run_historical_backfill(
        session,
        HistoricalBackfillRequest(
            workspace_code="planning_intel",
            target_day_start="2026-05-10",
            target_day_end="2026-05-10",
            source_types=["rss"],
            backfill_mode="manual_import",
            manual_items=[
                {
                    "source_id": source.id,
                    "source_title": "手工补采新闻",
                    "source_url": "https://example.com/manual-news",
                    "raw_content": "手工补采正文",
                    "published_at": "2026-05-10T09:30:00Z",
                },
                {
                    "data_source_id": source.id,
                    "title": "窗外新闻",
                    "url": "https://example.com/old-manual-news",
                    "content": "窗外正文",
                    "published_at": "2026-05-08T09:30:00Z",
                },
            ],
        ),
        AdapterRegistry(),
        datetime(2026, 5, 14, 10, tzinfo=UTC),
    )
    session.commit()

    assert run.status == "completed"
    assert run.items_fetched == 2
    assert run.raw_created == 1
    assert run.params_json["manual_items"] == 2
    assert run.summary_json["items_in_target_range"] == 1
    assert run.summary_json["items_out_of_target_range"] == 1
    raw_item = session.scalar(select(RawItem))
    assert raw_item is not None
    assert raw_item.data_source_id == source.id
    assert raw_item.entry_key == "https://example.com/manual-news"
    assert raw_item.source_title == "手工补采新闻"
    assert raw_item.raw_payload_json["backfill_mode"] == "manual_import"
    assert raw_item.raw_payload_json["payload"]["source_id"] == source.id


def test_ingestion_job_opens_database_session(monkeypatch, tmp_path):
    database_path = tmp_path / "ingestion_job.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        seed_empty_workspace(session)

    payload = run_workspace_ingestion_job(
        workspace_code="planning_intel",
        source_types=["rss"],
    )

    assert payload["workspace_code"] == "planning_intel"
    assert payload["status"] == "no_sources"
    assert payload["source_total"] == 0


def test_historical_backfill_job_opens_database_session(monkeypatch, tmp_path):
    database_path = tmp_path / "backfill_job.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        seed_empty_workspace(session)

    payload = run_historical_backfill_job(
        workspace_code="planning_intel",
        target_day_start="2026-05-10",
        target_day_end="2026-05-10",
        source_types=["rss"],
    )

    assert payload["workspace_code"] == "planning_intel"
    assert payload["status"] == "no_sources"
    assert payload["source_total"] == 0
    assert payload["summary_json"]["target_day_start"] == "2026-05-10"


def test_manual_import_preview_accepts_csv_and_returns_row_errors(monkeypatch, tmp_path):
    client, engine = make_auth_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = add_workspace_source(session, name="Manual RSS", url="https://example.com/manual.xml")
        source_id = source.id

    response = client.post(
        "/api/ingestion/manual-import-preview",
        json={
            "workspace_code": "planning_intel",
            "source_types": ["rss"],
            "default_data_source_id": source_id,
            "input_format": "csv",
            "filename": "manual.csv",
            "input_text": (
                "source_title,source_url,raw_content,published_at\n"
                "有效新闻,https://example.com/manual,正文,2026-07-05T09:00:00Z\n"
                ",,,2026-07-05T09:00:00Z\n"
                "坏日期,https://example.com/bad,正文,not-a-date\n"
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input_format"] == "csv"
    assert payload["total_rows"] == 3
    assert payload["accepted_count"] == 1
    assert payload["rejected_count"] == 2
    assert payload["accepted_items"][0]["data_source_id"] == source_id
    assert payload["accepted_items"][0]["source_title"] == "有效新闻"
    error_codes = {item["code"] for item in payload["errors"]}
    assert {"empty_payload", "invalid_published_at"}.issubset(error_codes)
    assert "accepted" in payload["error_report_csv"]
    assert "rejected" in payload["error_report_csv"]


def test_manual_import_preview_parses_sql_insert_values(monkeypatch, tmp_path):
    client, engine = make_auth_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = add_workspace_source(session, name="Manual SQL", url="https://example.com/manual-sql.xml")
        source_id = source.id

    response = client.post(
        "/api/ingestion/manual-import-preview",
        json={
            "workspace_code": "planning_intel",
            "source_types": ["rss"],
            "default_data_source_id": source_id,
            "input_format": "sql",
            "filename": "manual.sql",
            "input_text": (
                "INSERT INTO manual_items (title, url, content, published_at) VALUES "
                "('SQL 新闻', 'https://example.com/sql', 'SQL 正文', '2026-07-05T09:00:00Z');"
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input_format"] == "sql"
    assert payload["accepted_count"] == 1
    assert payload["rejected_count"] == 0
    assert payload["accepted_items"][0]["source_title"] == "SQL 新闻"
    assert payload["accepted_items"][0]["source_url"] == "https://example.com/sql"
    assert payload["accepted_items"][0]["raw_content"] == "SQL 正文"


def test_manual_import_preview_blocks_sources_outside_workspace(monkeypatch, tmp_path):
    client, engine = make_auth_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = add_workspace_source(session, name="Manual RSS", url="https://example.com/manual.xml")
        source_id = source.id

    response = client.post(
        "/api/ingestion/manual-import-preview",
        json={
            "workspace_code": "planning_intel",
            "source_types": ["rss"],
            "default_data_source_id": source_id,
            "input_format": "csv",
            "input_text": "data_source_id,source_title\nunknown-source,不应导入\n",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted_count"] == 0
    assert payload["rejected_count"] == 1
    assert payload["errors"][0]["code"] == "source_not_enabled"


def test_retry_failed_sources_api_targets_only_failed_sources(monkeypatch, tmp_path):
    client, engine = make_auth_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ok_source = add_workspace_source(
            session,
            name="Healthy RSS",
            url="https://example.com/healthy.xml",
        )
        failed_source = add_workspace_source(
            session,
            name="Failed RSS",
            url="https://example.com/failed.xml",
        )
        original = IngestionRun(
            run_key="planning_intel:ingestion:failed-source-test",
            workspace_code="planning_intel",
            domain_code="ai",
            run_type="workspace_fetch",
            status="partial",
            started_at=datetime(2026, 5, 5, 10, tzinfo=UTC),
            completed_at=datetime(2026, 5, 5, 10, 1, tzinfo=UTC),
            source_total=2,
            source_succeeded=1,
            source_failed=1,
            params_json={
                "workspace_code": "planning_intel",
                "source_types": ["rss"],
                "max_items_per_source": 3,
            },
            summary_json={
                "sources": [
                    {
                        "data_source_id": ok_source.id,
                        "name": ok_source.name,
                        "source_type": "rss",
                        "status": "completed",
                    },
                    {
                        "data_source_id": failed_source.id,
                        "name": failed_source.name,
                        "source_type": "rss",
                        "status": "failed",
                        "error": "TimeoutError",
                    },
                ],
            },
        )
        session.add(original)
        session.commit()
        original_id = original.id
        failed_source_id = failed_source.id

    captured: dict[str, WorkspaceIngestionRequest] = {}

    async def fake_run_workspace_ingestion(session, request, registry=None, started_at=None):
        captured["request"] = request
        retry_run = IngestionRun(
            run_key="planning_intel:ingestion:retry-failed-source-test",
            workspace_code=request.workspace_code,
            domain_code="ai",
            run_type="workspace_fetch",
            status="failed",
            started_at=datetime(2026, 5, 5, 10, 2, tzinfo=UTC),
            completed_at=datetime(2026, 5, 5, 10, 3, tzinfo=UTC),
            source_total=len(request.source_ids or []),
            source_succeeded=0,
            source_failed=len(request.source_ids or []),
            params_json={
                "workspace_code": request.workspace_code,
                "source_types": request.source_types,
                "source_ids": request.source_ids or [],
                "concurrency": request.concurrency,
                "source_timeout_seconds": request.source_timeout_seconds,
                "max_items_per_source": request.max_items_per_source,
                "retry_of_run_id": request.retry_of_run_id,
            },
            summary_json={
                "sources": [
                    {
                        "data_source_id": source_id,
                        "source_type": "rss",
                        "status": "failed",
                        "error": "still failing",
                    }
                    for source_id in request.source_ids or []
                ],
                "retry_of_run_id": request.retry_of_run_id,
            },
        )
        session.add(retry_run)
        session.flush()
        return retry_run

    monkeypatch.setattr(ingestion_routes, "run_workspace_ingestion", fake_run_workspace_ingestion)

    response = client.post(f"/api/ingestion/runs/{original_id}/retry-failed-sources")

    assert response.status_code == 200
    request = captured["request"]
    assert request.source_ids == [failed_source_id]
    assert request.source_types == ["rss"]
    assert request.concurrency == 2
    assert request.source_timeout_seconds == 60.0
    assert request.max_items_per_source == 3
    assert response.json()["params_json"]["retry_of_run_id"] == original_id


def test_retry_failed_sources_api_rejects_runs_without_failed_sources(monkeypatch, tmp_path):
    client, engine = make_auth_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = add_workspace_source(
            session,
            name="Healthy RSS",
            url="https://example.com/healthy.xml",
        )
        original = IngestionRun(
            run_key="planning_intel:ingestion:no-failed-source-test",
            workspace_code="planning_intel",
            domain_code="ai",
            run_type="workspace_fetch",
            status="completed",
            source_total=1,
            source_succeeded=1,
            source_failed=0,
            params_json={"workspace_code": "planning_intel", "source_types": ["rss"]},
            summary_json={
                "sources": [
                    {
                        "data_source_id": source.id,
                        "name": source.name,
                        "source_type": "rss",
                        "status": "completed",
                    },
                ],
            },
        )
        session.add(original)
        session.commit()
        original_id = original.id

    response = client.post(f"/api/ingestion/runs/{original_id}/retry-failed-sources")

    assert response.status_code == 409
    assert response.json()["detail"] == "本次运行没有可重试的失败源。"


def test_ingestion_coverage_trends_aggregate_recent_runs_and_failures(monkeypatch, tmp_path):
    client, engine = make_auth_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    with Session() as session:
        source = add_workspace_source(session, name="Unstable RSS", url="https://example.com/unstable.xml")
        source_id = source.id
        failed_run = IngestionRun(
            run_key="planning_intel:ingestion:trend-failed",
            workspace_code="planning_intel",
            domain_code="ai",
            run_type="workspace_fetch",
            status="partial",
            started_at=now - timedelta(minutes=10),
            completed_at=now - timedelta(minutes=9),
            source_total=2,
            source_succeeded=1,
            source_failed=1,
            items_fetched=3,
            raw_created=2,
            raw_updated=1,
            params_json={"workspace_code": "planning_intel", "source_types": ["rss"]},
            summary_json={
                "source_skipped_unimplemented": 0,
                "sources": [
                    {
                        "data_source_id": source.id,
                        "name": source.name,
                        "source_type": "rss",
                        "status": "failed",
                        "error": "TimeoutError: read timed out",
                    },
                ],
            },
        )
        healthy_run = IngestionRun(
            run_key="planning_intel:ingestion:trend-ok",
            workspace_code="planning_intel",
            domain_code="ai",
            run_type="workspace_fetch",
            status="completed",
            started_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=4),
            source_total=1,
            source_succeeded=1,
            source_failed=0,
            items_fetched=4,
            raw_created=4,
            raw_updated=0,
            params_json={"workspace_code": "planning_intel", "source_types": ["rss"]},
            summary_json={"source_skipped_unimplemented": 0, "sources": []},
        )
        session.add_all([failed_run, healthy_run])
        session.commit()

    response = client.get("/api/ingestion/coverage/trends?workspace_code=planning_intel&days=14")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_code"] == "planning_intel"
    assert payload["total_runs"] == 2
    assert payload["total_source_failed"] == 1
    assert payload["total_raw_created"] == 6
    assert payload["average_success_rate"] == 0.6667
    active_points = [point for point in payload["points"] if point["run_count"]]
    assert len(active_points) == 1
    assert active_points[0]["source_total"] == 3
    assert active_points[0]["source_succeeded"] == 2
    assert active_points[0]["source_failed"] == 1
    assert payload["top_failed_sources"][0]["data_source_id"] == source_id
    assert payload["top_failed_sources"][0]["failure_count"] == 1
    assert "TimeoutError" in payload["top_failed_sources"][0]["last_error"]


@pytest.mark.asyncio
async def test_failed_source_auto_retry_replays_due_original_run(monkeypatch):
    session = make_session()
    source = seed_workspace_source(session)
    source_id = source.id
    original_time = datetime.now(UTC) - timedelta(hours=2)
    original = IngestionRun(
        run_key="planning_intel:ingestion:auto-retry-original",
        workspace_code="planning_intel",
        domain_code="ai",
        run_type="workspace_fetch",
        status="partial",
        started_at=original_time,
        completed_at=original_time + timedelta(minutes=1),
        source_total=1,
        source_succeeded=0,
        source_failed=1,
        params_json={"workspace_code": "planning_intel", "source_types": ["rss"]},
        summary_json={
            "sources": [
                {
                    "data_source_id": source_id,
                    "name": source.name,
                    "source_type": "rss",
                    "status": "failed",
                    "error": "TimeoutError",
                },
            ],
        },
    )
    session.add(original)
    session.commit()
    original_id = original.id

    monkeypatch.setenv("INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED", "true")
    monkeypatch.setenv("INGESTION_FAILED_SOURCE_RETRY_BASE_SECONDS", "1")
    get_settings.cache_clear()
    captured: dict[str, WorkspaceIngestionRequest] = {}

    async def fake_run_workspace_ingestion(session, request, registry=None, started_at=None):
        captured["request"] = request
        retry_run = IngestionRun(
            run_key="planning_intel:ingestion:auto-retry-created",
            workspace_code=request.workspace_code,
            domain_code="ai",
            run_type="workspace_fetch",
            status="completed",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            source_total=len(request.source_ids or []),
            source_succeeded=len(request.source_ids or []),
            source_failed=0,
            raw_created=1,
            params_json={
                "workspace_code": request.workspace_code,
                "source_types": request.source_types,
                "source_ids": request.source_ids or [],
                "retry_of_run_id": request.retry_of_run_id,
            },
            summary_json={"sources": []},
        )
        session.add(retry_run)
        session.flush()
        return retry_run

    monkeypatch.setattr(ingestion_retry, "run_workspace_ingestion", fake_run_workspace_ingestion)

    summary = ingestion_retry.failed_source_retry_summary(session, get_settings(), workspace_code="planning_intel")
    assert summary["due_count"] == 1

    payload = await ingestion_retry.retry_due_failed_sources(session, get_settings(), workspace_code="planning_intel")

    assert payload["status"] == "completed"
    assert payload["selected_failed_runs"] == 1
    assert payload["runs"][0]["retry_of_run_id"] == original_id
    request = captured["request"]
    assert request.source_ids == [source_id]
    assert request.retry_of_run_id == original_id
    assert request.concurrency == 2
    assert request.source_timeout_seconds >= 60

    summary_after = ingestion_retry.failed_source_retry_summary(session, get_settings(), workspace_code="planning_intel")
    assert summary_after["due_count"] == 0


@pytest.mark.asyncio
async def test_failed_source_auto_retry_emits_due_alert_notification(monkeypatch, tmp_path):
    client, engine = make_auth_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="public_password",
        INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED="true",
        INGESTION_FAILED_SOURCE_RETRY_BASE_SECONDS="1",
    )
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = add_workspace_source(session, name="Failed RSS", url="https://example.com/failed.xml")
        original_time = datetime.now(UTC) - timedelta(hours=2)
        original = IngestionRun(
            run_key="planning_intel:ingestion:alert-due",
            workspace_code="planning_intel",
            domain_code="ai",
            run_type="workspace_fetch",
            status="partial",
            started_at=original_time,
            completed_at=original_time + timedelta(minutes=1),
            source_total=1,
            source_succeeded=0,
            source_failed=1,
            params_json={"workspace_code": "planning_intel", "source_types": ["rss"]},
            summary_json={
                "sources": [
                    {
                        "data_source_id": source.id,
                        "name": source.name,
                        "source_type": "rss",
                        "status": "failed",
                        "error": "TimeoutError",
                    },
                ],
            },
        )
        session.add(original)
        session.commit()
        original_id = original.id

        async def fake_run_workspace_ingestion(session, request, registry=None, started_at=None):
            retry_run = IngestionRun(
                run_key="planning_intel:ingestion:alert-due-retry",
                workspace_code=request.workspace_code,
                domain_code="ai",
                run_type="workspace_fetch",
                status="completed",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                source_total=len(request.source_ids or []),
                source_succeeded=len(request.source_ids or []),
                source_failed=0,
                params_json={
                    "workspace_code": request.workspace_code,
                    "source_types": request.source_types,
                    "source_ids": request.source_ids or [],
                    "retry_of_run_id": request.retry_of_run_id,
                },
                summary_json={"sources": []},
            )
            session.add(retry_run)
            session.flush()
            return retry_run

        monkeypatch.setattr(ingestion_retry, "run_workspace_ingestion", fake_run_workspace_ingestion)
        payload = await ingestion_retry.retry_due_failed_sources(session, get_settings(), workspace_code="planning_intel")
        session.commit()

        assert payload["alerted_due_runs"] == 1
        assert payload["selected_failed_runs"] == 1
        event = session.scalar(
            select(ActivityEvent).where(
                ActivityEvent.event_type == "ingestion.failed_source_retry_due",
                ActivityEvent.object_id == original_id,
            ),
        )
        assert event is not None
        assert event.target_object_type == "ingestion_run"
        assert event.metadata_json["failed_source_count"] == 1
        assert event.metadata_json["attempt_count"] == 0
        assert session.scalar(
            select(func.count()).select_from(Notification).where(Notification.activity_event_id == event.id),
        ) == 1

    notifications = client.get("/api/notifications", params={"status": "all"})
    assert notifications.status_code == 200
    alert = [
        item for item in notifications.json()
        if item["activity_event"]["event_type"] == "ingestion.failed_source_retry_due"
    ][0]
    assert alert["priority"] == "important"
    assert alert["target_label"] == "查看抓取"
    assert alert["target_path"] == f"/ingestion-runs?run_id={original_id}"


@pytest.mark.asyncio
async def test_failed_source_auto_retry_emits_blocked_alert_once(monkeypatch, tmp_path):
    client, engine = make_auth_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="public_password",
        INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED="true",
        INGESTION_FAILED_SOURCE_RETRY_BASE_SECONDS="1",
        INGESTION_FAILED_SOURCE_RETRY_MAX_ATTEMPTS="1",
    )
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = add_workspace_source(session, name="Blocked RSS", url="https://example.com/blocked.xml")
        original_time = datetime.now(UTC) - timedelta(hours=3)
        original = IngestionRun(
            run_key="planning_intel:ingestion:alert-blocked",
            workspace_code="planning_intel",
            domain_code="ai",
            run_type="workspace_fetch",
            status="partial",
            started_at=original_time,
            completed_at=original_time + timedelta(minutes=1),
            source_total=1,
            source_succeeded=0,
            source_failed=1,
            params_json={"workspace_code": "planning_intel", "source_types": ["rss"]},
            summary_json={
                "sources": [
                    {
                        "data_source_id": source.id,
                        "name": source.name,
                        "source_type": "rss",
                        "status": "failed",
                        "error": "TimeoutError",
                    },
                ],
            },
        )
        session.add(original)
        session.flush()
        retry_run = IngestionRun(
            run_key="planning_intel:ingestion:alert-blocked-retry",
            workspace_code="planning_intel",
            domain_code="ai",
            run_type="workspace_fetch",
            status="partial",
            started_at=datetime.now(UTC) - timedelta(hours=2),
            completed_at=datetime.now(UTC) - timedelta(hours=2, minutes=-1),
            source_total=1,
            source_succeeded=0,
            source_failed=1,
            params_json={"workspace_code": "planning_intel", "retry_of_run_id": original.id},
            summary_json={"sources": []},
        )
        session.add(retry_run)
        session.commit()
        original_id = original.id

        first = await ingestion_retry.retry_due_failed_sources(session, get_settings(), workspace_code="planning_intel")
        second = await ingestion_retry.retry_due_failed_sources(session, get_settings(), workspace_code="planning_intel")
        session.commit()

        assert first["selected_failed_runs"] == 0
        assert first["alerted_blocked_runs"] == 1
        assert second["alerted_blocked_runs"] == 0
        event_count = session.scalar(
            select(func.count()).select_from(ActivityEvent).where(
                ActivityEvent.event_type == "ingestion.failed_source_retry_blocked",
                ActivityEvent.object_id == original_id,
            ),
        )
        assert event_count == 1
