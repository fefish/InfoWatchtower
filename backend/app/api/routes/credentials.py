"""Provider 预设目录投影与 LLM 凭据 CRUD API（WP4-B）。

事实源：docs/backend/generation-provider-design.md §4/§8/§9；契约：
config/contracts/llm_providers.json。

- GET    /api/generation/providers          登录即可读；llm_providers.json 目录
                                            原样投影（无任何密钥字段）
- GET    /api/generation/credentials        super_admin 或 editor_admin；
                                            永只含 masked 视图（****+后 4 位）
- POST   /api/generation/credentials        super_admin；base_url 缺省取目录默认、
                                            custom 必填；审计 generation.credential.create
- PATCH  /api/generation/credentials/{id}   super_admin；api_key 传新值即整体替换
                                            重加密；审计 generation.credential.update
- DELETE /api/generation/credentials/{id}   super_admin；软删（enabled=false +
                                            disabled_at），被引用时按 credential_missing
                                            降级；审计 generation.credential.disable

安全不变式（§6/§9.5）：明文 key 只在写入方向出现，落库仅密文（Fernet at rest，
app/core/crypto.py）；审计 detail 只含 provider/base_url_host/label/key_masked/
enabled；本表整表排除在 sync feed / 手工同步包 / 导出之外。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user, require_super_admin
from app.auth.service import write_audit
from app.core.config import Settings, get_settings
from app.core.crypto import credential_cipher
from app.core.database import get_db_session
from app.llm.provider import catalog_default_base_url, catalog_entry, provider_catalog
from app.models.common import utc_now
from app.models.identity import User
from app.models.llm import LlmProviderCredential
from app.schemas.credentials import LlmCredentialCreate, LlmCredentialRead, LlmCredentialUpdate

router = APIRouter(prefix="/api/generation", tags=["generation"])

CREDENTIAL_LIST_ROLES = {"super_admin", "editor_admin"}


def _validation_error(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=[{"loc": ["body", field], "msg": message, "type": "value_error"}],
    )


def _base_url_host(base_url: str) -> str:
    return urlparse(base_url).hostname or ""


def _credential_read(row: LlmProviderCredential) -> LlmCredentialRead:
    return LlmCredentialRead(
        id=row.global_id,
        provider=row.provider,
        base_url=row.base_url,
        base_url_host=_base_url_host(row.base_url),
        label=row.label,
        key_masked=row.key_masked,
        enabled=row.enabled,
        disabled_at=row.disabled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _audit_detail(row: LlmProviderCredential) -> dict[str, Any]:
    # 审计 detail 只含 masked 安全字段（§9.5）；write_audit 的 secret-like
    # redactor 兜底，但这里从源头就不放明文与密文。
    return {
        "credential_id": row.global_id,
        "provider": row.provider,
        "base_url_host": _base_url_host(row.base_url),
        "label": row.label,
        "key_masked": row.key_masked,
        "enabled": row.enabled,
    }


def _validate_base_url(provider: str, base_url: str | None) -> str:
    resolved = (base_url or "").strip()
    if not resolved:
        resolved = catalog_default_base_url(provider)
    if not resolved:
        raise _validation_error(
            "base_url",
            f"base_url is required for provider {provider!r} (no catalog default)",
        )
    if len(resolved) > 512:
        raise _validation_error("base_url", "base_url must be at most 512 chars")
    if not resolved.startswith(("http://", "https://")):
        raise _validation_error("base_url", "base_url must start with http:// or https://")
    return resolved


def _load_credential(session: Session, credential_id: str) -> LlmProviderCredential:
    row = session.scalar(
        select(LlmProviderCredential).where(LlmProviderCredential.global_id == credential_id),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return row


def _key_last4(plaintext: str) -> str:
    return plaintext[-4:] if len(plaintext) >= 4 else plaintext


@router.get("/providers")
def list_generation_providers(
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """§8 预设目录原样投影（登录即可读）：只是 UI 预填与下拉数据，
    不是安全边界也不是能力开关，响应无任何密钥字段。"""
    return {"catalog": [dict(entry) for entry in provider_catalog()]}


@router.get("/credentials", response_model=list[LlmCredentialRead])
def list_credentials(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[LlmCredentialRead]:
    roles = {role.code for role in current_user.roles}
    if roles.isdisjoint(CREDENTIAL_LIST_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires super_admin or editor_admin",
        )
    rows = session.scalars(
        select(LlmProviderCredential).order_by(LlmProviderCredential.created_at),
    ).all()
    return [_credential_read(row) for row in rows]


@router.post("/credentials", response_model=LlmCredentialRead, status_code=201)
def create_credential(
    payload: LlmCredentialCreate,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LlmCredentialRead:
    provider = (payload.provider or "").strip().lower()
    entry = catalog_entry(provider)
    if entry is None:
        # 凭据表值域是目录 code 本身；env 别名 openai_compatible 不进凭据表。
        codes = ", ".join(item["code"] for item in provider_catalog())
        raise _validation_error("provider", f"provider must be one of: {codes}")
    base_url = _validate_base_url(provider, payload.base_url)
    api_key = (payload.api_key or "").strip()
    if entry.get("key_required", True) and not api_key:
        raise _validation_error("api_key", f"api_key is required for provider {provider!r}")
    label = (payload.label or "").strip() or f"{provider} 凭据"
    if len(label) > 64:
        raise _validation_error("label", "label must be at most 64 chars")

    cipher = credential_cipher(settings)
    row = LlmProviderCredential(
        provider=provider,
        base_url=base_url,
        key_encrypted=cipher.encrypt(api_key) if api_key else "",
        key_last4=_key_last4(api_key),
        label=label,
        enabled=True,
        created_by_id=current_user.id,
    )
    session.add(row)
    session.flush()
    write_audit(
        session,
        current_user,
        action="generation.credential.create",
        object_type="llm_provider_credential",
        object_id=row.id,
        detail=_audit_detail(row),
    )
    session.commit()
    session.refresh(row)
    return _credential_read(row)


@router.patch("/credentials/{credential_id}", response_model=LlmCredentialRead)
def update_credential(
    credential_id: str,
    payload: LlmCredentialUpdate,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LlmCredentialRead:
    row = _load_credential(session, credential_id)
    before = _audit_detail(row)

    if payload.label is not None:
        label = payload.label.strip()
        if not label or len(label) > 64:
            raise _validation_error("label", "label must be 1..64 chars")
        row.label = label
    if payload.base_url is not None:
        row.base_url = _validate_base_url(row.provider, payload.base_url)
    if payload.api_key is not None:
        # 传新值即整体替换重加密（§4）；key_required=false 的 provider 允许清空。
        api_key = payload.api_key.strip()
        entry = catalog_entry(row.provider)
        if (entry or {}).get("key_required", True) and not api_key:
            raise _validation_error("api_key", f"api_key is required for provider {row.provider!r}")
        cipher = credential_cipher(settings)
        row.key_encrypted = cipher.encrypt(api_key) if api_key else ""
        row.key_last4 = _key_last4(api_key)
    if payload.enabled is not None:
        row.enabled = payload.enabled
        row.disabled_at = None if payload.enabled else utc_now()

    write_audit(
        session,
        current_user,
        action="generation.credential.update",
        object_type="llm_provider_credential",
        object_id=row.id,
        detail={"before": before, "after": _audit_detail(row)},
    )
    session.commit()
    session.refresh(row)
    return _credential_read(row)


@router.delete("/credentials/{credential_id}", response_model=LlmCredentialRead)
def disable_credential(
    credential_id: str,
    current_user: User = Depends(require_super_admin),
    session: Session = Depends(get_db_session),
) -> LlmCredentialRead:
    """软删：enabled=false + disabled_at；行保留（审计追溯）。被工作台引用时
    resolved 按 credential_missing 降级并在卡片/ping 显式暴露，不回落 env。"""
    row = _load_credential(session, credential_id)
    row.enabled = False
    row.disabled_at = utc_now()
    write_audit(
        session,
        current_user,
        action="generation.credential.disable",
        object_type="llm_provider_credential",
        object_id=row.id,
        detail=_audit_detail(row),
    )
    session.commit()
    session.refresh(row)
    return _credential_read(row)
