from __future__ import annotations

import csv
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


@dataclass(frozen=True)
class TechInsightLoopImportResult:
    created: int
    updated: int
    total: int
    fetchable: int
    metadata_only: int


def import_legacy_sources(session: Session, seed_root: Path) -> SeedImportResult:
    workspaces = _enabled_workspaces(session)
    sources = [
        *_load_wiseflow_sources(seed_root / "wiseflow_sources.json"),
        *_load_rss_sources(seed_root / "rss_sources.json"),
        *_load_page_sources(seed_root / "page_sources.json"),
        *_load_source_registry_csv_sources(seed_root / "source_catalog"),
    ]
    created = 0
    updated = 0
    for source in sources:
        source.enabled = True
        existing = session.scalar(
            _source_identity_statement(source),
        )
        if existing is None:
            session.add(source)
            session.flush()
            for workspace in workspaces:
                _ensure_workspace_source_link(session, workspace, source)
            session.flush()
            created += 1
        else:
            _copy_source_fields(existing, source)
            for workspace in workspaces:
                _ensure_workspace_source_link(session, workspace, existing)
            session.flush()
            updated += 1
    session.flush()
    return SeedImportResult(created=created, updated=updated, total=len(sources))


def import_tech_insight_loop_sources(session: Session, csv_path: Path) -> TechInsightLoopImportResult:
    workspaces = _enabled_workspaces(session)
    sources: list[DataSource] = []
    fetchable = 0
    metadata_only = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            source = _tech_insight_loop_row_to_source(row, csv_path.name)
            if source is None:
                continue
            sources.append(source)
            if source.metadata_json.get("metadata_only"):
                metadata_only += 1
            else:
                fetchable += 1

    created = 0
    updated = 0
    for source in sources:
        existing = session.scalar(_tech_source_identity_statement(source))
        if existing is None:
            session.add(source)
            session.flush()
            for workspace in workspaces:
                _ensure_workspace_source_link(
                    session,
                    workspace,
                    source,
                    enabled=source.enabled,
                    origin="tech_insight_loop",
                )
            created += 1
        else:
            manual_entry_url = existing.url
            has_manual_entry = (
                bool(manual_entry_url)
                and (existing.metadata_json or {}).get("fetch_entry_status") == "manual_entry_added"
            )
            _copy_source_fields(existing, source, update_enabled=False)
            if has_manual_entry and source.metadata_json.get("metadata_only"):
                # Re-imports of the governance CSV must not wipe manually filled entries.
                existing.url = manual_entry_url
                merged_metadata = dict(existing.metadata_json or {})
                merged_metadata["metadata_only"] = False
                merged_metadata["needs_entry"] = False
                merged_metadata["fetch_entry_status"] = "manual_entry_added"
                existing.metadata_json = merged_metadata
            for workspace in workspaces:
                _ensure_workspace_source_link(
                    session,
                    workspace,
                    existing,
                    enabled=source.enabled,
                    origin="tech_insight_loop",
                    update_enabled=False,
                )
            updated += 1
        session.flush()
    return TechInsightLoopImportResult(
        created=created,
        updated=updated,
        total=len(sources),
        fetchable=fetchable,
        metadata_only=metadata_only,
    )


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_identity_statement(source: DataSource) -> Select[tuple[DataSource]]:
    statement = select(DataSource).where(
        DataSource.source_type == source.source_type,
    )
    if source.url is None:
        return statement.where(DataSource.name == source.name, DataSource.url.is_(None))
    return statement.where(DataSource.url == source.url)


def _tech_source_identity_statement(source: DataSource) -> Select[tuple[DataSource]]:
    statement = select(DataSource)
    if source.url:
        return statement.where(DataSource.url == source.url)
    tech_source_id = str(source.metadata_json.get("tech_insight_loop_source_id") or "")
    if tech_source_id:
        return statement.where(
            DataSource.metadata_json["tech_insight_loop_source_id"].as_string() == tech_source_id,
        )
    return statement.where(DataSource.name == source.name, DataSource.url.is_(None))


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
        source_tags, source_secondary_tags = _source_tags_from_folo_metadata(folo_metadata)
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
                    "source_tags": source_tags,
                    "source_secondary_tags": source_secondary_tags,
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


