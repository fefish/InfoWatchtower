"""工作台 recommendation_policy（内容导向与精排参数）。

事实源：docs/backend/recommendation-scoring-design.md §5.1；契约：
config/contracts/recommendation_ranking.json `recommendation_policy`。

存放：workspaces.config_json.recommendation_policy（与 label/feedback/report/
schedule/generation policy 同级）。默认 llm_rerank_enabled=false —— 缺省策略
下 final_score = coarse_score，排序与纯粗排现状逐位一致（回归红线）。

planning_intel 默认导向（§5.5）：现状硬编码口径的转写文本（锁定在契约
`default_guidance.planning_intel`）作为该工作台 guidance 的种子缺省值——
存量库不需要迁移，读取路径在 guidance 从未显式写入时自动落种；一旦用户写过
guidance（含清空），以用户值为准。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

GUIDANCE_FIELDS = ("want", "avoid", "boost")
GUIDANCE_MAX_LENGTH = 2000
RERANK_TOP_M_RANGE = (10, 200)
RERANK_WINDOW_SIZE_RANGE = (6, 20)
DAILY_RERANK_CALL_BUDGET_RANGE = (1, 500)
FUSION_WEIGHT_KEYS = ("llm", "coarse")
FUSION_WEIGHTS_SUM_TOLERANCE = 0.001
RUBRIC_STATUSES = ("none", "active")
# feedback_workflow（feedback-heat-scoring §15/§16.1，契约
# recommendation_ranking.json feedback_workflow.policy_extension）：
# 默认 exploration_epsilon=0.0 —— 缺省配置下选择行为与现状逐位一致（回归红线）。
FEEDBACK_WORKFLOW_BOOL_KEYS = (
    "weekly_rollup_enabled",
    "monthly_review_enabled",
    "proposal_generation_enabled",
)
EXPLORATION_EPSILON_RANGE = (0.0, 0.1)

RECOMMENDATION_POLICY_DEFAULTS: dict[str, Any] = {
    "guidance": {"want": "", "avoid": "", "boost": ""},
    "active_rubric": None,
    "rubric_version": 0,
    "rubric_status": "none",
    "llm_rerank_enabled": False,
    "rerank_top_m": 60,
    "rerank_window_size": 12,
    "daily_rerank_call_budget": 60,
    "fusion_weights": {"llm": 0.6, "coarse": 0.4},
    "semantic_layer_enabled": False,
    "feedback_workflow": {
        "weekly_rollup_enabled": True,
        "monthly_review_enabled": True,
        "proposal_generation_enabled": True,
        "exploration_epsilon": 0.0,
    },
}

# 契约 default_guidance.planning_intel 的转写文本（一字不差）。
PLANNING_INTEL_DEFAULT_GUIDANCE: dict[str, str] = {
    "want": (
        "AI 工程能力与基础设施、模型训练/推理与服务加速、智能体平台、"
        "AI/通算硬件与芯片、核心网与通信系统架构、标准与产业联盟进展、厂商技术路线"
    ),
    "avoid": (
        "融资/财报/股价等纯商业新闻、消费电子与个人数码、活动报名与营销宣传、"
        "航天火箭等离题工程、生物医学与纯学术离题论文、法律/版权元讨论、"
        "标题党与未经证实爆料"
    ),
    "boost": (
        "一手技术证据（论文/官方工程博客/benchmark）、架构与成本/能耗/性能量化数据、"
        "开源可复现产物、厂商官方技术白皮书"
    ),
}

# PATCH 可写字段（active_rubric/rubric_version/rubric_status 只能经 activate 动作）。
PATCHABLE_POLICY_FIELDS = {
    "guidance",
    "llm_rerank_enabled",
    "rerank_top_m",
    "rerank_window_size",
    "daily_rerank_call_budget",
    "fusion_weights",
    "semantic_layer_enabled",
    "feedback_workflow",
}
ACTIVATE_ONLY_FIELDS = {"active_rubric", "rubric_version", "rubric_status"}


def default_guidance_for_workspace(workspace_code: str) -> dict[str, str]:
    if workspace_code == "planning_intel":
        return dict(PLANNING_INTEL_DEFAULT_GUIDANCE)
    return {"want": "", "avoid": "", "boost": ""}


def workspace_recommendation_policy(workspace: Any) -> dict[str, Any]:
    """工作台 recommendation_policy（缺省字段补默认值；非法值回退默认）。

    - guidance 从未显式写入时，planning_intel 取默认导向转写（§5.5 落种）；
    - daily_rerank_call_budget 显式 null 表示不限，与“缺省=60”区分；
    - active_rubric/rubric_version/rubric_status 只反映 activate 动作的结果。
    """
    config_json = (getattr(workspace, "config_json", None) if workspace is not None else None) or {}
    raw = dict(config_json.get("recommendation_policy") or {})
    policy = deepcopy(RECOMMENDATION_POLICY_DEFAULTS)

    if isinstance(raw.get("guidance"), dict):
        stored = raw["guidance"]
        policy["guidance"] = {
            key: str(stored.get(key) or "") for key in GUIDANCE_FIELDS
        }
    else:
        policy["guidance"] = default_guidance_for_workspace(
            str(getattr(workspace, "code", "") or ""),
        )

    if raw.get("active_rubric") is not None:
        policy["active_rubric"] = raw["active_rubric"]
    if isinstance(raw.get("rubric_version"), int) and not isinstance(raw.get("rubric_version"), bool):
        policy["rubric_version"] = max(0, raw["rubric_version"])
    if raw.get("rubric_status") in RUBRIC_STATUSES:
        policy["rubric_status"] = raw["rubric_status"]
    if isinstance(raw.get("llm_rerank_enabled"), bool):
        policy["llm_rerank_enabled"] = raw["llm_rerank_enabled"]
    if _valid_int_in_range(raw.get("rerank_top_m"), *RERANK_TOP_M_RANGE):
        policy["rerank_top_m"] = raw["rerank_top_m"]
    if _valid_int_in_range(raw.get("rerank_window_size"), *RERANK_WINDOW_SIZE_RANGE):
        policy["rerank_window_size"] = raw["rerank_window_size"]
    if "daily_rerank_call_budget" in raw:
        budget = raw["daily_rerank_call_budget"]
        if budget is None or _valid_int_in_range(budget, *DAILY_RERANK_CALL_BUDGET_RANGE):
            policy["daily_rerank_call_budget"] = budget
    if _valid_fusion_weights(raw.get("fusion_weights")):
        policy["fusion_weights"] = {
            "llm": float(raw["fusion_weights"]["llm"]),
            "coarse": float(raw["fusion_weights"]["coarse"]),
        }
    if isinstance(raw.get("semantic_layer_enabled"), bool):
        policy["semantic_layer_enabled"] = raw["semantic_layer_enabled"]
    if isinstance(raw.get("feedback_workflow"), dict):
        stored = raw["feedback_workflow"]
        workflow = dict(policy["feedback_workflow"])
        for key in FEEDBACK_WORKFLOW_BOOL_KEYS:
            if isinstance(stored.get(key), bool):
                workflow[key] = stored[key]
        epsilon = stored.get("exploration_epsilon")
        if (
            not isinstance(epsilon, bool)
            and isinstance(epsilon, (int, float))
            and EXPLORATION_EPSILON_RANGE[0] <= float(epsilon) <= EXPLORATION_EPSILON_RANGE[1]
        ):
            workflow["exploration_epsilon"] = float(epsilon)
        policy["feedback_workflow"] = workflow
    return policy


def _valid_int_in_range(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _valid_fusion_weights(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != set(FUSION_WEIGHT_KEYS):
        return False
    for key in FUSION_WEIGHT_KEYS:
        weight = value.get(key)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            return False
        if not 0.0 <= float(weight) <= 1.0:
            return False
    total = float(value["llm"]) + float(value["coarse"])
    return abs(total - 1.0) <= FUSION_WEIGHTS_SUM_TOLERANCE
