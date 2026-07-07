"""生成 provider 分层配置解析与 OpenAI-compatible 客户端（WP3-B，WP4-B R2 修订）。

事实源：docs/backend/generation-provider-design.md；契约：
config/contracts/workspace_model.json `generation_policy`、
config/contracts/llm_providers.json（预设目录 + 凭据表）、
config/contracts/deployment_modes.json `related_env`。

分层（R2）：
0. Provider 预设目录（llm_providers.json，随代码发布，只是 UI 预填数据）；
1. 实例 env（GENERATION_* 族兜底密钥存放处，MINIMAX_* 过渡期逐字段回退）；
1.5 落库凭据 llm_provider_credentials（Fernet at rest，super_admin UI 管理）；
2. 工作台 `workspaces.config_json.generation_policy`（credential_id 指针 +
   模型名/温度/max_tokens/超时/每日预算/fallback 行为，永不含 key 明文）；
3. 单次调用 resolved 参数：credential_id 命中 → provider/base_url/key 取凭据行；
   否则实例 env 链；模型参数仍走 policy 覆盖 env。

安全不变式：key 明文只出现在请求 Authorization 头；DB 只存 Fernet 密文；
不进审计 detail、不进任何 API 响应（含错误信息）。凭据失效
（禁用/删除/解密失败）按未配置 key 降级（key_source=credential_missing），
**不回落 env**——工作台显式选了凭据，静默换 key 属于安全事故。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import REPO_ROOT, Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_GENERATION_TIMEOUT_SECONDS = 45.0
FALLBACK_BEHAVIORS = ("rule_fallback", "fail")
GENERATION_POLICY_DEFAULTS: dict[str, Any] = {
    "credential_id": None,
    "model": None,
    "temperature": None,
    "max_tokens": None,
    "timeout_seconds": None,
    "daily_generation_budget": None,
    "fallback_behavior": "rule_fallback",
}

# Provider 预设目录（generation-provider-design §8）：写死在契约 JSON、随代码
# 发布，不落库、不可被 API 修改；由 GET /api/generation/providers 原样投影。
LOCAL_LLM_PROVIDERS_CONTRACT = REPO_ROOT / "config" / "contracts" / "llm_providers.json"
MOUNTED_LLM_PROVIDERS_CONTRACT = "/config/contracts/llm_providers.json"


@lru_cache
def provider_catalog() -> tuple[dict[str, Any], ...]:
    """目录条目（按 sort_order 排序）。逐字段与契约 JSON 一致，不做二次加工。"""
    path = LOCAL_LLM_PROVIDERS_CONTRACT
    if not path.exists():
        from pathlib import Path

        path = Path(MOUNTED_LLM_PROVIDERS_CONTRACT)
    data = json.loads(path.read_text(encoding="utf-8"))
    catalog = sorted(data["catalog"], key=lambda entry: entry.get("sort_order", 0))
    return tuple(catalog)


def catalog_entry(provider_code: str) -> dict[str, Any] | None:
    for entry in provider_catalog():
        if entry["code"] == provider_code:
            return entry
    return None


def catalog_default_base_url(provider_code: str) -> str:
    entry = catalog_entry(provider_code)
    if entry is None:
        return ""
    return str(entry.get("default_base_url") or "")


PING_HARD_TIMEOUT_SECONDS = 10.0
PING_PROBE_PROMPT = "ping"
ERROR_MESSAGE_MAX_LENGTH = 200

# 测试注入点：设置为 httpx.MockTransport 后所有 provider HTTP 调用走 fixture，
# 不外呼（None = httpx 默认 transport）。
TRANSPORT: httpx.BaseTransport | None = None


@dataclass(frozen=True)
class ResolvedGenerationConfig:
    """单次生成调用的 resolved 参数（policy 非 null 字段覆盖实例默认）。

    key_source 值域（R2）：credential（落库凭据）| credential_ref（env REF）|
    env | credential_missing（policy 指了凭据但已禁用/删除/解密失败，按未配置
    降级、不回落 env）| 空串（未配置）。
    """

    enabled: bool
    provider: str
    base_url: str
    api_key: str
    key_source: str
    model: str
    max_tokens: int
    temperature: float
    timeout_seconds: float
    retry_times: int
    retry_backoff_seconds: float
    daily_generation_budget: int | None
    fallback_behavior: str
    credential_id: str | None = None
    credential_label: str | None = None

    @property
    def key_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def base_url_host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    @property
    def generated_by(self) -> str:
        return f"{self.provider}:{self.model[:48]}"[:64]


def workspace_generation_policy(workspace: Any) -> dict[str, Any]:
    """工作台 generation_policy（缺省字段补默认值；非法 fallback 值回退默认）。"""
    config_json = (getattr(workspace, "config_json", None) if workspace is not None else None) or {}
    raw = dict(config_json.get("generation_policy") or {})
    policy = dict(GENERATION_POLICY_DEFAULTS)
    for key in GENERATION_POLICY_DEFAULTS:
        if raw.get(key) is not None:
            policy[key] = raw[key]
    if policy["fallback_behavior"] not in FALLBACK_BEHAVIORS:
        policy["fallback_behavior"] = "rule_fallback"
    return policy


@dataclass(frozen=True)
class CredentialResolution:
    """凭据层解析结果（generation-provider-design §9.4 第 1 步）。"""

    provider: str | None
    base_url: str | None
    api_key: str
    key_source: str
    credential_label: str | None


def resolve_credential_for_config(
    session: Any,
    settings: Settings,
    credential_id: str,
) -> CredentialResolution:
    """credential_id 非 null 的解析：命中且解密成功取凭据行；
    已禁用/不存在/解密失败按未配置 key 降级（credential_missing），
    **不回落 env**。命中旧 secret 加密的行立即用当前 secret 重加密（幂等）。
    """
    missing = CredentialResolution(
        provider=None,
        base_url=None,
        api_key="",
        key_source="credential_missing",
        credential_label=None,
    )
    if session is None:
        # 无 DB 会话无法核对凭据——同样按未配置降级，绝不静默换用 env key。
        logger.warning(
            "generation_policy.credential_id=%s set but no DB session was provided to "
            "resolve_generation_config; degrading to credential_missing",
            credential_id,
        )
        return missing
    from sqlalchemy import select

    from app.models.llm import LlmProviderCredential

    row = session.scalar(
        select(LlmProviderCredential).where(
            LlmProviderCredential.global_id == credential_id,
            LlmProviderCredential.enabled.is_(True),
        ),
    )
    if row is None:
        return missing
    from app.core.crypto import credential_cipher

    cipher = credential_cipher(settings)
    decrypted = cipher.decrypt(row.key_encrypted)
    if decrypted.plaintext is None:
        # 丢弃旧 secret（未走轮换列表）后的定义行为：降级 + 审计（无明文），
        # 不崩溃、不删行（generation-provider-design §9.3）。
        logger.warning(
            "llm_provider_credentials %s cannot be decrypted with the current "
            "AUTH_SESSION_SECRET(S); degrading to credential_missing (re-enter the key "
            "in the UI, or restore the old secret in the AUTH_SESSION_SECRETS rotation list)",
            credential_id,
        )
        from app.auth.service import write_audit

        write_audit(
            session,
            None,
            action="generation.credential.decrypt_failed",
            object_type="llm_provider_credential",
            object_id=row.id,
            detail={
                "credential_id": row.global_id,
                "provider": row.provider,
                "label": row.label,
                "key_masked": row.key_masked,
            },
        )
        return missing
    if decrypted.stale:
        # MultiFernet 轮换：能用旧 key 解密的行自动用当前 key 重加密（幂等）。
        row.key_encrypted = cipher.encrypt(decrypted.plaintext)
        session.add(row)
    return CredentialResolution(
        provider=row.provider,
        base_url=row.base_url,
        api_key=decrypted.plaintext,
        key_source="credential",
        credential_label=row.label,
    )


def resolve_generation_config(
    settings: Settings | None = None,
    *,
    workspace: Any = None,
    policy: dict[str, Any] | None = None,
    session: Any = None,
) -> ResolvedGenerationConfig:
    """resolved 配置：凭据层（credential_id）→ 实例 env（含 MINIMAX_* 兼容回退），
    模型参数走工作台 policy 覆盖实例默认。

    兼容红线：不建凭据、credential_id=null、仅配 MINIMAX_* 时 resolved 与现状
    字节一致（generation-provider-design §10.8）。
    """
    settings = settings or get_settings()
    if policy is None:
        policy = workspace_generation_policy(workspace)
    else:
        policy = {**GENERATION_POLICY_DEFAULTS, **{k: v for k, v in policy.items() if v is not None}}
        if policy["fallback_behavior"] not in FALLBACK_BEHAVIORS:
            policy["fallback_behavior"] = "rule_fallback"

    credential_id = policy.get("credential_id")
    credential_label: str | None = None
    if credential_id:
        if session is None and workspace is not None:
            # 生成链路（recommendations/reports）传的是挂在活跃 Session 上的
            # workspace ORM 对象：直接借用其会话查凭据行，调用方无需改签名。
            try:
                from sqlalchemy.orm import object_session

                session = object_session(workspace)
            except Exception:  # pragma: no cover - 非 ORM 对象（测试桩）按无会话处理
                session = None
        resolution = resolve_credential_for_config(session, settings, str(credential_id))
        provider = resolution.provider or settings.generation_provider_effective
        base_url = resolution.base_url or settings.generation_base_url_effective
        api_key = resolution.api_key
        key_source = resolution.key_source
        credential_label = resolution.credential_label
    else:
        provider = settings.generation_provider_effective
        base_url = settings.generation_base_url_effective
        api_key = settings.generation_api_key_effective
        key_source = settings.generation_api_key_source
        credential_id = None
    if not base_url:
        # 除 custom（及别名 openai_compatible）外目录 provider 自带默认 base_url；
        # minimax 的目录默认与既有 DEFAULT_MINIMAX_BASE_URL 相同（兼容红线）。
        base_url = catalog_default_base_url(provider)

    model = str(policy.get("model") or settings.generation_model_effective)
    temperature = (
        float(policy["temperature"])
        if policy.get("temperature") is not None
        else settings.generation_temperature_effective
    )
    max_tokens = (
        int(policy["max_tokens"])
        if policy.get("max_tokens") is not None
        else settings.generation_max_tokens_effective
    )
    timeout_seconds = (
        float(policy["timeout_seconds"])
        if policy.get("timeout_seconds") is not None
        else settings.generation_timeout_seconds_effective
    )
    budget = policy.get("daily_generation_budget")
    return ResolvedGenerationConfig(
        enabled=settings.generation_enabled_effective,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        key_source=key_source,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        retry_times=settings.generation_retry_times_effective,
        retry_backoff_seconds=settings.generation_retry_backoff_seconds_effective,
        daily_generation_budget=int(budget) if budget is not None else None,
        fallback_behavior=str(policy.get("fallback_behavior") or "rule_fallback"),
        credential_id=str(credential_id) if credential_id else None,
        credential_label=credential_label,
    )


def chat_completions_url(base_url: str) -> str:
    """/chat/completions 自动补全（沿用既有 _chat_completions_url 规则）。"""
    base_url = (base_url or DEFAULT_MINIMAX_BASE_URL).rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if not base_url.endswith("/v1") and "/api/v1" not in base_url:
        base_url = f"{base_url}/v1"
    return f"{base_url}/chat/completions"


def request_chat_completion(
    config: ResolvedGenerationConfig,
    system_prompt: str,
    user_prompt: str,
    *,
    timeout_seconds: float | None = None,
) -> str:
    """向 provider 发一次 chat/completions；529 按 retry 配置退避重试。

    payload 的 model/temperature/max_tokens 一律来自 resolved 配置
    （工作台 generation_policy 覆盖实例默认的落点）。
    """
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream": False,
    }
    retry_times = max(config.retry_times, 1)
    request_timeout = max(float(timeout_seconds or config.timeout_seconds), 5.0)
    with httpx.Client(timeout=request_timeout, trust_env=False, transport=TRANSPORT) as client:
        for attempt in range(1, retry_times + 1):
            response = client.post(
                chat_completions_url(config.base_url),
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code == 529 and attempt < retry_times:
                time.sleep(config.retry_backoff_seconds * attempt)
                continue
            response.raise_for_status()
            return choice_content(response.json())
    raise RuntimeError("Generation completion request did not return a response")


def choice_content(data: dict[str, Any]) -> str:
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


@dataclass(frozen=True)
class GenerationPingResult:
    """ping 结果：所有字段可安全展示/审计（不含 key、不含请求头）。"""

    status: str
    provider: str
    model: str
    base_url_host: str
    key_configured: bool
    latency_ms: int | None
    error_code: str | None
    error_message: str | None


def _sanitize_error_message(message: str, config: ResolvedGenerationConfig) -> str:
    text = " ".join(str(message).split())
    if config.api_key:
        text = text.replace(config.api_key, "[REDACTED]")
    return text[:ERROR_MESSAGE_MAX_LENGTH]


def ping_generation_provider(config: ResolvedGenerationConfig) -> GenerationPingResult:
    """最小连通性探针：max_tokens=1、硬超时 10s、不落任何业务表。

    分类报错：key_missing（不外呼）/ dns_or_connect_failed / auth_failed /
    timeout / http_{status} / bad_response。
    """

    def _result(
        status: str,
        *,
        latency_ms: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> GenerationPingResult:
        return GenerationPingResult(
            status=status,
            provider=config.provider,
            model=config.model,
            base_url_host=config.base_url_host,
            key_configured=config.key_configured,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
        )

    if not config.key_configured:
        return _result(
            "error",
            error_code="key_missing",
            error_message=(
                "Generation API key is not configured "
                "(register a credential in the UI or set it in the instance env)."
            ),
        )

    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": PING_PROBE_PROMPT}],
        "temperature": 0,
        "max_tokens": 1,
        "stream": False,
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=PING_HARD_TIMEOUT_SECONDS,
            trust_env=False,
            transport=TRANSPORT,
        ) as client:
            response = client.post(
                chat_completions_url(config.base_url),
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException as exc:
        return _result(
            "error",
            error_code="timeout",
            error_message=_sanitize_error_message(str(exc) or "request timed out", config),
        )
    except httpx.TransportError as exc:
        return _result(
            "error",
            error_code="dns_or_connect_failed",
            error_message=_sanitize_error_message(str(exc) or "connect failed", config),
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code in (401, 403):
        return _result(
            "error",
            latency_ms=latency_ms,
            error_code="auth_failed",
            error_message=f"provider answered HTTP {response.status_code}",
        )
    if response.status_code >= 400:
        return _result(
            "error",
            latency_ms=latency_ms,
            error_code=f"http_{response.status_code}",
            error_message=f"provider answered HTTP {response.status_code}",
        )
    try:
        content = choice_content(response.json())
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return _result(
            "error",
            latency_ms=latency_ms,
            error_code="bad_response",
            error_message=_sanitize_error_message(str(exc) or "unexpected response shape", config),
        )
    if not isinstance(content, str):
        return _result(
            "error",
            latency_ms=latency_ms,
            error_code="bad_response",
            error_message="unexpected response shape",
        )
    return _result("ok", latency_ms=latency_ms)
