from fastapi import APIRouter

from app.api.routes import (
    auth,
    domain_packs,
    exports,
    generation,
    groups,
    health,
    ingestion,
    meta,
    news,
    notifications,
    operations,
    pipeline,
    recommendations,
    renditions,
    reports,
    setup,
    search,
    sources,
    sync,
    workspace_access,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(setup.router)
api_router.include_router(auth.admin_router)
api_router.include_router(sources.router)
api_router.include_router(workspaces.router)
api_router.include_router(workspace_access.router)
api_router.include_router(generation.router)
api_router.include_router(groups.router)
api_router.include_router(domain_packs.router)
api_router.include_router(ingestion.router)
api_router.include_router(news.router)
api_router.include_router(notifications.router)
api_router.include_router(operations.router)
api_router.include_router(pipeline.router)
api_router.include_router(recommendations.router)
api_router.include_router(reports.router)
api_router.include_router(renditions.router)
api_router.include_router(exports.router)
api_router.include_router(search.router)
api_router.include_router(meta.router)
api_router.include_router(sync.router)
api_router.include_router(health.router)
