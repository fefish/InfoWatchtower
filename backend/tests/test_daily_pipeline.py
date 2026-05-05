from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.adapters.base import AdapterRegistry, RawItemInput
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.models.content import DedupeGroup, GeneratedNews, RawItem
from app.models.reports import DailyReport, DailyReportItem
from app.pipeline.daily import DailyPipelineRequest, run_daily_pipeline, run_daily_pipeline_job
from app.workers.scheduler import _enqueue_scheduled_job
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace


class FakeRssAdapter:
    source_type = "rss"

    async def fetch(self, data_source):
        return [
            RawItemInput(
                entry_key="entry:1",
                source_title="Agent platform release",
                source_url="https://example.com/agent-platform",
                raw_content="A useful agent platform release body.",
                published_at=datetime(2026, 5, 5, 8, tzinfo=UTC),
                raw_payload_json={"source": data_source.name},
            ),
        ]


class FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return type("Job", (), {"id": "job-1"})()


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.mark.asyncio
async def test_daily_pipeline_runs_ingestion_normalization_recommendation_and_draft():
    session = make_session()
    workspace = seed_workspace(session)
    seed_source(session, workspace, name="Example RSS")
    registry = AdapterRegistry()
    registry.register(FakeRssAdapter())

    result = await run_daily_pipeline(
        session,
        DailyPipelineRequest(
            workspace_code="planning_intel",
            source_types=["rss"],
            recommendation_limit=15,
            source_daily_limit=2,
            create_daily_draft=True,
            run_ingestion=True,
        ),
        registry=registry,
    )
    session.commit()

    assert result.ingestion_run is not None
    assert result.ingestion_run.status == "completed"
    assert result.normalization.news_created == 1
    assert result.normalization.dedupe_groups_updated == 1
    assert result.recommendation.selected_total == 1
    assert session.scalar(select(func.count(RawItem.id))) == 1
    assert session.scalar(select(func.count(DedupeGroup.id))) == 1
    assert session.scalar(select(func.count(GeneratedNews.id))) == 1
    assert session.scalar(select(func.count(DailyReportItem.id))) == 1


def test_daily_pipeline_job_can_process_existing_raw_without_ingestion(monkeypatch, tmp_path):
    database_path = tmp_path / "daily_pipeline.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspace = seed_workspace(session)
        source = seed_source(session, workspace)
        add_raw_item(
            session,
            source,
            "rss:1",
            "Scheduled recommendation item",
            "https://example.com/scheduled",
            "Scheduled recommendation body.",
        )
        session.commit()

    payload = run_daily_pipeline_job(
        workspace_code="planning_intel",
        source_types=["rss"],
        run_ingestion=False,
    )

    assert payload["workspace_code"] == "planning_intel"
    assert payload["ingestion_status"] == "skipped"
    assert payload["news_created"] == 1
    assert payload["dedupe_groups_updated"] == 1
    assert payload["selected_total"] == 1
    assert payload["daily_report_id"]

    with Session() as session:
        report = session.scalar(select(DailyReport))
        assert report is not None
        assert report.workspace_code == "planning_intel"
        assert report.items[0].generated_news.news_item.raw_item.raw_payload_json["author"] == (
            "Example Team"
        )


def test_scheduler_defaults_to_daily_pipeline_job():
    queue = FakeQueue()
    settings = type(
        "Settings",
        (),
        {
            "scheduler_job_mode": "daily_pipeline",
            "ingestion_scheduler_workspace_code": "planning_intel",
            "ingestion_source_type_list": ["rss"],
            "ingestion_scheduler_limit": 10,
            "daily_pipeline_recommendation_limit": 15,
            "daily_pipeline_source_daily_limit": 2,
            "daily_pipeline_create_daily_draft": True,
            "daily_pipeline_run_ingestion": True,
        },
    )()

    job = _enqueue_scheduled_job(queue, settings)

    assert job.id == "job-1"
    function, args, kwargs = queue.calls[0]
    assert function is run_daily_pipeline_job
    assert args == ("planning_intel", ["rss"], 10, 15, 2, True, True)
    assert kwargs["job_timeout"] == 60 * 60 * 3
