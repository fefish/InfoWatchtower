"""生成 provider 工作台策略与连通性自检 API（WP3-B）。

事实源：docs/backend/generation-provider-design.md §3.2/§4；契约：
config/contracts/workspace_model.json `generation_policy`。

- GET   /api/workspaces/{code}/generation-policy   workspace viewer+ 读
  （响应附只读 resolved 状态，「生成模型」卡不打 ping 也能展示）
- PATCH /api/workspaces/{code}/generation-policy   workspace admin+ 或 super_admin 写
  （取值域校验 422；secret-like 字段 422；审计 workspace.generation_policy.update）
- POST  /api/generation/ping                        super_admin 或 editor_admin
  （最小探针、分类报错、审计 generation.ping；detail 无 key）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import assert_workspace_member, get_current_user
from app.auth.service import write_audit
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.privacy import contains_secret_like_key
from app.llm.provider import (
    FALLBACK_BEHAVIORS,
    GENERATION_POLICY_DEFAULTS,
    ResolvedGenerationConfig,
    ping_generation_provider,
    resolve_generation_config,
    workspace_generation_policy,
)
from app.models.identity import User
from app.models.workspace import Workspace
from app.schemas.generation import (
    GenerationPingCreate,
    GenerationPingRead,
    GenerationPolicyRead,
    GenerationResolvedRead,
    WorkspaceGenerationPolicyRead,
)

router = APIRouter(prefix="/api", tags=["generation"])

GENERATION_PING_ROLES = {"super_admin", "editor_admin"}
POLICY_FIELDS = set(GENERATION_POLICY_DEFAULTS)


def _get_enabled_workspace(session: Session, workspace_code: str) -> Workspace:
    workspace = session.scalar(
        select(Workspace).where(Workspace.code == workspace_code, Workspace.enabled.is_(True)),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


def _resolved_to_read(config: ResolvedGenerationConfig) -> GenerationResolvedRead:
    # 只暴露状态位与主机名；key 本体永不出现在任何响应字段。
    return GenerationResolvedRead(
        provider=config.provider,
        model=config.model,
        base_url_host=config.base_url_host,
        enabled=config.enabled,
        key_configured=config.key_configured,
        key_source=config.key_source,
    )


def _policy_read(workspace: Workspace) -> GenerationPolicyRead:
    return GenerationPolicyRead(**workspace_generation_policy(workspace))


def _validation_error(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=[{"loc": ["body", field], "msg": message, "type": "value_error"}],
    )


def _validate_policy_patch(payload: dict[str, Any]) -> dict[str, Any]:
    """取值域校验（generation-provider-design §3.2）；返回只含合法字段的增量。"""
    if not isinstance(payload, dict):
        raise _validation_error("__root__", "payload must be a JSON object")
    if contains_secret_like_key(payload):
        raise _validation_error(
            "__root__",
            "secret-like keys are not allowed in generation_policy "
            "(keys/base urls live in instance env only)",
        )
    unknown = sorted(set(payload) - POLICY_FIELDS)
    if unknown:
        raise _validation_error(
            unknown[0],
            f"unknown generation_policy fields: {', '.join(unknown)}",
        )

    updates: dict[str, Any] = {}
    if "model" in payload:
        model = payload["model"]
        if model is not None:
            if not isinstance(model, str) or not model.strip() or len(model.strip()) > 64:
                raise _validation_error("model", "model must be null or a string of <=64 chars")
            model = model.strip()
        updates["model"] = model
    if "temperature" in payload:
        temperature = payload["temperature"]
        if temperature is not None:
            if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
                raise _validation_error("temperature", "temperature must be null or a number")
            temperature = float(temperature)
            if not 0 <= temperature <= 2:
                raise _validation_error("temperature", "temperature must be within 0..2")
        updates["temperature"] = temperature
    if "max_tokens" in payload:
        max_tokens = payload["max_tokens"]
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
                raise _validation_error("max_tokens", "max_tokens must be null or an integer")
            if not 256 <= max_tokens <= 8192:
                raise _validation_error("max_tokens", "max_tokens must be within 256..8192")
        updates["max_tokens"] = max_tokens
    if "timeout_seconds" in payload:
        timeout_seconds = payload["timeout_seconds"]
        if timeout_seconds is not None:
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
                raise _validation_error("timeout_seconds", "timeout_seconds must be null or a number")
            timeout_seconds = float(timeout_seconds)
            if not 5 <= timeout_seconds <= 300:
                raise _validation_error("timeout_seconds", "timeout_seconds must be within 5..300")
        updates["timeout_seconds"] = timeout_seconds
    if "daily_generation_budget" in payload:
        budget = payload["daily_generation_budget"]
        if budget is not None:
            if isinstance(budget, bool) or not isinstance(budget, int):
                raise _validation_error(
                    "daily_generation_budget",
                    "daily_generation_budget must be null or an integer",
                )
            if not 1 <= budget <= 1000:
                raise _validation_error(
                    "daily_generation_budget",
                    "daily_generation_budget must be within 1..1000",
                )
        updates["daily_generation_budget"] = budget
    if "fallback_behavior" in payload:
        behavior = payload["fallback_behavior"]
        if behavior not in FALLBACK_BEHAVIORS:
            raise _validation_error(
                "fallback_behavior",
                f"fallback_behavior must be one of: {', '.join(FALLBACK_BEHAVIORS)}",
            )
        updates["fallback_behavior"] = behavior
    return updates


@router.get(
    "/workspaces/{workspace_code}/generation-policy",
    response_model=WorkspaceGenerationPolicyRead,
)
def get_workspace_generation_policy(
    workspace_code: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> WorkspaceGenerationPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = _get_enabled_workspace(session, workspace_code)
    config = resolve_generation_config(settings, workspace=workspace)
    return WorkspaceGenerationPolicyRead(
        workspace_code=workspace.code,
        policy=_policy_read(workspace),
        resolved=_resolved_to_read(config),
    )


@router.patch(
    "/workspaces/{workspace_code}/generation-policy",
    response_model=WorkspaceGenerationPolicyRead,
)
def update_workspace_generation_policy(
    workspace_code: str,
    payload: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> WorkspaceGenerationPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    updates = _validate_policy_patch(payload)

    config_json = dict(workspace.config_json or {})
    before = workspace_generation_policy(workspace)
    policy = {**before, **updates}
    config_json["generation_policy"] = policy
    workspace.config_json = config_json
    write_audit(
        session,
        current_user,
        action="workspace.generation_policy.update",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "before": before,
            "after": policy,
        },
    )
    session.commit()
    session.refresh(workspace)
    config = resolve_generation_config(settings, workspace=workspace)
    return WorkspaceGenerationPolicyRead(
        workspace_code=workspace.code,
        policy=_policy_read(workspace),
        resolved=_resolved_to_read(config),
    )


@router.post("/generation/ping", response_model=GenerationPingRead)
def generation_ping(
    payload: GenerationPingCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> GenerationPingRead:
    roles = {role.code for role in current_user.roles}
    if roles.isdisjoint(GENERATION_PING_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires super_admin or editor_admin",
        )
    workspace = None
    if payload.workspace_code:
        workspace = _get_enabled_workspace(session, payload.workspace_code)
    config = resolve_generation_config(settings, workspace=workspace)
    result = ping_generation_provider(config)
    # 审计 detail 只含 provider/model/base_url_host/status/latency_ms——无 key、
    # 无 error_message（设计 §4；密钥红线见 security-secrets-privacy-design）。
    write_audit(
        session,
        current_user,
        action="generation.ping",
        object_type="generation_provider",
        object_id=config.provider,
        detail={
            "provider": result.provider,
            "model": result.model,
            "base_url_host": result.base_url_host,
            "status": result.status,
            "latency_ms": result.latency_ms,
        },
    )
    session.commit()
    return GenerationPingRead(
        status=result.status,
        provider=result.provider,
        model=result.model,
        base_url_host=result.base_url_host,
        key_configured=result.key_configured,
        latency_ms=result.latency_ms,
        error_code=result.error_code,
        error_message=result.error_message,
    )
