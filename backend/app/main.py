from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.auth.service import try_ensure_auth_seed
from app.core.config import get_settings
from app.core.database import get_session_factory


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    _validate_startup_settings(settings)
    try_ensure_auth_seed(get_session_factory(), settings)
    yield


def _validate_startup_settings(settings) -> None:
    if settings.app_env == "production" and not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is required when APP_ENV=production. "
            "Set it in the deployment environment file before starting the API.",
        )
    if settings.auth_mode == "public_password" and not settings.auth_session_secret:
        raise RuntimeError(
            "AUTH_SESSION_SECRET is required when AUTH_MODE=public_password. "
            "Set a long random value in the production environment file.",
        )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="InfoWatchtower API",
        version=settings.app_version,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        lifespan=lifespan,
    )

    cors_origins = settings.cors_origin_list
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router)
    return app


app = create_app()
