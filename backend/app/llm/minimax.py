from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import json_repair

from app.core.config import Settings, get_settings
from app.models.content import NewsItem
from app.news_keywords import coerce_key_points, fallback_key_points

DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
SQL_EFFECTS_FALLBACK = (
    "该信号可能影响规划部对技术路线、产品节奏、竞争态势或内部需求转化的"
    "后续判断，需要结合业务场景继续观察。"
)
CATEGORY_ALIASES = {
    "AI Agent": "智能体",
    "AI应用": "AI 应用",
    "AI 智能体": "智能体",
    "AI智能体": "智能体",
}


@dataclass(frozen=True)
class GeneratedNewsDraft:
    category: str
    title: str
    summary: str
    key_points: str
    content_json: dict[str, Any]
    generated_by: str


def generate_news_with_minimax(
    news_item: NewsItem,
    *,
    fallback_category: str,
    allowed_categories: Sequence[str],
    recommendation_reason: str,
    settings: Settings | None = None,
) -> GeneratedNewsDraft | None:
    settings = settings or get_settings()
    if not settings.minimax_generation_enabled or not settings.minimax_api_key:
        return None

    system_prompt = (
        "你是产业情报日报编辑。只输出一个 JSON 对象，不要 markdown，"
        "不要解释。字段必须适合直接写入 generated_news。"
    )
    user_prompt = _build_user_prompt(
        news_item=news_item,
        fallback_category=fallback_category,
        allowed_categories=allowed_categories,
        recommendation_reason=recommendation_reason,
    )
    try:
        content = _request_completion(settings, system_prompt, user_prompt)
        parsed = _normalize_generation_payload(_parse_json_object(content))
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    allowed = list(allowed_categories)
    category = str(parsed.get("category") or fallback_category)
    category = CATEGORY_ALIASES.get(category, category)
    if category not in allowed:
        category = _category_fallback(news_item, fallback_category, allowed)

    title = _coerce_text(parsed.get("title")) or _trim(news_item.source_title, 80)
    summary = _coerce_text(parsed.get("summary")) or _trim(
        news_item.summary or news_item.content,
        260,
    )
    key_points = coerce_key_points(parsed.get("keyPoints") or parsed.get("key_points"))
    if not key_points:
        key_points = fallback_key_points(news_item, category)
    content_json = _coerce_content(parsed.get("content"), news_item, recommendation_reason)
    model_name = settings.minimax_model[:48]
    return GeneratedNewsDraft(
        category=category,
        title=title,
        summary=summary,
        key_points=key_points,
        content_json=content_json,
        generated_by=f"minimax:{model_name}"[:64],
    )


def _build_user_prompt(
    *,
    news_item: NewsItem,
    fallback_category: str,
    allowed_categories: Sequence[str],
    recommendation_reason: str,
) -> str:
    content = _trim(news_item.content or news_item.summary or "", 5000)
    return json.dumps(
        {
            "task": "把来源新闻改写成公司内网 SQL 兼容的规划部日报条目。",
            "constraints": {
                "categoryMustBeOneOf": list(allowed_categories),
                "fallbackCategory": fallback_category,
                "language": "zh-CN",
                "doNotInventFacts": True,
                "keepSourceTraceable": True,
                "requiredForCompanySql": True,
                "outputSchema": {
                    "category": "一级标签",
                    "title": "80 字以内中文标题",
                    "summary": "3-4 句业务洞察摘要，避免一句话带过",
                    "keyPoints": "4-6 个核心关键词，用逗号分隔",
                    "sourceUrl": "原文 URL",
                    "content": {
                        "background": "对应「背景」，不少于 180 字，说明背景、来源语境和问题成因",
                        "effects": "对应「效果总结」，不少于 220 字，说明短中期外部影响、组织影响或产业变化",
                        "eventSummary": "对应「事件总结」，不少于 180 字，概括事件本身、涉及主体和关键进展",
                        "technologyAndInnovation": (
                            "对应「技术和创新点总结」，不少于 320 字，说明技术路线、创新点、工程实现或差异化"
                        ),
                        "valueAndImpact": "对应「价值和影响」，不少于 260 字，说明长期价值、应用潜力、风险和规划判断",
                    },
                },
            },
            "source": {
                "title": news_item.source_title,
                "url": news_item.source_url or news_item.canonical_url,
                "sourceName": news_item.source_name,
                "sourceType": news_item.source_type,
                "publishedAt": news_item.published_at.isoformat() if news_item.published_at else "",
                "summary": news_item.summary,
                "content": content,
                "recommendationReason": recommendation_reason,
            },
        },
        ensure_ascii=False,
    )


