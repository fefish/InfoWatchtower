from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.service import parse_default_workspace_targets, parse_department_workspace_targets
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/runtime")
def get_runtime(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """运行时能力下发（免登录，无敏感信息），前端启动时拉取一次。规格 §2.4。"""
    return {
        "deploy_mode": settings.deploy_mode,
        "instance_id": settings.effective_instance_id,
        "capabilities": {
            "ingestion": settings.capability_ingestion,
            "sync_publisher": settings.capability_sync_publisher,
            "sync_consumer": settings.capability_sync_consumer,
            "embedding": settings.capability_embedding,
            "search": settings.capability_search,
        },
        "auth_mode": settings.auth_mode,
        "auth_membership_mapping": _auth_membership_mapping(settings),
        "app_version": settings.app_version,
    }


def _auth_membership_mapping(settings: Settings) -> dict[str, object]:
    try:
        default_targets = parse_default_workspace_targets(settings.auth_default_workspace_codes)
        department_targets = parse_department_workspace_targets(settings.auth_department_workspace_map)
    except ValueError as exc:
        return {
            "status": "invalid",
            "default_workspaces": [],
            "department_workspaces": [],
            "error": str(exc),
        }
    default_workspaces = [
        {"workspace_code": target.code, "workspace_role": target.workspace_role}
        for target in default_targets
    ]
    department_workspaces = [
        {
            "department": department,
            "workspace_code": target.code,
            "workspace_role": target.workspace_role,
        }
        for department, target in department_targets
    ]
    return {
        "status": "configured" if default_workspaces or department_workspaces else "empty",
        "default_workspaces": default_workspaces,
        "department_workspaces": department_workspaces,
    }
