from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import check_database

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, object]:
    """存活探针（liveness）：只报进程活着，永远 200；就绪判定走 /readyz。"""
    settings = get_settings()
    return {
        "service": "infowatchtower-backend",
        "version": settings.app_version,
        "environment": settings.app_env,
        "database": check_database(),
    }


@router.get("/readyz")
def readyz() -> JSONResponse:
    """就绪探针（readiness）：数据库连通（SELECT 1）是硬条件，失联/未配置返回 503。

    compose/网关健康检查应指向本端点。能力位与部署形态只随 body 返回供巡检
    定位（如 intranet 应见 sync_consumer=true），不参与就绪判定：SYNC_REMOTE
    可达性之类的运行期波动属告警面，不应把实例摘下线。
    """
    settings = get_settings()
    database = check_database()
    ready = database.get("status") == "ok"
    payload = {
        "status": "ready" if ready else "unready",
        "service": "infowatchtower-backend",
        "version": settings.app_version,
        "environment": settings.app_env,
        "deploy_mode": settings.deploy_mode,
        "instance_id": settings.effective_instance_id,
        "database": database,
        "capabilities": {
            "ingestion": settings.capability_ingestion,
            "sync_publisher": settings.capability_sync_publisher,
            "sync_consumer": settings.capability_sync_consumer,
            "embedding": settings.capability_embedding,
            "search": settings.capability_search,
        },
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)
