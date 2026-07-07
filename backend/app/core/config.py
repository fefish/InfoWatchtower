from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_ENV_FILE = REPO_ROOT / "config" / ".env"
MOUNTED_ENV_FILE = Path("/config/.env")
DEFAULT_ENV_FILE = LOCAL_ENV_FILE if LOCAL_ENV_FILE.exists() else MOUNTED_ENV_FILE
DEFAULT_LEGACY_SEED_ROOT = (
    REPO_ROOT / "config" / "seeds" / "legacy"
    if (REPO_ROOT / "config" / "seeds" / "legacy").exists()
    else Path("/config/seeds/legacy")
)
DEFAULT_TECH_INSIGHT_LOOP_SOURCE_CSV = (
    REPO_ROOT / "config" / "seeds" / "tech_insight_loop" / "sources_full_zh.csv"
    if (REPO_ROOT / "config" / "seeds" / "tech_insight_loop" / "sources_full_zh.csv").exists()
    else Path("/config/seeds/tech_insight_loop/sources_full_zh.csv")
)
DEFAULT_CONTENT_SCORER_CONFIG_PATH = (
    REPO_ROOT / "config" / "scoring" / "content_scorer_v2.json"
    if (REPO_ROOT / "config" / "scoring" / "content_scorer_v2.json").exists()
    else Path("/config/scoring/content_scorer_v2.json")
)

