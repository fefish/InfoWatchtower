"""AUTH_TRUSTED_PROXY_CIDRS 信任边界：身份头与登录限流取 IP 共用同一 peer 判定。

- 配置 CIDR 后：intranet_header 身份头只信任来自白名单直连 peer 的请求，
  伪造来源按未登录处理；X-Forwarded-For 也只有受信 peer 递来的才采信。
- 未配置 CIDR：身份头沿用旧行为（部署层保证网关独占），限流一律用直连 peer IP。
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.core.security import peer_in_trusted_proxies
from app.main import create_app

INTRANET_IDENTITY_HEADERS = {
    "X-Employee-No": "E100",
    "X-Employee-Name": "%E5%86%85%E7%BD%91%E7%94%A8%E6%88%B7",
}


def make_client(monkeypatch, tmp_path, *, client_addr=("testclient", 50000), **env):
    database_path = tmp_path / "trusted_proxy.sqlite"
    base_env = {
        "DATABASE_URL": f"sqlite:///{database_path}",
        "AUTH_SESSION_SECRET": "test-session-secret",
        "AUTH_BOOTSTRAP_ADMIN_USERNAME": "admin",
        "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "password",
        "AUTH_TRUSTED_PROXY_CIDRS": "",
    }
    base_env.update(env)
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app(), client=client_addr)


def intranet_header_env(**extra):
    env = {
        "AUTH_MODE": "intranet_header",
        "AUTH_AUTO_PROVISION": "true",
        "AUTH_DEFAULT_ROLE": "viewer",
        "AUTH_DEFAULT_WORKSPACE_CODES": "planning_intel:viewer",
    }
    env.update(extra)
    return env


# --- peer_in_trusted_proxies 单元语义 ---


def test_peer_trust_returns_none_when_cidrs_unconfigured(monkeypatch, tmp_path):
    make_client(monkeypatch, tmp_path)
    settings = get_settings()
    assert peer_in_trusted_proxies("10.1.2.3", settings) is None
    assert peer_in_trusted_proxies(None, settings) is None


def test_peer_trust_matches_configured_cidrs(monkeypatch, tmp_path):
    make_client(
        monkeypatch,
        tmp_path,
        AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8, ::1/128",
    )
    settings = get_settings()
    assert peer_in_trusted_proxies("10.1.2.3", settings) is True
    assert peer_in_trusted_proxies("::1", settings) is True
    assert peer_in_trusted_proxies("203.0.113.9", settings) is False
    # 非 IP 的 peer（如 TestClient 默认 "testclient"）与缺失 peer 一律 fail-closed
    assert peer_in_trusted_proxies("testclient", settings) is False
    assert peer_in_trusted_proxies(None, settings) is False


# --- intranet_header 身份头来源校验 ---


def test_identity_headers_accepted_from_trusted_peer(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        client_addr=("10.0.0.9", 40000),
        **intranet_header_env(AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8"),
    )
    response = client.get("/api/auth/me", headers=INTRANET_IDENTITY_HEADERS)
    assert response.status_code == 200
    assert response.json()["user"]["employee_no"] == "E100"


def test_identity_headers_rejected_from_untrusted_peer(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        client_addr=("203.0.113.9", 40000),
        **intranet_header_env(AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8"),
    )
    response = client.get("/api/auth/me", headers=INTRANET_IDENTITY_HEADERS)
    assert response.status_code == 401


def test_identity_headers_rejected_even_with_forged_xff(monkeypatch, tmp_path):
    # 信任判定只看直连 socket peer，攻击者伪造 X-Forwarded-For 假装来自网关也没用
    client = make_client(
        monkeypatch,
        tmp_path,
        client_addr=("203.0.113.9", 40000),
        **intranet_header_env(AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8"),
    )
    response = client.get(
        "/api/auth/me",
        headers={**INTRANET_IDENTITY_HEADERS, "X-Forwarded-For": "10.0.0.9"},
    )
    assert response.status_code == 401


def test_identity_headers_keep_legacy_behavior_when_cidrs_unconfigured(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, **intranet_header_env())
    response = client.get("/api/auth/me", headers=INTRANET_IDENTITY_HEADERS)
    assert response.status_code == 200
    assert response.json()["user"]["external_provider"] == "intranet_header"


# --- 登录限流取 IP 的信任判定 ---


def _fail_login(client, forwarded_for=None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    return client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "bad"},
        headers=headers,
    )


def test_rotating_forged_xff_cannot_bypass_login_rate_limit(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        client_addr=("203.0.113.9", 40000),
        AUTH_MODE="public_password",
        AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8",
    )
    for index in range(5):
        assert _fail_login(client, forwarded_for=f"9.9.9.{index}").status_code == 401
    limited = _fail_login(client, forwarded_for="9.9.9.99")
    assert limited.status_code == 429


def test_rotating_xff_cannot_bypass_rate_limit_when_cidrs_unconfigured(monkeypatch, tmp_path):
    # 未配置 CIDR 时没有任何 peer 受信，X-Forwarded-For 一律不采信，直接用直连 peer IP
    client = make_client(
        monkeypatch,
        tmp_path,
        client_addr=("203.0.113.9", 40000),
        AUTH_MODE="public_password",
    )
    for index in range(5):
        assert _fail_login(client, forwarded_for=f"9.9.9.{index}").status_code == 401
    limited = _fail_login(client, forwarded_for="9.9.9.99")
    assert limited.status_code == 429


def test_xff_first_hop_is_honored_only_from_trusted_proxy(monkeypatch, tmp_path):
    client = make_client(
        monkeypatch,
        tmp_path,
        client_addr=("10.0.0.9", 40000),
        AUTH_MODE="public_password",
        AUTH_TRUSTED_PROXY_CIDRS="10.0.0.0/8",
    )
    for _ in range(5):
        assert _fail_login(client, forwarded_for="1.1.1.1").status_code == 401
    # 受信代理递来的 XFF 第一跳被采信：同一真实来源触发限流
    assert _fail_login(client, forwarded_for="1.1.1.1").status_code == 429
    # 不同真实来源（XFF 变化）落在不同限流桶，仍是 401 而不是 429
    assert _fail_login(client, forwarded_for="2.2.2.2").status_code == 401
