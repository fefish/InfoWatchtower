from __future__ import annotations

from typing import Any

SECRET_LIKE_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "cookie",
    "authorization",
    "api_key",
    ".env",
    "client_secret",
    "session",
)
REDACTED_VALUE = "[REDACTED]"


def contains_secret_like_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if is_secret_like_key(key):
                return True
            if contains_secret_like_key(nested):
                return True
    if isinstance(value, list):
        return any(contains_secret_like_key(item) for item in value)
    return False


def redact_secret_like_values(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            text_key = str(key)
            redacted[text_key] = REDACTED_VALUE if is_secret_like_key(text_key) else redact_secret_like_values(nested)
        return redacted
    if isinstance(value, list):
        return [redact_secret_like_values(item) for item in value]
    return value


def is_secret_like_key(key: Any) -> bool:
    key_lower = str(key).lower()
    return any(part in key_lower for part in SECRET_LIKE_KEY_PARTS)
