"""工作台内容策略解析（app.workspaces.policy）回归测试。

覆盖两条主线：
1. planning_intel 的解析结果必须与内置 AI 默认完全一致（回归红线）。
2. 非 AI 工作台按「标签策略 -> domain pack -> 内置默认」解析出自己的
   评分先验、分类降级、看板 taxonomy、生成人称与导出口径。
"""

from sqlalchemy import select

from app.models.labels import Label, LabelSet
from app.models.workspace import Workspace
from app.workspaces.policy import (
    AI_SQL_CATEGORIES,
    BUILTIN_CATEGORY_KEYWORD_RULES,
    _label_policy_board_taxonomy,
    ai_board_taxonomy,
    ensure_workspace_label_set,
    list_domain_packs,
    policy_for_workspace,
    resolve_workspace_content_policy,
)
from tests.test_news_normalization import seed_workspace
from tests.test_recommendations import make_session
from tests.test_workspaces_api import make_client

PLANNING_EFFECTS_FALLBACK = (
    "该信号可能影响规划部对技术路线、产品节奏、竞争态势或内部需求转化的"
    "后续判断，需要结合业务场景继续观察。"
)


def _add_workspace(session, code: str, name: str, domain_code: str, label_policy: dict | None = None) -> Workspace:
    workspace = Workspace(
        code=code,
        name=name,
        description="",
        default_domain_code=domain_code,
        config_json={"label_policy": label_policy} if label_policy else {},
    )
    session.add(workspace)
    session.flush()
    return workspace


def test_planning_intel_policy_locked_to_builtin_ai_defaults():
    session = make_session()
    workspace = seed_workspace(session)

    policy = policy_for_workspace(workspace)

    assert policy.policy_source == "builtin_ai"
    assert policy.scoring_mode == "ai_default"
    assert policy.allowed_primary_categories == AI_SQL_CATEGORIES
    assert policy.category_keyword_rules == BUILTIN_CATEGORY_KEYWORD_RULES
    assert policy.boards.source == "ai_builtin"
    assert policy.boards.board_order == ai_board_taxonomy().board_order
    assert len(policy.boards.board_order) == 14
    assert policy.boards.fallback_board == "基础竞争力"
    assert policy.persona == "规划部"
    assert policy.effects_fallback_text == PLANNING_EFFECTS_FALLBACK
    assert policy.export_category_mode == "news_primary"
    assert policy.company_sql_capable is True


def test_planning_intel_resets_foreign_label_set_code():
    session = make_session()
    workspace = seed_workspace(session)
    workspace.config_json = {
        "label_policy": {
            "label_set_code": "hardware_categories",
            "allowed_primary_categories": ["算力芯片"],
            "default_category": "算力芯片",
        },
    }
    session.flush()

    policy = policy_for_workspace(workspace)

    assert policy.label_set_code == "ai_sql_categories"
    assert policy.allowed_primary_categories == AI_SQL_CATEGORIES
    assert policy.scoring_mode == "ai_default"
    assert policy.boards.source == "ai_builtin"


def test_default_new_workspace_inherits_ai_taxonomy_declaration():
    """建台默认策略（ai_sql_categories）声明 AI 口径：评分/看板/导出与内置一致。"""
    session = make_session()
    workspace = _add_workspace(
        session,
        "strategy_intel",
        "战略情报工作台",
        "ai",
        label_policy={
            "label_set_code": "ai_sql_categories",
            "news_format_code": "company_sql_v1",
            "allowed_primary_categories": list(AI_SQL_CATEGORIES),
            "default_category": "AI 应用",
            "fallback_category": "AI 应用",
        },
    )

    policy = policy_for_workspace(workspace)

    assert policy.scoring_mode == "ai_default"
    assert policy.boards.source == "ai_builtin"
    assert policy.company_sql_capable is True
    # 生成降级文案人称默认取 workspace.name（planning_intel 之外不再自称规划部）
    assert policy.persona == "战略情报工作台"
    assert "战略情报工作台" in policy.effects_fallback_text
    assert "规划部" not in policy.effects_fallback_text


def test_hardware_pack_workspace_resolves_scoring_boards_and_category_rules():
    session = make_session()
    workspace = _add_workspace(
        session,
        "hardware_intel",
        "硬件情报工作台",
        "hardware",
        label_policy={
            "label_set_code": "hardware_categories",
            "news_format_code": "tech_insight_v1",
            "allowed_primary_categories": ["算力芯片", "端侧设备", "供应链与制造"],
            "default_category": "算力芯片",
            "fallback_category": "算力芯片",
        },
    )

    policy = policy_for_workspace(workspace)

    # 评分先验来自 domain pack scoring
    assert policy.scoring_mode == "workspace_neutral"
    assert policy.policy_source == "domain_pack:hardware"
    assert "gpu" in policy.scoring_prior_keywords
    assert "晶圆" in policy.scoring_prior_keywords
    assert policy.source_weight_hints["compute_chips"] == 1.2
    # 看板 taxonomy 来自 pack boards
    assert policy.boards.source == "domain_pack:hardware"
    assert policy.boards.board_order == ("算力芯片", "端侧设备", "供应链与制造")
    assert policy.boards.fallback_board == "算力芯片"
    # pack label set 的二级标签被看板归组消费
    assert policy.boards.category_to_board["GPU"] == "算力芯片"
    assert policy.boards.category_to_board["晶圆代工"] == "供应链与制造"
    # 分类降级关键词来自 pack category_keywords，不再是 AI 关键词表
    rules = dict(policy.category_keyword_rules)
    assert "hbm" in rules["算力芯片"]
    assert "代工" in rules["供应链与制造"]
    # 非 AI 十分类：不适配公司 SQL 导出
    assert policy.company_sql_capable is False


