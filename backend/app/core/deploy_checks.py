"""部署形态启动自检：非法组合必须 fail-fast（RuntimeError），不是 warning。

规则清单与 config/contracts/deployment_modes.json 的 startup_failfast_rules 一一对应，
API（app/main.py）、scheduler、worker 三个进程入口都必须调用。
"""

from __future__ import annotations

import logging

from app.core.config import (
    DEPLOY_MODES,
    GENERATION_PROVIDERS,
    KNOWN_INGESTION_SOURCE_TYPES,
    MODE_ALLOWED_AUTH_MODES,
    Settings,
)
from app.core.security import trusted_proxy_networks

logger = logging.getLogger(__name__)


def validate_deploy_settings(settings: Settings) -> None:
    if settings.deploy_mode not in DEPLOY_MODES:
        raise RuntimeError(
            f"DEPLOY_MODE must be one of {', '.join(DEPLOY_MODES)}; "
            f"got {settings.deploy_mode!r}.",
        )
    # 契约 modes.*.allowed_auth_modes：每形态只允许声明的登录方式。
    # 尤其是 cloud/extranet 等公网形态配 intranet_header 等于开放请求头伪造登录，必须拒启。
    allowed_auth_modes = MODE_ALLOWED_AUTH_MODES[settings.deploy_mode]
    if settings.auth_mode not in allowed_auth_modes:
        raise RuntimeError(
            f"DEPLOY_MODE={settings.deploy_mode} requires AUTH_MODE in "
            f"[{', '.join(allowed_auth_modes)}]; got AUTH_MODE={settings.auth_mode!r}.",
        )
    # 所有 auth_mode（local/public_password/oidc/intranet_header）都会签发签名 session cookie，
    # 缺 secret 不能拖到运行期每请求 500，必须启动时失败。
    # 口径：AUTH_SESSION_SECRET / AUTH_SESSION_SECRETS（轮换列表）任一非空即可
    # （auth_session_secret_list 已聚合两者）。
    if not settings.auth_session_secret_list:
        raise RuntimeError(
            f"AUTH_SESSION_SECRET is required for AUTH_MODE={settings.auth_mode} "
            "(session cookies are signed in every auth mode). "
            "Set a long random value in the environment file, or configure the "
            "AUTH_SESSION_SECRETS rotation list (first entry signs, all entries verify).",
        )
    if settings.auth_trusted_proxy_cidrs.strip():
        try:
            trusted_proxy_networks(settings.auth_trusted_proxy_cidrs.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"AUTH_TRUSTED_PROXY_CIDRS contains an invalid CIDR: {exc}",
            ) from exc
    elif settings.auth_mode == "intranet_header":
        # 未配置 CIDR 时不拒启（既有部署依赖部署层保证网关独占），但要留下告警：
        # 此时身份头对任何直连 peer 都可信，等于把信任边界完全交给网络拓扑。
        logger.warning(
            "AUTH_MODE=intranet_header without AUTH_TRUSTED_PROXY_CIDRS: identity headers "
            "are trusted from any peer; ensure the trusted gateway is the only ingress, "
            "or set AUTH_TRUSTED_PROXY_CIDRS to enforce the boundary in-process.",
        )
    # 游客登录只允许 standalone/cloud：intranet 的身份边界在网关（游客绕过
    # 门户身份注入），extranet 是机器同步面向公网的形态，都不该有匿名会话。
    if settings.auth_guest_enabled and settings.deploy_mode not in {"standalone", "cloud"}:
        raise RuntimeError(
            f"AUTH_GUEST_ENABLED=true is only allowed for DEPLOY_MODE in [standalone, cloud]; "
            f"got DEPLOY_MODE={settings.deploy_mode}.",
        )
    if settings.deploy_mode == "intranet" and settings.capability_ingestion_override is True:
        # 不变式：intranet 形态不采集，不允许用 env 覆盖打开
        raise RuntimeError(
            "DEPLOY_MODE=intranet forbids CAPABILITY_INGESTION=true; "
            "the intranet deployment never ingests.",
        )
    if settings.deploy_mode == "extranet" and not settings.sync_service_token_list:
        raise RuntimeError(
            "DEPLOY_MODE=extranet requires a non-empty SYNC_SERVICE_TOKENS "
            "for machine-to-machine feed authentication.",
        )
    if settings.auth_mode == "oidc":
        if not settings.oidc_client_id:
            raise RuntimeError("AUTH_MODE=oidc requires OIDC_CLIENT_ID.")
        if not (
            settings.oidc_issuer
            or (settings.oidc_authorization_endpoint and settings.oidc_token_endpoint)
        ):
            raise RuntimeError(
                "AUTH_MODE=oidc requires OIDC_ISSUER or explicit "
                "OIDC_AUTHORIZATION_ENDPOINT/OIDC_TOKEN_ENDPOINT.",
            )
    if (
        settings.capability_sync_consumer
        and settings.sync_pull_effective
        and (not settings.sync_remote_base_url or not settings.sync_remote_token)
    ):
        raise RuntimeError(
            "sync consumer with SYNC_PULL_ENABLED=true requires both "
            "SYNC_REMOTE_BASE_URL and SYNC_REMOTE_TOKEN "
            "(or set SYNC_PULL_ENABLED=false explicitly).",
        )
    # 部署预设 rss-only：INGESTION_SOURCE_TYPES 允许清单只接受已知类型子集
    # （config/contracts/source_fields.json 的 11 类 + 规划中的 wechat），
    # 拼写错误的清单等于静默漏采，必须启动时失败。
    unknown_source_types = [
        source_type
        for source_type in settings.ingestion_source_type_allowlist
        if source_type not in KNOWN_INGESTION_SOURCE_TYPES
    ]
    if unknown_source_types:
        raise RuntimeError(
            "INGESTION_SOURCE_TYPES contains unknown source types: "
            f"{', '.join(unknown_source_types)}; "
            f"allowed values: {', '.join(KNOWN_INGESTION_SOURCE_TYPES)}.",
        )
    # 生成 provider 启动自检（generation-provider-design §3.1/§9.6，契约
    # deployment_modes.json startup_failfast_rules 与本清单 1:1）。
    generation_provider = settings.generation_provider_effective
    if generation_provider not in GENERATION_PROVIDERS:
        raise RuntimeError(
            f"GENERATION_PROVIDER must be one of {', '.join(GENERATION_PROVIDERS)}; "
            f"got {generation_provider!r}.",
        )
    if settings.generation_enabled_effective and not settings.generation_api_key_effective:
        # R2 修订（D-2026-07-08-KEY）：key 可在运行期通过 UI 落库
        # （llm_provider_credentials），启动时无法断言最终配置——从拒启降级为
        # WARNING + 「生成模型」卡引导；未配置期间生成走规则降级稿（预期行为）。
        logger.warning(
            "GENERATION_ENABLED=true but no API key is configured in the environment "
            "(GENERATION_API_KEY / GENERATION_API_KEY_REF / legacy MINIMAX_API_KEY all "
            "empty). If no credential is registered in the UI either "
            "(workspace settings > generation model card), generation will degrade to "
            "rule-based fallback drafts until a key is provided. Keys never enter Git, "
            "sync feeds or audit logs; DB storage is Fernet-encrypted only.",
        )
    if (
        generation_provider in ("custom", "openai_compatible")
        and not settings.generation_base_url_effective
    ):
        raise RuntimeError(
            f"GENERATION_PROVIDER={generation_provider} requires GENERATION_BASE_URL "
            "(every other catalog preset carries a default base URL from "
            "config/contracts/llm_providers.json). Set GENERATION_BASE_URL to the "
            "provider's OpenAI-compatible endpoint.",
        )