def _source_tags_from_folo_metadata(metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    secondary_tags: list[str] = []

    def add(tag: str, *secondary: str) -> None:
        if tag not in tags:
            tags.append(tag)
        for item in secondary:
            if item and item not in secondary_tags:
                secondary_tags.append(item)

    if metadata.get("info_category") == "学术论文":
        add("AI前沿洞察", "论文")
    if metadata.get("is_model_related"):
        add("AI前沿洞察", "模型")
    if metadata.get("is_inference_related"):
        add("AI工程能力", "推理加速")
    if metadata.get("is_agent_related"):
        add("AI工程能力", "智能体")
    if metadata.get("is_application_related"):
        add("AI前沿洞察", "AI 应用")
    if metadata.get("is_cloud_related") or metadata.get("is_core_competency_related"):
        add("AI基础设施", "AI Infra")
    if metadata.get("is_hardware_related"):
        add("硬件/芯片/数据中心")
    if metadata.get("is_telco_related") or metadata.get("is_device_vendor_related"):
        add("核心网/通信系统")

    if not tags:
        add("AI前沿洞察")
    return tags, secondary_tags


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


def _load_source_registry_csv_sources(path: Path) -> list[DataSource]:
    if not path.exists():
        return []

    sources: list[DataSource] = []
    for csv_path in sorted(path.glob("*.csv")):
        with csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if "信息源名称" not in (reader.fieldnames or []):
                continue
            for row in reader:
                source = _csv_registry_row_to_source(row, csv_path.name)
                if source is not None:
                    sources.append(source)
    return sources


def _csv_registry_row_to_source(row: dict[str, str], filename: str) -> DataSource | None:
    feed_url = _first_non_empty(
        row.get("RSS订阅URL"),
        row.get("CLI RSS"),
        row.get("Folo RSS"),
    )
    if not feed_url or not feed_url.startswith(("http://", "https://")):
        return None
    if row.get("当前状态", "").strip() in {"暂停", "非文章页"}:
        return None

    source_tags, source_secondary_tags = _source_tags_from_registry_row(row)
    info_category = _first_non_empty(
        row.get("来源信息分类（兼容字段）"),
        row.get("来源内容类型"),
        row.get("来源类型（兼容字段）"),
    )
    source_type = "paper_rss" if _looks_like_paper_source(row) else "rss"
    source_score = _float_value(row.get("综合质量评分")) or _float_value(row.get("源质量分")) or 0.0
    name = _first_non_empty(
        row.get("RSS显示名称"),
        row.get("CLI标题"),
        row.get("Folo标题"),
        row.get("信息源名称"),
    )

    return DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type=source_type,
        name=name,
        url=feed_url,
        enabled=True,
        default_focus_id=1,
        backfill_days=30,
        fetch_config={
            "feed_url": feed_url,
            "fetch_interval_minutes": 1440,
            "registry_source": filename,
            "registry_source_id": row.get("信息源编号", ""),
            "original_page_url": row.get("原始页面URL", ""),
            "access_method": row.get("配置接入方式", ""),
        },
        paper_config={"enabled": source_type == "paper_rss"},
        metadata_json={
            "origin": "source_registry_csv",
            "registry_filename": filename,
            "registry_id": row.get("信息源编号", ""),
            "database_id": row.get("数据库ID", ""),
            "primary_category": row.get("来源一级分类", ""),
            "secondary_category": row.get("来源二级分类", ""),
            "info_category": info_category,
            "business_board": row.get("业务板块（兼容字段）") or row.get("主业务板块", ""),
            "current_status": row.get("当前状态", ""),
            "access_priority": row.get("接入优先级", ""),
            "source_tier": row.get("源层级", ""),
            "source_score": source_score,
            "source_tags": source_tags,
            "source_secondary_tags": source_secondary_tags,
            "recommendation": row.get("纳入建议", ""),
            "expert_routes": row.get("专家路由", ""),
            "evidence_strength": row.get("证据强度", ""),
            "competition_impact": row.get("竞争影响", ""),
            "evaluation_summary": row.get("信息源评估摘要") or row.get("备注", ""),
            "relevance_distribution": _json_object(row.get("板块相关度分布")),
            "score_detail": _json_object(row.get("评分原始明细")),
            "raw_registry_row": row,
        },
        source_score=source_score,
    )


