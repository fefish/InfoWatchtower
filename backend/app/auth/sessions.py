from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Iterable
from typing import Any


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_session_token(
    user_id: str,
    secret: str,
    ttl_seconds: int,
    session_version: str | None = None,
) -> str:
    if not secret:
        raise ValueError("AUTH_SESSION_SECRET is required")

    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    if session_version:
        payload["sv"] = session_version
    payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64encode(payload_text)
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256)
    return f"{payload_part}.{_b64encode(signature.digest())}"


def verify_session_token(
    token: str | None,
    secret: str | Iterable[str],
) -> dict[str, Any] | None:
    """验签 session token。

    secret 支持单值或多值（AUTH_SESSION_SECRETS 轮换语义：第一个用于签名、
    全部可验签）；任一 secret 验签通过即有效，换密钥不再全员掉线——
    旧 secret 签的 cookie 在其仍在列表中时保持有效，移出列表后失效。
    """
    secrets = [secret] if isinstance(secret, str) else [item for item in secret if item]
    secrets = [item for item in secrets if item]
    if not token or not secrets or "." not in token:
        return None

    payload_part, signature_part = token.split(".", 1)
    for candidate in secrets:
        expected = hmac.new(
            candidate.encode("utf-8"),
            payload_part.encode("ascii"),
            hashlib.sha256,
        )
        if hmac.compare_digest(_b64encode(expected.digest()), signature_part):
            break
    else:
        return None

    try:
        payload = json.loads(_b64decode(payload_part))
    except (ValueError, json.JSONDecodeError):
        return None

    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload if isinstance(payload.get("sub"), str) else None
