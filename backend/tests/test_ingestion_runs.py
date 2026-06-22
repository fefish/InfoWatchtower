from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.adapters.base import AdapterRegistry, RawItemInput
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.ingestion.jobs import run_historical_backfill_job, run_workspace_ingestion_job
from app.ingestion.runs import (
    HistoricalBackfillRequest,
    WorkspaceIngestionRequest,
    run_historical_backfill,
    run_workspace_ingestion,
)
from app.models.content import DataSource, IngestionRun, RawItem
from app.models.workspace import Workspace, WorkspaceSourceLink


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
        limit=0,
    )

    assert payload["workspace_code"] == "planning_intel"
    assert payload["status"] == "completed"
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
        limit=0,
    )

    assert payload["workspace_code"] == "planning_intel"
    assert payload["status"] == "completed"
    assert payload["source_total"] == 0
    assert payload["summary_json"]["target_day_start"] == "2026-05-10"
