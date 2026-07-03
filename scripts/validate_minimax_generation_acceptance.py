#!/usr/bin/env python3
"""Run MiniMax generation acceptance for SQL-ready and tech-insight drafts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_OUTPUT_JSON = ROOT / "outputs/minimax/minimax_generation_acceptance.json"
NEWS_CATEGORIES_PATH = ROOT / "config/taxonomy/news_categories.json"
REQUIRED_CONTENT_FIELDS = (
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-response-json", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)

    errors: list[str] = []
    try:
        result = run_acceptance(
            fixture_response_path=args.fixture_response_json,
            output_path=args.output_json,
            timeout_seconds=args.timeout_seconds,
        )
    except AcceptanceFailure as exc:
        result = exc.result
        errors = exc.errors
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        result = {"error": str(exc)}
        errors = [str(exc)]

    payload = {"status": "failed" if errors else "passed", **result}
    if errors:
        payload["errors"] = errors
    _write_json(args.output_json, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 1 if errors else 0


def run_acceptance(
    *,
    fixture_response_path: Path | None,
    output_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    from app.core.config import Settings

    allowed_categories = _load_allowed_categories()
    settings = Settings()
    fixture_response = fixture_response_path.read_text(encoding="utf-8") if fixture_response_path else None
    if fixture_response is None and (not settings.minimax_generation_enabled or not settings.minimax_api_key):
        raise AcceptanceFailure(
            ["set MINIMAX_GENERATION_ENABLED=true and MINIMAX_API_KEY, or pass --fixture-response-json"],
            {"mode": "live"},
        )
    from app.llm import minimax as minimax_module

    request_diagnostics: dict[str, Any] = {}
    if fixture_response is not None:
        settings = Settings(
            MINIMAX_GENERATION_ENABLED=True,
            MINIMAX_API_KEY="fixture-key",
            MINIMAX_MODEL="MiniMax-fixture",
        )
        original_request_completion = minimax_module._request_completion
        minimax_module._request_completion = lambda *_args, **_kwargs: fixture_response
    else:
        original_request_completion = minimax_module._request_completion

        def _diagnostic_request_completion(*request_args: Any, **request_kwargs: Any) -> str:
            try:
                content = original_request_completion(*request_args, **request_kwargs)
            except Exception as exc:
                request_diagnostics.update(_request_error_diagnostics(exc))
                raise
            response_path = output_path.with_suffix(".response.txt")
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(content, encoding="utf-8")
            request_diagnostics.update(
                {
                    "request_completed": True,
                    "response_chars": len(content),
                    "response_preview": _trim_for_diagnostics(content),
                    "response_path": str(response_path),
                },
            )
            return content

        minimax_module._request_completion = _diagnostic_request_completion

    try:
        draft = minimax_module.generate_news_with_minimax(
            _sample_news_item(),
            fallback_category="模型",
            allowed_categories=allowed_categories,
            recommendation_reason=(
                "admission=P0; pool=technical_signal; content_value=architecture_and_engineering_evidence"
            ),
            settings=settings,
            timeout_seconds=timeout_seconds,
        )
    finally:
        if original_request_completion is not None:
            minimax_module._request_completion = original_request_completion

    result: dict[str, Any] = {
        "mode": "fixture" if fixture_response is not None else "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.minimax_model,
        "endpoint_configured": bool(settings.minimax_base_url),
    }
    if request_diagnostics:
        result["request_diagnostics"] = request_diagnostics
    if draft is None:
        raise AcceptanceFailure(
            ["MiniMax generation returned no ready draft; check API key, endpoint and model output quality"],
            result,
        )

    draft_payload = asdict(draft)
    errors = _validate_draft(draft_payload, allowed_categories)
    result.update(
        {
            "category": draft.category,
            "generated_by": draft.generated_by,
            "content_fields": list(draft.content_json.keys()),
            "insight_fields": list(draft.insight_json.keys()),
            "draft": draft_payload,
        },
    )
    _write_json(output_path, {"status": "failed" if errors else "passed", **result, "errors": errors})
    if errors:
        raise AcceptanceFailure(errors, result)
    return result


class AcceptanceFailure(Exception):
    def __init__(self, errors: list[str], result: dict[str, Any]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors
        self.result = result


def _validate_draft(draft: dict[str, Any], allowed_categories: list[str]) -> list[str]:
    errors: list[str] = []
    if draft.get("category") not in allowed_categories:
        errors.append(f"category must be one of configured categories: {draft.get('category')}")
    if not str(draft.get("generated_by") or "").startswith("minimax:"):
        errors.append("generated_by must start with minimax:")

    content = draft.get("content_json") if isinstance(draft.get("content_json"), dict) else {}
    for field in REQUIRED_CONTENT_FIELDS:
        text = _text(content.get(field))
        if _cjk_count(text) < 40:
            errors.append(f"content_json.{field} is too short or missing")
    body = "\n".join([_text(draft.get("summary")), _text(draft.get("key_points"))])
    body += "\n" + "\n".join(_text(content.get(field)) for field in REQUIRED_CONTENT_FIELDS)
    if re.search(r"<(?:script|span|style|iframe)\b", body, flags=re.IGNORECASE):
        errors.append("generated text contains disallowed HTML/script markup")
    if _cjk_count(body) < 260:
        errors.append("generated body does not contain enough Chinese planning-intel content")
    unsupported_numbers = _unsupported_numeric_claims(body, _sample_source_text())
    if unsupported_numbers:
        errors.append(
            "generated text contains numeric claims not present in source: "
            + ", ".join(unsupported_numbers[:8]),
        )

    key_points = [_text(item) for item in re.split(r"[，,、;；]", _text(draft.get("key_points"))) if _text(item)]
    if not 3 <= len(key_points) <= 8:
        errors.append("key_points must contain 3-8 short keyword phrases")
    if any(_cjk_count(item) > 24 for item in key_points):
        errors.append("key_points contains a sentence-like phrase")

    insight = draft.get("insight_json") if isinstance(draft.get("insight_json"), dict) else {}
    if not _text(insight.get("board")):
        errors.append("insight_json.board is required for tech-insight rendition")
    bullets = insight.get("bullet_points") if isinstance(insight.get("bullet_points"), list) else []
    if len([item for item in bullets if _cjk_count(_text(item)) >= 12]) < 3:
        errors.append("insight_json.bullet_points must contain at least 3 useful bullets")
    if _cjk_count(_text(insight.get("takeaway"))) < 50:
        errors.append("insight_json.takeaway is too short")
    tag_line = insight.get("tag_line") if isinstance(insight.get("tag_line"), list) else []
    if len([item for item in tag_line if _text(item)]) < 2:
        errors.append("insight_json.tag_line must contain at least 2 tags")
    return errors


def _sample_news_item():
    from app.models.content import NewsItem

    return NewsItem(
        raw_item_id="acceptance-raw",
        data_source_id="acceptance-source",
        source_type="rss",
        source_name="MiniMax acceptance sample",
        source_url="https://example.com/minimax-acceptance",
        canonical_url="https://example.com/minimax-acceptance",
        source_title="Example AI lab releases a sparse MoE inference runtime for long-context agents",
        normalized_title="example-ai-lab-sparse-moe-runtime",
        summary=(
            "Example AI Lab released a sparse MoE inference runtime for long-context agent workloads. "
            "The public note describes scheduler changes, KV-cache paging, tool-call batching, and "
            "latency measurements on multi-GPU clusters."
        ),
        content=(
            "Example AI Lab 发布的技术说明介绍了面向长上下文智能体的稀疏 MoE 推理运行时。"
            "该运行时把请求调度、专家路由、KV-cache 分页和工具调用批处理放在统一队列中，"
            "在多 GPU 集群上降低尾延迟，并减少长会话在检索和函数调用阶段的显存浪费。"
            "材料还说明了兼容 OpenAI 风格接口、保留观测指标、支持灰度回滚和跨节点负载均衡。"
        ),
        published_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        focus_id=1,
        dedupe_key="example-ai-lab-sparse-moe-runtime",
        active=True,
    )


def _sample_source_text() -> str:
    item = _sample_news_item()
    return " ".join(
        [
            item.source_title or "",
            item.summary or "",
            item.content or "",
            item.published_at.isoformat() if item.published_at else "",
        ],
    )


def _load_allowed_categories() -> list[str]:
    data = json.loads(NEWS_CATEGORIES_PATH.read_text(encoding="utf-8"))
    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        raise AcceptanceFailure(["config/taxonomy/news_categories.json has no categories"], {})
    return [str(item) for item in categories]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _request_error_diagnostics(exc: Exception) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "request_completed": False,
        "exception_type": type(exc).__name__,
        "exception_message": _trim_for_diagnostics(str(exc), limit=500),
    }
    response = getattr(exc, "response", None)
    if response is not None:
        diagnostics["status_code"] = getattr(response, "status_code", None)
        diagnostics["response_preview"] = _trim_for_diagnostics(getattr(response, "text", ""), limit=500)
    return diagnostics


def _trim_for_diagnostics(value: str, *, limit: int = 300) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cjk_count(value: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", value))


def _unsupported_numeric_claims(body: str, source_text: str) -> list[str]:
    source = _normalize_numeric_source(source_text)
    claims = []
    patterns = (
        r"\bP\d{2,3}\b",
        r"\d+(?:\.\d+)?\s*(?:%|％|倍|x|X|ms|毫秒|秒|GB|MB|tokens?|Tokens?)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, body):
            claim = match.group(0).strip()
            if _normalize_numeric_source(claim) not in source:
                claims.append(claim)
    return list(dict.fromkeys(claims))


def _normalize_numeric_source(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


if __name__ == "__main__":
    raise SystemExit(main())
