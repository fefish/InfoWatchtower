from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / "config" / ".env"
DEFAULT_LEGACY_SEED_ROOT = (
    REPO_ROOT / "config" / "seeds" / "legacy"
    if (REPO_ROOT / "config" / "seeds" / "legacy").exists()
    else Path("/config/seeds/legacy")
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    enable_docs: bool = Field(default=True, alias="ENABLE_DOCS")

    database_url: str = Field(default="", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    auth_mode: str = Field(default="public_password", alias="AUTH_MODE")
    auth_session_secret: str = Field(default="", alias="AUTH_SESSION_SECRET")
    auth_session_cookie: str = Field(default="infowatchtower_session", alias="AUTH_SESSION_COOKIE")
    auth_session_ttl_seconds: int = Field(default=60 * 60 * 12, alias="AUTH_SESSION_TTL_SECONDS")
    auth_auto_provision: bool = Field(default=False, alias="AUTH_AUTO_PROVISION")
    auth_default_role: str = Field(default="viewer", alias="AUTH_DEFAULT_ROLE")
    auth_bootstrap_admin_username: str = Field(
        default="admin",
        alias="AUTH_BOOTSTRAP_ADMIN_USERNAME",
    )
    auth_bootstrap_admin_password: str = Field(default="", alias="AUTH_BOOTSTRAP_ADMIN_PASSWORD")
    auth_bootstrap_admin_display_name: str = Field(
        default="规划部管理员",
        alias="AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME",
    )

    auth_header_employee_no: str = Field(default="X-Employee-No", alias="AUTH_HEADER_EMPLOYEE_NO")
    auth_header_display_name: str = Field(
        default="X-Employee-Name",
        alias="AUTH_HEADER_DISPLAY_NAME",
    )
    auth_header_department: str = Field(default="X-Department", alias="AUTH_HEADER_DEPARTMENT")
    auth_header_email: str = Field(default="X-Email", alias="AUTH_HEADER_EMAIL")

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")
    legacy_seed_root: str = Field(default=str(DEFAULT_LEGACY_SEED_ROOT), alias="LEGACY_SEED_ROOT")

    ingestion_scheduler_enabled: bool = Field(default=False, alias="INGESTION_SCHEDULER_ENABLED")
    ingestion_scheduler_interval_seconds: int = Field(
        default=60 * 60 * 24,
        alias="INGESTION_SCHEDULER_INTERVAL_SECONDS",
    )
    ingestion_scheduler_workspace_code: str = Field(
        default="planning_intel",
        alias="INGESTION_SCHEDULER_WORKSPACE_CODE",
    )
    ingestion_scheduler_source_types: str = Field(
        default="rss,paper_rss",
        alias="INGESTION_SCHEDULER_SOURCE_TYPES",
    )
    ingestion_scheduler_limit: int | None = Field(default=None, alias="INGESTION_SCHEDULER_LIMIT")
    scheduler_job_mode: str = Field(default="daily_pipeline", alias="SCHEDULER_JOB_MODE")
    daily_pipeline_run_ingestion: bool = Field(default=True, alias="DAILY_PIPELINE_RUN_INGESTION")
    daily_pipeline_create_daily_draft: bool = Field(
        default=True,
        alias="DAILY_PIPELINE_CREATE_DAILY_DRAFT",
    )
    daily_pipeline_recommendation_limit: int = Field(
        default=15,
        alias="DAILY_PIPELINE_RECOMMENDATION_LIMIT",
    )
    daily_pipeline_source_daily_limit: int = Field(
        default=2,
        alias="DAILY_PIPELINE_SOURCE_DAILY_LIMIT",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def ingestion_source_type_list(self) -> list[str]:
        return [
            item.strip()
            for item in self.ingestion_scheduler_source_types.split(",")
            if item.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
