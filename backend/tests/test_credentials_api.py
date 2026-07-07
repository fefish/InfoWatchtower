"""WP4-B Provider 目录 + 凭据落库验收（generation-provider-design §10 断言 1-8）。

fixture provider：app.llm.provider.TRANSPORT 注入 httpx.MockTransport，
所有 chat/completions 调用不出进程；加密走 app/core/crypto.py（HKDF 派生 +
MultiFernet 轮换），secret 由 AUTH_SESSION_SECRET(S) 提供。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.llm.provider as provider
from app.auth.passwords import hash_password
from app.core.config import (
    GENERATION_PROVIDER_CATALOG_CODES,
    GENERATION_PROVIDERS,
    Settings,
    get_settings,
)
from app.core.crypto import CredentialCipher, credential_cipher
from app.llm.provider import resolve_generation_config
from app.main import create_app
from app.models.feedback import AuditLog
from app.models.identity import Role, User
from app.models.llm import LlmProviderCredential
from app.models.workspace import Workspace
from app.sync.feed import feed_page
from app.sync.records import PAYLOAD_BUILDERS, SYNC_FEED_OBJECT_TYPES
from tests.test_generation_provider import (
    FIXTURE_KEY,
    RecordingHandler,
    _create_viewer,
    _install_fixture_provider,
    _login,
    _pipeline_session,
    _run_pipeline,
    make_client,
)

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "config" / "contracts" / "llm_providers.json"
PLAIN_KEY = "sk-test-1234abcd"


def _ok_transport(monkeypatch) -> RecordingHandler:
    handler = RecordingHandler(
        lambda request, payload: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "pong"}}]},
        ),
    )
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    return handler


def _create_editor_admin(engine, username: str = "editor1", password: str = "editor-pass") -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        role = session.scalar(select(Role).where(Role.code == "editor_admin"))
        assert role is not None
        user = User(
            external_provider="local",
            external_id=username,
            username=username,
            display_name=username.title(),
            password_hash=hash_password(password),
            status="active",
            roles=[role],
        )
        session.add(user)
        session.commit()


def _post_credential(client, **overrides) -> dict:
    payload = {"provider": "deepseek", "api_key": PLAIN_KEY, "label": "测试"}
    payload.update(overrides)
    response = client.post("/api/generation/credentials", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --- 断言 1：GET /api/generation/providers 与契约逐字段一致、无凭据数据 ---


def test_providers_catalog_projects_contract_verbatim(monkeypatch, tmp_path):
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected = sorted(contract["catalog"], key=lambda entry: entry["sort_order"])
    assert tuple(entry["code"] for entry in expected) == GENERATION_PROVIDER_CATALOG_CODES
    assert len(expected) == 9
    # env 值域 = 目录 code + deprecated 别名 openai_compatible（config.py 与契约同步）
    assert set(GENERATION_PROVIDERS) == set(GENERATION_PROVIDER_CATALOG_CODES) | {
        "openai_compatible",
    }

    client, _engine = make_client(monkeypatch, tmp_path, filename="providers.sqlite")
    _login(client)
    response = client.get("/api/generation/providers")
    assert response.status_code == 200
    assert response.json()["catalog"] == expected
    # 纯静态目录：无任何凭据字段/密钥值
    body = response.json()
    for entry in body["catalog"]:
        assert set(entry) == {
            "code",
            "name",
            "default_base_url",
            "auth_header",
            "key_required",
            "common_models",
            "notes",
            "sort_order",
        }
    # 登录即可读（viewer 也行），未登录 401
    anonymous = TestClient(create_app())
    assert anonymous.get("/api/generation/providers").status_code == 401


# --- 断言 2：凭据录入——密文落库、masked 回显、目录默认 base_url、权限/校验 ---


def test_create_credential_encrypts_masks_and_defaults_base_url(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, filename="cred_create.sqlite")
    _login(client)

    body = _post_credential(client)
    assert body["provider"] == "deepseek"
    assert body["base_url"] == "https://api.deepseek.com/v1"  # 目录默认自动预填
    assert body["key_masked"] == "****abcd"
    assert body["label"] == "测试"
    assert PLAIN_KEY not in json.dumps(body)

    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.scalar(select(LlmProviderCredential))
        assert row is not None
        assert row.key_last4 == "abcd"
        assert PLAIN_KEY not in row.key_encrypted
        assert "sk-test" not in row.key_encrypted
        # 密文可用当前 secret 解密回原文（加密可逆性，仅测试侧核对）
        assert credential_cipher(get_settings()).decrypt(row.key_encrypted).plaintext == PLAIN_KEY

    # 随后任何 GET 只含 masked
    listed = client.get("/api/generation/credentials")
    assert listed.status_code == 200
    assert PLAIN_KEY not in listed.text
    assert listed.json()[0]["key_masked"] == "****abcd"

    # custom 不带 base_url 提交 422；带 base_url 可建（key_required=false 允许空 key）
    invalid = client.post(
        "/api/generation/credentials",
        json={"provider": "custom", "api_key": "sk-any", "label": "兜底"},
    )
    assert invalid.status_code == 422
    ok_custom = client.post(
        "/api/generation/credentials",
        json={"provider": "custom", "base_url": "https://gw.example/v1", "api_key": "sk-any"},
    )
    assert ok_custom.status_code == 201
    assert ok_custom.json()["label"] == "custom 凭据"  # label 缺省 "{provider} 凭据"

    # 目录外 provider 422（凭据表值域不含 env 别名 openai_compatible）
    assert (
        client.post(
            "/api/generation/credentials",
            json={"provider": "openai_compatible", "api_key": "sk-x"},
        ).status_code
        == 422
    )
    # key_required=true 的 provider 空 key 422
    assert (
        client.post(
            "/api/generation/credentials",
            json={"provider": "deepseek", "api_key": ""},
        ).status_code
        == 422
    )

    # 审计 detail 无明文（create）
    with Session() as session:
        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "generation.credential.create"),
        ).all()
        assert audits
        for audit in audits:
            text = json.dumps(audit.detail_json, ensure_ascii=False)
            assert PLAIN_KEY not in text
            assert "sk-any" not in text
            assert audit.detail_json.get("key_masked", "").startswith("****")


def test_credential_write_requires_super_admin_and_list_allows_editor_admin(
    monkeypatch,
    tmp_path,
):
    client, engine = make_client(monkeypatch, tmp_path, filename="cred_roles.sqlite")
    _login(client)
    body = _post_credential(client)

    _create_viewer(engine)
    viewer = TestClient(create_app())
    _login(viewer, "viewer1", "viewer-pass")
    assert (
        viewer.post(
            "/api/generation/credentials",
            json={"provider": "deepseek", "api_key": "sk-viewer"},
        ).status_code
        == 403
    )
    assert viewer.get("/api/generation/credentials").status_code == 403
    assert viewer.patch(
        f"/api/generation/credentials/{body['id']}",
        json={"label": "viewer 改名"},
    ).status_code == 403
    assert viewer.delete(f"/api/generation/credentials/{body['id']}").status_code == 403

    # editor_admin：读列表放宽（也只有 masked 视图），写仍然 403（§9.7）
    _create_editor_admin(engine)
    editor = TestClient(create_app())
    _login(editor, "editor1", "editor-pass")
    listed = editor.get("/api/generation/credentials")
    assert listed.status_code == 200
    assert PLAIN_KEY not in listed.text
    assert (
        editor.post(
            "/api/generation/credentials",
            json={"provider": "deepseek", "api_key": "sk-editor"},
        ).status_code
        == 403
    )


def test_update_credential_replaces_key_and_audits_masked(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, filename="cred_update.sqlite")
    _login(client)
    body = _post_credential(client)

    updated = client.patch(
        f"/api/generation/credentials/{body['id']}",
        json={"api_key": "sk-new-9999wxyz", "label": "换新 key"},
    )
    assert updated.status_code == 200
    assert updated.json()["key_masked"] == "****wxyz"
    assert "sk-new" not in updated.text

    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.scalar(select(LlmProviderCredential))
        assert "sk-new" not in row.key_encrypted
        assert credential_cipher(get_settings()).decrypt(row.key_encrypted).plaintext == (
            "sk-new-9999wxyz"
        )
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "generation.credential.update"),
        )
        assert audit is not None
        text = json.dumps(audit.detail_json, ensure_ascii=False)
        assert "sk-new" not in text and PLAIN_KEY not in text
        assert audit.detail_json["before"]["key_masked"] == "****abcd"
        assert audit.detail_json["after"]["key_masked"] == "****wxyz"


# --- 断言 3：generation_policy.credential_id——resolved 取凭据、生成调用带凭据 key ---


def test_policy_credential_id_resolves_and_validates(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, filename="cred_policy.sqlite")
    _login(client)
    body = _post_credential(client)

    updated = client.patch(
        "/api/workspaces/planning_intel/generation-policy",
        json={"credential_id": body["id"]},
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["policy"]["credential_id"] == body["id"]
    assert payload["resolved"]["key_source"] == "credential"
    assert payload["resolved"]["provider"] == "deepseek"
    assert payload["resolved"]["base_url_host"] == "api.deepseek.com"
    assert payload["resolved"]["credential_id"] == body["id"]
    assert payload["resolved"]["credential_label"] == "测试"
    assert PLAIN_KEY not in updated.text
    # admin 视角带 credential_options（masked）；「跟随实例 env」由前端置 null 首位
    options = payload["credential_options"]
    assert options and options[0]["key_masked"] == "****abcd"

    # 指向不存在/禁用凭据的 PATCH 422
    assert (
        client.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"credential_id": "no-such-credential"},
        ).status_code
        == 422
    )
    client.delete(f"/api/generation/credentials/{body['id']}")
    assert (
        client.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"credential_id": body["id"]},
        ).status_code
        == 422
    )

    # viewer 只见 resolved，不返回凭据清单
    _create_viewer(engine)
    viewer = TestClient(create_app())
    _login(viewer, "viewer1", "viewer-pass")
    viewer_read = viewer.get("/api/workspaces/planning_intel/generation-policy")
    assert viewer_read.status_code == 200
    assert viewer_read.json()["credential_options"] is None
    assert PLAIN_KEY not in viewer_read.text


def test_next_generation_call_carries_credential_key(monkeypatch):
    """fixture transport 断言：credential_id 命中后 Authorization 携带凭据 key。"""
    captured_headers: list[str] = []

    def _responder(request: httpx.Request, payload: dict) -> httpx.Response:
        captured_headers.append(request.headers.get("Authorization", ""))
        from tests.test_generation_provider import _completion_response, _quality_payload

        return _completion_response(_quality_payload())

    handler = RecordingHandler(_responder)
    _install_fixture_provider(monkeypatch, handler)  # env 配的是 FIXTURE_KEY
    monkeypatch.setenv("AUTH_SESSION_SECRET", "pipeline-secret")
    get_settings.cache_clear()

    session, workspace = _pipeline_session()
    cipher = credential_cipher(get_settings())
    credential = LlmProviderCredential(
        provider="moonshot",
        base_url="https://api.moonshot.cn/v1",
        key_encrypted=cipher.encrypt("sk-cred-5678efgh"),
        key_last4="efgh",
        label="月之暗面共享",
        enabled=True,
        created_by_id=_first_user_id(session),
    )
    session.add(credential)
    session.flush()
    config_json = dict(workspace.config_json or {})
    config_json["generation_policy"] = {"credential_id": credential.global_id}
    workspace.config_json = config_json
    session.flush()

    resolved = resolve_generation_config(workspace=workspace, session=session)
    assert resolved.key_source == "credential"
    assert resolved.api_key == "sk-cred-5678efgh"
    assert resolved.provider == "moonshot"
    assert resolved.base_url_host == "api.moonshot.cn"

    _run_pipeline(session)
    assert captured_headers, "fixture provider must be called"
    for header in captured_headers:
        assert header == "Bearer sk-cred-5678efgh"
        assert FIXTURE_KEY not in header


def _first_user_id(session) -> str:
    user = session.scalar(select(User))
    if user is not None:
        return user.id
    role = session.scalar(select(Role).where(Role.code == "super_admin"))
    if role is None:
        role = Role(code="super_admin", name="super admin")
        session.add(role)
        session.flush()
    user = User(
        external_provider="local",
        external_id="cred-owner",
        username="cred-owner",
        display_name="Cred Owner",
        password_hash="",
        status="active",
        roles=[role],
    )
    session.add(user)
    session.flush()
    return user.id


# --- 断言 4：软删后 credential_missing 降级——不回落 env、规则降级稿、ping 无外呼 ---


def test_disabled_credential_degrades_without_env_fallback(monkeypatch):
    def _fail_if_called(request: httpx.Request, payload: dict) -> httpx.Response:
        raise AssertionError("disabled credential must not reach the provider")

    handler = RecordingHandler(_fail_if_called)
    _install_fixture_provider(monkeypatch, handler)  # env 配了 FIXTURE_KEY 也不用
    monkeypatch.setenv("AUTH_SESSION_SECRET", "pipeline-secret")
    get_settings.cache_clear()

    session, workspace = _pipeline_session()
    cipher = credential_cipher(get_settings())
    credential = LlmProviderCredential(
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        key_encrypted=cipher.encrypt(PLAIN_KEY),
        key_last4="abcd",
        label="将被禁用",
        enabled=False,  # 软删后状态
        created_by_id=_first_user_id(session),
    )
    session.add(credential)
    session.flush()
    config_json = dict(workspace.config_json or {})
    config_json["generation_policy"] = {"credential_id": credential.global_id}
    workspace.config_json = config_json
    session.flush()

    resolved = resolve_generation_config(workspace=workspace, session=session)
    assert resolved.key_source == "credential_missing"
    assert resolved.api_key == ""  # env 配了 key 也不用（不回落 env）
    assert resolved.key_configured is False

    result = _run_pipeline(session)
    assert handler.requests == []
    summary = result.run.summary_json
    statuses = summary["generation_status"]
    assert statuses.get("fallback_needs_review", 0) >= 1  # 规则降级稿
    assert statuses.get("ready", 0) == 0
    for item in result.daily_report.items:
        assert item.generated_news.generated_by == "rule_v1:fallback"


def test_ping_workspace_with_disabled_credential_reports_key_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERATION_ENABLED", "true")
    monkeypatch.setenv("GENERATION_API_KEY", FIXTURE_KEY)
    client, _engine = make_client(monkeypatch, tmp_path, filename="cred_ping_missing.sqlite")
    _login(client)
    body = _post_credential(client)
    assert (
        client.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"credential_id": body["id"]},
        ).status_code
        == 200
    )
    deleted = client.delete(f"/api/generation/credentials/{body['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["enabled"] is False
    assert deleted.json()["disabled_at"] is not None

    # resolved 显式暴露 credential_missing（env 配了 key 也不回落）
    read = client.get("/api/workspaces/planning_intel/generation-policy")
    assert read.json()["resolved"]["key_source"] == "credential_missing"
    assert read.json()["resolved"]["key_configured"] is False

    handler = RecordingHandler()
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    ping = client.post("/api/generation/ping", json={"workspace_code": "planning_intel"})
    assert ping.status_code == 200
    assert ping.json()["error_code"] == "key_missing"
    assert handler.requests == [], "credential_missing must not reach the provider"


# --- 断言 5：ping by credential_id——探针外呼、审计含指针无 key ---


def test_ping_by_credential_id_probes_and_audits(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, filename="cred_ping.sqlite")
    _login(client)
    body = _post_credential(client)

    handler = _ok_transport(monkeypatch)
    ok = client.post("/api/generation/ping", json={"credential_id": body["id"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "ok"
    assert ok.json()["base_url_host"] == "api.deepseek.com"
    assert isinstance(ok.json()["latency_ms"], int)
    assert PLAIN_KEY not in ok.text
    # 探针确实用凭据 key 外呼
    assert handler.requests, "ping by credential must call the provider once"

    monkeypatch.setattr(
        provider,
        "TRANSPORT",
        httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "bad key"})),
    )
    auth_failed = client.post("/api/generation/ping", json={"credential_id": body["id"]})
    assert auth_failed.json()["error_code"] == "auth_failed"

    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.scalar(select(LlmProviderCredential))
        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "generation.ping"),
        ).all()
        assert len(audits) == 2
        for audit in audits:
            text = json.dumps(audit.detail_json, ensure_ascii=False)
            assert audit.detail_json["credential_id"] == body["id"]
            assert audit.detail_json["base_url_host"] == "api.deepseek.com"
            assert "status" in audit.detail_json and "latency_ms" in audit.detail_json
            assert PLAIN_KEY not in text
            assert row.key_encrypted not in text  # 密文也不进审计


# --- 断言 6：密钥轮换回归——旧 secret 保留可解密并重加密；直接丢弃则降级+审计 ---


def test_secret_rotation_reencrypts_and_dropped_secret_degrades(monkeypatch, tmp_path):
    # 用 secret A 录入凭据（AUTH_SESSION_SECRETS 首位=当前签名/加密 secret，
    # 覆盖 make_client 内置的单值 AUTH_SESSION_SECRET）
    monkeypatch.setenv("AUTH_SESSION_SECRETS", "secret-A")
    client, engine = make_client(monkeypatch, tmp_path, filename="cred_rotate.sqlite")
    _login(client)
    body = _post_credential(client)
    assert (
        client.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"credential_id": body["id"]},
        ).status_code
        == 200
    )

    # 轮换：新 secret B 放首位、旧 A 保留在尾部 → 仍可解密使用
    monkeypatch.setenv("AUTH_SESSION_SECRETS", "secret-B,secret-A")
    get_settings.cache_clear()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        resolved = resolve_generation_config(get_settings(), workspace=workspace, session=session)
        assert resolved.key_source == "credential"
        assert resolved.api_key == PLAIN_KEY
        session.commit()  # 解析路径完成 stale 重加密的落库
    with Session() as session:
        row = session.scalar(select(LlmProviderCredential))
        # 该行已被重加密：仅用 B 派生 key 即可单独解密
        only_b = CredentialCipher(["secret-B"])
        assert only_b.decrypt(row.key_encrypted).plaintext == PLAIN_KEY

    # 生成/ping 仍可用（轮换后走凭据 key）
    handler = _ok_transport(monkeypatch)
    get_settings.cache_clear()
    ping = client.post("/api/generation/ping", json={"credential_id": body["id"]})
    assert ping.json()["status"] == "ok"
    assert handler.requests

    # 直接丢弃当前加密 secret B（轮换列表只剩 C 与最早的 A，密文已是 B 加密）
    # → 解密失败降级 + decrypt_failed 审计，无异常、不删行
    monkeypatch.setenv("AUTH_SESSION_SECRETS", "secret-C,secret-A")
    get_settings.cache_clear()
    with Session() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        resolved = resolve_generation_config(get_settings(), workspace=workspace, session=session)
        assert resolved.key_source == "credential_missing"
        assert resolved.api_key == ""
        session.commit()
    with Session() as session:
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "generation.credential.decrypt_failed"),
        )
        assert audit is not None
        text = json.dumps(audit.detail_json, ensure_ascii=False)
        assert PLAIN_KEY not in text
        assert audit.detail_json["credential_id"] == body["id"]

    handler = RecordingHandler()
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    ping = client.post("/api/generation/ping", json={"credential_id": body["id"]})
    assert ping.json()["error_code"] == "key_missing"
    assert handler.requests == []


# --- 断言 7：同步与导出边界——feed/手工包 grep 不到表名、明文与密文 ---


def test_sync_feed_and_manual_package_exclude_credentials(monkeypatch, tmp_path):
    # 结构性排除：凭据表不在 feed 对象类型与 payload builder 里
    assert "llm_provider_credentials" not in SYNC_FEED_OBJECT_TYPES
    assert "llm_provider_credentials" not in PAYLOAD_BUILDERS

    client, engine = make_client(monkeypatch, tmp_path, filename="cred_sync.sqlite")
    _login(client)
    _post_credential(client)

    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = session.scalar(select(LlmProviderCredential))
        ciphertext = row.key_encrypted
        # feed 发布端逐对象类型翻页，内容 grep 不到表名/明文/密文
        for object_type in SYNC_FEED_OBJECT_TYPES:
            page = feed_page(session, object_type, cursor=None, limit=200)
            text = json.dumps(page.records, ensure_ascii=False, default=str)
            assert "llm_provider_credentials" not in text
            assert PLAIN_KEY not in text
            assert ciphertext not in text

    # 手工同步包导出（super_admin）同理
    export = client.post(
        "/api/sync/packages/export",
        json={"source_instance_id": "extranet-a", "target_instance_id": "intranet-b"},
    )
    assert export.status_code == 200, export.text
    package_text = json.dumps(export.json(), ensure_ascii=False)
    assert "llm_provider_credentials" not in package_text
    assert PLAIN_KEY not in package_text
    assert ciphertext not in package_text


# --- 断言 8：兼容回归——无凭据时 resolved 与 R2 之前逐字节一致 ---


def test_no_credentials_keeps_env_chain_byte_identical(monkeypatch, tmp_path):
    # 仅配 MINIMAX_* 的老兼容断言（与 §7 断言 1 同口径，credential 层不改变结果）
    settings = Settings(
        AUTH_SESSION_SECRET="compat-secret",
        MINIMAX_GENERATION_ENABLED=True,
        MINIMAX_API_KEY="legacy-key",
        MINIMAX_BASE_URL="https://legacy.example/v1",
        MINIMAX_MODEL="legacy-model",
    )
    config = resolve_generation_config(settings)
    assert config.enabled is True
    assert config.provider == "minimax"
    assert config.base_url == "https://legacy.example/v1"
    assert config.api_key == "legacy-key"
    assert config.key_source == "env"
    assert config.credential_id is None
    assert config.credential_label is None

    # credential_id=null + 建了凭据行也不影响 env 链（凭据只在被引用时生效）
    database_path = tmp_path / "compat.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    from app.core.database import Base

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        cipher = CredentialCipher(["compat-secret"])
        session.add(
            LlmProviderCredential(
                provider="deepseek",
                base_url="https://api.deepseek.com/v1",
                key_encrypted=cipher.encrypt("sk-unused-key"),
                key_last4="-key",
                label="未被引用",
                enabled=True,
                created_by_id=_first_user_id(session),
            ),
        )
        session.flush()
        config = resolve_generation_config(settings, session=session)
        assert config.api_key == "legacy-key"
        assert config.key_source == "env"
        assert config.credential_id is None


def test_generation_policy_defaults_include_credential_id():
    """policy 默认形态含 credential_id=null（契约 workspace_model.json default）。"""
    from app.llm.provider import GENERATION_POLICY_DEFAULTS

    assert GENERATION_POLICY_DEFAULTS["credential_id"] is None
    assert set(GENERATION_POLICY_DEFAULTS) == {
        "credential_id",
        "model",
        "temperature",
        "max_tokens",
        "timeout_seconds",
        "daily_generation_budget",
        "fallback_behavior",
    }


def test_policy_patch_still_rejects_secret_like_fields(monkeypatch, tmp_path):
    """credential_id 是白名单指针；key 明文字段仍 422（§6 不变式）。"""
    client, _engine = make_client(monkeypatch, tmp_path, filename="cred_secretlike.sqlite")
    _login(client)
    for payload in (
        {"api_key": "sk-should-never-land"},
        {"credential_id": None, "api_key": "sk-x"},
        {"base_url": "https://elsewhere.example"},
    ):
        assert (
            client.patch(
                "/api/workspaces/planning_intel/generation-policy",
                json=payload,
            ).status_code
            == 422
        ), payload
    # credential_id 显式置 null 合法（跟随实例 env）
    ok = client.patch(
        "/api/workspaces/planning_intel/generation-policy",
        json={"credential_id": None},
    )
    assert ok.status_code == 200
    assert ok.json()["policy"]["credential_id"] is None
