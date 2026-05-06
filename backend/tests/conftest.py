import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def disable_external_llm_calls(monkeypatch):
    monkeypatch.setenv("MINIMAX_GENERATION_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
