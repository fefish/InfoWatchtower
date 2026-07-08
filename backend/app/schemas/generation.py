"""生成 provider 配置 API 的响应模型（WP3-B，WP4-B R2 修订）。

安全不变式：任何字段不含 key 明文——resolved 只暴露 key_configured /
key_source（来源标注）与 base_url_host（主机名，不含路径/凭据）；
凭据只回显 masked 视图（****+后 4 位）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GenerationPolicyRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    credential_id: str | None = None
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
    # credential | credential_ref | env | credential_missing | ""（未配置）
    key_source: str
    credential_id: str | None = None
    credential_label: str | None = None


class CredentialOptionRead(BaseModel):
    """工作台「生成模型」卡凭据下拉项（workspace admin+ 才返回）。"""

    id: str
    label: str
    provider: str
    base_url_host: str
    key_masked: str


class WorkspaceGenerationPolicyRead(BaseModel):
    workspace_code: str
    policy: GenerationPolicyRead
    resolved: GenerationResolvedRead
    # viewer 只见 resolved；workspace admin+ / super_admin 才有凭据清单。
    credential_options: list[CredentialOptionRead] | None = None


class GenerationPingCreate(BaseModel):
    workspace_code: str | None = None
    # R2：按凭据测试（保存后立即试连）；与 workspace_code 同给时 credential_id 优先。
    credential_id: str | None = None


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
