"""工作台内容策略解析（多工作台目标态的策略中枢）。

planning_intel 的 AI 情报口径只是内置默认样板：评分/准入关键词先验、
LLM 不可用时的分类降级映射、成稿看板 taxonomy、生成降级文案人称与
公司 SQL 导出口径都在这里按统一顺序解析，不再散落硬编码在通用层：

    workspace 标签策略（数据库 config_json.label_policy）
        -> workspace 关联的 domain pack（config/domain_packs/{default_domain_code}.json）
        -> 内置默认（= planning_intel 的 AI 规则）

不变式：planning_intel 的解析结果必须与内置 AI 默认完全一致，这是
公司 SQL 契约与既有推荐/成稿行为的回归红线。

二级标签消费语义（最小闭环）：
- 自定义 label_set_code 会在推荐链路运行时随标签策略 upsert 成
  LabelSet/Label 记录（一级/二级层级与 seed 的 domain pack 注册同构）。
- secondary_labels_by_primary 参与两处解析：作为分类降级与评分先验的
  关键词；以及成稿看板归组映射（命中二级标签的 category 归入其一级
  分类对应的看板）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.models.labels import Label, LabelSet
from app.models.workspace import Workspace

PLANNING_WORKSPACE_CODE = "planning_intel"
PLANNING_PERSONA = "规划部"
DEFAULT_LABEL_SET_CODE = "ai_sql_categories"
COMPANY_SQL_FORMAT_CODE = "company_sql_v1"
SINGLE_GROUP_BOARD = "全部"
# 生成降级文案模板：persona 按工作台解析，planning_intel 固定为「规划部」，
# 其余工作台默认使用 workspace.name（可用 config_json.persona 覆盖）。
EFFECTS_FALLBACK_TEMPLATE = (
    "该信号可能影响{persona}对技术路线、产品节奏、竞争态势或内部需求转化的"
    "后续判断，需要结合业务场景继续观察。"
)
# seed 注册的内置标签集：不在推荐链路重复 upsert。
BUILTIN_LABEL_SET_CODES = {
    "ai_sql_categories",
    "ai_tools_categories",
    "planning_source_tags",
}

AI_SQL_CATEGORIES = (
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
)

# 内置分类降级关键词表（顺序即命中优先级，覆盖 AI 十分类与 AI 工具类目；
# 这是 planning_intel / ai_tools 的默认策略数据，不再对所有工作台隐含生效）。
BUILTIN_CATEGORY_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("工具新功能", ("release", "发布", "更新", "feature")),
    ("工具新案例", ("case", "案例", "实践")),
    ("工具新技术", ("技术", "architecture", "benchmark")),
    ("智能体", ("agent", "agents", "智能体")),
    ("推理加速", ("inference", "推理", "加速", "kv cache", "serving", "latency", "吞吐")),
    ("训练技术", ("training", "训练", "fine-tuning", "finetune", "post-training", "后训练")),
    ("测评技术", ("benchmark", "评测", "evaluation", "eval", "dataset", "数据集")),
    ("AI Infra", ("infra", "infrastructure", "gpu", "hbm", "cxl", "集群", "数据中心")),
    ("模型", ("model", "模型", "llm")),
    ("算法", ("algorithm", "算法", "architecture", "架构", "优化")),
    ("大厂动态", ("openai", "google", "deepmind", "meta", "microsoft", "anthropic", "amazon")),
    ("AI 应用", ("application", "应用", "assistant", "copilot", "workflow", "case")),
)


@dataclass(frozen=True)
class BoardTaxonomy:
    """成稿看板 taxonomy：来源 + 顺序 + 分类到看板的归组映射。"""

    source: str  # ai_builtin / domain_pack:<code> / label_policy / single_group
    board_order: tuple[str, ...]
    fallback_board: str
    category_to_board: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceContentPolicy:
    workspace_code: str
    workspace_name: str
    policy_source: str  # builtin_ai / domain_pack:<code> / label_policy
    # 评分/准入：ai_default = 内置 AI 情报口径（含噪声降权与全局 scorer 配置），
    # workspace_neutral = 中性口径（不套 AI 噪声，先验关键词经 policy 获取）。
    scoring_mode: str
    scoring_prior_keywords: tuple[str, ...]
    source_weight_hints: dict[str, float]
    # 标签策略与分类降级
    label_set_code: str
    allowed_primary_categories: tuple[str, ...]
    default_category: str
    fallback_category: str
    category_keyword_rules: tuple[tuple[str, tuple[str, ...]], ...]
    secondary_labels_by_primary: dict[str, tuple[str, ...]]
    # 成稿与导出
    boards: BoardTaxonomy
    news_format_code: str
    export_category_mode: str
    company_sql_capable: bool
    # 生成文案人称
    persona: str
    effects_fallback_text: str


def domain_pack_dir() -> Path:
    return REPO_ROOT / "config" / "domain_packs"


@lru_cache(maxsize=32)
def load_domain_pack(domain_code: str) -> dict[str, Any] | None:
    """读取 config/domain_packs/{domain_code}.json；不存在或非法返回 None。"""
    if not domain_code:
        return None
    path = domain_pack_dir() / f"{domain_code}.json"
    if not path.exists():
        return None
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return pack if isinstance(pack, dict) else None


def list_domain_packs() -> list[dict[str, Any]]:
    """列出可用 domain pack 概要（供 GET /api/domain-packs 与建台向导消费）。"""
    packs: list[dict[str, Any]] = []
    pack_dir = domain_pack_dir()
    if not pack_dir.exists():
        return packs
    for path in sorted(pack_dir.glob("*.json")):
        pack = load_domain_pack(path.stem)
        if not pack:
            continue
        domain_code = str(pack.get("domain_code") or path.stem)
        scoring = pack.get("scoring") if isinstance(pack.get("scoring"), dict) else {}
        packs.append(
            {
                "domain_code": domain_code,
                "name": str(pack.get("name") or domain_code),
                "description": str(pack.get("description") or ""),
                "boards": [
                    {
                        "code": str(board.get("code") or ""),
                        "name": str(board.get("name") or board.get("code") or ""),
                        "description": str(board.get("description") or ""),
                        "suggested_categories": [
                            str(item) for item in board.get("suggested_categories") or []
                        ],
                    }
                    for board in pack.get("boards") or []
                    if isinstance(board, dict)
                ],
                "fallback_board": str(pack.get("fallback_board") or ""),
                "label_sets": [
                    {
                        "code": str(label_set.get("code") or ""),
                        "name": str(label_set.get("name") or ""),
                        "categories": [str(item) for item in label_set.get("categories") or []],
                        "secondary_labels_by_primary": {
                            str(primary): [str(label) for label in labels or []]
                            for primary, labels in (label_set.get("secondary_labels_by_primary") or {}).items()
                        },
                    }
                    for label_set in pack.get("label_sets") or []
                    if isinstance(label_set, dict)
                ],
                "category_keywords": {
                    str(category): [str(keyword) for keyword in keywords or []]
                    for category, keywords in (pack.get("category_keywords") or {}).items()
                },
                "scoring": {
                    "prior_keywords": [str(item) for item in scoring.get("prior_keywords") or []],
                    "source_weight_hints": {
                        str(key): float(value)
                        for key, value in (scoring.get("source_weight_hints") or {}).items()
                        if isinstance(value, (int, float))
                    },
                },
                "associate_by": "workspace.default_domain_code",
            },
        )
    return packs


@lru_cache
def _business_boards_config() -> dict[str, Any]:
    path = REPO_ROOT / "config" / "taxonomy" / "business_boards.json"
    return json.loads(path.read_text(encoding="utf-8"))


def ai_board_taxonomy() -> BoardTaxonomy:
    """内置 AI/通信 14 板块 taxonomy（planning_intel 及声明 AI 口径的工作台）。"""
    config = _business_boards_config()
    mapping: dict[str, str] = {}
    for board in config.get("boards") or []:
        for category in board.get("suggested_categories") or []:
            mapping.setdefault(str(category), str(board["code"]))
    return BoardTaxonomy(
        source="ai_builtin",
        board_order=tuple(str(code) for code in config.get("board_order") or []),
        fallback_board=str(config.get("fallback_board") or "基础竞争力"),
        category_to_board=mapping,
    )


def _pack_board_taxonomy(
    pack: dict[str, Any],
    secondary_labels_by_primary: dict[str, tuple[str, ...]],
) -> BoardTaxonomy | None:
    boards = [board for board in pack.get("boards") or [] if isinstance(board, dict)]
    board_names: list[str] = []
    mapping: dict[str, str] = {}
    for board in boards:
        name = str(board.get("name") or board.get("code") or "")
        if not name:
            continue
        board_names.append(name)
        mapping.setdefault(name, name)
        for category in board.get("suggested_categories") or []:
            mapping.setdefault(str(category), name)
    if not board_names:
        return None
    # 二级标签归入其一级分类对应的看板
    for primary, labels in secondary_labels_by_primary.items():
        primary_board = mapping.get(str(primary))
        if not primary_board:
            continue
        for label in labels:
            mapping.setdefault(str(label), primary_board)
    fallback = str(pack.get("fallback_board") or "")
    if fallback not in board_names:
        fallback = board_names[0]
    domain_code = str(pack.get("domain_code") or "")
    return BoardTaxonomy(
        source=f"domain_pack:{domain_code}",
        board_order=tuple(board_names),
        fallback_board=fallback,
        category_to_board=mapping,
    )


def _label_policy_board_taxonomy(
    allowed_primary_categories: tuple[str, ...],
    fallback_category: str,
    secondary_labels_by_primary: dict[str, tuple[str, ...]],
) -> BoardTaxonomy:
    if not allowed_primary_categories:
        return _single_group_taxonomy()
    mapping: dict[str, str] = {}
    for primary in allowed_primary_categories:
        mapping.setdefault(primary, primary)
        for label in secondary_labels_by_primary.get(primary, ()):  # 二级标签归入一级看板
            mapping.setdefault(str(label), primary)
    fallback = fallback_category if fallback_category in allowed_primary_categories else allowed_primary_categories[0]
    return BoardTaxonomy(
        source="label_policy",
        board_order=tuple(allowed_primary_categories),
        fallback_board=fallback,
        category_to_board=mapping,
    )


def _single_group_taxonomy() -> BoardTaxonomy:
    return BoardTaxonomy(
        source="single_group",
        board_order=(SINGLE_GROUP_BOARD,),
        fallback_board=SINGLE_GROUP_BOARD,
        category_to_board={},
    )


def _pack_label_set(pack: dict[str, Any] | None, label_set_code: str) -> dict[str, Any] | None:
    if not pack or not label_set_code:
        return None
    for label_set in pack.get("label_sets") or []:
        if isinstance(label_set, dict) and str(label_set.get("code") or "") == label_set_code:
            return label_set
    return None


def _normalize_keywords(keywords: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for keyword in keywords:
        value = str(keyword).strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _custom_category_rules(
    allowed: tuple[str, ...],
    secondary_labels_by_primary: dict[str, tuple[str, ...]],
    pack: dict[str, Any] | None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """自定义类目的分类降级规则：pack 的 category_keywords 优先，
    其次以类目名与其二级标签作为关键词。"""
    pack_keywords = {}
    if pack and isinstance(pack.get("category_keywords"), dict):
        pack_keywords = {
            str(category): [str(keyword) for keyword in keywords or []]
            for category, keywords in pack["category_keywords"].items()
        }
    rules: list[tuple[str, tuple[str, ...]]] = []
    for category in allowed:
        keywords = [
            *pack_keywords.get(category, []),
            category,
            *secondary_labels_by_primary.get(category, ()),
        ]
        rules.append((category, _normalize_keywords(keywords)))
    return tuple(rules)


def policy_for_workspace(workspace: Workspace) -> WorkspaceContentPolicy:
    """按「标签策略 -> domain pack -> 内置默认」解析工作台内容策略。"""
    config = dict(workspace.config_json or {})
    raw_policy = dict(config.get("label_policy") or {})
    is_planning = workspace.code == PLANNING_WORKSPACE_CODE
    # planning_intel 的口径锁死为内置 AI 默认：异常的 label_set_code 一律重置。
    if is_planning and raw_policy.get("label_set_code") not in {None, DEFAULT_LABEL_SET_CODE}:
        raw_policy = {}

    label_set_code = str(raw_policy.get("label_set_code") or DEFAULT_LABEL_SET_CODE)
    allowed = tuple(str(item) for item in raw_policy.get("allowed_primary_categories") or [])
    if not allowed:
        allowed = AI_SQL_CATEGORIES
    default_category = str(raw_policy.get("default_category") or allowed[0])
    fallback_category = str(raw_policy.get("fallback_category") or allowed[0])
    secondary_labels = {
        str(primary): tuple(str(label) for label in labels or [])
        for primary, labels in (raw_policy.get("secondary_labels_by_primary") or {}).items()
    }
    news_format_code = str(raw_policy.get("news_format_code") or COMPANY_SQL_FORMAT_CODE)
    export_category_mode = str(raw_policy.get("export_category_mode") or "news_primary")

    pack = None if is_planning else load_domain_pack(workspace.default_domain_code)
    pack_scoring = dict(pack.get("scoring") or {}) if pack else {}
    pack_domain = str(pack.get("domain_code") or "") if pack else ""
    is_builtin_ai_labels = label_set_code == DEFAULT_LABEL_SET_CODE
    is_builtin_tool_labels = label_set_code == "ai_tools_categories"
    pack_owns_label_set = _pack_label_set(pack, label_set_code) is not None
    if pack_owns_label_set and not secondary_labels:
        pack_set = _pack_label_set(pack, label_set_code) or {}
        secondary_labels = {
            str(primary): tuple(str(label) for label in labels or [])
            for primary, labels in (pack_set.get("secondary_labels_by_primary") or {}).items()
        }

    # 分类降级规则：内置标签集用内置关键词表（保持既有优先级顺序），
    # 自定义标签集按 policy/pack 构造。
    if is_builtin_ai_labels or is_builtin_tool_labels:
        category_rules = BUILTIN_CATEGORY_KEYWORD_RULES
    else:
        category_rules = _custom_category_rules(allowed, secondary_labels, pack)

    # 评分/准入口径
    pack_prior_keywords = _normalize_keywords(
        [str(item) for item in pack_scoring.get("prior_keywords") or []],
    )
    if is_planning:
        scoring_mode = "ai_default"
        policy_source = "builtin_ai"
        prior_keywords: tuple[str, ...] = ()
    elif pack_prior_keywords:
        scoring_mode = "workspace_neutral"
        policy_source = f"domain_pack:{pack_domain}"
        prior_keywords = pack_prior_keywords
    elif is_builtin_ai_labels:
        scoring_mode = "ai_default"
        policy_source = "builtin_ai"
        prior_keywords = ()
    else:
        scoring_mode = "workspace_neutral"
        policy_source = "label_policy"
        prior_keywords = _normalize_keywords(
            [keyword for _, keywords in category_rules for keyword in keywords],
        )
    source_weight_hints = {
        str(key): float(value)
        for key, value in (pack_scoring.get("source_weight_hints") or {}).items()
        if isinstance(value, (int, float))
    }

    # 成稿看板 taxonomy
    if is_planning:
        boards = ai_board_taxonomy()
    elif pack_owns_label_set:
        boards = _pack_board_taxonomy(pack or {}, secondary_labels) or _label_policy_board_taxonomy(
            allowed, fallback_category, secondary_labels,
        )
    elif not is_builtin_ai_labels:
        boards = _label_policy_board_taxonomy(allowed, fallback_category, secondary_labels)
    elif pack:
        boards = _pack_board_taxonomy(pack, secondary_labels) or ai_board_taxonomy()
    else:
        boards = ai_board_taxonomy()
    if not boards.board_order:
        boards = _single_group_taxonomy()

    # 生成文案人称与公司 SQL 口径
    persona = PLANNING_PERSONA if is_planning else str(config.get("persona") or workspace.name or workspace.code)
    company_sql_capable = news_format_code == COMPANY_SQL_FORMAT_CODE and set(allowed) <= set(AI_SQL_CATEGORIES)

    return WorkspaceContentPolicy(
        workspace_code=workspace.code,
        workspace_name=workspace.name,
        policy_source=policy_source,
        scoring_mode=scoring_mode,
        scoring_prior_keywords=prior_keywords,
        source_weight_hints=source_weight_hints,
        label_set_code=label_set_code,
        allowed_primary_categories=allowed,
        default_category=default_category,
        fallback_category=fallback_category,
        category_keyword_rules=category_rules,
        secondary_labels_by_primary=secondary_labels,
        boards=boards,
        news_format_code=news_format_code,
        export_category_mode=export_category_mode,
        company_sql_capable=company_sql_capable,
        persona=persona,
        effects_fallback_text=EFFECTS_FALLBACK_TEMPLATE.format(persona=persona),
    )


def resolve_workspace_content_policy(session: Session, workspace_code: str) -> WorkspaceContentPolicy:
    workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
    if workspace is None:
        raise ValueError(f"Workspace not found: {workspace_code}")
    return policy_for_workspace(workspace)


def board_taxonomy_for_workspace(session: Session, workspace_code: str) -> BoardTaxonomy:
    """成稿层的看板 taxonomy 解析；工作台缺失时退回内置 AI 默认。"""
    workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
    if workspace is None:
        return ai_board_taxonomy()
    return policy_for_workspace(workspace).boards


def ensure_workspace_label_set(
    session: Session,
    workspace: Workspace,
    policy: WorkspaceContentPolicy,
) -> LabelSet | None:
    """自定义 label_set_code 落 LabelSet/Label 记录（幂等 upsert）。

    内置标签集与 domain pack 的 shared 标签集由 seed 负责注册，这里跳过；
    其余（如建台向导生成的 `${code}_custom_categories`）随推荐链路运行落库，
    使标签策略在 LabelSet 目录中可发现、可被看板归组消费。
    """
    code = policy.label_set_code
    if not code or code in BUILTIN_LABEL_SET_CODES:
        return None
    if _pack_label_set(load_domain_pack(workspace.default_domain_code), code) is not None:
        return None
    label_set = session.scalar(
        select(LabelSet).where(
            LabelSet.workspace_code == workspace.code,
            LabelSet.code == code,
        ),
    )
    if label_set is None:
        label_set = LabelSet(
            workspace_code=workspace.code,
            domain_code=workspace.default_domain_code,
            code=code,
            name=f"{workspace.name}标签策略",
            description="由工作台标签策略生成的一级/二级标签集。",
            scope_type="workspace",
            target_types={
                "target_types": [
                    "news_item",
                    "dedupe_group",
                    "daily_report_item",
                    "weekly_report_item",
                ],
            },
            enabled=True,
            config_json={"managed_by": "workspace_label_policy"},
        )
        session.add(label_set)
        session.flush()
    existing_labels = {label.code: label for label in label_set.labels}

    def upsert_label(code_value: str, name: str, level: int, parent: Label | None, sort_order: int) -> Label:
        label = existing_labels.get(code_value)
        if label is None:
            label = Label(
                label_set=label_set,
                code=code_value,
                name=name,
                label_level=level,
                parent_label=parent,
                sort_order=sort_order,
                enabled=True,
            )
            session.add(label)
            existing_labels[code_value] = label
        else:
            label.name = name
            label.label_level = level
            label.parent_label = parent
            label.sort_order = sort_order
            label.enabled = True
        return label

    for index, category in enumerate(policy.allowed_primary_categories, start=1):
        primary = upsert_label(category, category, 1, None, index)
        for secondary_index, secondary in enumerate(
            policy.secondary_labels_by_primary.get(category, ()), start=1,
        ):
            upsert_label(
                f"{category}:{secondary}",
                secondary,
                2,
                primary,
                1000 + index * 100 + secondary_index,
            )
    session.flush()
    return label_set
