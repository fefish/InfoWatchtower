from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol


class NewsKeywordSource(Protocol):
    source_title: str
    summary: str
    content: str


KEYWORD_SPLIT_RE = re.compile(r"[，,；;、。.!?\n]+")
ENGLISH_TERM_RE = re.compile(r"\b[A-Z][A-Za-z0-9][A-Za-z0-9+._:-]{1,}\b")
NOISE_KEYWORDS = {
    "canonical_url",
    "page_manual",
    "page_monitor",
    "paper_rss",
    "rss",
    "source",
    "url",
    "wiseflow",
}
LONG_PHRASE_MARKERS = (
    "采用",
    "作为",
    "支持",
    "提升",
    "具备",
    "适用于",
    "发布",
    "推出",
    "通过",
    "实现",
    "提供",
    "能够",
    "旨在",
    "面向",
    "解决",
    "说明",
    "影响",
    "带来",
    "成为",
)
KEYWORD_HINTS = (
    "AI Infra",
    "AI 应用",
    "测评技术",
    "大厂动态",
    "模型",
    "算法",
    "推理加速",
    "训练技术",
    "智能体",
    "基础竞争力",
    "工具新功能",
    "工具新案例",
    "工具新技术",
    "视频生成",
    "端到端",
    "归一化流",
    "扩散模型",
    "原生似然估计",
    "因果预测",
    "多模态",
    "模型评估",
    "基准测试",
    "Agent",
    "Cursor",
    "Claude Code",
    "OpenCode",
    "Codex",
)


def coerce_key_points(value: object) -> str:
    parts: list[str] = []
    if isinstance(value, Iterable) and not isinstance(value, str | bytes | dict):
        for item in value:
            parts.extend(_split_candidate(item))
    else:
        parts.extend(_split_candidate(value))
    return ", ".join(_unique_keywords(parts)[:6])


def fallback_key_points(news_item: NewsKeywordSource, category: str) -> str:
    text_parts = [
        news_item.source_title or "",
        news_item.summary or "",
        news_item.content or "",
    ]
    full_text = " ".join(text_parts)
    full_text_lower = full_text.lower()
    candidates: list[str] = [category]

    for text in text_parts:
        for match in ENGLISH_TERM_RE.finditer(text):
            candidates.append(match.group(0))

    for hint in KEYWORD_HINTS:
        if hint.lower() in full_text_lower:
            candidates.append(hint)

    return ", ".join(_unique_keywords(candidates)[:6])


def _split_candidate(value: object) -> list[str]:
    if value is None:
        return []
    text = " ".join(str(value).split())
    return [part.strip() for part in KEYWORD_SPLIT_RE.split(text) if part.strip()]


def _unique_keywords(candidates: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for candidate in candidates:
        keyword = " ".join(str(candidate).split()).strip(" -_|")
        key = keyword.lower()
        if not keyword or key in seen or key in NOISE_KEYWORDS:
            continue
        if not _is_keyword_like(keyword):
            continue
        seen.add(key)
        keywords.append(keyword)
    return keywords


def _is_keyword_like(keyword: str) -> bool:
    if len(keyword) > 32:
        return False
    if keyword.count(" ") >= 5:
        return False
    if len(keyword) >= 7 and any(marker in keyword for marker in LONG_PHRASE_MARKERS):
        return False
    return True
