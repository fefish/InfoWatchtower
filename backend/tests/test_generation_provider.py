"""WP3-B 生成 provider 分层配置验收（generation-provider-design §7 断言 1-8）。

fixture provider：app.llm.provider.TRANSPORT 注入 httpx.MockTransport，
所有 chat/completions 调用不出进程。
"""

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.llm.provider as provider
from app.auth.passwords import hash_password
from app.auth.service import ensure_auth_seed
from app.core.config import Settings, get_settings
from app.core.database import Base, get_engine
from app.core.deploy_checks import validate_deploy_settings
from app.llm.provider import resolve_generation_config
from app.main import create_app
from app.models.feedback import AuditLog
from app.models.identity import Role, User
from app.models.workspace import Workspace, WorkspaceMembership
from app.normalization.news import NewsNormalizationRequest, normalize_workspace_raw_items
from app.recommendations.service import (
    DailyReportGenerationRerunRequest,
    RecommendationRunRequest,
    regenerate_daily_report_generated_news,
    run_daily_recommendation,
)
from app.sync.records import generated_news_payload
from tests.test_news_normalization import add_raw_item, seed_source, seed_workspace
from tests.test_recommendations import make_session

FIXTURE_KEY = "fixture-secret-key-0123456789"
QUALITY_CN = (
    "该框架通过图级算子融合与动态批调度优化推理性能，显著提升单卡吞吐并降低显存"
    "占用，为规划部推理服务选型提供直接参照，值得持续跟踪其社区生态与工程落地进展。"
)


def _quality_payload() -> dict:
    return {
        "category": "AI 应用",
        "title": "开源推理框架发布带来单卡吞吐提升",
        "summary": QUALITY_CN,
        "keyPoints": "推理框架, 算子融合, 单卡吞吐, 显存优化",
        "content": {
            "background": QUALITY_CN,
            "effects": QUALITY_CN,
            "eventSummary": QUALITY_CN,
            "technologyAndInnovation": QUALITY_CN,
            "valueAndImpact": QUALITY_CN,
        },
    }


def _completion_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
    )


class RecordingHandler:
    """记录每次 provider 调用的请求体，按 responder 返回响应。"""

    def __init__(self, responder=None):
        self.requests: list[dict] = []
        self.responder = responder or (lambda request, payload: _completion_response(_quality_payload()))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        self.requests.append({"url": str(request.url), "payload": payload})
        return self.responder(request, payload)


