import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.auth import _safe_relative_redirect
from app.auth.passwords import hash_password
from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.feedback import AuditLog
from app.models.identity import Role, User
from app.models.labels import Label, LabelSet
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceSection

# 测试专用 RSA-1024 密钥（仅用于本地 mock JWKS 验签，勿用于任何真实场景）
TEST_RSA_N = int(
    "0x8e832348c122ff8e8ff84acb85a2379a98e020fc49db63cdfa70f6cde3feec6b"
    "40265132497c9a8f7a0a2700422275ddb3cfefc13398cf1feaf9cc76aac69a2d"
    "fe3b9a103a75b1c590d0ca638ea154e038c4df7df0c86b246546ff5e7f7d4558"
    "13757e0922fb1bd7c0e921b59e8017523b2f9bf7861d144b08529517f36571b9",
    16,
)
TEST_RSA_D = int(
    "0x1e771641e557cffdeff50a383bd713bfeed26afac3e72c8cc9ef0033bf7bad9a"
    "b7d9f91da0ec0c3683c64bd4184f39972d6b543b9f0619b11f104b8f4aaeae22"
    "b7da61ee1dda2a6f0211237969597c77a8909891314b7d5f8ac32b41e2b0af2f"
    "b1a240c73e1734d84880c8631050504efb86878066cec9bfb7c8cdbfd3323349",
    16,
)
TEST_RSA_E = 65537


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_segment(payload: dict) -> str:
    return _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def make_test_jwks(kid: str = "test-key") -> dict:
    key_len = (TEST_RSA_N.bit_length() + 7) // 8
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url(TEST_RSA_N.to_bytes(key_len, "big")),
                "e": _b64url(TEST_RSA_E.to_bytes(3, "big")),
            },
        ],
    }


def sign_id_token(
    claims: dict,
    *,
    alg: str = "RS256",
    kid: str = "test-key",
    tamper: bool = False,
) -> str:
    header = {"alg": alg, "typ": "JWT"}
    if kid:
        header["kid"] = kid
    signing_input = f"{_jwt_segment(header)}.{_jwt_segment(claims)}"
    if alg == "none":
        return f"{signing_input}."
    digest_info = (
        bytes.fromhex("3031300d060960864801650304020105000420")
        + hashlib.sha256(signing_input.encode("ascii")).digest()
    )
    key_len = (TEST_RSA_N.bit_length() + 7) // 8
    padded = b"\x00\x01" + b"\xff" * (key_len - len(digest_info) - 3) + b"\x00" + digest_info
    signature = pow(int.from_bytes(padded, "big"), TEST_RSA_D, TEST_RSA_N).to_bytes(key_len, "big")
    if tamper:
        signature = bytes([signature[0] ^ 0x01]) + signature[1:]
    return f"{signing_input}.{_b64url(signature)}"


class FakeOidcResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeOidcClient:
    token_requests: list[dict] = []
    userinfo_headers: list[dict] = []
    token_payload: dict = {"access_token": "access-token-1", "token_type": "Bearer"}
    userinfo_payload: dict = {
        "sub": "oidc-user-001",
        "email": "oidc-user@example.com",
        "preferred_username": "oidc-user",
        "name": "OIDC 用户",
        "department": "战略部",
    }

    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url: str, data: dict):
        self.token_requests.append({"url": url, "data": data})
        return FakeOidcResponse(dict(self.token_payload))

    def get(self, url: str, headers: dict | None = None):
        self.userinfo_headers.append(headers or {})
        return FakeOidcResponse(dict(self.userinfo_payload))


def make_client(monkeypatch, tmp_path, **env):
    database_path = tmp_path / "auth.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME", "规划部管理员")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app()), engine


def oidc_env(**extra):
    env = {
        "AUTH_MODE": "oidc",
        "AUTH_AUTO_PROVISION": "true",
        "AUTH_DEFAULT_ROLE": "viewer",
        "OIDC_PROVIDER": "example_oidc",
        "OIDC_CLIENT_ID": "client-1",
        "OIDC_CLIENT_SECRET": "secret-1",
        "OIDC_AUTHORIZATION_ENDPOINT": "https://idp.example.com/oauth/authorize",
        "OIDC_TOKEN_ENDPOINT": "https://idp.example.com/oauth/token",
        "OIDC_USERINFO_ENDPOINT": "https://idp.example.com/oauth/userinfo",
        "OIDC_REDIRECT_URL": "https://app.example.com/api/auth/oidc/callback",
        "OIDC_POST_LOGIN_REDIRECT_URL": "https://app.example.com/",
    }
    env.update(extra)
    return env