def test_custom_label_policy_without_pack_uses_own_taxonomy():
    session = make_session()
    workspace = _add_workspace(
        session,
        "policy_intel",
        "政策情报工作台",
        "policy",
        label_policy={
            "label_set_code": "policy_intel_custom_categories",
            "news_format_code": "company_sql_v1",
            "allowed_primary_categories": ["合规监管", "行业动态"],
            "secondary_labels_by_primary": {"合规监管": ["数据出境", "牌照审批"]},
            "default_category": "行业动态",
            "fallback_category": "行业动态",
        },
    )

    policy = policy_for_workspace(workspace)

    assert policy.scoring_mode == "workspace_neutral"
    assert policy.policy_source == "label_policy"
    # 先验关键词由类目名与二级标签构成
    assert "合规监管" in policy.scoring_prior_keywords
    assert "数据出境" in policy.scoring_prior_keywords
    # 看板 = 一级类目；二级标签归入其一级看板
    assert policy.boards.source == "label_policy"
    assert policy.boards.board_order == ("合规监管", "行业动态")
    assert policy.boards.fallback_board == "行业动态"
    assert policy.boards.category_to_board["数据出境"] == "合规监管"
    # 分类降级规则按类目构造
    rules = dict(policy.category_keyword_rules)
    assert "牌照审批" in rules["合规监管"]
    # 类目不是 AI 十分类：即便 news_format_code 是 company_sql_v1 也不适配导出
    assert policy.company_sql_capable is False
    assert policy.persona == "政策情报工作台"


def test_board_taxonomy_defensive_single_group_when_empty():
    taxonomy = _label_policy_board_taxonomy((), "", {})
    assert taxonomy.source == "single_group"
    assert taxonomy.board_order == ("全部",)
    assert taxonomy.fallback_board == "全部"


def test_resolve_workspace_content_policy_by_code():
    session = make_session()
    seed_workspace(session)
    policy = resolve_workspace_content_policy(session, "planning_intel")
    assert policy.workspace_code == "planning_intel"


def test_ensure_workspace_label_set_upserts_custom_sets_only():
    session = make_session()
    custom = _add_workspace(
        session,
        "policy_intel",
        "政策情报工作台",
        "policy",
        label_policy={
            "label_set_code": "policy_intel_custom_categories",
            "allowed_primary_categories": ["合规监管", "行业动态"],
            "secondary_labels_by_primary": {"合规监管": ["数据出境"]},
            "default_category": "行业动态",
        },
    )
    policy = policy_for_workspace(custom)

    created = ensure_workspace_label_set(session, custom, policy)
    session.flush()

    assert created is not None
    stored = session.scalar(
        select(LabelSet).where(
            LabelSet.workspace_code == "policy_intel",
            LabelSet.code == "policy_intel_custom_categories",
        ),
    )
    assert stored is not None
    assert stored.config_json["managed_by"] == "workspace_label_policy"
    labels = session.scalars(select(Label).where(Label.label_set_id == stored.id)).all()
    primary_codes = {label.code for label in labels if label.label_level == 1}
    secondary = [label for label in labels if label.label_level == 2]
    assert primary_codes == {"合规监管", "行业动态"}
    assert [label.code for label in secondary] == ["合规监管:数据出境"]
    assert secondary[0].parent_label.code == "合规监管"

    # 幂等：重复调用不产生重复标签
    ensure_workspace_label_set(session, custom, policy)
    session.flush()
    assert len(session.scalars(select(Label).where(Label.label_set_id == stored.id)).all()) == 3

    # 内置标签集与 pack shared 标签集跳过（由 seed 负责）
    planning = seed_workspace(session)
    assert ensure_workspace_label_set(session, planning, policy_for_workspace(planning)) is None
    hardware = _add_workspace(
        session,
        "hardware_intel",
        "硬件情报工作台",
        "hardware",
        label_policy={
            "label_set_code": "hardware_categories",
            "allowed_primary_categories": ["算力芯片"],
            "default_category": "算力芯片",
        },
    )
    assert ensure_workspace_label_set(session, hardware, policy_for_workspace(hardware)) is None


def test_list_domain_packs_exposes_consumable_summary():
    packs = {pack["domain_code"]: pack for pack in list_domain_packs()}
    hardware = packs["hardware"]
    assert hardware["name"] == "硬件情报板块"
    assert [board["name"] for board in hardware["boards"]] == ["算力芯片", "端侧设备", "供应链与制造"]
    assert hardware["fallback_board"] == "算力芯片"
    assert hardware["label_sets"][0]["code"] == "hardware_categories"
    assert "GPU" in hardware["label_sets"][0]["secondary_labels_by_primary"]["算力芯片"]
    assert "gpu" in hardware["category_keywords"]["算力芯片"]
    assert "GPU" in hardware["scoring"]["prior_keywords"]
    assert hardware["scoring"]["source_weight_hints"]["compute_chips"] == 1.2
    assert hardware["associate_by"] == "workspace.default_domain_code"


def test_domain_packs_api_lists_packs_for_logged_in_users(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path)

    unauthenticated = client.get("/api/domain-packs")
    assert unauthenticated.status_code == 401

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    response = client.get("/api/domain-packs")
    assert response.status_code == 200
    payload = {pack["domain_code"]: pack for pack in response.json()}
    assert "hardware" in payload
    hardware = payload["hardware"]
    assert hardware["associate_by"] == "workspace.default_domain_code"
    assert [board["code"] for board in hardware["boards"]] == [
        "compute_chips",
        "edge_devices",
        "supply_chain",
    ]
    assert hardware["scoring"]["prior_keywords"]
    assert hardware["label_sets"][0]["categories"][0] == "算力芯片"