def _install_fixture_provider(monkeypatch, handler, **env: str) -> None:
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("GENERATION_ENABLED", "true")
    monkeypatch.setenv("GENERATION_API_KEY", FIXTURE_KEY)
    monkeypatch.setenv("GENERATION_BASE_URL", "https://provider.fixture.test/v1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def _pipeline_session(day_key: str = "2026-04-30"):
    session = make_session()
    workspace = seed_workspace(session)
    source = seed_source(session, workspace, name="Example Official RSS")
    for index in range(3):
        add_raw_item(
            session,
            source,
            f"rss:gen-{index}",
            f"Agent model release {index} improves tool orchestration",
            f"https://example.com/gen-{index}",
            "Agent platform release with detailed architecture and benchmark body.",
            published_at=datetime(2026, 4, 30, 8 + index, tzinfo=UTC),
        )
    normalize_workspace_raw_items(
        session,
        NewsNormalizationRequest(workspace_code="planning_intel", source_types=[], limit=None),
    )
    return session, workspace


def _run_pipeline(session, day_key: str = "2026-04-30"):
    result = run_daily_recommendation(
        session,
        RecommendationRunRequest(
            workspace_code="planning_intel",
            day_key=day_key,
            limit=15,
            source_daily_limit=5,
            create_daily_draft=True,
        ),
        now=datetime(2026, 4, 30, 10, tzinfo=UTC),
    )
    assert result.daily_report is not None
    return result


# --- 断言 1：仅配 MINIMAX_* 时 resolved 与现状字节一致（兼容回归） ---


def test_minimax_only_env_resolves_byte_identical_to_legacy():
    settings = Settings(
        MINIMAX_GENERATION_ENABLED=True,
        MINIMAX_API_KEY="legacy-key",
        MINIMAX_BASE_URL="https://legacy.example/v1",
        MINIMAX_MODEL="legacy-model",
        MINIMAX_MAX_TOKENS=1234,
        MINIMAX_TEMPERATURE=0.7,
        MINIMAX_RETRY_TIMES=5,
        MINIMAX_RETRY_BACKOFF_SECONDS=2.5,
        GENERATION_ENABLED=None,
        GENERATION_BASE_URL="",
        GENERATION_API_KEY="",
        GENERATION_API_KEY_REF="",
        GENERATION_MODEL="",
    )
    config = resolve_generation_config(settings)
    assert config.enabled is True
    assert config.provider == "minimax"
    assert config.base_url == "https://legacy.example/v1"
    assert config.api_key == "legacy-key"
    assert config.model == "legacy-model"
    assert config.max_tokens == 1234
    assert config.temperature == 0.7
    assert config.timeout_seconds == 45.0
    assert config.retry_times == 5
    assert config.retry_backoff_seconds == 2.5
    assert config.generated_by == "minimax:legacy-model"


def test_generation_env_wins_over_minimax_when_both_configured():
    settings = Settings(
        MINIMAX_GENERATION_ENABLED=False,
        MINIMAX_API_KEY="legacy-key",
        MINIMAX_BASE_URL="https://legacy.example/v1",
        MINIMAX_MODEL="legacy-model",
        GENERATION_ENABLED=True,
        GENERATION_API_KEY="new-key",
        GENERATION_BASE_URL="https://new.example/v1",
        GENERATION_MODEL="new-model",
        GENERATION_TEMPERATURE=0.1,
    )
    config = resolve_generation_config(settings)
    assert config.enabled is True
    assert config.api_key == "new-key"
    assert config.base_url == "https://new.example/v1"
    assert config.model == "new-model"
    assert config.temperature == 0.1


# --- 断言 2（§9.6 R2 修订）：enabled 无 key 降级 WARNING；custom/openai_compatible
# 无 base_url 与非法 provider 值仍拒启 ---


def _deploy_settings(**overrides) -> Settings:
    values = {
        "AUTH_SESSION_SECRET": "test-secret",
        "MINIMAX_GENERATION_ENABLED": False,
        "MINIMAX_API_KEY": "",
        "MINIMAX_BASE_URL": "",
    }
    values.update(overrides)
    return Settings(**values)


def test_generation_enabled_with_empty_key_warns_but_starts(caplog):
    """R2 修订（D-2026-07-08-KEY）：key 可运行期在 UI 落库，启动降级 WARNING。"""
    settings = _deploy_settings(GENERATION_ENABLED=True, GENERATION_API_KEY="")
    with caplog.at_level("WARNING", logger="app.core.deploy_checks"):
        validate_deploy_settings(settings)  # 不再拒启
    assert any(
        "GENERATION_ENABLED=true but no API key" in record.message for record in caplog.records
    )


def test_generation_key_ref_unresolvable_warns_and_resolvable_passes(monkeypatch, caplog):
    monkeypatch.delenv("GEN_TEST_KEY_VAR", raising=False)
    broken = _deploy_settings(
        GENERATION_ENABLED=True,
        GENERATION_API_KEY="also-set-but-ref-wins",
        GENERATION_API_KEY_REF="env:GEN_TEST_KEY_VAR",
    )
    with caplog.at_level("WARNING", logger="app.core.deploy_checks"):
        validate_deploy_settings(broken)  # REF 解析失败=未配置：WARNING 而非拒启
    assert any(
        "GENERATION_ENABLED=true but no API key" in record.message for record in caplog.records
    )

    monkeypatch.setenv("GEN_TEST_KEY_VAR", "resolved-key")
    ok = _deploy_settings(
        GENERATION_ENABLED=True,
        GENERATION_API_KEY_REF="env:GEN_TEST_KEY_VAR",
    )
    caplog.clear()
    with caplog.at_level("WARNING", logger="app.core.deploy_checks"):
        validate_deploy_settings(ok)
    assert not any(
        "GENERATION_ENABLED=true but no API key" in record.message for record in caplog.records
    )
    assert ok.generation_api_key_effective == "resolved-key"
    assert ok.generation_api_key_source == "credential_ref"


def test_openai_compatible_without_base_url_fails_startup():
    settings = _deploy_settings(GENERATION_PROVIDER="openai_compatible", GENERATION_BASE_URL="")
    with pytest.raises(RuntimeError, match="GENERATION_BASE_URL"):
        validate_deploy_settings(settings)
    validate_deploy_settings(
        _deploy_settings(
            GENERATION_PROVIDER="openai_compatible",
            GENERATION_BASE_URL="https://compat.example/v1",
        ),
    )


def test_custom_without_base_url_fails_startup():
    """§9.6：custom（openai_compatible 的正名）缺 base_url 仍拒启。"""
    settings = _deploy_settings(GENERATION_PROVIDER="custom", GENERATION_BASE_URL="")
    with pytest.raises(RuntimeError, match="GENERATION_BASE_URL"):
        validate_deploy_settings(settings)
    validate_deploy_settings(
        _deploy_settings(
            GENERATION_PROVIDER="custom",
            GENERATION_BASE_URL="https://gateway.example/v1",
        ),
    )


def test_unknown_generation_provider_fails_startup():
    """值域=目录 9 code + deprecated 别名；目录外值仍拒启，目录内新值放行。"""
    settings = _deploy_settings(GENERATION_PROVIDER="no_such_provider")
    with pytest.raises(RuntimeError, match="GENERATION_PROVIDER"):
        validate_deploy_settings(settings)
    # R2 值域扩展：市面常用 provider 目录 code 均可启动（自带目录默认 base_url）
    validate_deploy_settings(_deploy_settings(GENERATION_PROVIDER="anthropic"))
    validate_deploy_settings(_deploy_settings(GENERATION_PROVIDER="deepseek"))


def test_api_entrypoint_starts_with_warning_on_missing_env_key(monkeypatch, tmp_path, caplog):
    """create_app（API 入口）与 worker/scheduler 共用 validate_deploy_settings；
    R2 后 enabled+env 无 key 是 WARNING（可先启动、再进 UI 配 key）。"""
    database_path = tmp_path / "failfast.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("GENERATION_ENABLED", "true")
    monkeypatch.setenv("GENERATION_API_KEY", "")
    monkeypatch.setenv("GENERATION_API_KEY_REF", "")
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    get_settings.cache_clear()
    app = create_app()
    with caplog.at_level("WARNING", logger="app.core.deploy_checks"):
        with TestClient(app):
            pass
    assert any(
        "GENERATION_ENABLED=true but no API key" in record.message for record in caplog.records
    )
    # 非法 provider 值仍在入口 fail-fast（拒启语义未整体放松）
    monkeypatch.setenv("GENERATION_PROVIDER", "no_such_provider")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="GENERATION_PROVIDER"):
        with TestClient(create_app()):
            pass
    monkeypatch.delenv("GENERATION_PROVIDER", raising=False)
    get_settings.cache_clear()
    # worker 与 scheduler 入口同样调用 validate_deploy_settings（入口级同构）
    import app.workers.scheduler as scheduler_module
    import app.workers.worker as worker_module

    assert worker_module.validate_deploy_settings is validate_deploy_settings
    assert scheduler_module.validate_deploy_settings is validate_deploy_settings