def test_public_password_login_sets_session_and_returns_current_user(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")

    response = client.post("/api/auth/login", json={"username": "admin", "password": "password"})

    assert response.status_code == 200
    assert "infowatchtower_session" in response.headers["set-cookie"]
    payload = response.json()
    assert payload["user"]["display_name"] == "规划部管理员"
    assert payload["user"]["roles"] == ["super_admin"]

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"


def test_oidc_start_redirects_to_provider_with_pkce(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, **oidc_env())

    response = client.get("/api/auth/oidc/start", follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert location.startswith("https://idp.example.com/oauth/authorize?")
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["client-1"]
    assert query["redirect_uri"] == ["https://app.example.com/api/auth/oidc/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid email profile"]
    assert client.cookies.get("infowatchtower_oidc_state") == query["state"][0]
    assert client.cookies.get("infowatchtower_oidc_verifier")
    assert client.cookies.get("infowatchtower_oidc_nonce")


def test_oidc_callback_provisions_local_user_and_sets_session(monkeypatch, tmp_path):
    FakeOidcClient.token_requests = []
    FakeOidcClient.userinfo_headers = []
    FakeOidcClient.token_payload = {"access_token": "access-token-1", "token_type": "Bearer"}
    FakeOidcClient.userinfo_payload = {
        "sub": "oidc-user-001",
        "email": "oidc-user@example.com",
        "preferred_username": "oidc-user",
        "name": "OIDC 用户",
        "department": "战略部",
    }
    monkeypatch.setattr("app.auth.oidc.httpx.Client", FakeOidcClient)
    client, _ = make_client(monkeypatch, tmp_path, **oidc_env())
    start = client.get("/api/auth/oidc/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    callback = client.get(
        "/api/auth/oidc/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "https://app.example.com/"
    assert FakeOidcClient.token_requests[0]["url"] == "https://idp.example.com/oauth/token"
    token_payload = FakeOidcClient.token_requests[0]["data"]
    assert token_payload["code"] == "code-1"
    assert token_payload["client_id"] == "client-1"
    assert token_payload["client_secret"] == "secret-1"
    assert token_payload["code_verifier"]
    assert FakeOidcClient.userinfo_headers[0]["Authorization"] == "Bearer access-token-1"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    payload = me.json()["user"]
    assert payload["external_provider"] == "example_oidc"
    assert payload["external_id"] == "oidc-user-001"
    assert payload["username"] == "oidc-user"
    assert payload["display_name"] == "OIDC 用户"
    assert payload["department"] == "战略部"
    assert payload["roles"] == ["viewer"]


def test_oidc_claim_mapping_redirect_and_auto_membership(monkeypatch, tmp_path):
    FakeOidcClient.token_requests = []
    FakeOidcClient.userinfo_headers = []
    FakeOidcClient.token_payload = {"access_token": "access-token-1", "token_type": "Bearer"}
    FakeOidcClient.userinfo_payload = {
        "corp": {
            "employee_id": "E-OIDC-001",
            "mail": "mapped@example.com",
            "cn": "映射用户",
            "dept_name": "战略部",
        },
    }
    monkeypatch.setattr("app.auth.oidc.httpx.Client", FakeOidcClient)
    client, engine = make_client(
        monkeypatch,
        tmp_path,
        **oidc_env(
            OIDC_CLAIM_EXTERNAL_ID="corp.employee_id",
            OIDC_CLAIM_EMPLOYEE_NO="corp.employee_id",
            OIDC_CLAIM_USERNAME="corp.mail",
            OIDC_CLAIM_DISPLAY_NAME="corp.cn",
            OIDC_CLAIM_DEPARTMENT="corp.dept_name",
            OIDC_CLAIM_EMAIL="corp.mail",
            AUTH_DEFAULT_WORKSPACE_CODES="planning_intel:viewer",
            AUTH_DEPARTMENT_WORKSPACE_MAP="战略部:ai_tools:member",
        ),
    )
    start = client.get(
        "/api/auth/oidc/start",
        params={"next": "/daily-reports?day=2026-07-05"},
        follow_redirects=False,
    )
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    callback = client.get(
        "/api/auth/oidc/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/daily-reports?day=2026-07-05"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    payload = me.json()["user"]
    assert payload["external_provider"] == "example_oidc"
    assert payload["external_id"] == "E-OIDC-001"
    assert payload["employee_no"] == "E-OIDC-001"
    assert payload["username"] == "mapped@example.com"
    assert payload["display_name"] == "映射用户"
    assert payload["department"] == "战略部"

    Session = sessionmaker(bind=engine)
    with Session() as session:
        user = session.scalar(select(User).where(User.external_id == "E-OIDC-001"))
        assert user is not None
        memberships = session.scalars(
            select(WorkspaceMembership)
            .join(Workspace)
            .where(WorkspaceMembership.user_id == user.id)
            .order_by(Workspace.code),
        ).all()
        assert [(membership.workspace.code, membership.workspace_role) for membership in memberships] == [
            ("ai_tools", "member"),
            ("planning_intel", "viewer"),
        ]


def test_oidc_start_configuration_error_redirects_to_login(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")

    response = client.get("/api/auth/oidc/start", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/login?auth_error=oidc_not_configured"


def test_oidc_callback_provider_error_redirects_to_login(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, **oidc_env())
    start = client.get("/api/auth/oidc/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    callback = client.get(
        "/api/auth/oidc/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=provider_error"


def test_oidc_callback_state_mismatch_redirects_to_login(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, **oidc_env())
    client.get("/api/auth/oidc/start", follow_redirects=False)

    callback = client.get(
        "/api/auth/oidc/callback",
        params={"code": "code-1", "state": "tampered-state"},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=state_mismatch"


def test_oidc_callback_token_exchange_error_redirects_to_login(monkeypatch, tmp_path):
    FakeOidcClient.token_requests = []
    FakeOidcClient.userinfo_headers = []
    FakeOidcClient.token_payload = {"token_type": "Bearer"}
    monkeypatch.setattr("app.auth.oidc.httpx.Client", FakeOidcClient)
    client, _ = make_client(monkeypatch, tmp_path, **oidc_env())
    start = client.get("/api/auth/oidc/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    callback = client.get(
        "/api/auth/oidc/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=token_exchange_failed"


def test_oidc_callback_identity_error_redirects_to_login(monkeypatch, tmp_path):
    FakeOidcClient.token_requests = []
    FakeOidcClient.userinfo_headers = []
    FakeOidcClient.token_payload = {"access_token": "access-token-1", "token_type": "Bearer"}
    FakeOidcClient.userinfo_payload = {"email": "missing-sub@example.com"}
    monkeypatch.setattr("app.auth.oidc.httpx.Client", FakeOidcClient)
    client, _ = make_client(monkeypatch, tmp_path, **oidc_env())
    start = client.get("/api/auth/oidc/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    callback = client.get(
        "/api/auth/oidc/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_local_http_can_disable_secure_session_cookie(monkeypatch, tmp_path):
    client, _ = make_client(
        monkeypatch,
        tmp_path,
        APP_ENV="production",
        AUTH_MODE="public_password",
        AUTH_SESSION_COOKIE_SECURE="false",
    )

    response = client.post("/api/auth/login", json={"username": "admin", "password": "password"})

    assert response.status_code == 200
    assert "secure" not in response.headers["set-cookie"].lower()
    me = client.get("/api/auth/me")
    assert me.status_code == 200


def test_auth_seed_creates_default_workspaces(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspaces = session.scalars(select(Workspace).order_by(Workspace.code)).all()
        assert [workspace.code for workspace in workspaces] == ["ai_tools", "planning_intel"]
        memberships = session.scalars(select(WorkspaceMembership)).all()
        assert len(memberships) == 2
        for workspace in workspaces:
            label_policy = workspace.config_json["label_policy"]
            assert label_policy["tagging_stages"] == ["news_generation", "post_dedupe_labeling"]
            if workspace.code == "ai_tools":
                assert label_policy["label_set_code"] == "ai_tools_categories"
                assert label_policy["allowed_primary_categories"] == [
                    "工具新功能",
                    "工具新案例",
                    "工具新技术",
                ]
                assert label_policy["secondary_labels_by_primary"] == {
                    "工具新功能": ["cursor", "claude code", "opencode", "codex"],
                    "工具新案例": ["cursor", "claude code", "opencode", "codex"],
                    "工具新技术": ["cursor", "claude code", "opencode", "codex"],
                }
            else:
                assert label_policy["label_set_code"] == "ai_sql_categories"
                assert label_policy["export_category_mode"] == "news_primary"
                assert label_policy["allowed_primary_categories"] == [
                    "AI Infra",
                    "AI 应用",
                    "测评技术",
                    "大厂动态",
                    "模型",
                    "算法",
                    "推理加速",
                    "训练技术",
                    "智能体",
                    "基础竞争力",
                ]
                assert label_policy["secondary_labels_by_primary"] == {}
            enabled_sections = {
                section.section_key
                for section in session.scalars(
                    select(WorkspaceSection).where(
                        WorkspaceSection.workspace_id == workspace.id,
                        WorkspaceSection.enabled.is_(True),
                    ),
                ).all()
            }
            assert {
                "dashboard",
                "source_management",
                "candidate_pool",
                "daily_reports",
                "weekly_reports",
                "historical_reports",
                "entity_milestones",
                "quality_archive",
                "requirements",
                "topic_tasks",
                "sync",
                "exports",
                "users",
                "audit_logs",
            }.issubset(enabled_sections)
            assert {"sources", "topics", "tool_catalog", "tool_runs"}.isdisjoint(enabled_sections)


def test_authenticated_user_can_load_workspace_sections(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    workspaces = client.get("/api/workspaces")
    assert workspaces.status_code == 200
    assert [item["code"] for item in workspaces.json()] == ["planning_intel", "ai_tools"]

    sections = client.get("/api/workspaces/ai_tools/sections")
    assert sections.status_code == 200
    section_keys = [item["section_key"] for item in sections.json()]
    assert section_keys == [
        "dashboard",
        "source_management",
        "ingestion_coverage",
        "candidate_pool",
        "daily_reports",
        "weekly_reports",
        "historical_reports",
        "entity_milestones",
        "quality_archive",
        "strategic_insights",
        "requirements",
        "topic_tasks",
        "sync",
        "exports",
        "users",
        "audit_logs",
    ]
    section_groups = {item["section_key"]: item["group"] for item in sections.json()}
    assert section_groups["dashboard"] == "today"
    assert section_groups["ingestion_coverage"] == "collect"
    assert section_groups["daily_reports"] == "curate"
    assert section_groups["historical_reports"] == "library"
    assert section_groups["audit_logs"] == "system"
    assert "topics" not in section_keys
    assert "tool_catalog" not in section_keys
    assert "tool_runs" not in section_keys

    label_policy = client.get("/api/workspaces/planning_intel/label-policy")
    assert label_policy.status_code == 200
    assert label_policy.json()["news_format_code"] == "company_sql_v1"
    assert label_policy.json()["export_category_mode"] == "news_primary"
    assert label_policy.json()["required_content_fields"] == [
        "background",
        "effects",
        "eventSummary",
        "technologyAndInnovation",
        "valueAndImpact",
    ]
    assert label_policy.json()["allowed_primary_categories"] == [
        "AI Infra",
        "AI 应用",
        "测评技术",
        "大厂动态",
        "模型",
        "算法",
        "推理加速",
        "训练技术",
        "智能体",
        "基础竞争力",
    ]

    updated_policy = client.patch(
        "/api/workspaces/planning_intel/label-policy",
        json={
            "label_set_code": "ai_sql_categories",
            "news_format_code": "company_sql_v1",
            "export_category_mode": "news_primary",
            "required_content_fields": [
                "background",
                "effects",
                "eventSummary",
                "technologyAndInnovation",
                "valueAndImpact",
            ],
            "allowed_primary_categories": ["AI 应用", "智能体", "基础竞争力", "具身智能"],
            "default_category": "AI 应用",
            "fallback_category": "具身智能",
        },
    )
    assert updated_policy.status_code == 200
    assert updated_policy.json()["allowed_primary_categories"] == [
        "AI 应用",
        "智能体",
        "基础竞争力",
        "具身智能",
    ]
    assert updated_policy.json()["secondary_labels_by_primary"] == {}
    assert updated_policy.json()["fallback_category"] == "具身智能"

    invalid_policy = client.patch(
        "/api/workspaces/planning_intel/label-policy",
        json={
            "label_set_code": "ai_sql_categories",
            "news_format_code": "company_sql_v1",
            "export_category_mode": "news_primary",
            "required_content_fields": ["background", "eventSummary"],
            "allowed_primary_categories": ["AI 应用", "智能体"],
            "default_category": "AI 应用",
            "fallback_category": "AI 应用",
        },
    )
    assert invalid_policy.status_code == 400

    tool_policy = client.get("/api/workspaces/ai_tools/label-policy")
    assert tool_policy.status_code == 200
    assert tool_policy.json()["label_set_code"] == "ai_tools_categories"
    assert tool_policy.json()["news_format_code"] == "tool_intel_v1"
    assert tool_policy.json()["allowed_primary_categories"] == [
        "工具新功能",
        "工具新案例",
        "工具新技术",
    ]
    assert tool_policy.json()["secondary_labels_by_primary"] == {
        "工具新功能": ["cursor", "claude code", "opencode", "codex"],
        "工具新案例": ["cursor", "claude code", "opencode", "codex"],
        "工具新技术": ["cursor", "claude code", "opencode", "codex"],
    }


def test_auth_seed_creates_default_label_set(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        label_set = session.scalar(select(LabelSet).where(LabelSet.code == "ai_sql_categories"))
        assert label_set is not None
        assert label_set.workspace_code == "planning_intel"
        assert session.scalar(select(Label).where(Label.name == "基础竞争力")) is not None
        source_tag_label_set = session.scalar(
            select(LabelSet).where(LabelSet.code == "planning_source_tags"),
        )
        assert source_tag_label_set is not None
        assert source_tag_label_set.workspace_code == "planning_intel"
        assert session.scalar(select(Label).where(Label.code == "AI工程能力:智能体")) is not None
        tool_label_set = session.scalar(
            select(LabelSet).where(LabelSet.code == "ai_tools_categories"),
        )
        assert tool_label_set is not None
        assert tool_label_set.workspace_code == "ai_tools"
        assert session.scalar(select(Label).where(Label.code == "工具新功能:cursor")) is not None
        hardware_label_set = session.scalar(
            select(LabelSet).where(LabelSet.code == "hardware_categories"),
        )
        assert hardware_label_set is not None
        assert hardware_label_set.workspace_code == "shared"
        assert hardware_label_set.domain_code == "hardware"
        assert hardware_label_set.config_json["domain_pack"] == "hardware"
        assert "compute_chips" in {
            board["code"] for board in hardware_label_set.config_json["boards"]
        }
        assert session.scalar(select(Label).where(Label.code == "算力芯片:GPU")) is not None


def test_super_admin_can_list_roles_and_update_user_roles(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        viewer_role = session.scalar(select(Role).where(Role.code == "viewer"))
        user = User(
            external_provider="local",
            external_id="analyst",
            username="analyst",
            display_name="分析员",
            password_hash=hash_password("password"),
            status="active",
            roles=[viewer_role],
        )
        session.add(user)
        session.commit()
        user_id = user.id

    roles = client.get("/api/roles")
    assert roles.status_code == 200
    assert {item["code"] for item in roles.json()} == {
        "analyst",
        "editor_admin",
        "super_admin",
        "viewer",
    }

    updated = client.patch(f"/api/users/{user_id}/roles", json={"role_codes": ["analyst"]})
    assert updated.status_code == 200
    assert updated.json()["roles"] == ["analyst"]


def test_permission_changes_explain_and_rollback_roles_membership_and_policy(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        viewer_role = session.scalar(select(Role).where(Role.code == "viewer"))
        user = User(
            external_provider="local",
            external_id="rollback-user",
            username="rollback-user",
            display_name="回滚用户",
            password_hash=hash_password("password"),
            status="active",
            roles=[viewer_role],
        )
        session.add(user)
        session.commit()
        user_id = user.id

    updated_roles = client.patch(f"/api/users/{user_id}/roles", json={"role_codes": ["analyst"]})
    assert updated_roles.status_code == 200

    role_changes = client.get("/api/identity/permission-changes", params={"workspace_code": "planning_intel"})
    assert role_changes.status_code == 200
    role_change = next(item for item in role_changes.json() if item["action"] == "users.roles.update")
    assert role_change["title"] == "全局角色变更"
    assert role_change["diffs"][0]["before"] == ["viewer"]
    assert role_change["diffs"][0]["after"] == ["analyst"]
    assert "全局角色从 viewer 调整为 analyst" in role_change["diffs"][0]["explanation"]

    rollback_roles = client.post(
        "/api/identity/permission-rollbacks",
        json={"audit_log_ids": [role_change["id"]]},
    )
    assert rollback_roles.status_code == 200
    assert rollback_roles.json()["results"][0]["status"] == "rolled_back"
    users = client.get("/api/users")
    assert next(item for item in users.json() if item["id"] == user_id)["roles"] == ["viewer"]

    added_member = client.post(
        "/api/workspaces/planning_intel/members",
        json={"user_id": user_id, "workspace_role": "member"},
    )
    assert added_member.status_code == 200
    member_changes = client.get("/api/identity/permission-changes", params={"workspace_code": "planning_intel"})
    member_change = next(item for item in member_changes.json() if item["action"] == "workspace.member.upsert")
    assert member_change["rollback_available"] is True
    assert any(diff["field"] == "workspace_role" for diff in member_change["diffs"])

    rollback_member = client.post(
        "/api/identity/permission-rollbacks",
        json={"audit_log_ids": [member_change["id"]]},
    )
    assert rollback_member.status_code == 200
    assert rollback_member.json()["results"][0]["status"] == "rolled_back"
    members = client.get("/api/workspaces/planning_intel/members")
    assert "rollback-user" not in {item["user"]["username"] for item in members.json()}

    updated_policy = client.patch(
        "/api/workspaces/planning_intel/feedback-policy",
        json={
            "viewer_can_react": True,
            "viewer_can_rate": True,
            "viewer_can_comment": False,
            "viewer_can_edit": False,
            "notify_on_comment": True,
            "notify_on_publish": False,
        },
    )
    assert updated_policy.status_code == 200
    policy_changes = client.get("/api/identity/permission-changes", params={"workspace_code": "planning_intel"})
    policy_change = next(item for item in policy_changes.json() if item["action"] == "workspace.feedback_policy.update")
    assert policy_change["diffs"][0]["label"] == "viewer 评论"
    assert policy_change["diffs"][0]["before"] == "开启"
    assert policy_change["diffs"][0]["after"] == "关闭"

    rollback_policy = client.post(
        "/api/identity/permission-rollbacks",
        json={"audit_log_ids": [policy_change["id"]]},
    )
    assert rollback_policy.status_code == 200
    assert rollback_policy.json()["results"][0]["status"] == "rolled_back"
    reread_policy = client.get("/api/workspaces/planning_intel/feedback-policy")
    assert reread_policy.json()["viewer_can_comment"] is True

    with Session() as session:
        rollback_audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "identity.permission_rollback"),
        ).all()
        assert len(rollback_audits) == 3


def test_intranet_header_auto_provisions_viewer(monkeypatch, tmp_path):
    client, engine = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="intranet_header",
        AUTH_AUTO_PROVISION="true",
        AUTH_DEFAULT_ROLE="viewer",
        AUTH_DEFAULT_WORKSPACE_CODES="planning_intel:viewer",
        AUTH_DEPARTMENT_WORKSPACE_MAP="规划部:ai_tools:member",
    )

    response = client.get(
        "/api/auth/me",
        headers={
            "X-Employee-No": "E001",
            "X-Employee-Name": "%E5%86%85%E7%BD%91%E7%94%A8%E6%88%B7",
            "X-Department": "%E8%A7%84%E5%88%92%E9%83%A8",
            "X-Email": "e001@example.com",
        },
    )

    assert response.status_code == 200
    payload = response.json()["user"]
    assert payload["external_provider"] == "intranet_header"
    assert payload["external_id"] == "E001"
    assert payload["employee_no"] == "E001"
    assert payload["display_name"] == "内网用户"
    assert payload["roles"] == ["viewer"]

    Session = sessionmaker(bind=engine)
    with Session() as session:
        user = session.scalar(select(User).where(User.external_id == "E001"))
        assert user is not None
        memberships = session.scalars(
            select(WorkspaceMembership)
            .join(Workspace)
            .where(WorkspaceMembership.user_id == user.id)
            .order_by(Workspace.code),
        ).all()
        assert [(membership.workspace.code, membership.workspace_role) for membership in memberships] == [
            ("ai_tools", "member"),
            ("planning_intel", "viewer"),
        ]


class JwksOidcClient(FakeOidcClient):
    """按 URL 路由的 mock：/jwks 返回 JWKS，其余 GET 走 userinfo。"""

    jwks_payload: dict = {}

    def get(self, url: str, headers: dict | None = None):
        if url.endswith("/jwks"):
            return FakeOidcResponse(dict(self.jwks_payload))
        return super().get(url, headers)


def _oidc_callback_with_id_token(
    monkeypatch,
    tmp_path,
    *,
    claims_mutator=None,
    sign_kwargs=None,
    env_extra=None,
):
    JwksOidcClient.token_requests = []
    JwksOidcClient.userinfo_headers = []
    JwksOidcClient.jwks_payload = make_test_jwks()
    monkeypatch.setattr("app.auth.oidc.httpx.Client", JwksOidcClient)
    env = oidc_env(
        OIDC_USERINFO_ENDPOINT="",
        OIDC_JWKS_URI="https://idp.example.com/jwks",
        OIDC_ISSUER="https://idp.example.com",
    )
    env.update(env_extra or {})
    client, _ = make_client(monkeypatch, tmp_path, **env)
    start = client.get("/api/auth/oidc/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    nonce = client.cookies.get("infowatchtower_oidc_nonce")
    assert nonce
    claims = {
        "iss": "https://idp.example.com",
        "aud": "client-1",
        "exp": int(time.time()) + 600,
        "nonce": nonce,
        "sub": "oidc-user-jwks",
        "preferred_username": "jwks-user",
        "name": "JWKS 用户",
    }
    if claims_mutator:
        claims_mutator(claims)
    JwksOidcClient.token_payload = {
        "access_token": "access-token-1",
        "token_type": "Bearer",
        "id_token": sign_id_token(claims, **(sign_kwargs or {})),
    }
    callback = client.get(
        "/api/auth/oidc/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )
    return client, callback


def test_oidc_id_token_with_valid_jwks_signature_logs_in(monkeypatch, tmp_path):
    client, callback = _oidc_callback_with_id_token(monkeypatch, tmp_path)

    assert callback.status_code == 307
    assert callback.headers["location"] == "https://app.example.com/"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    payload = me.json()["user"]
    assert payload["external_id"] == "oidc-user-jwks"
    assert payload["username"] == "jwks-user"


def test_oidc_id_token_with_tampered_signature_is_rejected(monkeypatch, tmp_path):
    _, callback = _oidc_callback_with_id_token(
        monkeypatch,
        tmp_path,
        sign_kwargs={"tamper": True},
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_oidc_id_token_signed_by_unknown_kid_is_rejected(monkeypatch, tmp_path):
    _, callback = _oidc_callback_with_id_token(
        monkeypatch,
        tmp_path,
        sign_kwargs={"kid": "rogue-key"},
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_oidc_id_token_nonce_mismatch_is_rejected(monkeypatch, tmp_path):
    def mutate(claims):
        claims["nonce"] = "attacker-replayed-nonce"

    _, callback = _oidc_callback_with_id_token(monkeypatch, tmp_path, claims_mutator=mutate)

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_oidc_id_token_missing_nonce_is_rejected(monkeypatch, tmp_path):
    def mutate(claims):
        claims.pop("nonce", None)

    _, callback = _oidc_callback_with_id_token(monkeypatch, tmp_path, claims_mutator=mutate)

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_oidc_id_token_alg_none_is_rejected_even_without_jwks(monkeypatch, tmp_path):
    _, callback = _oidc_callback_with_id_token(
        monkeypatch,
        tmp_path,
        sign_kwargs={"alg": "none", "kid": ""},
        env_extra={"OIDC_JWKS_URI": ""},
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_oidc_id_token_without_jwks_enforces_iss_aud_exp(monkeypatch, tmp_path):
    # 没有 JWKS 时退化为强校验 claims：iss/aud/exp 任一不对都拒绝
    for mutate in (
        lambda claims: claims.update(iss="https://evil.example.com"),
        lambda claims: claims.update(aud="other-client"),
        lambda claims: claims.update(exp=int(time.time()) - 10),
        lambda claims: claims.pop("exp"),
    ):
        _, callback = _oidc_callback_with_id_token(
            monkeypatch,
            tmp_path,
            claims_mutator=mutate,
            env_extra={"OIDC_JWKS_URI": ""},
        )
        assert callback.status_code == 307
        assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_oidc_id_token_without_jwks_accepts_strongly_checked_claims(monkeypatch, tmp_path):
    # 退化路径不验签（签名故意破坏），但 iss/aud/exp/nonce 全对即放行
    client, callback = _oidc_callback_with_id_token(
        monkeypatch,
        tmp_path,
        sign_kwargs={"tamper": True},
        env_extra={"OIDC_JWKS_URI": ""},
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "https://app.example.com/"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["external_id"] == "oidc-user-jwks"


def test_oidc_userinfo_path_still_verifies_id_token_nonce(monkeypatch, tmp_path):
    # 即便 userinfo 提供了完整 claims，随 token 返回的 id_token nonce 不对也必须拒绝
    def mutate(claims):
        claims["nonce"] = "attacker-replayed-nonce"

    _, callback = _oidc_callback_with_id_token(
        monkeypatch,
        tmp_path,
        claims_mutator=mutate,
        env_extra={"OIDC_USERINFO_ENDPOINT": "https://idp.example.com/oauth/userinfo"},
    )

    assert callback.status_code == 307
    assert callback.headers["location"] == "/login?auth_error=identity_resolution_failed"


def test_safe_relative_redirect_rejects_backslash_variants():
    # 浏览器把 URL 里的反斜杠规范化为斜杠，这些值等价于 //evil.com 协议相对跳转
    assert _safe_relative_redirect("/\\evil.com") == ""
    assert _safe_relative_redirect("/%5Cevil.com") == ""
    assert _safe_relative_redirect("/\\/evil.com") == ""
    assert _safe_relative_redirect("/%5C%2Fevil.com") == ""
    assert _safe_relative_redirect("//evil.com") == ""
    assert _safe_relative_redirect("/daily-reports?day=2026-07-05") == "/daily-reports?day=2026-07-05"


def test_oidc_start_ignores_backslash_next(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, **oidc_env())

    response = client.get(
        "/api/auth/oidc/start",
        params={"next": "/\\evil.com"},
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert client.cookies.get("infowatchtower_oidc_next") is None


def test_intranet_header_applies_stored_department_membership_mapping(monkeypatch, tmp_path):
    client, engine = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="intranet_header",
        AUTH_AUTO_PROVISION="true",
        AUTH_DEFAULT_ROLE="viewer",
        AUTH_DEFAULT_WORKSPACE_CODES="planning_intel:viewer",
        AUTH_DEPARTMENT_WORKSPACE_MAP="",
    )

    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "ai_tools"))
        assert workspace is not None
        config = dict(workspace.config_json or {})
        config["auth_membership_mapping"] = {
            "department_workspaces": [{"department": "规划部", "workspace_role": "member"}],
        }
        workspace.config_json = config
        session.commit()

    response = client.get(
        "/api/auth/me",
        headers={
            "X-Employee-No": "E002",
            "X-Employee-Name": "%E5%86%85%E7%BD%91%E7%94%A8%E6%88%B72",
            "X-Department": "%E8%A7%84%E5%88%92%E9%83%A8",
        },
    )

    assert response.status_code == 200
    with Session() as session:
        user = session.scalar(select(User).where(User.external_id == "E002"))
        assert user is not None
        memberships = session.scalars(
            select(WorkspaceMembership)
            .join(Workspace)
            .where(WorkspaceMembership.user_id == user.id)
            .order_by(Workspace.code),
        ).all()
        assert [(membership.workspace.code, membership.workspace_role) for membership in memberships] == [
            ("ai_tools", "member"),
            ("planning_intel", "viewer"),
        ]


# ---- AUTH_SESSION_SECRETS 多版本轮换（第一个签名、全部可验签） ----


def test_verify_session_token_accepts_any_secret_in_rotation_list():
    from app.auth.sessions import create_session_token, verify_session_token

    token = create_session_token("user-1", "old-secret", ttl_seconds=600)

    # 轮换后：新 secret 排第一（签名用），旧 secret 保留可验签 → 不掉线
    assert verify_session_token(token, ["new-secret", "old-secret"])["sub"] == "user-1"
    # 旧 secret 移出列表 → 旧 cookie 失效
    assert verify_session_token(token, ["new-secret"]) is None
    # 单值字符串入参保持兼容
    assert verify_session_token(token, "old-secret")["sub"] == "user-1"
    assert verify_session_token(token, "") is None
    assert verify_session_token(token, []) is None


def test_settings_session_secrets_first_signs_all_verify(monkeypatch):
    from app.core.config import Settings

    settings = Settings(AUTH_SESSION_SECRETS="new-secret, old-secret", AUTH_SESSION_SECRET="legacy")

    # 列表第一个是签名 secret（回写单值字段，签发/自检共用口径）
    assert settings.auth_session_secret == "new-secret"
    assert settings.auth_session_secret_list == ["new-secret", "old-secret"]

    # 未配置列表时回退单值 AUTH_SESSION_SECRET
    fallback = Settings(AUTH_SESSION_SECRETS="", AUTH_SESSION_SECRET="only-secret")
    assert fallback.auth_session_secret == "only-secret"
    assert fallback.auth_session_secret_list == ["only-secret"]


def test_session_cookie_survives_secret_rotation_until_old_secret_removed(monkeypatch, tmp_path):
    client, _ = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="public_password",
        AUTH_SESSION_SECRETS="old-secret",
    )
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    old_cookie = client.cookies.get("infowatchtower_session")
    assert old_cookie

    # 轮换：新 secret 上位签名，旧 secret 保留验签 → 旧 cookie 仍有效
    rotated, _ = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="public_password",
        AUTH_SESSION_SECRETS="new-secret,old-secret",
    )
    rotated.cookies.set("infowatchtower_session", old_cookie)
    assert rotated.get("/api/auth/me").status_code == 200

    # 旧 secret 移出列表 → 旧 cookie 失效
    retired, _ = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="public_password",
        AUTH_SESSION_SECRETS="new-secret",
    )
    retired.cookies.set("infowatchtower_session", old_cookie)
    assert retired.get("/api/auth/me").status_code == 401