DEPLOY_MODES = ("standalone", "cloud", "intranet", "extranet")
# 与 config/contracts/source_fields.json 的 source_types 保持一致（11 类），
# 外加规划中的第 12 类 wechat（wx 桥接 adapter，见 docs/backend/backend-capability-test-matrix.md）。
# INGESTION_SOURCE_TYPES 允许清单（部署预设 rss-only 等）只接受该集合的子集，
# 非法值由启动自检 fail-fast 拒绝。
KNOWN_INGESTION_SOURCE_TYPES = (
    "wiseflow",
    "rss",
    "page_monitor",
    "page_manual",
    "crawler",
    "csv",
    "paper_rss",
    "paper_api",
    "paper_page",
    "manual",
    "internal",
    "wechat",
)
# 与 config/contracts/deployment_modes.json 的 modes.*.capabilities 保持一致
MODE_CAPABILITIES: dict[str, dict[str, bool]] = {
    "standalone": {
        "ingestion": True,
        "sync_publisher": False,
        "sync_consumer": False,
        "embedding": False,
    },
    "cloud": {
        "ingestion": True,
        "sync_publisher": False,
        "sync_consumer": False,
        "embedding": False,
    },
    "intranet": {
        "ingestion": False,
        "sync_publisher": False,
        "sync_consumer": True,
        "embedding": True,
    },
    "extranet": {
        "ingestion": True,
        "sync_publisher": True,
        "sync_consumer": False,
        "embedding": False,
    },
}
# 与 config/contracts/deployment_modes.json 的 modes.*.csrf_default 保持一致
MODE_CSRF_DEFAULTS: dict[str, bool] = {
    "standalone": False,
    "cloud": True,
    "intranet": True,
    "extranet": True,
}
# 与 config/contracts/deployment_modes.json 的 modes.*.allowed_auth_modes 保持一致：
# 每种部署形态只允许契约声明的登录方式，非法组合由启动自检 fail-fast 拒绝
# （cloud/extranet 属公网形态，配置 intranet_header 等于开放请求头伪造登录）。
MODE_ALLOWED_AUTH_MODES: dict[str, tuple[str, ...]] = {
    "standalone": ("local", "public_password"),
    "cloud": ("public_password", "oidc"),
    "intranet": ("intranet_header",),
    "extranet": ("oidc", "public_password"),
}


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

    # 部署形态与能力开关（契约：config/contracts/deployment_modes.json，规格 §2）
    deploy_mode: str = Field(default="standalone", alias="DEPLOY_MODE")
    instance_id: str = Field(default="", alias="INSTANCE_ID")
    capability_ingestion_override: bool | None = Field(default=None, alias="CAPABILITY_INGESTION")
    capability_sync_publisher_override: bool | None = Field(
        default=None,
        alias="CAPABILITY_SYNC_PUBLISHER",
    )
    capability_sync_consumer_override: bool | None = Field(
        default=None,
        alias="CAPABILITY_SYNC_CONSUMER",
    )
    sync_service_tokens: str = Field(default="", alias="SYNC_SERVICE_TOKENS")
    sync_remote_base_url: str = Field(default="", alias="SYNC_REMOTE_BASE_URL")
    sync_remote_token: str = Field(default="", alias="SYNC_REMOTE_TOKEN")
    sync_pull_enabled: bool | None = Field(default=None, alias="SYNC_PULL_ENABLED")
    sync_pull_interval_seconds: int = Field(default=900, alias="SYNC_PULL_INTERVAL_SECONDS")
    sync_failed_inbox_auto_retry_enabled: bool | None = Field(
        default=None,
        alias="SYNC_FAILED_INBOX_AUTO_RETRY_ENABLED",
    )
    sync_failed_inbox_retry_base_seconds: int = Field(
        default=300,
        alias="SYNC_FAILED_INBOX_RETRY_BASE_SECONDS",
    )
    sync_failed_inbox_retry_max_seconds: int = Field(
        default=3600,
        alias="SYNC_FAILED_INBOX_RETRY_MAX_SECONDS",
    )
    sync_failed_inbox_retry_max_attempts: int = Field(
        default=5,
        alias="SYNC_FAILED_INBOX_RETRY_MAX_ATTEMPTS",
    )
    sync_failed_inbox_retry_limit: int = Field(
        default=50,
        alias="SYNC_FAILED_INBOX_RETRY_LIMIT",
    )
    embed_frame_ancestors: str = Field(default="'self'", alias="EMBED_FRAME_ANCESTORS")
    auth_csrf_enabled: bool | None = Field(default=None, alias="AUTH_CSRF_ENABLED")
    auth_trusted_proxy_cidrs: str = Field(default="", alias="AUTH_TRUSTED_PROXY_CIDRS")

    auth_mode: str = Field(default="public_password", alias="AUTH_MODE")
    auth_session_secret: str = Field(default="", alias="AUTH_SESSION_SECRET")
    # 多版本轮换：逗号分隔，第一个用于签名、全部可验签；配置后覆盖单值
    # AUTH_SESSION_SECRET（见 _sync_session_secret_rotation）。换密钥时把新
    # secret 放到第一位、旧 secret 保留在列表尾部即可平滑轮换不掉线，
    # 旧 secret 移出列表后旧 cookie 立即失效。
    auth_session_secrets: str = Field(default="", alias="AUTH_SESSION_SECRETS")
    auth_session_cookie: str = Field(default="infowatchtower_session", alias="AUTH_SESSION_COOKIE")
    auth_session_cookie_secure: bool | None = Field(default=None, alias="AUTH_SESSION_COOKIE_SECURE")
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
    oidc_provider: str = Field(default="oidc", alias="OIDC_PROVIDER")
    oidc_issuer: str = Field(default="", alias="OIDC_ISSUER")
    oidc_client_id: str = Field(default="", alias="OIDC_CLIENT_ID")
    oidc_client_secret: str = Field(default="", alias="OIDC_CLIENT_SECRET")
    oidc_scopes: str = Field(default="openid email profile", alias="OIDC_SCOPES")
    oidc_redirect_url: str = Field(default="", alias="OIDC_REDIRECT_URL")
    oidc_authorization_endpoint: str = Field(default="", alias="OIDC_AUTHORIZATION_ENDPOINT")
    oidc_token_endpoint: str = Field(default="", alias="OIDC_TOKEN_ENDPOINT")
    oidc_userinfo_endpoint: str = Field(default="", alias="OIDC_USERINFO_ENDPOINT")
    oidc_jwks_uri: str = Field(default="", alias="OIDC_JWKS_URI")
    oidc_post_login_redirect_url: str = Field(default="", alias="OIDC_POST_LOGIN_REDIRECT_URL")
    oidc_claim_external_id: str = Field(default="sub", alias="OIDC_CLAIM_EXTERNAL_ID")
    oidc_claim_employee_no: str = Field(default="employee_no", alias="OIDC_CLAIM_EMPLOYEE_NO")
    oidc_claim_username: str = Field(default="preferred_username", alias="OIDC_CLAIM_USERNAME")
    oidc_claim_display_name: str = Field(default="name", alias="OIDC_CLAIM_DISPLAY_NAME")
    oidc_claim_department: str = Field(default="department", alias="OIDC_CLAIM_DEPARTMENT")
    oidc_claim_email: str = Field(default="email", alias="OIDC_CLAIM_EMAIL")
    auth_default_workspace_codes: str = Field(default="", alias="AUTH_DEFAULT_WORKSPACE_CODES")
    auth_department_workspace_map: str = Field(default="", alias="AUTH_DEPARTMENT_WORKSPACE_MAP")

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")
    legacy_seed_root: str = Field(default=str(DEFAULT_LEGACY_SEED_ROOT), alias="LEGACY_SEED_ROOT")
    tech_insight_loop_source_csv: str = Field(
        default=str(DEFAULT_TECH_INSIGHT_LOOP_SOURCE_CSV),
        alias="TECH_INSIGHT_LOOP_SOURCE_CSV",
    )
    content_scorer_config_path: str = Field(
        default=str(DEFAULT_CONTENT_SCORER_CONFIG_PATH),
        alias="CONTENT_SCORER_CONFIG_PATH",
    )

    ingestion_scheduler_enabled: bool = Field(default=False, alias="INGESTION_SCHEDULER_ENABLED")
    ingestion_scheduler_interval_seconds: int = Field(
        default=60 * 60 * 24,
        alias="INGESTION_SCHEDULER_INTERVAL_SECONDS",
    )
    # 默认每天 12:00（配合 DAILY_PIPELINE_DAY_OFFSET_DAYS=-1「中午汇总昨天」的
    # 用户口径）；置空回退 INGESTION_SCHEDULER_INTERVAL_SECONDS 间隔模式。
    ingestion_scheduler_daily_time: str = Field(
        default="12:00",
        alias="INGESTION_SCHEDULER_DAILY_TIME",
    )
    ingestion_scheduler_timezone: str = Field(
        default="Asia/Shanghai",
        alias="INGESTION_SCHEDULER_TIMEZONE",
    )
    ingestion_scheduler_workspace_code: str = Field(
        default="planning_intel",
        alias="INGESTION_SCHEDULER_WORKSPACE_CODE",
    )
    ingestion_scheduler_source_types: str = Field(
        default="rss,paper_rss,page_manual,page_monitor,wiseflow",
        alias="INGESTION_SCHEDULER_SOURCE_TYPES",
    )
    ingestion_scheduler_limit: int | None = Field(default=None, alias="INGESTION_SCHEDULER_LIMIT")
    # 部署级采集类型允许清单（预设 rss-only 用）：逗号分隔，空 = 全部允许。
    # 与 INGESTION_SCHEDULER_SOURCE_TYPES 不同：后者只决定 scheduler 请求哪些类型，
    # 本清单在 run 内部过滤启用源，不在清单的源计入 run 摘要 skipped_type_disabled。
    ingestion_source_types: str = Field(default="", alias="INGESTION_SOURCE_TYPES")
    ingestion_concurrency: int = Field(default=8, alias="INGESTION_CONCURRENCY")
    ingestion_source_timeout_seconds: float = Field(
        default=25.0,
        alias="INGESTION_SOURCE_TIMEOUT_SECONDS",
    )
    ingestion_max_items_per_source: int | None = Field(default=None, alias="INGESTION_MAX_ITEMS_PER_SOURCE")
    ingestion_failed_source_auto_retry_enabled: bool | None = Field(
        default=None,
        alias="INGESTION_FAILED_SOURCE_AUTO_RETRY_ENABLED",
    )
    ingestion_failed_source_retry_base_seconds: int = Field(
        default=900,
        alias="INGESTION_FAILED_SOURCE_RETRY_BASE_SECONDS",
    )
    ingestion_failed_source_retry_max_seconds: int = Field(
        default=3600,
        alias="INGESTION_FAILED_SOURCE_RETRY_MAX_SECONDS",
    )
    ingestion_failed_source_retry_max_attempts: int = Field(
        default=3,
        alias="INGESTION_FAILED_SOURCE_RETRY_MAX_ATTEMPTS",
    )
    ingestion_failed_source_retry_limit: int = Field(
        default=10,
        alias="INGESTION_FAILED_SOURCE_RETRY_LIMIT",
    )
    rsshub_base_url: str = Field(default="", alias="RSSHUB_BASE_URL")
    semantic_scholar_api_key: str = Field(default="", alias="SEMANTIC_SCHOLAR_API_KEY")
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
    daily_pipeline_day_offset_days: int = Field(default=0, alias="DAILY_PIPELINE_DAY_OFFSET_DAYS")

    minimax_generation_enabled: bool = Field(default=False, alias="MINIMAX_GENERATION_ENABLED")
    minimax_api_key: str = Field(default="", alias="MINIMAX_API_KEY")
    minimax_base_url: str = Field(default="", alias="MINIMAX_BASE_URL")
    minimax_anthropic_base_url: str = Field(default="", alias="MINIMAX_ANTHROPIC_BASE_URL")
    minimax_model: str = Field(default="MiniMax-M2.7-highspeed", alias="MINIMAX_MODEL")
    minimax_max_tokens: int = Field(default=3200, alias="MINIMAX_MAX_TOKENS")
    minimax_temperature: float = Field(default=0.4, alias="MINIMAX_TEMPERATURE")
    minimax_retry_times: int = Field(default=3, alias="MINIMAX_RETRY_TIMES")
    minimax_retry_backoff_seconds: float = Field(
        default=8.0,
        alias="MINIMAX_RETRY_BACKOFF_SECONDS",
    )

    @model_validator(mode="after")
    def _sync_session_secret_rotation(self) -> "Settings":
        # AUTH_SESSION_SECRETS 配置时，列表第一个即当前签名 secret；回写
        # auth_session_secret，让签发（create_session_token）与启动自检等所有
        # 单值读取点自动拿到签名值（自检口径：两个变量任一非空即可）。
        secrets = [item.strip() for item in self.auth_session_secrets.split(",") if item.strip()]
        if secrets:
            self.auth_session_secret = secrets[0]
        return self

    @property
    def auth_session_secret_list(self) -> list[str]:
        # 可验签 secret 全集（轮换语义）：AUTH_SESSION_SECRETS 优先，
        # 未配置时回退单值 AUTH_SESSION_SECRET。
        items = [item.strip() for item in self.auth_session_secrets.split(",") if item.strip()]
        if items:
            return items
        return [self.auth_session_secret] if self.auth_session_secret else []

    def _mode_capability(self, name: str) -> bool:
        return MODE_CAPABILITIES.get(self.deploy_mode, MODE_CAPABILITIES["standalone"])[name]

    @property
    def capability_ingestion(self) -> bool:
        # 不变式：intranet 形态不采集，override 打开由启动自检拒绝，这里恒为 False
        if self.deploy_mode == "intranet":
            return False
        if self.capability_ingestion_override is not None:
            return self.capability_ingestion_override
        return self._mode_capability("ingestion")

    @property
    def capability_sync_publisher(self) -> bool:
        if self.capability_sync_publisher_override is not None:
            return self.capability_sync_publisher_override
        return self._mode_capability("sync_publisher")

    @property
    def capability_sync_consumer(self) -> bool:
        if self.capability_sync_consumer_override is not None:
            return self.capability_sync_consumer_override
        return self._mode_capability("sync_consumer")

    @property
    def capability_embedding(self) -> bool:
        # 契约中 embedding 无 override env，只随 DEPLOY_MODE 派生
        return self._mode_capability("embedding")

    @property
    def capability_search(self) -> bool:
        # Search 是只读能力，所有部署形态默认可用；具体对象仍由 API 按权限和部署能力过滤。
        return True

    @property
    def sync_service_token_list(self) -> list[str]:
        return [item.strip() for item in self.sync_service_tokens.split(",") if item.strip()]

    @property
    def effective_instance_id(self) -> str:
        return self.instance_id.strip() or self.deploy_mode

    @property
    def sync_pull_effective(self) -> bool:
        if self.sync_pull_enabled is not None:
            return self.sync_pull_enabled
        return self.deploy_mode == "intranet"

    @property
    def sync_failed_inbox_auto_retry_effective(self) -> bool:
        if self.sync_failed_inbox_auto_retry_enabled is not None:
            return self.sync_failed_inbox_auto_retry_enabled
        return self.capability_sync_consumer and self.sync_pull_effective

    @property
    def ingestion_failed_source_auto_retry_effective(self) -> bool:
        if self.ingestion_failed_source_auto_retry_enabled is not None:
            return self.ingestion_failed_source_auto_retry_enabled
        return False

    @property
    def auth_csrf_effective(self) -> bool:
        if self.auth_csrf_enabled is not None:
            return self.auth_csrf_enabled
        return MODE_CSRF_DEFAULTS.get(self.deploy_mode, False)

    @property
    def auth_trusted_proxy_cidr_list(self) -> list[str]:
        return [item.strip() for item in self.auth_trusted_proxy_cidrs.split(",") if item.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def ingestion_source_type_allowlist(self) -> list[str]:
        # 空清单 = 不限制（full 预设）；非空时抓取 run 只抓清单内类型的源。
        normalized: list[str] = []
        for item in self.ingestion_source_types.split(","):
            value = item.strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

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