# --- 断言 3/4：generation-policy 读写、resolved 无 key、下一次调用用工作台值 ---


def make_client(monkeypatch, tmp_path, *, filename: str = "generation_api.sqlite"):
    database_path = tmp_path / filename
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_MODE", "public_password")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app()), engine


def _login(client, username: str = "admin", password: str = "password") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def _create_viewer(engine, username: str = "viewer1", password: str = "viewer-pass") -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        role = session.scalar(select(Role).where(Role.code == "viewer"))
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        assert role is not None and workspace is not None
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
        session.flush()
        session.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=user.id,
                workspace_role="viewer",
                enabled=True,
            ),
        )
        session.commit()


def test_generation_policy_patch_persists_audits_and_validates(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path)
    _login(client)

    updated = client.patch(
        "/api/workspaces/planning_intel/generation-policy",
        json={"model": "gpt-4o-mini", "temperature": 0.2},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["policy"]["model"] == "gpt-4o-mini"
    assert payload["policy"]["temperature"] == 0.2
    assert payload["policy"]["fallback_behavior"] == "rule_fallback"
    assert payload["resolved"]["model"] == "gpt-4o-mini"

    fetched = client.get("/api/workspaces/planning_intel/generation-policy")
    assert fetched.status_code == 200
    assert fetched.json()["policy"]["model"] == "gpt-4o-mini"

    Session = sessionmaker(bind=engine)
    with Session() as session:
        audit = session.scalar(
            select(AuditLog)
            .where(AuditLog.action == "workspace.generation_policy.update")
            .order_by(AuditLog.created_at.desc()),
        )
        assert audit is not None
        assert audit.detail_json["before"]["model"] is None
        assert audit.detail_json["after"]["model"] == "gpt-4o-mini"

    # 取值域校验 422
    assert (
        client.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"temperature": 3},
        ).status_code
        == 422
    )
    # secret-like 字段 422（key 永不进 workspace policy）
    assert (
        client.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"api_key": "sk-should-never-land"},
        ).status_code
        == 422
    )
    # 未知字段 422
    assert (
        client.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"base_url": "https://elsewhere.example"},
        ).status_code
        == 422
    )

    # viewer PATCH 403
    _create_viewer(engine)
    viewer = TestClient(create_app())
    _login(viewer, "viewer1", "viewer-pass")
    assert (
        viewer.patch(
            "/api/workspaces/planning_intel/generation-policy",
            json={"model": "other"},
        ).status_code
        == 403
    )
    # viewer 可读
    assert viewer.get("/api/workspaces/planning_intel/generation-policy").status_code == 200