def _tech_insight_loop_row_to_source(row: dict[str, str], filename: str) -> DataSource | None:
    name = _first_non_empty(
        row.get("信息源名称"),
        row.get("字段：rss_name"),
        row.get("字段：cli_title"),
        row.get("字段：folo_title"),
    )
    if not name:
        return None

    feed_url = _tech_feed_url(row)
    original_url = _clean(row.get("原始URL"))
    http_original_url = original_url if _is_http_url(original_url) else ""
    has_fetch_entry = bool(feed_url or http_original_url)
    metadata_only = not has_fetch_entry
    source_type = _tech_source_type(row, feed_url, http_original_url)
    source_tags, source_secondary_tags = _source_tags_from_tech_insight_row(row)
    source_score = (
        _float_value(row.get("字段：source_quality_score"))
        or _float_value(row.get("信息源综合评分"))
        or 0.0
    )
    expert_routes = _json_list(row.get("专家路由JSON"))
    source_entities = _json_list(row.get("字段：source_entity_types_json"))
    impact_types = _json_list(row.get("字段：impact_types_json"))
    board_relevance = _json_object(row.get("字段：board_relevance_json"))
    score_breakdown = _json_object(row.get("字段：source_score_breakdown_json"))
    entry_url = feed_url or http_original_url or None

    fetch_config: dict[str, Any] = {
        "registry_source": filename,
        "registry_source_id": row.get("信息源编码", ""),
        "access_method": row.get("接入方式配置", ""),
        "original_url": original_url,
        "rss_url": _clean(row.get("RSS订阅源")),
        "cli_rss": _clean(row.get("CLI RSS")),
        "folo_rss": _clean(row.get("Folo RSS")),
        "metadata_only": metadata_only,
    }
    if source_type in {"rss", "paper_rss"}:
        fetch_config["feed_url"] = feed_url
    elif source_type == "page_manual" and http_original_url:
        fetch_config["type"] = "manual"
        fetch_config["articles"] = [{"url": http_original_url}]

    return DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type=source_type,
        name=name,
        url=entry_url,
        enabled=has_fetch_entry,
        default_focus_id=1,
        backfill_days=30,
        fetch_config=fetch_config,
        paper_config={"enabled": source_type == "paper_rss"},
        metadata_json={
            "origin": "tech_insight_loop",
            "registry_filename": filename,
            "database_id": row.get("数据库ID", ""),
            "tech_insight_loop_source_id": row.get("信息源编码", ""),
            "source_tier": row.get("源等级", ""),
            "source_channel_type": row.get("来源渠道类型", ""),
            "access_method": row.get("接入方式配置", ""),
            "current_status": row.get("当前状态", ""),
            "csv_status": row.get("字段：csv_status", ""),
            "primary_category": row.get("一级分类", ""),
            "secondary_category": row.get("二级分类", ""),
            "info_category": row.get("来源信息分类", ""),
            "business_board": row.get("业务板块", ""),
            "primary_board": row.get("主业务板块", ""),
            "source_score": source_score,
            "source_tags": source_tags,
            "source_secondary_tags": source_secondary_tags,
            "expert_routes": expert_routes,
            "source_entity_types": source_entities,
            "impact_types": impact_types,
            "board_relevance_json": board_relevance,
            "source_score_breakdown_json": score_breakdown,
            "source_quality_notes": row.get("字段：quality_notes", ""),
            "source_eval_summary": row.get("字段：source_eval_summary", ""),
            "inclusion_recommendation": row.get("字段：inclusion_recommendation", ""),
            "recent_fetch_failure_reason": row.get("最近抓取失败原因", ""),
            "consecutive_failure_count": _int_value(row.get("连续失败次数")),
            "field_governance_status": row.get("字段：field_governance_status", ""),
            "metadata_only": metadata_only,
            "needs_entry": metadata_only,
            "fetch_entry_status": "ready" if has_fetch_entry else "needs_entry",
            "raw_registry_row": row,
        },
        source_score=source_score,
    )


def _looks_like_paper_source(row: dict[str, str]) -> bool:
    text = " ".join(
        [
            row.get("来源一级分类", ""),
            row.get("来源二级分类", ""),
            row.get("来源信息分类（兼容字段）", ""),
            row.get("来源内容类型", ""),
            row.get("信息源名称", ""),
            row.get("RSS显示名称", ""),
        ],
    )
    return any(token in text.lower() for token in ["arxiv", "论文", "paper", "research paper"])


