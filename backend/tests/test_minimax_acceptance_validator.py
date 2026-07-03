from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_minimax_generation_acceptance.py"


def test_minimax_acceptance_validator_passes_fixture_response(tmp_path: Path):
    fixture_path = tmp_path / "response.json"
    fixture_path.write_text(json.dumps(_fixture_payload()), encoding="utf-8")
    output_path = tmp_path / "acceptance.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture-response-json",
            str(fixture_path),
            "--output-json",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["category"] == "模型"
    assert payload["generated_by"].startswith("minimax:")
    assert output_path.exists()


def test_minimax_acceptance_validator_requires_tech_insight_fields(tmp_path: Path):
    payload = _fixture_payload()
    payload.pop("insight")
    fixture_path = tmp_path / "response.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path = tmp_path / "acceptance.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture-response-json",
            str(fixture_path),
            "--output-json",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    response = json.loads(result.stdout)
    assert response["status"] == "failed"
    assert any("insight_json" in error for error in response["errors"])


def test_minimax_acceptance_validator_rejects_unsupported_numeric_claims(tmp_path: Path):
    payload = _fixture_payload()
    payload["content"]["effects"] += " 多GPU集群测试中P99延迟降低40%，显存利用率提升25%。"
    fixture_path = tmp_path / "response.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path = tmp_path / "acceptance.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture-response-json",
            str(fixture_path),
            "--output-json",
            str(output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    response = json.loads(result.stdout)
    assert any("numeric claims" in error for error in response["errors"])


def test_minimax_acceptance_validator_requires_live_key_without_fixture(tmp_path: Path):
    output_path = tmp_path / "acceptance.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-json", str(output_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    response = json.loads(result.stdout)
    assert response["status"] == "failed"
    assert "MINIMAX_API_KEY" in response["errors"][0]
    assert json.loads(output_path.read_text(encoding="utf-8")) == response


def _fixture_payload() -> dict:
    return {
        "category": "模型",
        "title": "长上下文智能体推理运行时发布",
        "summary": (
            "Example AI Lab 发布面向长上下文智能体的稀疏 MoE 推理运行时，重点解决多轮任务中的"
            "调度、缓存和工具调用效率问题。该方案把专家路由、KV 缓存分页和工具调用批处理纳入"
            "统一运行队列，适合关注模型服务化和智能体平台演进的团队复核。"
        ),
        "keyPoints": "稀疏MoE，长上下文，KV缓存，工具调用，推理调度",
        "content": {
            "background": _long(
                "长上下文智能体在执行检索、规划和工具调用时会持续占用缓存与调度资源，"
                "传统推理服务往往把模型请求和工具调用分开处理，导致尾延迟与显存浪费同时上升。"
            ),
            "effects": _long(
                "该运行时把请求队列、专家路由、KV缓存分页和工具调用批处理统一起来，"
                "可在多GPU集群上降低长会话尾延迟，并为服务团队提供更稳定的吞吐与回滚能力。"
            ),
            "eventSummary": _long(
                "Example AI Lab 在公开技术说明中发布稀疏MoE推理运行时，强调其面向长上下文"
                "智能体任务，支持OpenAI风格接口、跨节点负载均衡、观测指标和灰度发布。"
            ),
            "technologyAndInnovation": _long(
                "技术创新点在于把专家选择、缓存迁移、工具调用等待和批处理合并为统一调度问题，"
                "并通过分页式KV缓存减少长上下文对单卡显存的占用，同时保留服务侧指标。"
            ),
            "valueAndImpact": _long(
                "对规划部而言，该信号说明智能体平台竞争正在从单模型能力延伸到运行时工程能力，"
                "后续可跟踪其对成本、延迟、可靠性和企业级部署模式的影响。"
            ),
        },
        "insight": {
            "board": "智能体平台、协议与执行系统",
            "bulletPoints": [
                "运行时把模型推理、工具调用和缓存调度统一处理，减少长会话资源浪费。",
                "多GPU集群场景下强调尾延迟治理，说明智能体服务进入工程优化阶段。",
                "兼容OpenAI风格接口和灰度回滚，有利于现有平台做平滑接入验证。",
            ],
            "takeaway": (
                "该信号值得作为智能体平台基础设施趋势观察样本。相比单纯模型发布，运行时优化更直接"
                "影响企业部署成本、系统稳定性和长任务体验，后续应关注真实负载指标与生态适配情况。"
            ),
            "tagLine": ["智能体平台", "推理运行时", "长上下文", "成本优化"],
        },
    }


def _long(text: str) -> str:
    return text + text