def _chat_completions_url(settings: Settings) -> str:
    base_url = (settings.minimax_base_url or DEFAULT_MINIMAX_BASE_URL).rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if not base_url.endswith("/v1") and "/api/v1" not in base_url:
        base_url = f"{base_url}/v1"
    return f"{base_url}/chat/completions"


def _request_completion(settings: Settings, system_prompt: str, user_prompt: str) -> str:
    payload = {
        "model": settings.minimax_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": settings.minimax_temperature,
        "max_tokens": settings.minimax_max_tokens,
        "stream": False,
    }
    retry_times = max(settings.minimax_retry_times, 1)
    with httpx.Client(timeout=180.0, trust_env=False) as client:
        for attempt in range(1, retry_times + 1):
            response = client.post(
                _chat_completions_url(settings),
                headers={
                    "Authorization": f"Bearer {settings.minimax_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code == 529 and attempt < retry_times:
                time.sleep(settings.minimax_retry_backoff_seconds * attempt)
                continue
            response.raise_for_status()
            return _choice_content(response.json())
    raise RuntimeError("MiniMax completion request did not return a response")


def _choice_content(data: dict[str, Any]) -> str:
    message = data["choices"][0]["message"]["content"]
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = []
        for item in message:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                parts.append(str(text))
        return "".join(parts)
    return str(message)


def _parse_json_object(value: str) -> dict[str, Any]:
    text = _strip_thinking(value).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start : end + 1]
    parsed = json_repair.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("MiniMax response is not a JSON object")
    return parsed


def _normalize_generation_payload(parsed: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parsed)
    raw_content = normalized.get("content")
    if not isinstance(raw_content, dict):
        return normalized

    content = dict(raw_content)
    for key in (
        "category",
        "title",
        "summary",
        "keyPoints",
        "key_points",
        "sourceUrl",
        "source_url",
        "created",
    ):
        if not normalized.get(key) and content.get(key):
            normalized[key] = content.get(key)
        content.pop(key, None)
    normalized["content"] = content
    return normalized


def _strip_thinking(value: str) -> str:
    return re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL | re.IGNORECASE)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(value).split())


def _category_fallback(news_item: NewsItem, fallback_category: str, allowed: list[str]) -> str:
    text = f"{news_item.source_title} {news_item.summary} {news_item.content}".lower()
    if "智能体" in allowed and any(token in text for token in ("agent", "agents", "智能体")):
        return "智能体"
    if fallback_category in allowed:
        return fallback_category
    return allowed[0]


def _coerce_content(
    value: Any,
    news_item: NewsItem,
    recommendation_reason: str,
) -> dict[str, Any]:
    if isinstance(value, dict):
        content = {
            "background": _coerce_text(value.get("background")),
            "effects": _coerce_text(value.get("effects")),
            "eventSummary": _coerce_text(value.get("eventSummary") or value.get("event_summary")),
            "technologyAndInnovation": _coerce_text(
                value.get("technologyAndInnovation") or value.get("technology_and_innovation"),
            ),
            "valueAndImpact": _coerce_text(
                value.get("valueAndImpact") or value.get("value_and_impact"),
            ),
        }
    else:
        content = {
            "background": f"来源：{news_item.source_name}；类型：{news_item.source_type}",
            "effects": SQL_EFFECTS_FALLBACK,
            "eventSummary": news_item.summary or news_item.source_title,
            "technologyAndInnovation": _trim(news_item.content, 500),
            "valueAndImpact": "该信号进入日报候选，后续由管理员结合业务场景判断采信和改写。",
        }

    for key, fallback in {
        "background": f"来源：{news_item.source_name}；类型：{news_item.source_type}",
        "effects": SQL_EFFECTS_FALLBACK,
        "eventSummary": news_item.summary or news_item.source_title,
        "technologyAndInnovation": _trim(news_item.content, 500),
        "valueAndImpact": "该信号进入日报候选，后续由管理员结合业务场景判断采信和改写。",
    }.items():
        if not content.get(key):
            content[key] = fallback
    content["recommendationReason"] = recommendation_reason
    return content


def _trim(value: str | None, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."
