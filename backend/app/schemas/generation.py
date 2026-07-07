"""生成 provider 配置 API 的响应模型（WP3-B）。

安全不变式：任何字段不含 key 明文——resolved 只暴露 key_configured /
key_source（来源标注）与 base_url_host（主机名，不含路径/凭据）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GenerationPolicyRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    daily_generation_budget: int | None = None
    fallback_behavior: str = "rule_fallback"


class GenerationResolvedRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: str
    model: str
    base_url_host: str
    enabled: bool
    key_configured: bool
    key_source: str


class WorkspaceGenerationPolicyRead(BaseModel):
    workspace_code: str
    policy: GenerationPolicyRead
    resolved: GenerationResolvedRead


class GenerationPingCreate(BaseModel):
    workspace_code: str | None = None


class GenerationPingRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str
    provider: str
    model: str
    base_url_host: str
    key_configured: bool
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
