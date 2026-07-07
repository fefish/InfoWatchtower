"""WP4 部署形态与能力开关（契约：config/contracts/deployment_modes.json）。"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.adapters.base import AdapterRegistry, RawItemInput
from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.core.deploy_checks import validate_deploy_settings
from app.ingestion.runs import WorkspaceIngestionRequest, run_workspace_ingestion
from app.main import create_app
from app.models.workspace import Workspace, WorkspaceSourceLink
from app.models.common import utc_now
from app.models.content import DataSource, GeneratedNews, NewsItem, RawItem
from app.models.feedback import (
    ActivityEvent,
    Comment,
    Notification,
    NotificationPreference,
    ObjectWatcher,
    Rating,
    Reaction,
)
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.models.strategy import Requirement, TopicTask

DEPLOY_ENV_KEYS = (
    "DEPLOY_MODE",
    "INSTANCE_ID",
    "AUTH_SESSION_SECRET",
    "AUTH_SESSION_SECRETS",
    "CAPABILITY_INGESTION",
    "CAPABILITY_SYNC_PUBLISHER",
    "CAPABILITY_SYNC_CONSUMER",
    "SYNC_SERVICE_TOKENS",
    "SYNC_REMOTE_BASE_URL",
    "SYNC_REMOTE_TOKEN",
    "SYNC_PULL_ENABLED",
    "SYNC_PULL_INTERVAL_SECONDS",
    "INGESTION_SOURCE_TYPES",
    "EMBED_FRAME_ANCESTORS",
    "AUTH_CSRF_ENABLED",
    "AUTH_TRUSTED_PROXY_CIDRS",
    "AUTH_MODE",
    "AUTH_DEFAULT_WORKSPACE_CODES",
    "AUTH_DEPARTMENT_WORKSPACE_MAP",
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_AUTHORIZATION_ENDPOINT",
    "OIDC_TOKEN_ENDPOINT",
)

INGESTION_GATED_PATHS = (
    "/api/ingestion/runs",
    "/api/ingestion/runs/any-run-id/retry-failed-sources",
    "/api/ingestion/backfill-runs",
    "/api/sources/any-source-id/fetch",
    "/api/sources/import-legacy-seeds",
    "/api/sources/import-tech-insight-loop",
    "/api/pipeline/daily-runs",
)


def make_settings(monkeypatch, **env):
    for key in DEPLOY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # 启动自检对所有 auth_mode 都要求 session secret，测试默认给一个可用值
    env.setdefault("AUTH_SESSION_SECRET", "test-session-secret")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


def make_client(monkeypatch, tmp_path, **env):
    database_path = tmp_path / "deployment_modes.sqlite"
    base_env = {
        "DATABASE_URL": f"sqlite:///{database_path}",
        "AUTH_MODE": "public_password",
        "AUTH_SESSION_SECRET": "test-session-secret",
        "AUTH_BOOTSTRAP_ADMIN_USERNAME": "admin",
        "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "password",
        "LEGACY_SEED_ROOT": str(
            Path(__file__).resolve().parents[2] / "config" / "seeds" / "legacy",
        ),
    }
    base_env.update(env)
    for key in DEPLOY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app())


def intranet_env(**extra):
    env = {
        "DEPLOY_MODE": "intranet",
        "AUTH_MODE": "intranet_header",
        "SYNC_REMOTE_BASE_URL": "https://extranet.example.com",
        "SYNC_REMOTE_TOKEN": "pull-token",
    }
    env.update(extra)
    return env


# --- capability 派生（四形态） ---


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (
            "standalone",
            {"ingestion": True, "sync_publisher": False, "sync_consumer": False, "embedding": False, "search": True},
        ),
        (
            "cloud",
            {"ingestion": True, "sync_publisher": False, "sync_consumer": False, "embedding": False, "search": True},
        ),
        (
            "intranet",
            {"ingestion": False, "sync_publisher": False, "sync_consumer": True, "embedding": True, "search": True},
        ),
        (
            "extranet",
            {"ingestion": True, "sync_publisher": True, "sync_consumer": False, "embedding": False, "search": True},
        ),
    ],
)
def test_mode_capability_derivation(monkeypatch, mode, expected):
    settings = make_settings(monkeypatch, DEPLOY_MODE=mode)
    assert settings.capability_ingestion is expected["ingestion"]
    assert settings.capability_sync_publisher is expected["sync_publisher"]
    assert settings.capability_sync_consumer is expected["sync_consumer"]
    assert settings.capability_embedding is expected["embedding"]
    assert settings.capability_search is expected["search"]
    assert settings.effective_instance_id == mode


def test_deploy_mode_defaults_to_standalone(monkeypatch):
    settings = make_settings(monkeypatch)
    assert settings.deploy_mode == "standalone"
    assert settings.effective_instance_id == "standalone"
    assert settings.sync_pull_interval_seconds == 900
    assert settings.embed_frame_ancestors == "'self'"


def test_explicit_instance_id_wins(monkeypatch):
    settings = make_settings(monkeypatch, DEPLOY_MODE="extranet", INSTANCE_ID="extranet-prod-1")
    assert settings.effective_instance_id == "extranet-prod-1"


# --- override 行为 ---


def test_standalone_can_override_sync_publisher_for_debugging(monkeypatch):
    settings = make_settings(monkeypatch, CAPABILITY_SYNC_PUBLISHER="true")
    assert settings.capability_sync_publisher is True


def test_extranet_can_override_ingestion_off(monkeypatch):
    settings = make_settings(
        monkeypatch,
        DEPLOY_MODE="extranet",
        SYNC_SERVICE_TOKENS="tok-1",
        CAPABILITY_INGESTION="false",
    )
    assert settings.capability_ingestion is False


def test_cloud_can_override_sync_consumer_on(monkeypatch):
    settings = make_settings(monkeypatch, DEPLOY_MODE="cloud", CAPABILITY_SYNC_CONSUMER="true")
    assert settings.capability_sync_consumer is True


def test_intranet_ingestion_ignores_true_override(monkeypatch):
    # 不变式：intranet 形态不采集；即便自检被绕过，派生属性也恒为 False
    settings = make_settings(monkeypatch, **intranet_env(CAPABILITY_INGESTION="true"))
    assert settings.capability_ingestion is False


def test_sync_service_token_list_parses_comma_separated(monkeypatch):
    settings = make_settings(monkeypatch, SYNC_SERVICE_TOKENS=" tok-1, tok-2,,tok-3 ")
    assert settings.sync_service_token_list == ["tok-1", "tok-2", "tok-3"]


def test_sync_pull_defaults_true_only_for_intranet(monkeypatch):
    assert make_settings(monkeypatch, **intranet_env()).sync_pull_effective is True
    assert make_settings(monkeypatch).sync_pull_effective is False
    disabled = make_settings(monkeypatch, **intranet_env(SYNC_PULL_ENABLED="false"))
    assert disabled.sync_pull_effective is False


def test_csrf_defaults_follow_deploy_mode(monkeypatch):
    assert make_settings(monkeypatch).auth_csrf_effective is False
    assert make_settings(monkeypatch, DEPLOY_MODE="cloud").auth_csrf_effective is True
    assert make_settings(monkeypatch, **intranet_env()).auth_csrf_effective is True
    extranet = make_settings(monkeypatch, DEPLOY_MODE="extranet", SYNC_SERVICE_TOKENS="tok")
    assert extranet.auth_csrf_effective is True
    overridden = make_settings(monkeypatch, AUTH_CSRF_ENABLED="true")
    assert overridden.auth_csrf_effective is True


# --- 启动自检 failfast 规则 ---


def test_failfast_rejects_unknown_deploy_mode(monkeypatch):
    settings = make_settings(monkeypatch, DEPLOY_MODE="hybrid")
    with pytest.raises(RuntimeError, match="DEPLOY_MODE"):
        validate_deploy_settings(settings)


def test_failfast_intranet_requires_intranet_header_auth(monkeypatch):
    settings = make_settings(monkeypatch, **intranet_env(AUTH_MODE="public_password"))
    with pytest.raises(RuntimeError, match="intranet_header"):
        validate_deploy_settings(settings)


@pytest.mark.parametrize(
    ("deploy_mode", "auth_mode"),
    [
        # 契约 modes.*.allowed_auth_modes 之外的组合逐形态拒启；
        # 公网形态配 intranet_header 是重点（否则任何人带身份头即伪造登录）
        ("standalone", "intranet_header"),
        ("standalone", "oidc"),
        ("cloud", "intranet_header"),
        ("cloud", "local"),
        ("intranet", "public_password"),
        ("intranet", "oidc"),
        ("intranet", "local"),
        ("extranet", "intranet_header"),
        ("extranet", "local"),
    ],
)
def test_failfast_rejects_auth_mode_outside_contract_whitelist(monkeypatch, deploy_mode, auth_mode):
    env = {"DEPLOY_MODE": deploy_mode, "AUTH_MODE": auth_mode}
    if deploy_mode == "extranet":
        env["SYNC_SERVICE_TOKENS"] = "tok-1"
    if deploy_mode == "intranet":
        env.update(
            SYNC_REMOTE_BASE_URL="https://extranet.example.com",
            SYNC_REMOTE_TOKEN="pull-token",
        )
    settings = make_settings(monkeypatch, **env)
    with pytest.raises(RuntimeError, match=rf"DEPLOY_MODE={deploy_mode} requires AUTH_MODE"):
        validate_deploy_settings(settings)


@pytest.mark.parametrize(
    ("deploy_mode", "auth_mode", "extra"),
    [
        ("standalone", "local", {}),
        ("standalone", "public_password", {}),
        (
            "cloud",
            "oidc",
            {"OIDC_CLIENT_ID": "client-1", "OIDC_ISSUER": "https://idp.example.com"},
        ),
        ("extranet", "public_password", {"SYNC_SERVICE_TOKENS": "tok-1"}),
    ],
)
def test_failfast_allows_contract_auth_mode_combinations(
    monkeypatch,
    deploy_mode,
    auth_mode,
    extra,
):
    settings = make_settings(monkeypatch, DEPLOY_MODE=deploy_mode, AUTH_MODE=auth_mode, **extra)
    validate_deploy_settings(settings)


@pytest.mark.parametrize(
    ("deploy_mode", "auth_mode", "extra"),
    [
        ("standalone", "public_password", {}),
        ("standalone", "local", {}),
        (
            "cloud",
            "oidc",
            {"OIDC_CLIENT_ID": "client-1", "OIDC_ISSUER": "https://idp.example.com"},
        ),
        (
            "intranet",
            "intranet_header",
            {
                "SYNC_REMOTE_BASE_URL": "https://extranet.example.com",
                "SYNC_REMOTE_TOKEN": "pull-token",
            },
        ),
        ("extranet", "public_password", {"SYNC_SERVICE_TOKENS": "tok-1"}),
    ],
)
def test_failfast_requires_session_secret_for_every_auth_mode(
    monkeypatch,
    deploy_mode,
    auth_mode,
    extra,
):
    settings = make_settings(
        monkeypatch,
        DEPLOY_MODE=deploy_mode,
        AUTH_MODE=auth_mode,
        AUTH_SESSION_SECRET="",
        **extra,
    )
    with pytest.raises(RuntimeError, match="AUTH_SESSION_SECRET is required"):
        validate_deploy_settings(settings)


def test_failfast_accepts_rotation_list_without_single_secret(monkeypatch):
    # 自检口径：AUTH_SESSION_SECRET / AUTH_SESSION_SECRETS 任一非空即可启动
    settings = make_settings(
        monkeypatch,
        AUTH_SESSION_SECRET="",
        AUTH_SESSION_SECRETS="new-secret,old-secret",
    )

    validate_deploy_settings(settings)

    # 列表第一个是签名 secret，回写单值读取点
    assert settings.auth_session_secret == "new-secret"
    assert settings.auth_session_secret_list == ["new-secret", "old-secret"]


def test_failfast_rejects_invalid_trusted_proxy_cidr(monkeypatch):
    settings = make_settings(monkeypatch, AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8,not-a-cidr")
    with pytest.raises(RuntimeError, match="AUTH_TRUSTED_PROXY_CIDRS"):
        validate_deploy_settings(settings)


def test_intranet_without_trusted_proxy_cidrs_warns_but_starts(monkeypatch, caplog):
    settings = make_settings(monkeypatch, **intranet_env())
    with caplog.at_level("WARNING", logger="app.core.deploy_checks"):
        validate_deploy_settings(settings)
    assert any("AUTH_TRUSTED_PROXY_CIDRS" in record.message for record in caplog.records)


def test_intranet_with_trusted_proxy_cidrs_does_not_warn(monkeypatch, caplog):
    settings = make_settings(monkeypatch, **intranet_env(AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8"))
    with caplog.at_level("WARNING", logger="app.core.deploy_checks"):
        validate_deploy_settings(settings)
    assert not any("AUTH_TRUSTED_PROXY_CIDRS" in record.message for record in caplog.records)


def test_failfast_intranet_rejects_ingestion_override(monkeypatch):
    settings = make_settings(monkeypatch, **intranet_env(CAPABILITY_INGESTION="true"))
    with pytest.raises(RuntimeError, match="CAPABILITY_INGESTION"):
        validate_deploy_settings(settings)


def test_failfast_extranet_requires_service_tokens(monkeypatch):
    settings = make_settings(monkeypatch, DEPLOY_MODE="extranet")
    with pytest.raises(RuntimeError, match="SYNC_SERVICE_TOKENS"):
        validate_deploy_settings(settings)


def test_failfast_oidc_requires_client_id(monkeypatch):
    settings = make_settings(
        monkeypatch,
        DEPLOY_MODE="cloud",
        AUTH_MODE="oidc",
        OIDC_AUTHORIZATION_ENDPOINT="https://idp.example.com/auth",
        OIDC_TOKEN_ENDPOINT="https://idp.example.com/token",
    )
    with pytest.raises(RuntimeError, match="OIDC_CLIENT_ID"):
        validate_deploy_settings(settings)


def test_failfast_oidc_requires_issuer_or_explicit_endpoints(monkeypatch):
    settings = make_settings(
        monkeypatch,
        DEPLOY_MODE="cloud",
        AUTH_MODE="oidc",
        OIDC_CLIENT_ID="client-1",
    )
    with pytest.raises(RuntimeError, match="OIDC_ISSUER"):
        validate_deploy_settings(settings)


def test_failfast_consumer_pull_requires_remote_config(monkeypatch):
    settings = make_settings(monkeypatch, DEPLOY_MODE="intranet", AUTH_MODE="intranet_header")
    with pytest.raises(RuntimeError, match="SYNC_REMOTE_BASE_URL"):
        validate_deploy_settings(settings)


def test_valid_mode_combinations_pass_failfast(monkeypatch):
    validate_deploy_settings(make_settings(monkeypatch))
    validate_deploy_settings(make_settings(monkeypatch, DEPLOY_MODE="cloud"))
    validate_deploy_settings(
        make_settings(monkeypatch, DEPLOY_MODE="extranet", SYNC_SERVICE_TOKENS="tok-1,tok-2"),
    )
    validate_deploy_settings(make_settings(monkeypatch, **intranet_env()))
    validate_deploy_settings(
        make_settings(
            monkeypatch,
            DEPLOY_MODE="intranet",
            AUTH_MODE="intranet_header",
            SYNC_PULL_ENABLED="false",
        ),
    )


# --- GET /api/meta/runtime ---


def test_runtime_endpoint_standalone_defaults(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    response = client.get("/api/meta/runtime")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert response.json() == {
        "deploy_mode": "standalone",
        "instance_id": "standalone",
        "capabilities": {
            "ingestion": True,
            "sync_publisher": False,
            "sync_consumer": False,
            "embedding": False,
            "search": True,
        },
        "auth_mode": "public_password",
        "auth_guest_enabled": False,
        "auth_membership_mapping": {
            "status": "empty",
            "default_workspaces": [],
            "department_workspaces": [],
        },
        "app_version": get_settings().app_version,
    }


def test_runtime_endpoint_reflects_intranet_without_login(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        **intranet_env(
            INSTANCE_ID="intranet-01",
            AUTH_DEFAULT_WORKSPACE_CODES="planning_intel:viewer",
            AUTH_DEPARTMENT_WORKSPACE_MAP="规划部:ai_tools:member",
        ),
    )
    response = client.get("/api/meta/runtime")
    assert response.status_code == 200
    payload = response.json()
    assert payload["deploy_mode"] == "intranet"
    assert payload["instance_id"] == "intranet-01"
    assert payload["auth_mode"] == "intranet_header"
    assert payload["capabilities"] == {
        "ingestion": False,
        "sync_publisher": False,
        "sync_consumer": True,
        "embedding": True,
        "search": True,
    }
    assert payload["auth_membership_mapping"] == {
        "status": "configured",
        "default_workspaces": [{"workspace_code": "planning_intel", "workspace_role": "viewer"}],
        "department_workspaces": [
            {"department": "规划部", "workspace_code": "ai_tools", "workspace_role": "member"}
        ],
    }


def test_csrf_enabled_deploy_modes_require_double_submit_token(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, DEPLOY_MODE="cloud")
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    csrf_token = client.cookies.get("infowatchtower_csrf")
    assert csrf_token

    missing = client.post("/api/sync-runs", json={})
    assert missing.status_code == 403
    assert missing.json()["detail"] == {"code": "csrf_failed"}

    accepted = client.post("/api/sync-runs", json={}, headers={"X-CSRF-Token": csrf_token})
    assert accepted.status_code == 200


def test_csrf_exemption_covers_invite_accept_but_not_revoke(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, DEPLOY_MODE="cloud")
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    csrf_token = client.cookies.get("infowatchtower_csrf")
    assert csrf_token

    def create_invite(email: str) -> str:
        response = client.post(
            "/api/auth/invites",
            json={
                "email": email,
                "role_code": "viewer",
                "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert response.status_code == 200
        return response.json()["code"]

    # revoke 是 super_admin 会话鉴权写操作，不在豁免面内：缺 X-CSRF-Token 必须 403
    revoke_code = create_invite("revokee@example.com")
    rejected = client.post(f"/api/auth/invites/{revoke_code}/revoke")
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == {"code": "csrf_failed"}

    revoked = client.post(
        f"/api/auth/invites/{revoke_code}/revoke",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert revoked.status_code == 200

    # 匿名 accept 属于豁免面（受邀人没有会话也拿不到 CSRF cookie），不应被 CSRF 拦下
    accept_code = create_invite("invitee@example.com")
    accepted = client.post(
        f"/api/auth/invites/{accept_code}/accept",
        json={"username": "invitee", "display_name": "受邀人", "password": "new-password"},
    )
    assert accepted.status_code == 200


def test_extranet_sync_feed_requires_service_token_and_returns_page(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="extranet",
        SYNC_SERVICE_TOKENS="feed-token",
    )
    engine = get_engine()
    assert engine is not None
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            DataSource(
                global_id="source-feed-001",
                origin_instance_id="extranet-test",
                revision=3,
                content_hash="source-hash-v3",
                workspace_code="shared",
                domain_code="ai",
                visibility_scope="public",
                sync_policy="public_to_intranet",
                source_type="rss",
                name="Feed Source",
                url="https://example.com/feed.xml",
            ),
        )
        session.commit()

    unauthorized = client.get("/api/sync/feed", params={"object_type": "data_sources"})
    assert unauthorized.status_code == 401

    manifest = client.get(
        "/api/sync/feed/manifest",
        headers={"Authorization": "Bearer feed-token"},
    )
    assert manifest.status_code == 200
    assert "data_sources" in manifest.json()["object_types"]

    page = client.get(
        "/api/sync/feed",
        params={"object_type": "data_sources", "limit": 1},
        headers={"Authorization": "Bearer feed-token"},
    )
    assert page.status_code == 200
    payload = page.json()
    assert payload["object_type"] == "data_sources"
    assert payload["next_cursor"]
    assert payload["records"][0]["event_id"]
    assert payload["records"][0]["object_global_id"] == "source-feed-001"
    assert payload["records"][0]["payload"]["url"] == "https://example.com/feed.xml"


def test_extranet_sync_feed_excludes_strategy_loop_private_objects(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="extranet",
        SYNC_SERVICE_TOKENS="feed-token",
    )
    engine = get_engine()
    assert engine is not None
    Session = sessionmaker(bind=engine)
    with Session() as session:
        requirement = Requirement(
            global_id="requirement-feed-forbidden",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="requirement-hash-v1",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            title="不应进入 feed 的内部需求",
            description="即使字段看起来可同步，也必须被 feed 对象集合排除。",
            status="open",
        )
        task = TopicTask(
            global_id="topic-task-feed-forbidden",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="task-hash-v1",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            requirement=requirement,
            title="不应进入 feed 的内部任务",
            status="open",
        )
        session.add_all([requirement, task])
        session.commit()

    manifest = client.get(
        "/api/sync/feed/manifest",
        headers={"Authorization": "Bearer feed-token"},
    )
    assert manifest.status_code == 200
    assert "requirements" not in manifest.json()["object_types"]
    assert "topic_tasks" not in manifest.json()["object_types"]

    requirement_feed = client.get(
        "/api/sync/feed",
        params={"object_type": "requirements"},
        headers={"Authorization": "Bearer feed-token"},
    )
    assert requirement_feed.status_code == 400
    assert "object_type must be one of" in requirement_feed.json()["detail"]

    task_feed = client.get(
        "/api/sync/feed",
        params={"object_type": "topic_tasks"},
        headers={"Authorization": "Bearer feed-token"},
    )
    assert task_feed.status_code == 400
    assert "object_type must be one of" in task_feed.json()["detail"]


def test_extranet_sync_feed_excludes_local_collaboration_notifications(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="extranet",
        SYNC_SERVICE_TOKENS="feed-token",
    )
    engine = get_engine()
    assert engine is not None
    Session = sessionmaker(bind=engine)
    with Session() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        source = DataSource(
            global_id="source-feed-collab-boundary",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="source-collab-boundary-hash",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="Collaboration Boundary Source",
            url="https://example.com/collab.xml",
        )
        raw_item = RawItem(
            global_id="raw-feed-collab-boundary",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="raw-collab-boundary-hash",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="collab-boundary-001",
            source_title="Collaboration Boundary Raw",
            source_url="https://example.com/collab/raw",
            raw_content="raw evidence",
            fetched_at=utc_now(),
        )
        news_item = NewsItem(
            global_id="news-feed-collab-boundary",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="news-collab-boundary-hash",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            raw_item=raw_item,
            data_source=source,
            source_type="rss",
            source_name=source.name,
            source_url="https://example.com/collab/news",
            canonical_url="https://example.com/collab/news",
            source_title="Collaboration Boundary News",
            normalized_title="Collaboration Boundary News",
            dedupe_key="collab-boundary-news",
        )
        generated_news = GeneratedNews(
            global_id="generated-feed-collab-boundary",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="generated-collab-boundary-hash",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            news_item=news_item,
            category="基础竞争力",
            title="Collaboration Boundary Generated",
            generation_status="ready",
            generated_by="llm_v1",
        )
        report = DailyReport(
            global_id="daily-feed-collab-boundary",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="daily-collab-boundary-hash",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            day_key="2026-07-05",
            title="Collaboration Boundary Daily",
            status="published",
        )
        report_item = DailyReportItem(
            global_id="daily-item-feed-collab-boundary",
            origin_instance_id="extranet-test",
            revision=1,
            content_hash="daily-item-collab-boundary-hash",
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            daily_report=report,
            generated_news=generated_news,
            adoption_status=2,
        )
        session.add_all([source, raw_item, news_item, generated_news, report, report_item])
        session.flush()

        comment = Comment(user=user, daily_report_item=report_item, body="内网本地评论")
        reaction = Reaction(user=user, daily_report_item=report_item, reaction_type="like")
        rating = Rating(user=user, daily_report_item=report_item, score=5)
        watcher = ObjectWatcher(
            user=user,
            workspace_code="planning_intel",
            object_type="daily_report_item",
            object_id=report_item.id,
            active=True,
        )
        activity_event = ActivityEvent(
            workspace_code="planning_intel",
            domain_code="ai",
            actor_user_id=user.id,
            event_type="comment.created",
            object_type="comment",
            object_id="comment-feed-forbidden",
            target_object_type="daily_report_item",
            target_object_id=report_item.id,
            summary="本地评论不应同步",
            metadata_json={"daily_report_item_id": report_item.id},
            sync_policy="sync_allowed",
        )
        session.add_all([comment, reaction, rating, watcher, activity_event])
        session.flush()
        session.add_all(
            [
                Notification(
                    user=user,
                    workspace_code="planning_intel",
                    activity_event=activity_event,
                    priority="important",
                ),
                NotificationPreference(
                    user=user,
                    workspace_code="planning_intel",
                    event_type="comment.created",
                    in_app_enabled=True,
                ),
            ],
        )
        session.commit()

    manifest = client.get(
        "/api/sync/feed/manifest",
        headers={"Authorization": "Bearer feed-token"},
    )
    assert manifest.status_code == 200
    object_types = set(manifest.json()["object_types"])
    assert {
        "comments",
        "reactions",
        "ratings",
        "activity_events",
        "notifications",
        "notification_preferences",
        "object_watchers",
    }.isdisjoint(object_types)

    for object_type in (
        "comments",
        "reactions",
        "ratings",
        "activity_events",
        "notifications",
        "notification_preferences",
        "object_watchers",
    ):
        response = client.get(
            "/api/sync/feed",
            params={"object_type": object_type},
            headers={"Authorization": "Bearer feed-token"},
        )
        assert response.status_code == 400, object_type
        assert "object_type must be one of" in response.json()["detail"]


# --- ingestion API 门 ---


def test_intranet_gates_ingestion_write_endpoints_with_403(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, **{**intranet_env(), "AUTH_CSRF_ENABLED": "false"})
    for path in INGESTION_GATED_PATHS:
        response = client.post(path)
        assert response.status_code == 403, path
        assert response.json()["detail"] == {
            "code": "capability_disabled",
            "capability": "ingestion",
        }, path


def test_standalone_does_not_gate_ingestion_endpoints(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    for path in INGESTION_GATED_PATHS:
        response = client.post(path)
        # 能力门放行，落到既有登录检查（401），而不是 capability 403
        assert response.status_code == 401, path

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    imported = client.post("/api/sources/import-legacy-seeds")
    assert imported.status_code == 200


# --- 源定义写端点门（create/patch 关闭，workspace-link 消费侧配置保留） ---


def test_intranet_gates_source_definition_writes_with_403(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, **{**intranet_env(), "AUTH_CSRF_ENABLED": "false"})

    created = client.post("/api/sources")
    assert created.status_code == 403
    detail = created.json()["detail"]
    assert detail["code"] == "capability_disabled"
    assert detail["capability"] == "ingestion"
    # 错误信息必须解释：源是只读镜像，消费侧改用 workspace-link
    assert "只读镜像" in detail["message"]
    assert "workspace-link" in detail["message"]

    patched = client.patch("/api/sources/any-source-id")
    assert patched.status_code == 403
    assert patched.json()["detail"]["code"] == "capability_disabled"

    # workspace-link 是消费侧工作台配置（不进 sync feed），不挂 ingestion 门：
    # 未登录时落到既有登录检查（401），而不是 capability 403
    link = client.patch("/api/sources/any-source-id/workspace-link")
    assert link.status_code == 401


def test_standalone_does_not_gate_source_definition_writes(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    created = client.post(
        "/api/sources",
        json={
            "workspace_code": "planning_intel",
            "source_type": "rss",
            "name": "能力门放行源",
            "url": "https://example.com/gate-pass.xml",
        },
    )
    assert created.status_code == 201
    source_id = created.json()["source"]["id"]

    renamed = client.patch(
        f"/api/sources/{source_id}",
        params={"workspace_code": "planning_intel"},
        json={"name": "能力门放行源（改名）"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "能力门放行源（改名）"


# --- worker 执行侧能力门（第二道防线：手工投递进队列的任务也不跑） ---


def test_intranet_worker_jobs_refuse_ingestion_without_touching_db(monkeypatch, caplog):
    from app.ingestion.jobs import run_historical_backfill_job, run_workspace_ingestion_job
    from app.pipeline.daily import run_daily_pipeline_job

    # 不配置 DATABASE_URL：若能力门失守，job 会因缺库先炸而不是返回 skipped
    monkeypatch.delenv("DATABASE_URL", raising=False)
    make_settings(monkeypatch, **intranet_env())
    get_engine.cache_clear()

    expected = {
        "status": "skipped",
        "reason": "capability_ingestion_disabled",
        "workspace_code": "planning_intel",
    }
    with caplog.at_level("WARNING", logger="app.ingestion.jobs"):
        assert run_workspace_ingestion_job("planning_intel") == expected
        assert run_historical_backfill_job("planning_intel") == expected
        assert run_daily_pipeline_job("planning_intel") == expected
    refusals = [record for record in caplog.records if "capability_ingestion is disabled" in record.message]
    assert len(refusals) == 3


def test_standalone_worker_jobs_pass_capability_gate(monkeypatch):
    from app.ingestion.jobs import run_workspace_ingestion_job

    monkeypatch.delenv("DATABASE_URL", raising=False)
    make_settings(monkeypatch)
    get_engine.cache_clear()

    # standalone 能力门放行，落到既有的缺库报错，而不是被 skipped 挡下
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        run_workspace_ingestion_job("planning_intel")


# --- 部署预设（任务 B：rss-only / full / mirror 三种启动形式） ---


def mirror_env(**extra):
    """mirror 预设：standalone/cloud 形态 + 不采集 + sync consumer 拉取外部部署成果。"""
    env = {
        "DEPLOY_MODE": "cloud",
        "CAPABILITY_INGESTION": "false",
        "CAPABILITY_SYNC_CONSUMER": "true",
        "SYNC_PULL_ENABLED": "true",
        "SYNC_REMOTE_BASE_URL": "https://extranet.example.com",
        "SYNC_REMOTE_TOKEN": "pull-token",
    }
    env.update(extra)
    return env


def test_ingestion_source_type_allowlist_defaults_open_and_parses(monkeypatch):
    # full 预设：不写允许清单 = 空 = 全部允许
    assert make_settings(monkeypatch).ingestion_source_type_allowlist == []
    settings = make_settings(monkeypatch, INGESTION_SOURCE_TYPES=" rss, paper_rss ,,rss ")
    assert settings.ingestion_source_type_allowlist == ["rss", "paper_rss"]


def test_failfast_rejects_unknown_ingestion_source_types(monkeypatch):
    settings = make_settings(monkeypatch, INGESTION_SOURCE_TYPES="rss,no_such_type")
    with pytest.raises(RuntimeError, match="INGESTION_SOURCE_TYPES.*no_such_type"):
        validate_deploy_settings(settings)


def test_failfast_accepts_known_ingestion_source_types_including_wechat(monkeypatch):
    settings = make_settings(monkeypatch, INGESTION_SOURCE_TYPES="rss,paper_rss,wechat")
    validate_deploy_settings(settings)


@pytest.mark.parametrize("deploy_mode", ["standalone", "cloud"])
def test_mirror_preset_combination_passes_failfast(monkeypatch, deploy_mode):
    settings = make_settings(monkeypatch, **mirror_env(DEPLOY_MODE=deploy_mode))
    validate_deploy_settings(settings)
    assert settings.capability_ingestion is False
    assert settings.capability_sync_consumer is True
    assert settings.sync_pull_effective is True
    # mirror 只影响能力开关，不影响 embedding 等其它派生位
    assert settings.capability_search is True


def test_mirror_preset_without_remote_config_fails_failfast(monkeypatch):
    settings = make_settings(
        monkeypatch,
        **mirror_env(SYNC_REMOTE_BASE_URL="", SYNC_REMOTE_TOKEN=""),
    )
    with pytest.raises(RuntimeError, match="SYNC_REMOTE_BASE_URL"):
        validate_deploy_settings(settings)


class _AllowlistedRssAdapter:
    source_type = "rss"

    async def fetch(self, data_source) -> list[RawItemInput]:
        return [
            RawItemInput(
                entry_key="rss:allow:1",
                source_title="Allowlisted item",
                source_url="https://example.com/allow",
                raw_content="Body",
                published_at=datetime(2026, 7, 6, 8, tzinfo=UTC),
                raw_payload_json={"entry": 1},
            ),
        ]


class _ForbiddenCrawlerAdapter:
    source_type = "crawler"

    async def fetch(self, data_source) -> list[RawItemInput]:
        raise AssertionError("type-disabled source must not be fetched")


def _seed_two_type_workspace(session):
    workspace = Workspace(
        code="planning_intel",
        name="规划部情报工作台",
        description="",
        default_domain_code="ai",
    )
    rss_source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type="rss",
        name="RSS Source",
        url="https://example.com/rss.xml",
    )
    crawler_source = DataSource(
        workspace_code="shared",
        domain_code="ai",
        source_type="crawler",
        name="Crawler Source",
        url="https://example.com/site",
    )
    session.add_all(
        [
            WorkspaceSourceLink(
                workspace=workspace,
                data_source=rss_source,
                domain_code="ai",
                enabled=True,
            ),
            WorkspaceSourceLink(
                workspace=workspace,
                data_source=crawler_source,
                domain_code="ai",
                enabled=True,
            ),
        ],
    )
    session.commit()
    return rss_source, crawler_source


@pytest.mark.asyncio
async def test_rss_only_allowlist_filters_run_and_reports_skipped_type_disabled(monkeypatch):
    make_settings(monkeypatch, INGESTION_SOURCE_TYPES="rss")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    rss_source, crawler_source = _seed_two_type_workspace(session)

    registry = AdapterRegistry()
    registry.register(_AllowlistedRssAdapter())
    registry.register(_ForbiddenCrawlerAdapter())

    run = await run_workspace_ingestion(
        session,
        WorkspaceIngestionRequest(
            workspace_code="planning_intel",
            source_types=["rss", "crawler"],
        ),
        registry,
    )
    session.commit()

    # 呈现语义参照 skipped_unimplemented：计入 source_total、独立摘要计数、状态降级为 partial
    assert run.status == "partial"
    assert run.source_total == 2
    assert run.source_succeeded == 1
    assert run.source_failed == 0
    assert run.items_fetched == 1
    assert run.summary_json["source_skipped_type_disabled"] == 1
    entries = {entry["data_source_id"]: entry for entry in run.summary_json["sources"]}
    assert entries[rss_source.id]["status"] == "completed"
    disabled_entry = entries[crawler_source.id]
    assert disabled_entry["status"] == "skipped_type_disabled"
    assert "INGESTION_SOURCE_TYPES" in disabled_entry["error"]
    assert disabled_entry["fetched"] == 0


@pytest.mark.asyncio
async def test_all_sources_type_disabled_marks_run_skipped_type_disabled(monkeypatch):
    make_settings(monkeypatch, INGESTION_SOURCE_TYPES="paper_rss")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    _seed_two_type_workspace(session)

    run = await run_workspace_ingestion(
        session,
        WorkspaceIngestionRequest(
            workspace_code="planning_intel",
            source_types=["rss", "crawler"],
        ),
        AdapterRegistry(),
    )
    session.commit()

    assert run.status == "skipped_type_disabled"
    assert run.source_total == 2
    assert run.source_succeeded == 0
    assert run.summary_json["source_skipped_type_disabled"] == 2


@pytest.mark.asyncio
async def test_full_preset_empty_allowlist_does_not_filter_run(monkeypatch):
    make_settings(monkeypatch, INGESTION_SOURCE_TYPES="")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    rss_source, _ = _seed_two_type_workspace(session)

    registry = AdapterRegistry()
    registry.register(_AllowlistedRssAdapter())

    run = await run_workspace_ingestion(
        session,
        WorkspaceIngestionRequest(workspace_code="planning_intel", source_types=["rss"]),
        registry,
    )
    session.commit()

    assert run.status == "completed"
    assert run.source_total == 1
    assert run.summary_json["source_skipped_type_disabled"] == 0
    assert run.summary_json["sources"][0]["data_source_id"] == rss_source.id


# --- scripts/check_prod_deploy.py 用三份 env 样例实跑 ---

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_prod_deploy_checker():
    spec = importlib.util.spec_from_file_location(
        "check_prod_deploy",
        REPO_ROOT / "scripts" / "check_prod_deploy.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checker_passes_full_and_mirror_env_examples():
    checker = load_prod_deploy_checker()
    for env_name in ("env.production.example", "env.mirror.example"):
        errors = checker.check_prod_deploy(REPO_ROOT, REPO_ROOT / "deploy" / env_name)
        assert errors == [], env_name


def test_checker_passes_rss_only_env_variant(tmp_path):
    checker = load_prod_deploy_checker()
    base = (REPO_ROOT / "deploy" / "env.production.example").read_text(encoding="utf-8")
    env_file = tmp_path / "env.rss-only"
    env_file.write_text(base + "\nINGESTION_SOURCE_TYPES=rss,paper_rss\n", encoding="utf-8")
    assert checker.check_prod_deploy(REPO_ROOT, env_file) == []


def test_checker_rejects_unknown_source_types_and_broken_mirror_combo(tmp_path):
    checker = load_prod_deploy_checker()
    base = (REPO_ROOT / "deploy" / "env.production.example").read_text(encoding="utf-8")

    bad_types = tmp_path / "env.bad-types"
    bad_types.write_text(base + "\nINGESTION_SOURCE_TYPES=rss,no_such_type\n", encoding="utf-8")
    errors = checker.check_prod_deploy(REPO_ROOT, bad_types)
    assert any("INGESTION_SOURCE_TYPES" in error for error in errors)

    broken_mirror = tmp_path / "env.broken-mirror"
    broken_mirror.write_text(
        base
        + "\nCAPABILITY_INGESTION=false\nCAPABILITY_SYNC_CONSUMER=true\nSYNC_PULL_ENABLED=true\n",
        encoding="utf-8",
    )
    errors = checker.check_prod_deploy(REPO_ROOT, broken_mirror)
    assert any("SYNC_REMOTE_BASE_URL" in error for error in errors)
    assert any("SYNC_REMOTE_TOKEN" in error for error in errors)

    pull_off_mirror = tmp_path / "env.pull-off-mirror"
    pull_off_mirror.write_text(
        base + "\nCAPABILITY_INGESTION=false\nCAPABILITY_SYNC_CONSUMER=true\n",
        encoding="utf-8",
    )
    errors = checker.check_prod_deploy(REPO_ROOT, pull_off_mirror)
    assert any("SYNC_PULL_ENABLED=true" in error for error in errors)


# --- /readyz 按形态回报能力位 ---


def test_readyz_reports_intranet_capabilities(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, **intranet_env(INSTANCE_ID="intranet-01"))
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["deploy_mode"] == "intranet"
    assert payload["instance_id"] == "intranet-01"
    assert payload["database"]["status"] == "ok"
    assert payload["capabilities"] == {
        "ingestion": False,
        "sync_publisher": False,
        "sync_consumer": True,
        "embedding": True,
        "search": True,
    }
