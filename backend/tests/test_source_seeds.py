from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.ingestion.source_seeds import import_legacy_sources
from app.models.content import DataSource
from app.models.workspace import Workspace, WorkspaceSourceLink


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def legacy_seed_root() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "seeds" / "legacy"


def test_import_legacy_sources_maps_all_seed_types_and_is_idempotent():
    session = make_session()

    first = import_legacy_sources(session, legacy_seed_root())
    session.commit()

    assert first.created == 294
    assert first.updated == 67
    assert first.total == 361

    counts = dict(
        session.execute(
            select(DataSource.source_type, func.count(DataSource.id)).group_by(DataSource.source_type),
        ).all(),
    )
    assert counts == {
        "page_manual": 2,
        "page_monitor": 2,
        "paper_rss": 21,
        "rss": 268,
        "wiseflow": 1,
    }

    sample = next(
        source
        for source in session.scalars(select(DataSource).where(DataSource.source_type == "paper_rss")).all()
        if source.metadata_json["origin"] == "legacy_rss"
    )
    assert sample is not None
    assert sample.workspace_code == "shared"
    assert sample.domain_code == "ai"
    assert sample.paper_config == {"enabled": True}
    assert sample.metadata_json["info_category"] == "学术论文"

    registry_sample = session.scalar(
        select(DataSource).where(DataSource.url == "https://arstechnica.com/ai/feed"),
    )
    assert registry_sample is not None
    assert registry_sample.metadata_json["origin"] == "source_registry_csv"
    assert "AI前沿洞察" in registry_sample.metadata_json["source_tags"]
    assert "AI安全" in registry_sample.metadata_json["source_secondary_tags"]
    assert registry_sample.enabled is True

    workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
    assert workspace is not None
    assert session.scalar(select(func.count(WorkspaceSourceLink.id))) == 294
    assert (
        session.scalar(select(func.count(DataSource.id)).where(DataSource.enabled.is_(True))) == 294
    )
    assert (
        session.scalar(
            select(func.count(WorkspaceSourceLink.id)).where(WorkspaceSourceLink.enabled.is_(True)),
        )
        == 294
    )

    second = import_legacy_sources(session, legacy_seed_root())
    session.commit()

    assert second.created == 0
    assert second.updated == 361
    assert session.scalar(select(func.count(DataSource.id))) == 294
    assert session.scalar(select(func.count(WorkspaceSourceLink.id))) == 294
