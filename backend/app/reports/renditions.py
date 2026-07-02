"""报告多版成稿（rendition）服务。

设计文档：docs/report-renditions-design.md
不变式：
- rendition 是采信条目的投影快照，可随时重生成，不回写采信状态、
  generated_news 与公司 SQL 出口。
- 业务板块只存在于 insight 辅助字段和成稿分组里，不写 category。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import REPO_ROOT
from app.models.common import utc_now
from app.models.reports import (
    DailyReport,
    DailyReportItem,
    ReportFormat,
    ReportRendition,
    WeeklyReport,
    WeeklyReportItem,
)

ReportItem = DailyReportItem | WeeklyReportItem

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

RENDITION_ITEM_FIELDS = [
    "tag_line",
    "bullet_points",
    "takeaway",
    "five_fields",
    "summary",
    "source_link",
    "score",
]

BUILTIN_REPORT_FORMATS = [
    {
        "format_code": "company_sql_v1",
        "name": "内网版",
        "description": "公司内网口径：十分类平铺、五段正文，公司 SQL 导出的唯一来源。",
        "builtin": True,
        "locked": True,
        "group_by": "category",
        "headline_enabled": False,
        "headline_auto_top_n": 0,
        "item_fields": {"fields": ["five_fields", "source_link"]},
        "export_targets": {"targets": []},
        "sort_order": 10,
    },
    {
        "format_code": "tech_insight_v1",
        "name": "技术洞察版",
        "description": "对齐技术洞察快报：头条区 + 业务板块分组 + 标签行/要点/总结/来源。",
        "builtin": True,
        "locked": False,
        "group_by": "board",
        "headline_enabled": True,
        "headline_auto_top_n": 6,
        "item_fields": {"fields": ["tag_line", "bullet_points", "takeaway", "source_link"]},
        "export_targets": {"targets": ["md", "html"]},
        "sort_order": 20,
    },
]


@lru_cache
def _board_taxonomy() -> dict[str, Any]:
    path = REPO_ROOT / "config" / "taxonomy" / "business_boards.json"
    return json.loads(path.read_text(encoding="utf-8"))


def board_order() -> list[str]:
    return list(_board_taxonomy().get("board_order") or [])


def fallback_board() -> str:
    return str(_board_taxonomy().get("fallback_board") or "基础竞争力")


def _category_to_board() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for board in _board_taxonomy().get("boards") or []:
        for category in board.get("suggested_categories") or []:
            mapping.setdefault(str(category), str(board["code"]))
    return mapping


def ensure_report_formats(session: Session, workspace_code: str) -> list[ReportFormat]:
    """为工作台注册内置格式（幂等）。locked 内置格式的结构以代码定义为准。"""
    existing = {
        fmt.format_code: fmt
        for fmt in session.scalars(
            select(ReportFormat).where(ReportFormat.workspace_code == workspace_code),
        ).all()
    }
    for definition in BUILTIN_REPORT_FORMATS:
        fmt = existing.get(definition["format_code"])
        if fmt is None:
            fmt = ReportFormat(workspace_code=workspace_code, **definition)
            session.add(fmt)
            existing[definition["format_code"]] = fmt
        elif fmt.locked:
            for key, value in definition.items():
                if key != "format_code":
                    setattr(fmt, key, value)
    session.flush()
    return list(existing.values())


def resolve_insight(item: ReportItem) -> dict[str, Any]:
    """条目的技术洞察辅助字段：优先模型产出的 insight_json，缺省规则降级。"""
    news = item.generated_news
    insight = dict(news.insight_json or {})
    content = news.content_json or {}

    board = str(insight.get("board") or "")
    if board not in board_order():
        board = _board_from_source(item) or _category_to_board().get(news.category) or fallback_board()

    bullet_points = [str(point) for point in insight.get("bullet_points") or [] if str(point).strip()]
    if not bullet_points:
        bullet_points = _fallback_bullets(content, news.summary)

    takeaway = str(insight.get("takeaway") or "").strip()
    if not takeaway:
        takeaway = str(content.get("valueAndImpact") or content.get("effects") or news.summary or "").strip()

    tag_line = [str(tag) for tag in insight.get("tag_line") or [] if str(tag).strip()]
    if not tag_line:
        tag_line = _fallback_tag_line(item, board)

    return {
        "board": board,
        "bullet_points": bullet_points,
        "takeaway": takeaway,
        "tag_line": tag_line,
        "insight_source": "model" if insight.get("bullet_points") else "rule_fallback",
    }


def _board_from_source(item: ReportItem) -> str | None:
    news_item = item.generated_news.news_item
    data_source = news_item.data_source if news_item else None
    metadata = (data_source.metadata_json or {}) if data_source else {}
    relevance = metadata.get("board_relevance_json") or {}
    if isinstance(relevance, dict) and relevance:
        candidates = [
            (str(board), float(score))
            for board, score in relevance.items()
            if isinstance(score, (int, float)) and str(board) in board_order()
        ]
        if candidates:
            return max(candidates, key=lambda pair: pair[1])[0]
    return None


def _fallback_bullets(content: dict[str, Any], summary: str) -> list[str]:
    parts: list[str] = []
    for key in ("eventSummary", "technologyAndInnovation"):
        value = str(content.get(key) or "").strip()
        if value:
            parts.append(value)
    if not parts and summary:
        parts.append(summary.strip())
    return parts


def _fallback_tag_line(item: ReportItem, board: str) -> list[str]:
    tags = [board, item.generated_news.category]
    recommendation = item.generated_news.recommendation_item
    if recommendation is not None:
        routes = recommendation.expert_routes_json or []
        if isinstance(routes, list) and routes:
            tags.append(str(routes[0]))
    seen: list[str] = []
    for tag in tags:
        value = str(tag).strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def ensure_headlines(session: Session, report: DailyReport, top_n: int) -> None:
    """无任何头条标记时按推荐分初始化 Top N（只初始化，不覆盖编辑选择）。"""
    adopted = [item for item in report.items if item.adoption_status == 2]
    if not adopted or any(item.is_headline for item in adopted):
        return
    scored = sorted(adopted, key=_item_score, reverse=True)
    for item in scored[: max(0, top_n)]:
        item.is_headline = True
    session.flush()


def _item_score(item: ReportItem) -> float:
    recommendation = item.generated_news.recommendation_item
    return float(recommendation.final_score) if recommendation is not None else 0.0


@dataclass(frozen=True)
class RenditionContext:
    report_type: str
    report_id: str
    workspace_code: str
    domain_code: str
    period_key: str
    period_label: str
    workspace_name: str


def build_daily_rendition(
    session: Session,
    report: DailyReport,
    fmt: ReportFormat,
    workspace_name: str = "",
) -> ReportRendition:
    if fmt.headline_enabled:
        ensure_headlines(session, report, fmt.headline_auto_top_n)

    adopted = sorted(
        (item for item in report.items if item.adoption_status == 2),
        key=lambda item: (item.sort_order, item.created_at),
    )
    context = RenditionContext(
        report_type="daily",
        report_id=report.id,
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        period_key=report.day_key,
        period_label=f"{report.day_key} 技术洞察日报",
        workspace_name=workspace_name or report.workspace_code,
    )
    return _upsert_rendition(session, context, fmt, adopted)


def build_weekly_rendition(
    session: Session,
    report: WeeklyReport,
    fmt: ReportFormat,
    workspace_name: str = "",
) -> ReportRendition:
    """周报成稿：与日报同构；周报条目没有头条标记，头条区留空。"""
    adopted = sorted(
        (
            item
            for item in report.items
            if item.adoption_status == 2 and item.generated_news is not None
        ),
        key=lambda item: (item.sort_order, item.created_at),
    )
    context = RenditionContext(
        report_type="weekly",
        report_id=report.id,
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        period_key=report.week_key,
        period_label=f"{report.week_key} 技术洞察周报",
        workspace_name=workspace_name or report.workspace_code,
    )
    return _upsert_rendition(session, context, fmt, adopted)


def _upsert_rendition(
    session: Session,
    context: RenditionContext,
    fmt: ReportFormat,
    items: list[ReportItem],
) -> ReportRendition:
    snapshots = [_item_snapshot(item, fmt) for item in items]
    groups = _group_snapshots(snapshots, fmt)
    headlines = [snapshot for snapshot in snapshots if snapshot["is_headline"]] if fmt.headline_enabled else []

    board_distribution: dict[str, int] = {}
    for snapshot in snapshots:
        key = snapshot["board"] if fmt.group_by == "board" else snapshot["category"]
        board_distribution[key] = board_distribution.get(key, 0) + 1

    rendition = session.scalar(
        select(ReportRendition).where(
            ReportRendition.report_type == context.report_type,
            ReportRendition.report_id == context.report_id,
            ReportRendition.format_code == fmt.format_code,
        ),
    )
    if rendition is None:
        rendition = ReportRendition(
            report_type=context.report_type,
            report_id=context.report_id,
            format_code=fmt.format_code,
            workspace_code=context.workspace_code,
            domain_code=context.domain_code,
        )
        session.add(rendition)

    rendition.title = f"{context.period_key} {context.workspace_name} {fmt.name}"
    rendition.status = "draft"
    rendition.summary_json = {
        "period_key": context.period_key,
        "item_total": len(snapshots),
        "group_distribution": board_distribution,
        "headline_titles": [snapshot["title"] for snapshot in headlines],
        "source_total": len({snapshot["source_name"] for snapshot in snapshots if snapshot["source_name"]}),
    }
    rendition.body_json = {
        "format_code": fmt.format_code,
        "group_by": fmt.group_by,
        "item_fields": list((fmt.item_fields or {}).get("fields") or []),
        "headlines": [snapshot["item_id"] for snapshot in headlines],
        "groups": groups,
        "items": {snapshot["item_id"]: snapshot for snapshot in snapshots},
    }
    rendition.generated_by = "rule_projection_v1"
    rendition.generated_at = utc_now()
    session.flush()
    return rendition


def _item_snapshot(item: ReportItem, fmt: ReportFormat) -> dict[str, Any]:
    news = item.generated_news
    assert news is not None
    insight = resolve_insight(item)
    content = news.content_json or {}
    news_item = news.news_item
    return {
        "item_id": item.id,
        "generated_news_id": news.id,
        "title": item.editor_title or news.title,
        "summary": item.editor_summary or news.summary,
        "category": news.category,
        "board": insight["board"],
        "tag_line": insight["tag_line"],
        "bullet_points": insight["bullet_points"],
        "takeaway": insight["takeaway"],
        "insight_source": insight["insight_source"],
        "five_fields": {
            key: str(content.get(key) or "")
            for key in ("background", "effects", "eventSummary", "technologyAndInnovation", "valueAndImpact")
        },
        "source_url": news.source_url,
        "source_name": news_item.source_name if news_item else "",
        "score": _item_score(item),
        "is_headline": bool(getattr(item, "is_headline", False)),
        "generation_status": news.generation_status,
    }


def _group_snapshots(snapshots: list[dict[str, Any]], fmt: ReportFormat) -> list[dict[str, Any]]:
    if fmt.group_by == "none":
        return [{"key": "all", "title": "全部条目", "item_ids": [s["item_id"] for s in snapshots]}]

    key_field = "board" if fmt.group_by == "board" else "category"
    ordered_keys: list[str]
    if fmt.group_by == "board":
        present = {s[key_field] for s in snapshots}
        ordered_keys = [board for board in board_order() if board in present]
        ordered_keys += sorted(present - set(ordered_keys))
    else:
        ordered_keys = sorted({s[key_field] for s in snapshots})

    groups = []
    for key in ordered_keys:
        item_ids = [s["item_id"] for s in snapshots if s[key_field] == key]
        if item_ids:
            groups.append({"key": key, "title": key, "item_ids": item_ids})
    return groups


def render_markdown(rendition: ReportRendition) -> str:
    """对齐 周报文件/技术洞察日报-*.md 的结构。"""
    summary = rendition.summary_json or {}
    body = rendition.body_json or {}
    items: dict[str, dict[str, Any]] = body.get("items") or {}
    groups: list[dict[str, Any]] = body.get("groups") or []
    headlines: list[str] = body.get("headlines") or []
    fields: list[str] = body.get("item_fields") or []
    period_key = str(summary.get("period_key") or "")
    now_cst = datetime.now(BEIJING_TZ)

    lines: list[str] = []
    lines.append(f"# {rendition.title}")
    lines.append("")
    lines.append(f"> 报告类型：{rendition.title.split()[-1] if rendition.title else '成稿'}")
    if period_key:
        window_start = _period_window_start(rendition.report_type, period_key)
        lines.append(f"> 覆盖周期：{window_start} ~ {period_key}")
    lines.append(f"> Markdown 导出时间：{now_cst.strftime('%Y-%m-%d %H:%M:%S')} CST")
    lines.append("")
    lines.append(
        f"**生效信源：{summary.get('source_total', 0)} 个 | 本期条目：{summary.get('item_total', 0)} 条 "
        f"| 覆盖板块：{len(summary.get('group_distribution') or {})} 个**",
    )
    lines.append("")

    distribution = summary.get("group_distribution") or {}
    if distribution:
        parts = "，".join(f"{key} {count} 条" for key, count in distribution.items())
        lines.append(":::summary")
        lines.append(f"- 板块分布：{parts}，合计 {summary.get('item_total', 0)} 条。")
        headline_titles = summary.get("headline_titles") or []
        if headline_titles:
            lines.append(f"- 今日头条：{'；'.join(headline_titles[:4])}。")
        lines.append(":::")
        lines.append("")

    if headlines:
        lines.append("---")
        lines.append("")
        lines.append("## 今日头条")
        lines.append("")
        for item_id in headlines:
            snapshot = items.get(item_id)
            if snapshot:
                lines.append(f"- [{snapshot['title']}](#item-{item_id[:8]})")
                lines.append("")

    for group in groups:
        lines.append("---")
        lines.append("")
        lines.append(f"## {group['title']}")
        lines.append("")
        for index, item_id in enumerate(group.get("item_ids") or [], start=1):
            snapshot = items.get(item_id)
            if not snapshot:
                continue
            lines.append(f"### {index}、{snapshot['title']} {{#item-{item_id[:8]}}}")
            lines.append("")
            if "tag_line" in fields and snapshot.get("tag_line"):
                lines.append(" ".join(f"【{tag}】" for tag in snapshot["tag_line"]))
                lines.append("")
            if "bullet_points" in fields and snapshot.get("bullet_points"):
                bullet_text = "；".join(snapshot["bullet_points"])
                lines.append(f"📋 **要点**：{bullet_text}")
            if "takeaway" in fields and snapshot.get("takeaway"):
                lines.append(f"📌 **总结**：{snapshot['takeaway']}")
            if "summary" in fields and snapshot.get("summary"):
                lines.append(snapshot["summary"])
            if "five_fields" in fields:
                for label, key in (
                    ("背景", "background"),
                    ("事件总结", "eventSummary"),
                    ("技术和创新点", "technologyAndInnovation"),
                    ("价值和影响", "valueAndImpact"),
                    ("效果总结", "effects"),
                ):
                    value = (snapshot.get("five_fields") or {}).get(key)
                    if value:
                        lines.append(f"**{label}**：{value}")
            if "score" in fields:
                lines.append(f"推荐分：{snapshot.get('score', 0):.1f}")
            if "source_link" in fields:
                source_name = snapshot.get("source_name") or "来源"
                if snapshot.get("source_url"):
                    lines.append(f"来源：[{source_name}]({snapshot['source_url']})")
                else:
                    lines.append(f"来源：{source_name}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _period_window_start(report_type: str, period_key: str) -> str:
    if report_type == "daily":
        try:
            day = datetime.strptime(period_key, "%Y-%m-%d")
            return (day - timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            return period_key
    return period_key


def load_daily_report_for_rendition(session: Session, report_id: str) -> DailyReport | None:
    return session.scalar(
        select(DailyReport)
        .options(
            selectinload(DailyReport.items).selectinload(DailyReportItem.generated_news),
        )
        .where(DailyReport.id == report_id),
    )


def load_weekly_report(session: Session, report_id: str) -> WeeklyReport | None:
    return session.scalar(
        select(WeeklyReport)
        .options(
            selectinload(WeeklyReport.items).selectinload(WeeklyReportItem.generated_news),
        )
        .where(WeeklyReport.id == report_id),
    )
