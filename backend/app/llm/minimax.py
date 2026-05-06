from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.models.content import NewsItem


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
        parsed = _parse_json_object(content)
    except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    allowed = list(allowed_categories)
    category = str(parsed.get("category") or fallback_category)
    if category not in allowed:
        category = fallback_category if fallback_category in allowed else allowed[0]

    title = _coerce_text(parsed.get("title")) or _trim(news_item.source_title, 80)
    summary = _coerce_text(parsed.get("summary")) or _trim(
        news_item.summary or news_item.content,
        260,
    )
    key_points = _coerce_key_points(parsed.get("keyPoints") or parsed.get("key_points"))
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
            "task": "把来源新闻改写成规划部日报条目。",
            "constraints": {
                "categoryMustBeOneOf": list(allowed_categories),
                "fallbackCategory": fallback_category,
                "language": "zh-CN",
                "doNotInventFacts": True,
                "keepSourceTraceable": True,
                "outputSchema": {
                    "category": "一级标签",
                    "title": "80 字以内中文标题",
                    "summary": "120-220 字摘要",
                    "keyPoints": ["要点 1", "要点 2", "要点 3"],
                    "content": {
                        "eventSummary": "事件概述",
                        "technologyAndInnovation": "技术与创新点",
                        "valueAndImpact": "价值、影响和规划部关注点",
                        "background": "背景和来源说明",
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
    base_url = (
        settings.minimax_base_url
        or settings.minimax_anthropic_base_url
        or "https://api.minimax.io/v1"
    ).rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if not base_url.endswith("/v1") and "/api/v1" not in base_url:
        base_url = f"{base_url}/v1"
    return f"{base_url}/chat/completions"


def _anthropic_messages_url(settings: Settings) -> str:
    base_url = settings.minimax_anthropic_base_url.rstrip("/")
    if base_url.endswith("/v1/messages"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/messages"
    return f"{base_url}/v1/messages"


def _request_completion(settings: Settings, system_prompt: str, user_prompt: str) -> str:
    if settings.minimax_anthropic_base_url and not settings.minimax_base_url:
        payload = {
            "model": settings.minimax_model,
            "max_tokens": settings.minimax_max_tokens,
            "temperature": settings.minimax_temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            response = client.post(
                _anthropic_messages_url(settings),
                headers={
                    "Authorization": f"Bearer {settings.minimax_api_key}",
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json=payload,
            )
            response.raise_for_status()
        return _anthropic_content(response.json())

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
    with httpx.Client(timeout=180.0, trust_env=False) as client:
        response = client.post(
            _chat_completions_url(settings),
            headers={
                "Authorization": f"Bearer {settings.minimax_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
    return _choice_content(response.json())


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


def _anthropic_content(data: dict[str, Any]) -> str:
    content = data["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif item.get("text"):
                    parts.append(str(item.get("text")))
        return "".join(parts)
    return str(content)


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
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("MiniMax response is not a JSON object")
    return parsed


def _strip_thinking(value: str) -> str:
    return re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL | re.IGNORECASE)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(value).split())


def _coerce_key_points(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(_coerce_text(item) for item in value if _coerce_text(item))
    return _coerce_text(value)


def _coerce_content(
    value: Any,
    news_item: NewsItem,
    recommendation_reason: str,
) -> dict[str, Any]:
    if isinstance(value, dict):
        content = {
            "eventSummary": _coerce_text(value.get("eventSummary") or value.get("event_summary")),
            "technologyAndInnovation": _coerce_text(
                value.get("technologyAndInnovation") or value.get("technology_and_innovation"),
            ),
            "valueAndImpact": _coerce_text(
                value.get("valueAndImpact") or value.get("value_and_impact"),
            ),
            "background": _coerce_text(value.get("background")),
        }
    else:
        content = {
            "eventSummary": news_item.summary or news_item.source_title,
            "technologyAndInnovation": _trim(news_item.content, 500),
            "valueAndImpact": "该信号进入日报候选，后续由管理员结合业务场景判断采信和改写。",
            "background": f"来源：{news_item.source_name}；类型：{news_item.source_type}",
        }

    for key, fallback in {
        "eventSummary": news_item.summary or news_item.source_title,
        "technologyAndInnovation": _trim(news_item.content, 500),
        "valueAndImpact": "该信号进入日报候选，后续由管理员结合业务场景判断采信和改写。",
        "background": f"来源：{news_item.source_name}；类型：{news_item.source_type}",
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
