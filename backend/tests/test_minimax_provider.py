from types import SimpleNamespace

from app.core.config import Settings
from app.llm.minimax import (
    _chat_completions_url,
    _coerce_content,
    _normalize_generation_payload,
    _parse_json_object,
)
from app.news_keywords import coerce_key_points, fallback_key_points


def test_minimax_uses_legacy_verified_chat_completions_endpoint_by_default():
    settings = Settings(
        MINIMAX_API_KEY="test-key",
        MINIMAX_BASE_URL="",
        MINIMAX_ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic",
    )

    assert _chat_completions_url(settings) == "https://api.minimaxi.com/v1/chat/completions"


def test_minimax_respects_openai_compatible_base_url():
    settings = Settings(
        MINIMAX_API_KEY="test-key",
        MINIMAX_BASE_URL="https://example.com/custom/v1",
        MINIMAX_ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic",
    )

    assert _chat_completions_url(settings) == "https://example.com/custom/v1/chat/completions"


def test_minimax_parser_repairs_model_json():
    parsed = _parse_json_object("<think>skip</think>```json\n{'title':'ok',}\n```")

    assert parsed == {"title": "ok"}


def test_minimax_content_coercion_matches_sql_required_fields():
    content = _coerce_content(
        {"eventSummary": "事件"},
        SimpleNamespace(
            source_name="Example RSS",
            source_type="rss",
            source_title="Example title",
            summary="Example summary",
            content="Example body",
        ),
        "topic_match",
    )

    assert {
        "background",
        "effects",
        "eventSummary",
        "technologyAndInnovation",
        "valueAndImpact",
        "recommendationReason",
    }.issubset(content)


def test_minimax_hoists_top_level_fields_from_nested_content():
    normalized = _normalize_generation_payload(
        {
            "content": {
                "title": "生成标题",
                "summary": "生成摘要",
                "keyPoints": "模型, 端到端, 视频生成",
                "background": "背景正文",
            },
        },
    )

    assert normalized["title"] == "生成标题"
    assert normalized["summary"] == "生成摘要"
    assert normalized["keyPoints"] == "模型, 端到端, 视频生成"
    assert normalized["content"] == {"background": "背景正文"}


def test_key_points_are_short_keywords_not_sentence_summary():
    long_sentence = (
        "STARFlow-V采用归一化流替代扩散模型作为视频生成核心架构；"
        "支持端到端学习和原生似然估计；提升模型可解释性；"
        "具备稳健的因果预测能力；适用于时序视频生成任务"
    )

    assert coerce_key_points(long_sentence) == ""
    keywords = fallback_key_points(
        SimpleNamespace(
            source_title="Apple发布STARFlow-V：基于归一化流的端到端视频生成模型",
            summary="STARFlow-V 是 Apple 机器学习团队发布的视频生成研究。",
            content="该模型讨论归一化流、扩散模型、原生似然估计和因果预测。",
        ),
        "模型",
    )
    assert "STARFlow-V" in keywords
    assert "视频生成" in keywords
    assert "归一化流" in keywords
