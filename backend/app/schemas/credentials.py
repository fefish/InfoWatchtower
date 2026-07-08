"""LLM provider 凭据 CRUD API 的请求/响应模型（WP4-B，generation-provider-design §4/§9.5）。

安全不变式：响应永远只有 masked 视图（`key_masked = "****" + 后 4 位`）；
`api_key` 只出现在写入方向（write-only），`key_encrypted` 密文也不出现在响应里。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LlmCredentialRead(BaseModel):
    """masked 视图：任何角色（含 super_admin）都只见后 4 位。"""

    id: str
    provider: str
    base_url: str
    base_url_host: str
    label: str
    key_masked: str
    enabled: bool
    disabled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LlmCredentialCreate(BaseModel):
    provider: str
    # 缺省取目录 default_base_url；custom 必填（422）。
    base_url: str | None = None
    # write-only：落库前即加密；key_required=false 的 provider（ollama/custom）允许空。
    api_key: str | None = None
    label: str | None = None


class LlmCredentialUpdate(BaseModel):
    """PATCH 为增量语义：None=未发送保持原值；api_key 传新值即整体替换重加密。"""

    label: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    api_key: str | None = None