def _tech_source_type(row: dict[str, str], feed_url: str, original_url: str) -> str:
    text = " ".join(
        [
            row.get("一级分类", ""),
            row.get("二级分类", ""),
            row.get("来源信息分类", ""),
            row.get("来源类型", ""),
            row.get("信息源名称", ""),
            row.get("业务板块", ""),
            row.get("主业务板块", ""),
        ],
    )
    if feed_url:
        return "paper_rss" if any(token in text.lower() for token in ["arxiv", "论文", "paper"]) else "rss"
    if original_url:
        return "page_manual"
    return "manual"


def _tech_feed_url(row: dict[str, str]) -> str:
    feed_url = _first_non_empty(
        row.get("RSS订阅源"),
        row.get("CLI RSS"),
        row.get("Folo RSS"),
    )
    if _is_http_url(feed_url):
        return feed_url
    if feed_url.startswith("rsshub://"):
        route = feed_url.removeprefix("rsshub://").strip("/")
        return f"https://rsshub.app/{route}" if route else ""
    original_url = _clean(row.get("原始URL"))
    if original_url.startswith("rsshub://"):
        route = original_url.removeprefix("rsshub://").strip("/")
        return f"https://rsshub.app/{route}" if route else ""
    return ""


def _source_tags_from_registry_row(row: dict[str, str]) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    secondary_tags: list[str] = []

    def add(tag: str, *secondary: str) -> None:
        if tag not in tags:
            tags.append(tag)
        for item in secondary:
            if item and item not in secondary_tags:
                secondary_tags.append(item)

    relevance_rules = [
        ("AI模型历史相关度", "AI前沿洞察", "模型"),
        ("AI推理与服务加速相关度", "AI工程能力", "推理加速"),
        ("智能体平台、协议与执行系统相关度", "AI工程能力", "智能体"),
        ("AI应用与产品化场景相关度", "AI前沿洞察", "AI 应用"),
        ("通信设备供应商相关度", "核心网/通信系统", "通信设备供应商"),
        ("通信服务提供商相关度", "核心网/通信系统", "通信服务提供商"),
        ("云与AI基础设施相关度", "AI基础设施", "AI Infra"),
        ("AI与通算硬件相关度", "硬件/芯片/数据中心", "AI芯片"),
        ("基础竞争力/软件性能相关度", "软件性能/内存/成本", "软件性能"),
        ("基础竞争力/系统效率相关度", "软件性能/内存/成本", "系统效率"),
        ("核心网与通信系统架构相关度", "核心网/通信系统", "核心网"),
        ("标准、协议与产业联盟相关度", "标准/产业联盟", "标准"),
        ("AI安全、可信与治理相关度", "AI前沿洞察", "AI安全"),
    ]
    for field, tag, secondary in relevance_rules:
        if _is_relevant(row.get(field, "")):
            add(tag, secondary)

    board_text = " ".join([row.get("业务板块（兼容字段）", ""), row.get("主业务板块", "")])
    if any(token in board_text for token in ["推理", "智能体", "系统效率"]):
        add("AI工程能力")
    if any(token in board_text for token in ["硬件", "芯片"]):
        add("硬件/芯片/数据中心")
    if any(token in board_text for token in ["核心网", "通信"]):
        add("核心网/通信系统")
    if any(token in board_text for token in ["标准", "协议", "联盟"]):
        add("标准/产业联盟")

    if not tags:
        add("AI前沿洞察")
    return tags, secondary_tags


