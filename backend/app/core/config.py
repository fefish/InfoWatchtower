from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / "config" / ".env"


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
    auth_auto_provision: bool = Field(default=False, alias="AUTH_AUTO_PROVISION")
    auth_default_role: str = Field(default="viewer", alias="AUTH_DEFAULT_ROLE")

    auth_header_employee_no: str = Field(default="X-Employee-No", alias="AUTH_HEADER_EMPLOYEE_NO")
    auth_header_display_name: str = Field(
        default="X-Employee-Name",
        alias="AUTH_HEADER_DISPLAY_NAME",
    )
    auth_header_department: str = Field(default="X-Department", alias="AUTH_HEADER_DEPARTMENT")
    auth_header_email: str = Field(default="X-Email", alias="AUTH_HEADER_EMAIL")

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