def test_next_generation_call_uses_workspace_policy_values(monkeypatch):
    handler = RecordingHandler()
    _install_fixture_provider(monkeypatch, handler)
    session, workspace = _pipeline_session()
    config_json = dict(workspace.config_json or {})
    config_json["generation_policy"] = {"model": "gpt-4o-mini", "temperature": 0.2}
    workspace.config_json = config_json
    session.flush()

    _run_pipeline(session)
    assert handler.requests, "fixture provider must be called"
    for request in handler.requests:
        assert request["payload"]["model"] == "gpt-4o-mini"
        assert request["payload"]["temperature"] == 0.2


def test_generation_policy_read_never_contains_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERATION_ENABLED", "true")
    monkeypatch.setenv("GENERATION_API_KEY", FIXTURE_KEY)
    client, _engine = make_client(monkeypatch, tmp_path, filename="key_configured.sqlite")
    _login(client)
    response = client.get("/api/workspaces/planning_intel/generation-policy")
    assert response.status_code == 200
    assert FIXTURE_KEY not in response.text
    body = response.json()
    assert body["resolved"]["key_configured"] is True
    assert body["resolved"]["key_source"] == "env"


def test_generation_policy_read_key_not_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERATION_ENABLED", "false")
    monkeypatch.setenv("GENERATION_API_KEY", "")
    monkeypatch.setenv("GENERATION_API_KEY_REF", "")
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    client, _engine = make_client(monkeypatch, tmp_path, filename="key_missing.sqlite")
    _login(client)
    body = client.get("/api/workspaces/planning_intel/generation-policy").json()
    assert body["resolved"]["key_configured"] is False
    assert body["resolved"]["key_source"] == ""


# --- 断言 5：ping 分类报错 + 审计无 key + 未配 key 不外呼 + 权限 ---


def test_generation_ping_classifies_and_audits_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERATION_ENABLED", "true")
    monkeypatch.setenv("GENERATION_API_KEY", FIXTURE_KEY)
    monkeypatch.setenv("GENERATION_BASE_URL", "https://provider.fixture.test/v1")
    client, engine = make_client(monkeypatch, tmp_path, filename="ping.sqlite")
    _login(client)

    handler = RecordingHandler()
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    ok = client.post("/api/generation/ping", json={})
    assert ok.status_code == 200
    body = ok.json()
    assert body["status"] == "ok"
    assert body["error_code"] is None
    assert isinstance(body["latency_ms"], int)
    assert body["base_url_host"] == "provider.fixture.test"
    assert FIXTURE_KEY not in ok.text

    monkeypatch.setattr(
        provider,
        "TRANSPORT",
        httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "bad key"})),
    )
    auth_failed = client.post("/api/generation/ping", json={}).json()
    assert auth_failed["status"] == "error"
    assert auth_failed["error_code"] == "auth_failed"

    def _connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns lookup failed", request=request)

    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(_connect_error))
    unreachable = client.post("/api/generation/ping", json={}).json()
    assert unreachable["error_code"] == "dns_or_connect_failed"
    assert FIXTURE_KEY not in json.dumps(unreachable)

    Session = sessionmaker(bind=engine)
    with Session() as session:
        audits = session.scalars(select(AuditLog).where(AuditLog.action == "generation.ping")).all()
        assert len(audits) == 3
        for audit in audits:
            detail_text = json.dumps(audit.detail_json, ensure_ascii=False)
            assert FIXTURE_KEY not in detail_text
            assert set(audit.detail_json) == {
                "provider",
                "model",
                "base_url_host",
                "status",
                "latency_ms",
            }


