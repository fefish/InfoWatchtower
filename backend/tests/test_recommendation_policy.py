"""WP4-A recommendation-policy 四端点验收（recommendation-scoring-design §5/§11、
config/contracts/recommendation_ranking.json `recommendation_policy` /
`rubric_compile` / `rubric_activate` / `secrets_boundary`）。

覆盖契约断言：
- rubric_compile_idempotent_preview（断言 4）：同 guidance 两次编译同 fingerprint，
  第二次缓存命中零模型调用，active_rubric/rubric_version 不变；
- rubric_activate_versioned_audited（断言 5）：activate 版本 +1 + 审计，
  未知/过期 fingerprint 422；
- fusion_formula（断言 8 PATCH 面）：fusion 权重和 ≠ 1.0 的 PATCH 422；
- budget_buckets_isolated（断言 13 编译面）：rubric_compile 固定 20 次/日上限，
  编译计数不进 generation 桶；
- secrets_boundary（断言 14）：payload 命中 secret-like 检测 422，响应无 key。
LLM 调用全部走 app.llm.provider.TRANSPORT 的 MockTransport。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.llm.provider as provider
from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.llm.budget import (
    PURPOSE_GENERATION,
    PURPOSE_RERANK,
    PURPOSE_RUBRIC_COMPILE,
    current_day_key,
)
from app.main import create_app
from app.models.content import GenerationUsage, RecommendationRubricCompile
from app.models.feedback import AuditLog
from app.models.workspace import Workspace
from app.recommendations.policy import PLANNING_INTEL_DEFAULT_GUIDANCE

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUBRIC = json.loads(
    (REPO_ROOT / "config" / "scoring" / "rubrics" / "planning_intel_default.json").read_text(
        encoding="utf-8",
    ),
)
FIXTURE_KEY = "fixture-secret-key-0123456789"
POLICY_URL = "/api/workspaces/planning_intel/recommendation-policy"


def make_client(monkeypatch, tmp_path, **env):
    database_path = tmp_path / "recommendation_policy_api.sqlite"
    base_env = {
        "DATABASE_URL": f"sqlite:///{database_path}",
        "AUTH_MODE": "public_password",
        "AUTH_SESSION_SECRET": "test-session-secret",
        "AUTH_BOOTSTRAP_ADMIN_USERNAME": "admin",
        "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "password",
    }
    base_env.update(env)
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        ensure_auth_seed(session, get_settings())
    client = TestClient(create_app())
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    return client, session_factory


class CompileHandler:
    """记录编译调用次数，按 responder 返回（默认回默认 rubric 编译产物）。"""

    def __init__(self, responder=None):
        self.calls = 0
        self.responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.responder is not None:
            return self.responder(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(DEFAULT_RUBRIC, ensure_ascii=False)}},
                ],
            },
        )


def install_provider(monkeypatch, handler) -> None:
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("GENERATION_ENABLED", "true")
    monkeypatch.setenv("GENERATION_API_KEY", FIXTURE_KEY)
    monkeypatch.setenv("GENERATION_BASE_URL", "https://provider.fixture.test/v1")
    get_settings.cache_clear()


def usage_total(session_factory, purpose: str) -> int:
    with session_factory() as session:
        usage = session.scalar(
            select(GenerationUsage).where(
                GenerationUsage.workspace_code == "planning_intel",
                GenerationUsage.day_key == current_day_key(),
                GenerationUsage.purpose == purpose,
            ),
        )
        return usage.calls_total if usage else 0


# ---------------------------------------------------------------------------
# GET：默认 policy + resolved 状态 + planning_intel 默认导向落种
# ---------------------------------------------------------------------------


def test_policy_get_returns_defaults_resolved_and_seeded_guidance(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    response = client.get(POLICY_URL)
    assert response.status_code == 200
    payload = response.json()
    policy = payload["policy"]
    assert policy["llm_rerank_enabled"] is False
    assert policy["rerank_top_m"] == 60
    assert policy["rerank_window_size"] == 12
    assert policy["daily_rerank_call_budget"] == 60
    assert policy["fusion_weights"] == {"llm": 0.6, "coarse": 0.4}
    assert policy["active_rubric"] is None
    assert policy["rubric_version"] == 0
    assert policy["rubric_status"] == "none"
    # planning_intel 默认导向转写落种（§5.5，契约 default_guidance.planning_intel）。
    assert policy["guidance"] == PLANNING_INTEL_DEFAULT_GUIDANCE

    resolved = payload["resolved"]
    assert resolved["llm_rerank_available"] is False
    assert resolved["provider_usable"] is False
    assert resolved["rerank_calls_used_today"] == 0
    assert resolved["rerank_budget"] == 60
    assert resolved["active_rubric_version"] == 0
    assert resolved["semantic_layer_available"] is False
    # 断言 14：响应不含任何 key 材料。
    assert FIXTURE_KEY not in response.text
    assert "api_key" not in response.text


# ---------------------------------------------------------------------------
# PATCH：取值域校验、secret-like 422、审计
# ---------------------------------------------------------------------------


def test_policy_patch_persists_values_and_audits(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    updated = client.patch(
        POLICY_URL,
        json={
            "llm_rerank_enabled": True,
            "rerank_top_m": 80,
            "rerank_window_size": 10,
            "daily_rerank_call_budget": 120,
            "fusion_weights": {"llm": 0.5, "coarse": 0.5},
            "guidance": {"want": "推理服务加速", "avoid": "融资新闻", "boost": "一手 benchmark"},
        },
    )
    assert updated.status_code == 200
    policy = updated.json()["policy"]
    assert policy["llm_rerank_enabled"] is True
    assert policy["rerank_top_m"] == 80
    assert policy["rerank_window_size"] == 10
    assert policy["daily_rerank_call_budget"] == 120
    assert policy["fusion_weights"] == {"llm": 0.5, "coarse": 0.5}
    assert policy["guidance"]["want"] == "推理服务加速"

    with session_factory() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        stored = workspace.config_json["recommendation_policy"]
        assert stored["llm_rerank_enabled"] is True
        assert stored["rerank_top_m"] == 80
        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "workspace.recommendation_policy.update"),
        ).all()
        assert len(audits) == 1
        detail = audits[0].detail_json
        assert detail["before"]["llm_rerank_enabled"] is False
        assert detail["after"]["llm_rerank_enabled"] is True

    # budget 显式 null = 不限。
    unlimited = client.patch(POLICY_URL, json={"daily_rerank_call_budget": None})
    assert unlimited.status_code == 200
    assert unlimited.json()["policy"]["daily_rerank_call_budget"] is None


def test_policy_patch_rejects_invalid_and_secret_like_payloads(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    for bad_payload in (
        {"fusion_weights": {"llm": 0.7, "coarse": 0.4}},  # 和 ≠ 1.0（断言 8）
        {"fusion_weights": {"llm": 1.2, "coarse": -0.2}},
        {"fusion_weights": {"llm": 0.6}},
        {"rerank_top_m": 5},
        {"rerank_top_m": 201},
        {"rerank_window_size": 4},
        {"rerank_window_size": 21},
        {"daily_rerank_call_budget": 0},
        {"daily_rerank_call_budget": 501},
        {"llm_rerank_enabled": "yes"},
        {"guidance": {"want": "x" * 2001}},
        {"guidance": {"unknown_field": "x"}},
        {"unknown_field": 1},
        {"active_rubric": {}},  # 只能经 activate 动作写入
        {"rubric_version": 3},
        {"rubric_status": "active"},
        {"api_key": "sk-should-never-be-here"},  # secret-like（断言 14）
        {"guidance": {"want": "ok"}, "generation_api_key": "sk-x"},
    ):
        response = client.patch(POLICY_URL, json=bad_payload)
        assert response.status_code == 422, bad_payload


# ---------------------------------------------------------------------------
# 断言 4：rubric 编译幂等预览（缓存命中零模型调用，active 不变）
# ---------------------------------------------------------------------------


def test_compile_rubric_idempotent_preview(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = CompileHandler()
    install_provider(monkeypatch, handler)

    guidance = {"want": "推理服务与硬件", "avoid": "融资", "boost": "benchmark"}
    first = client.post(f"{POLICY_URL}/compile-rubric", json={"guidance": guidance})
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["persistence"] == "not_persisted"
    assert first_payload["cached"] is False
    assert first_payload["fingerprint"].startswith("sha256:")
    assert first_payload["rubric"]["schema_version"] == 1
    assert first_payload["rubric"]["source_guidance_fingerprint"] == first_payload["fingerprint"]
    assert handler.calls == 1

    second = client.post(f"{POLICY_URL}/compile-rubric", json={"guidance": guidance})
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["fingerprint"] == first_payload["fingerprint"]
    assert second_payload["rubric"] == first_payload["rubric"]
    assert second_payload["cached"] is True
    assert handler.calls == 1  # 缓存命中零模型调用

    # 编译不改变 active_rubric / rubric_version。
    policy = client.get(POLICY_URL).json()["policy"]
    assert policy["active_rubric"] is None
    assert policy["rubric_version"] == 0
    # 编译计数进 rubric_compile 桶，不进 generation/rerank 桶（断言 13）。
    assert usage_total(session_factory, PURPOSE_RUBRIC_COMPILE) == 1
    assert usage_total(session_factory, PURPOSE_GENERATION) == 0
    assert usage_total(session_factory, PURPOSE_RERANK) == 0
    # secret-like payload 422（断言 14）。
    bad = client.post(
        f"{POLICY_URL}/compile-rubric",
        json={"guidance": {"want": "ok"}, "api_key": "sk-x"},
    )
    assert bad.status_code == 422


def test_compile_rubric_invalid_output_twice_returns_502(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    handler = CompileHandler(
        responder=lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{\"topics\": []}"}}]},
        ),
    )
    install_provider(monkeypatch, handler)

    response = client.post(f"{POLICY_URL}/compile-rubric", json={})
    assert response.status_code == 502
    assert handler.calls == 2  # schema 校验失败重试 1 次
    policy = client.get(POLICY_URL).json()["policy"]
    assert policy["active_rubric"] is None
    assert policy["rubric_version"] == 0


def test_compile_rubric_daily_cap_20_answers_429(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = CompileHandler()
    install_provider(monkeypatch, handler)
    with session_factory() as session:
        session.add(
            GenerationUsage(
                workspace_code="planning_intel",
                day_key=current_day_key(),
                purpose=PURPOSE_RUBRIC_COMPILE,
                calls_total=20,
            ),
        )
        session.commit()

    response = client.post(f"{POLICY_URL}/compile-rubric", json={"guidance": {"want": "新导向"}})
    assert response.status_code == 429
    assert handler.calls == 0
    # cap 只作用于 rubric_compile 桶：generation 桶不受影响。
    assert usage_total(session_factory, PURPOSE_GENERATION) == 0


def test_compile_rubric_provider_unusable_answers_503(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    def _explode(request):
        raise AssertionError("no provider calls expected")

    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(_explode))
    # conftest 已置 MINIMAX_GENERATION_ENABLED=false 且无 GENERATION_*。
    response = client.post(f"{POLICY_URL}/compile-rubric", json={})
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# 断言 5：activate 版本化 + 审计；未知/过期 fingerprint 422
# ---------------------------------------------------------------------------


def test_activate_rubric_versions_audits_and_gates_fingerprint(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = CompileHandler()
    install_provider(monkeypatch, handler)

    compiled = client.post(f"{POLICY_URL}/compile-rubric", json={})
    assert compiled.status_code == 200
    fingerprint = compiled.json()["fingerprint"]

    activated = client.post(f"{POLICY_URL}/activate-rubric", json={"fingerprint": fingerprint})
    assert activated.status_code == 200
    policy = activated.json()["policy"]
    assert policy["rubric_version"] == 1
    assert policy["rubric_status"] == "active"
    assert policy["active_rubric"]["source_guidance_fingerprint"] == fingerprint
    assert activated.json()["resolved"]["active_rubric_version"] == 1

    with session_factory() as session:
        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "workspace.recommendation_rubric.activate"),
        ).all()
        assert len(audits) == 1
        detail = audits[0].detail_json
        assert detail["before"] == {"rubric_version": 0, "fingerprint": None}
        assert detail["after"] == {"rubric_version": 1, "fingerprint": fingerprint}

    # 重复 activate：版本继续 +1（版本化）。
    again = client.post(f"{POLICY_URL}/activate-rubric", json={"fingerprint": fingerprint})
    assert again.status_code == 200
    assert again.json()["policy"]["rubric_version"] == 2

    # 未知 fingerprint 422。
    unknown = client.post(
        f"{POLICY_URL}/activate-rubric",
        json={"fingerprint": "sha256:" + "0" * 64},
    )
    assert unknown.status_code == 422

    # 超 7 天的编译记录过期 422（防陈旧产物生效）。
    with session_factory() as session:
        row = session.scalar(
            select(RecommendationRubricCompile).where(
                RecommendationRubricCompile.fingerprint == fingerprint,
            ),
        )
        row.created_at = row.created_at - timedelta(days=8)
        session.commit()
    expired = client.post(f"{POLICY_URL}/activate-rubric", json={"fingerprint": fingerprint})
    assert expired.status_code == 422


# ---------------------------------------------------------------------------
# 权限：viewer 可读、写 403（workspace admin+ 门禁）
# ---------------------------------------------------------------------------


def test_policy_write_requires_workspace_admin(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    invite = client.post(
        "/api/auth/invites",
        json={
            "role_code": "viewer",
            "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
            "expires_in_days": 7,
        },
    )
    assert invite.status_code == 200
    viewer = TestClient(create_app())
    accepted = viewer.post(
        f"/api/auth/invites/{invite.json()['code']}/accept",
        json={"username": "ws-viewer", "display_name": "ws-viewer", "password": "strong-password"},
    )
    assert accepted.status_code == 200

    read = viewer.get(POLICY_URL)
    assert read.status_code == 200
    for method, url, payload in (
        ("patch", POLICY_URL, {"llm_rerank_enabled": True}),
        ("post", f"{POLICY_URL}/compile-rubric", {}),
        ("post", f"{POLICY_URL}/activate-rubric", {"fingerprint": "sha256:" + "0" * 64}),
    ):
        response = getattr(viewer, method)(url, json=payload)
        assert response.status_code == 403, (method, url)