def _source_tags_from_tech_insight_row(row: dict[str, str]) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    secondary_tags: list[str] = []

    def add(tag: str, *secondary: str) -> None:
        if tag not in tags:
            tags.append(tag)
        for item in secondary:
            if item and item not in secondary_tags:
                secondary_tags.append(item)

    relevance = _json_object(row.get("字段：board_relevance_json"))
    board_rules = [
        ("AI模型", "AI前沿洞察", "模型"),
        ("AI模型、训练与评测", "AI前沿洞察", "模型"),
        ("模型训练", "AI工程能力", "训练技术"),
        ("模型评测", "AI前沿洞察", "测评技术"),
        ("AI推理与服务加速", "AI工程能力", "推理加速"),
        ("智能体平台、协议与执行系统", "AI工程能力", "智能体"),
        ("AI应用与产品化场景", "AI前沿洞察", "AI 应用"),
        ("AI安全、可信与治理", "AI前沿洞察", "AI安全"),
        ("云与AI基础设施", "AI基础设施", "AI Infra"),
        ("AI与通算硬件", "硬件/芯片/数据中心", "AI芯片"),
        ("基础竞争力", "软件性能/内存/成本", "软件性能"),
        ("核心网与通信系统架构", "核心网/通信系统", "核心网"),
        ("通信设备供应商", "核心网/通信系统", "通信设备供应商"),
        ("通信服务提供商", "核心网/通信系统", "通信服务提供商"),
        ("标准、协议与产业联盟", "标准/产业联盟", "标准"),
    ]
    for board, tag, secondary in board_rules:
        value = relevance.get(board)
        if isinstance(value, str) and value.strip() in {"强相关", "中相关", "弱相关"}:
            add(tag, secondary)

    relevance_fields = [
        ("字段：ai_model_training_eval_relevance", "AI前沿洞察", "模型"),
        ("字段：ai_inference_serving_relevance", "AI工程能力", "推理加速"),
        ("字段：agent_platform_relevance", "AI工程能力", "智能体"),
        ("字段：ai_application_relevance", "AI前沿洞察", "AI 应用"),
        ("字段：telecom_vendor_relevance", "核心网/通信系统", "通信设备供应商"),
        ("字段：telecom_operator_relevance", "核心网/通信系统", "通信服务提供商"),
        ("字段：cloud_ai_infra_relevance", "AI基础设施", "AI Infra"),
        ("字段：ai_hardware_relevance", "硬件/芯片/数据中心", "AI芯片"),
        ("字段：software_perf_relevance", "软件性能/内存/成本", "软件性能"),
        ("字段：telecom_system_efficiency_relevance", "通信系统成本", "TCO"),
        ("字段：core_network_relevance", "核心网/通信系统", "核心网"),
        ("字段：standards_relevance", "标准/产业联盟", "标准"),
        ("字段：ai_security_relevance", "AI前沿洞察", "AI安全"),
    ]
    for field, tag, secondary in relevance_fields:
        if _is_relevant(row.get(field, "")):
            add(tag, secondary)

    board_text = " ".join([row.get("业务板块", ""), row.get("主业务板块", "")])
    if any(token in board_text for token in ["推理", "智能体", "训练"]):
        add("AI工程能力")
    if any(token in board_text for token in ["云", "基础设施"]):
        add("AI基础设施")
    if any(token in board_text for token in ["硬件", "芯片"]):
        add("硬件/芯片/数据中心")
    if any(token in board_text for token in ["通信", "核心网"]):
        add("核心网/通信系统")
    if any(token in board_text for token in ["标准", "协议", "联盟"]):
        add("标准/产业联盟")

    if not tags:
        add("AI前沿洞察")
    return tags, secondary_tags


def _is_relevant(value: str) -> bool:
    return value.strip() in {"强相关", "中相关", "弱相关"}


def _is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        clean = (value or "").strip()
        if clean:
            return clean
    return ""


def _float_value(value: str | None) -> float | None:
    try:
        return float((value or "").strip())
    except ValueError:
        return None


def _int_value(value: str | None) -> int:
    try:
        return int(float((value or "").strip()))
    except ValueError:
        return 0


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _first_manual_article_url(item: dict[str, Any]) -> str | None:
    articles = item.get("articles") or []
    if not articles:
        return None
    return articles[0].get("url")


def _copy_source_fields(target: DataSource, source: DataSource, *, update_enabled: bool = True) -> None:
    target.workspace_code = source.workspace_code
    target.domain_code = source.domain_code
    target.url = source.url
    if update_enabled:
        target.enabled = source.enabled
    target.default_focus_id = source.default_focus_id
    target.backfill_days = source.backfill_days
    target.fetch_config = source.fetch_config or {}
    target.paper_config = source.paper_config or {}
    target.metadata_json = source.metadata_json or {}
    target.source_score = source.source_score or 0.0


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
    *,
    enabled: bool = True,
    origin: str = "legacy_seed",
    update_enabled: bool = True,
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
            enabled=enabled,
            source_weight=1.0,
            config_json={
                "clustering_config": {},
                "origin": origin,
            },
        )
        session.add(link)
    else:
        config = link.config_json or {}
        link.domain_code = source.domain_code
        if update_enabled:
            link.enabled = enabled
        link_config = {
            **config,
            "clustering_config": config.get("clustering_config", {}),
            "origin": config.get("origin", origin),
        }
        link_config.pop("label_set_codes", None)
        link_config.pop("default_label_paths", None)
        link.config_json = link_config
    return link
