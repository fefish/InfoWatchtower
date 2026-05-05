from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_session_token(user_id: str, secret: str, ttl_seconds: int) -> str:
    if not secret:
        raise ValueError("AUTH_SESSION_SECRET is required")

    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64encode(payload_text)
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256)
    return f"{payload_part}.{_b64encode(signature.digest())}"


def verify_session_token(token: str | None, secret: str) -> dict[str, Any] | None:
    if not token or not secret or "." not in token:
        return None

    payload_part, signature_part = token.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256)
    if not hmac.compare_digest(_b64encode(expected.digest()), signature_part):
        return None

    try:
        payload = json.loads(_b64decode(payload_part))
    except (ValueError, json.JSONDecodeError):
        return None

    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload if isinstance(payload.get("sub"), str) else None
