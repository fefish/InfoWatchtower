from app.core.config import Settings
from app.llm.minimax import _chat_completions_url, _parse_json_object


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
