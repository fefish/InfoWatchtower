from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.content import DataSource
from app.models.workspace import Workspace, WorkspaceSourceLink


@dataclass(frozen=True)
class SeedImportResult:
    created: int
    updated: int
    total: int


def import_legacy_sources(session: Session, seed_root: Path) -> SeedImportResult:
    workspaces = _enabled_workspaces(session)
    sources = [
        *_load_wiseflow_sources(seed_root / "wiseflow_sources.json"),
        *_load_rss_sources(seed_root / "rss_sources.json"),
        *_load_page_sources(seed_root / "page_sources.json"),
    ]
    created = 0
    updated = 0
    for source in sources:
        existing = session.scalar(
            _source_identity_statement(source),
        )
        if existing is None:
            session.add(source)
            session.flush()
            for workspace in workspaces:
                _ensure_workspace_source_link(session, workspace, source)
            created += 1
        else:
            _copy_source_fields(existing, source)
            for workspace in workspaces:
                _ensure_workspace_source_link(session, workspace, existing)
            updated += 1
    session.flush()
    return SeedImportResult(created=created, updated=updated, total=len(sources))


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_identity_statement(source: DataSource) -> Select[tuple[DataSource]]:
    statement = select(DataSource).where(
        DataSource.source_type == source.source_type,
        DataSource.name == source.name,
    )
    if source.url is None:
        return statement.where(DataSource.url.is_(None))
    return statement.where(DataSource.url == source.url)


def _load_wiseflow_sources(path: Path) -> list[DataSource]:
    sources: list[DataSource] = []
    for item in _load_json(path):
        sources.append(
            DataSource(
                workspace_code="shared",
                domain_code="ai",
                source_type="wiseflow",
                name=item["name"],
                url=None,
                enabled=bool(item.get("enabled", True)),
                default_focus_id=item.get("default_focus_id") or 1,
                backfill_days=item.get("backfill_days") or 7,
                fetch_config={
                    "base_url_env": item.get("base_url_env"),
                    "read_info_url_env": item.get("read_info_url_env"),
                    "page_size_env": item.get("page_size_env"),
                    "state_path_env": item.get("state_path_env"),
                    "lookback_seconds_env": item.get("lookback_seconds_env"),
                    "required_full_sync_endpoint": item.get("required_full_sync_endpoint"),
                    "do_not_use_for_full_sync": item.get("do_not_use_for_full_sync"),
                },
                metadata_json={
                    "origin": "legacy_wiseflow",
                    "notes": item.get("notes", ""),
                    "legacy_metadata": item.get("metadata", {}),
                    "raw_seed": item,
                },
            ),
        )
    return sources


def _load_rss_sources(path: Path) -> list[DataSource]:
    sources: list[DataSource] = []
    for item in _load_json(path):
        folo_metadata = item.get("folo_metadata", {})
        info_category = folo_metadata.get("info_category", "")
        source_type = "paper_rss" if info_category == "学术论文" else "rss"
        sources.append(
            DataSource(
                workspace_code="shared",
                domain_code="ai",
                source_type=source_type,
                name=item["name"],
                url=item.get("feed_url"),
                enabled=bool(item.get("enabled", True)),
                default_focus_id=item.get("default_focus_id") or 1,
                backfill_days=item.get("backfill_days") or 30,
                fetch_config={
                    "feed_url": item.get("feed_url"),
                    "fetch_interval_minutes": item.get("fetch_interval_minutes", 1440),
                },
                paper_config={"enabled": source_type == "paper_rss"},
                metadata_json={
                    "origin": "legacy_rss",
                    "primary_category": folo_metadata.get("primary_category", ""),
                    "secondary_category": folo_metadata.get("secondary_category", ""),
                    "info_category": info_category,
                    "topic_flags": {
                        key: folo_metadata.get(key)
                        for key in [
                            "is_model_related",
                            "is_inference_related",
                            "is_agent_related",
                            "is_application_related",
                            "is_device_vendor_related",
                            "is_telco_related",
                            "is_cloud_related",
                            "is_hardware_related",
                            "is_core_competency_related",
                        ]
                    },
                    "raw_seed": item,
                },
            ),
        )
    return sources


def _load_page_sources(path: Path) -> list[DataSource]:
    sources: list[DataSource] = []
    for item in _load_json(path):
        source_type = "page_manual" if item.get("type") == "manual" else "page_monitor"
        sources.append(
            DataSource(
                workspace_code="shared",
                domain_code="ai",
                source_type=source_type,
                name=item["name"],
                url=item.get("page_url") or _first_manual_article_url(item),
                enabled=bool(item.get("enabled", True)),
                default_focus_id=item.get("default_focus_id") or 1,
                backfill_days=item.get("backfill_days") or 45,
                fetch_config={
                    "type": item.get("type"),
                    "page_url": item.get("page_url"),
                    "href_contains": item.get("href_contains", []),
                    "exclude_exact": item.get("exclude_exact", []),
                    "max_links": item.get("max_links"),
                    "articles": item.get("articles", []),
                },
                metadata_json={"origin": "legacy_page", "raw_seed": item},
            ),
        )
    return sources


def _first_manual_article_url(item: dict[str, Any]) -> str | None:
    articles = item.get("articles") or []
    if not articles:
        return None
    return articles[0].get("url")


def _copy_source_fields(target: DataSource, source: DataSource) -> None:
    target.workspace_code = source.workspace_code
    target.domain_code = source.domain_code
    target.url = source.url
    target.enabled = source.enabled
    target.default_focus_id = source.default_focus_id
    target.backfill_days = source.backfill_days
    target.fetch_config = source.fetch_config
    target.paper_config = source.paper_config
    target.metadata_json = source.metadata_json


def _ensure_default_workspace(session: Session) -> Workspace:
    workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
    if workspace is not None:
        return workspace

    workspace = Workspace(
        code="planning_intel",
        name="规划部情报工作台",
        description="行业信号、日报周报、专题洞察和内部需求闭环。",
        workspace_type="intelligence_workspace",
        default_domain_code="ai",
        enabled=True,
    )
    session.add(workspace)
    session.flush()
    return workspace


def _enabled_workspaces(session: Session) -> list[Workspace]:
    workspaces = session.scalars(select(Workspace).where(Workspace.enabled.is_(True))).all()
    if workspaces:
        return workspaces
    return [_ensure_default_workspace(session)]


def _ensure_workspace_source_link(
    session: Session,
    workspace: Workspace,
    source: DataSource,
) -> WorkspaceSourceLink:
    link = session.scalar(
        select(WorkspaceSourceLink).where(
            WorkspaceSourceLink.workspace_id == workspace.id,
            WorkspaceSourceLink.data_source_id == source.id,
        ),
    )
    if link is None:
        link = WorkspaceSourceLink(
            workspace=workspace,
            data_source=source,
            domain_code=source.domain_code,
            enabled=source.enabled,
            source_weight=1.0,
            config_json={
                "label_set_codes": ["ai_sql_categories"],
                "default_label_paths": [],
                "clustering_config": {},
                "origin": "legacy_seed",
            },
        )
        session.add(link)
    else:
        config = link.config_json or {}
        link.domain_code = source.domain_code
        link.enabled = source.enabled
        link.config_json = {
            **config,
            "label_set_codes": config.get("label_set_codes", ["ai_sql_categories"]),
            "default_label_paths": config.get("default_label_paths", []),
            "clustering_config": config.get("clustering_config", {}),
            "origin": config.get("origin", "legacy_seed"),
        }
    return link
