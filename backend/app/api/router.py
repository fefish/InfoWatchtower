from fastapi import APIRouter

from app.api.routes import auth, health, ingestion, news, sources, workspaces

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(auth.admin_router)
api_router.include_router(sources.router)
api_router.include_router(workspaces.router)
api_router.include_router(ingestion.router)
api_router.include_router(news.router)
api_router.include_router(health.router)
