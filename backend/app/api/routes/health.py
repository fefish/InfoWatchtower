from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import check_database

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, object]:
    settings = get_settings()
    return {
        "service": "infowatchtower-backend",
        "version": settings.app_version,
        "environment": settings.app_env,
        "database": check_database(),
    }