def test_generation_ping_key_missing_makes_no_outbound_call(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERATION_ENABLED", "false")
    monkeypatch.setenv("GENERATION_API_KEY", "")
    monkeypatch.setenv("GENERATION_API_KEY_REF", "")
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    client, _engine = make_client(monkeypatch, tmp_path, filename="ping_nokey.sqlite")
    _login(client)
    handler = RecordingHandler()
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    body = client.post("/api/generation/ping", json={}).json()
    assert body["status"] == "error"
    assert body["error_code"] == "key_missing"
    assert handler.requests == [], "key_missing must not reach the provider"


def test_generation_ping_requires_admin_role(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, filename="ping_role.sqlite")
    _create_viewer(engine)
    viewer = TestClient(create_app())
    _login(viewer, "viewer1", "viewer-pass")
    assert viewer.post("/api/generation/ping", json={}).status_code == 403


# --- 断言 6：daily_generation_budget=2，第 3 条起不外呼，run summary 计数 ---


def test_daily_generation_budget_caps_provider_calls(monkeypatch):
    handler = RecordingHandler()
    _install_fixture_provider(monkeypatch, handler)
    session, workspace = _pipeline_session()
    config_json = dict(workspace.config_json or {})
    config_json["generation_policy"] = {"daily_generation_budget": 2}
    workspace.config_json = config_json
    session.flush()

    result = _run_pipeline(session)
    assert len(handler.requests) == 2, "third item must not reach the provider"
    summary = result.run.summary_json
    assert summary["generation_budget_exhausted"] >= 1
    statuses = summary["generation_status"]
    # 预算内 ready，预算外按默认 rule_fallback 降级
    assert statuses.get("ready", 0) == 2
    assert statuses.get("fallback_needs_review", 0) >= 1


# --- 断言 7：fallback_behavior=fail 不产降级稿，regenerate 可补跑 ---


def test_fallback_behavior_fail_marks_failed_and_regenerate_backfills(monkeypatch):
    def _timeout(request: httpx.Request, payload: dict) -> httpx.Response:
        raise httpx.ConnectTimeout("provider timed out", request=request)

    handler = RecordingHandler(_timeout)
    _install_fixture_provider(monkeypatch, handler)
    session, workspace = _pipeline_session()
    config_json = dict(workspace.config_json or {})
    config_json["generation_policy"] = {"fallback_behavior": "fail"}
    workspace.config_json = config_json
    session.flush()

    result = _run_pipeline(session)
    report = result.daily_report
    for item in report.items:
        generated = item.generated_news
        assert generated.generation_status == "failed"
        assert not generated.generated_by.startswith("rule_v1")

    # provider 恢复后 regenerate-generated-news 可补跑为 ready
    good_handler = RecordingHandler()
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(good_handler))
    rerun = regenerate_daily_report_generated_news(
        session,
        DailyReportGenerationRerunRequest(report_id=report.id),
    )
    assert rerun.attempted_total >= 1
    assert rerun.ready_total == rerun.attempted_total
    for item in report.items:
        assert item.generated_news.generation_status == "ready"


def test_fallback_behavior_default_keeps_rule_fallback_semantics(monkeypatch):
    def _timeout(request: httpx.Request, payload: dict) -> httpx.Response:
        raise httpx.ConnectTimeout("provider timed out", request=request)

    handler = RecordingHandler(_timeout)
    _install_fixture_provider(monkeypatch, handler)
    session, _workspace = _pipeline_session()
    result = _run_pipeline(session)
    for item in result.daily_report.items:
        generated = item.generated_news
        assert generated.generation_status == "fallback_needs_review"
        assert generated.generated_by == "rule_v1:fallback"


# --- 断言 8：同步/导出边界 grep 不到 key；公司 SQL gating 两 provider 一致 ---


def test_sync_record_and_company_sql_gating_are_provider_agnostic(monkeypatch):
    handler = RecordingHandler()
    _install_fixture_provider(
        monkeypatch,
        handler,
        GENERATION_PROVIDER="openai_compatible",
        GENERATION_MODEL="compat-model",
    )
    session, _workspace = _pipeline_session()
    result = _run_pipeline(session)
    report = result.daily_report
    ready_items = [item for item in report.items if item.generated_news.generation_status == "ready"]
    assert ready_items, "fixture provider quality drafts must be ready"
    generated = ready_items[0].generated_news
    assert generated.generated_by == "openai_compatible:compat-model"

    record_text = json.dumps(generated_news_payload(generated), ensure_ascii=False, default=str)
    assert FIXTURE_KEY not in record_text

    # 公司 SQL gating：ready + 非 rule_v1 在两种 provider 前缀下一致
    from app.exports.company_sql import generate_company_sql_for_daily_report

    report.status = "published"
    report.published_at = datetime(2026, 4, 30, 12, tzinfo=UTC)
    for item in report.items:
        item.adoption_status = 2 if item.generated_news.generation_status == "ready" else 0
    session.flush()
    export = generate_company_sql_for_daily_report(session, report.id)
    assert FIXTURE_KEY not in export.sql_text
    assert export.item_count == len(ready_items)
