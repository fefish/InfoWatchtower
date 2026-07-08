"""LLM provider 落库凭据（generation-provider-design §9.2，WP4-B）。

instance 级资产（无 workspace_code）：工作台通过
`generation_policy.credential_id`（存 global_id）引用。安全边界：
- `key_encrypted` 只存 Fernet 密文（app/core/crypto.py 派生），明文永不落库；
- `key_last4` 供 masked 展示（****+后4位），展示路径永不解密；
- 本表整表排除在 sync feed / 手工同步包 / 任何导出之外
  （SYNC_FEED_OBJECT_TYPES 不含本表；密钥表跨环境不同步，每个环境自己录 key）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdMixin, TimestampMixin, new_id


class LlmProviderCredential(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_provider_credentials"

    global_id: Mapped[str] = mapped_column(String(64), default=new_id, unique=True, index=True)
    # §8 目录 code（含 custom）；env 别名 openai_compatible 不进本表值域。
    provider: Mapped[str] = mapped_column(String(32), index=True)
    # 落库时已解析：目录默认或用户改写；custom 必填。
    base_url: Mapped[str] = mapped_column(String(512), default="")
    # Fernet token；ollama 等免 key 场景允许空串。
    key_encrypted: Mapped[str] = mapped_column(Text, default="")
    # 明文后 4 位（少于 4 位取全部），供 masked 展示，展示路径永不解密。
    key_last4: Mapped[str] = mapped_column(String(8), default="")
    label: Mapped[str] = mapped_column(String(64), default="")
    # DELETE = enabled=False + disabled_at（软删）；被引用时按 credential_missing 降级。
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    @property
    def key_masked(self) -> str:
        return f"****{self.key_last4}" if self.key_last4 else "****"
