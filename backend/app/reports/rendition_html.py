"""技术洞察成稿的自包含 HTML 导出。

版式对齐 周报文件/技术洞察日报-*.html 的阅读结构：
头部信息 → 摘要块 → 今日头条锚点 → 板块分组 → 条目（标签行/要点/总结/来源）。
单文件内联样式，便于直接挂内网静态页。
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from app.models.reports import ReportRendition

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

_HTML_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 16px 80px;
  background: #f5f7fb;
  color: #1d1d1f;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif;
  line-height: 1.7;
}
.page { max-width: 860px; margin: 0 auto; }
h1 { font-size: 26px; letter-spacing: -0.02em; margin: 0 0 6px; }
.meta { color: #6e6e73; font-size: 13px; margin: 0 0 4px; }
.stats { font-weight: 700; margin: 14px 0; }
.summary-box {
  border: 1px solid rgba(10, 132, 255, 0.25);
  border-left: 4px solid #0a84ff;
  border-radius: 10px;
  background: rgba(10, 132, 255, 0.05);
  padding: 14px 18px;
  margin: 18px 0 26px;
  font-size: 14px;
}
.summary-box p { margin: 6px 0; }
h2 {
  font-size: 19px;
  margin: 38px 0 14px;
  padding-bottom: 8px;
  border-bottom: 2px solid #e4e8f0;
}
.headlines { margin: 0; padding-left: 22px; }
.headlines li { margin: 6px 0; }
.headlines a { color: #0a84ff; text-decoration: none; font-weight: 600; }
.item {
  border: 1px solid #e4e8f0;
  border-radius: 12px;
  background: #ffffff;
  padding: 18px 20px;
  margin: 14px 0;
}
.item h3 { margin: 0 0 8px; font-size: 16px; line-height: 1.5; }
.tags { margin: 0 0 10px; }
.tag {
  display: inline-block;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.08);
  color: #0066d6;
  padding: 2px 10px;
  margin: 0 6px 6px 0;
  font-size: 12px;
  font-weight: 600;
}
.block { margin: 8px 0; font-size: 14px; }
.block strong { color: #1d1d1f; }
.source { margin-top: 10px; font-size: 13px; color: #6e6e73; }
.source a { color: #0a84ff; text-decoration: none; word-break: break-all; }
.footer { margin-top: 44px; color: #98989d; font-size: 12px; text-align: center; }
"""


def render_html(rendition: ReportRendition) -> str:
    summary = rendition.summary_json or {}
    body = rendition.body_json or {}
    items: dict[str, dict[str, Any]] = body.get("items") or {}
    groups: list[dict[str, Any]] = body.get("groups") or []
    headlines: list[str] = body.get("headlines") or []
    fields: list[str] = body.get("item_fields") or []
    now_cst = datetime.now(BEIJING_TZ)

    parts: list[str] = []
    parts.append(f"<h1>{escape(rendition.title)}</h1>")
    parts.append(f"<p class='meta'>导出时间：{now_cst.strftime('%Y-%m-%d %H:%M:%S')} CST（Asia/Shanghai）</p>")
    parts.append(
        "<p class='stats'>生效信源：{sources} 个 | 本期条目：{total} 条 | 覆盖板块：{boards} 个</p>".format(
            sources=summary.get("source_total", 0),
            total=summary.get("item_total", 0),
            boards=len(summary.get("group_distribution") or {}),
        ),
    )

    distribution = summary.get("group_distribution") or {}
    if distribution:
        dist_text = "，".join(f"{escape(str(key))} {count} 条" for key, count in distribution.items())
        headline_titles = summary.get("headline_titles") or []
        parts.append("<div class='summary-box'>")
        parts.append(f"<p><strong>板块分布：</strong>{dist_text}，合计 {summary.get('item_total', 0)} 条。</p>")
        if headline_titles:
            parts.append(
                "<p><strong>今日头条：</strong>"
                + "；".join(escape(str(title)) for title in headline_titles[:4])
                + "。</p>",
            )
        parts.append("</div>")

    if headlines:
        parts.append("<h2>今日头条</h2>")
        parts.append("<ol class='headlines'>")
        for item_id in headlines:
            snapshot = items.get(item_id)
            if snapshot:
                parts.append(
                    f"<li><a href='#item-{escape(item_id[:8])}'>{escape(str(snapshot['title']))}</a></li>",
                )
        parts.append("</ol>")

    for group in groups:
        parts.append(f"<h2>{escape(str(group['title']))}</h2>")
        for item_id in group.get("item_ids") or []:
            snapshot = items.get(item_id)
            if not snapshot:
                continue
            parts.append(f"<article class='item' id='item-{escape(item_id[:8])}'>")
            parts.append(f"<h3>{escape(str(snapshot['title']))}</h3>")
            if "tag_line" in fields and snapshot.get("tag_line"):
                tags = "".join(f"<span class='tag'>{escape(str(tag))}</span>" for tag in snapshot["tag_line"])
                parts.append(f"<p class='tags'>{tags}</p>")
            if "bullet_points" in fields and snapshot.get("bullet_points"):
                bullets = "；".join(escape(str(point)) for point in snapshot["bullet_points"])
                parts.append(f"<p class='block'>📋 <strong>要点</strong>：{bullets}</p>")
            if "takeaway" in fields and snapshot.get("takeaway"):
                parts.append(f"<p class='block'>📌 <strong>总结</strong>：{escape(str(snapshot['takeaway']))}</p>")
            if "summary" in fields and snapshot.get("summary"):
                parts.append(f"<p class='block'>{escape(str(snapshot['summary']))}</p>")
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
                        parts.append(f"<p class='block'><strong>{label}</strong>：{escape(str(value))}</p>")
            if "score" in fields:
                parts.append(f"<p class='block'>推荐分：{float(snapshot.get('score') or 0):.1f}</p>")
            if "source_link" in fields:
                source_name = escape(str(snapshot.get("source_name") or "来源"))
                if snapshot.get("source_url"):
                    url = escape(str(snapshot["source_url"]))
                    parts.append(f"<p class='source'>来源：<a href='{url}' target='_blank'>{source_name}</a></p>")
                else:
                    parts.append(f"<p class='source'>来源：{source_name}</p>")
            parts.append("</article>")

    parts.append("<p class='footer'>InfoWatchtower · 一次采信，多版成稿</p>")

    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'><title>{escape(rendition.title)}</title>"
        f"<style>{_HTML_STYLE}</style></head><body><main class='page'>" + "".join(parts) + "</main></body></html>"
    )
