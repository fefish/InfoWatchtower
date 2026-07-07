"""内容导向 rubric：schema 校验、fingerprint、LLM 编译与幂等预览缓存。

事实源：docs/backend/recommendation-scoring-design.md §5；契约：
config/contracts/recommendation_ranking.json `rubric_schema` / `rubric_compile`
/ `rubric_activate`。

- fingerprint = sha256(canonical_json(guidance) + schema_version + compile_prompt_v1)；
- 缓存命中（recommendation_rubric_compiles 同 workspace+fingerprint）零模型调用；
- 编译走统一生成 provider 解析链 resolve_generation_config（§17 D1），
  记账 purpose=rubric_compile（固定 20 次/工作台/日）；
- 编译产物严格校验：未知键剥离、缺失键拒绝，失败重试 1 次仍失败抛
  RubricCompileInvalidError（API 层 502），active rubric 不受影响。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import try_acquire_rubric_compile_call
from app.llm.provider import request_chat_completion, resolve_generation_config
from app.models.common import utc_now
from app.models.content import RecommendationRubricCompile
from app.recommendations.policy import GUIDANCE_FIELDS

RUBRIC_SCHEMA_VERSION = 1
COMPILE_PROMPT_VERSION = "compile_prompt_v1"
ACTIVATE_FINGERPRINT_MAX_AGE_DAYS = 7

TOPIC_CODE_PATTERN = re.compile(r"^[a-z0-9_]{2,32}$")
TOPICS_COUNT_RANGE = (3, 12)
TOPIC_WEIGHT_RANGE = (0.0, 5.0)
EXCLUSIONS_MAX = 10
EXCLUSION_SEVERITIES = ("hard", "soft")
BOOST_SIGNALS_MAX = 8
BOOST_BONUS_RANGE = (1, 10)
SCORING_DIMENSION_CODES = ("relevance", "evidence", "impact", "timeliness", "actionability")
SCORING_WEIGHTS_SUM_TOLERANCE = 0.001
LANGUAGES = ("zh", "en")

COMPILE_SYSTEM_PROMPT = """你是情报工作台的「内容导向编译器」。把用户的自然语言导向三段
（want=想要什么 / avoid=不要什么 / boost=加分信号）编译成固定 schema 的评分 rubric JSON。

要求：
1. topics：3-12 个主题，code 用 ^[a-z0-9_]{2,32}$ 的英文小写句柄且互不重复，
   label 用中文短语，weight 0.0-5.0（越核心越高），keywords_hint 给 2-6 个关键词提示。
2. exclusions：0-10 条排除规则（来自 avoid），severity 取 hard（强排除）或 soft。
3. boost_signals：0-8 条加分信号（来自 boost），bonus 1-10。
4. scoring_dimensions：必须包含 relevance；code 只能取
   relevance/evidence/impact/timeliness/actionability；weight 之和 = 1.0。
5. language 取 zh 或 en。
只输出一个合法 JSON 对象，不要输出 Markdown 代码块或解释文字。"""


class RubricValidationError(ValueError):
    """编译产物不符合 rubric schema。"""


class RubricCompileBudgetError(RuntimeError):
    """rubric_compile 桶当日 20 次上限已用尽。"""


class RubricCompileProviderError(RuntimeError):
    """生成 provider 不可用（未启用/key 未配置/凭据失效）。"""


class RubricCompileInvalidError(RuntimeError):
    """模型两次输出都不符合 schema（API 层映射 502）。"""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail[:200]


@dataclass(frozen=True)
class RubricCompileResult:
    rubric: dict[str, Any]
    fingerprint: str
    cached: bool


def normalize_guidance(guidance: Any) -> dict[str, str]:
    data = guidance if isinstance(guidance, dict) else {}
    return {key: str(data.get(key) or "") for key in GUIDANCE_FIELDS}


def guidance_fingerprint(guidance: dict[str, str]) -> str:
    """sha256(canonical_json(guidance) + schema_version + compile_prompt_v1)。"""
    canonical = json.dumps(
        normalize_guidance(guidance),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{canonical}|{RUBRIC_SCHEMA_VERSION}|{COMPILE_PROMPT_VERSION}".encode(),
    ).hexdigest()
    return f"sha256:{digest}"


def validate_rubric(data: Any, *, fingerprint: str) -> dict[str, Any]:
    """严格校验编译产物：未知键剥离、缺失/越界键拒绝（§5.2）。"""
    if not isinstance(data, dict):
        raise RubricValidationError("rubric must be a JSON object")

    topics_raw = data.get("topics")
    if not isinstance(topics_raw, list) or not (
        TOPICS_COUNT_RANGE[0] <= len(topics_raw) <= TOPICS_COUNT_RANGE[1]
    ):
        raise RubricValidationError("topics must contain 3..12 items")
    topics: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for entry in topics_raw:
        if not isinstance(entry, dict):
            raise RubricValidationError("topic entries must be objects")
        code = entry.get("code")
        if not isinstance(code, str) or not TOPIC_CODE_PATTERN.fullmatch(code):
            raise RubricValidationError(f"invalid topic code: {code!r}")
        if code in seen_codes:
            raise RubricValidationError(f"duplicate topic code: {code}")
        seen_codes.add(code)
        weight = entry.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise RubricValidationError(f"topic {code} weight must be a number")
        weight = float(weight)
        if not TOPIC_WEIGHT_RANGE[0] <= weight <= TOPIC_WEIGHT_RANGE[1]:
            raise RubricValidationError(f"topic {code} weight out of range 0.0..5.0")
        keywords_hint = entry.get("keywords_hint") or []
        if not isinstance(keywords_hint, list):
            raise RubricValidationError(f"topic {code} keywords_hint must be a list")
        topics.append(
            {
                "code": code,
                "label": str(entry.get("label") or code),
                "weight": weight,
                "keywords_hint": [str(item) for item in keywords_hint],
            },
        )

    exclusions_raw = data.get("exclusions") or []
    if not isinstance(exclusions_raw, list) or len(exclusions_raw) > EXCLUSIONS_MAX:
        raise RubricValidationError("exclusions must contain 0..10 items")
    exclusions: list[dict[str, Any]] = []
    for entry in exclusions_raw:
        if not isinstance(entry, dict):
            raise RubricValidationError("exclusion entries must be objects")
        code = entry.get("code")
        if not isinstance(code, str) or not TOPIC_CODE_PATTERN.fullmatch(code):
            raise RubricValidationError(f"invalid exclusion code: {code!r}")
        severity = entry.get("severity")
        if severity not in EXCLUSION_SEVERITIES:
            raise RubricValidationError(f"exclusion {code} severity must be hard|soft")
        exclusions.append(
            {
                "code": code,
                "rule": str(entry.get("rule") or ""),
                "severity": severity,
            },
        )

    boosts_raw = data.get("boost_signals") or []
    if not isinstance(boosts_raw, list) or len(boosts_raw) > BOOST_SIGNALS_MAX:
        raise RubricValidationError("boost_signals must contain 0..8 items")
    boost_signals: list[dict[str, Any]] = []
    for entry in boosts_raw:
        if not isinstance(entry, dict):
            raise RubricValidationError("boost entries must be objects")
        code = entry.get("code")
        if not isinstance(code, str) or not TOPIC_CODE_PATTERN.fullmatch(code):
            raise RubricValidationError(f"invalid boost code: {code!r}")
        bonus = entry.get("bonus")
        if isinstance(bonus, bool) or not isinstance(bonus, int):
            raise RubricValidationError(f"boost {code} bonus must be an integer")
        if not BOOST_BONUS_RANGE[0] <= bonus <= BOOST_BONUS_RANGE[1]:
            raise RubricValidationError(f"boost {code} bonus out of range 1..10")
        boost_signals.append(
            {
                "code": code,
                "description": str(entry.get("description") or ""),
                "bonus": bonus,
            },
        )

    dimensions_raw = data.get("scoring_dimensions")
    if not isinstance(dimensions_raw, list) or not dimensions_raw:
        raise RubricValidationError("scoring_dimensions is required")
    dimensions: list[dict[str, Any]] = []
    dimension_codes: set[str] = set()
    weight_total = 0.0
    for entry in dimensions_raw:
        if not isinstance(entry, dict):
            raise RubricValidationError("scoring_dimensions entries must be objects")
        code = entry.get("code")
        if code not in SCORING_DIMENSION_CODES:
            raise RubricValidationError(f"invalid scoring dimension code: {code!r}")
        if code in dimension_codes:
            raise RubricValidationError(f"duplicate scoring dimension: {code}")
        dimension_codes.add(code)
        weight = entry.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise RubricValidationError(f"dimension {code} weight must be a number")
        weight = float(weight)
        weight_total += weight
        dimensions.append({"code": code, "weight": weight})
    if "relevance" not in dimension_codes:
        raise RubricValidationError("scoring_dimensions must include relevance")
    if abs(weight_total - 1.0) > SCORING_WEIGHTS_SUM_TOLERANCE:
        raise RubricValidationError("scoring_dimensions weights must sum to 1.0")

    language = data.get("language")
    if language not in LANGUAGES:
        raise RubricValidationError("language must be zh|en")

    # 未知键在此剥离：只回传固定 schema 的键。
    return {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "topics": topics,
        "exclusions": exclusions,
        "boost_signals": boost_signals,
        "scoring_dimensions": dimensions,
        "language": language,
        "source_guidance_fingerprint": fingerprint,
    }


def hard_exclusion_codes(rubric: dict[str, Any] | None) -> set[str]:
    if not isinstance(rubric, dict):
        return set()
    return {
        str(entry.get("code"))
        for entry in rubric.get("exclusions") or []
        if isinstance(entry, dict) and entry.get("severity") == "hard"
    }


def _parse_model_json(content: str) -> Any:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def compile_rubric(
    session: Session,
    workspace: Any,
    guidance: dict[str, str],
    *,
    created_by: str = "",
) -> RubricCompileResult:
    """编译导向为 rubric（幂等预览）：缓存命中零模型调用，未命中恰 1 次调用
    （schema 失败重试 1 次，重试同样计 rubric_compile 预算）。

    编译不改变 active_rubric / rubric_version —— 预览确认前对推荐零影响。
    """
    guidance = normalize_guidance(guidance)
    fingerprint = guidance_fingerprint(guidance)
    workspace_code = str(getattr(workspace, "code", "") or "")

    cached_row = session.scalar(
        select(RecommendationRubricCompile).where(
            RecommendationRubricCompile.workspace_code == workspace_code,
            RecommendationRubricCompile.fingerprint == fingerprint,
        ),
    )
    if cached_row is not None:
        return RubricCompileResult(
            rubric=dict(cached_row.rubric_json or {}),
            fingerprint=fingerprint,
            cached=True,
        )

    # 统一解析链（§17 D1）：凭据 → 实例 env；不可用即拒绝，零外呼。
    config = resolve_generation_config(workspace=workspace)
    if not (config.enabled and config.key_configured):
        raise RubricCompileProviderError(
            "generation provider is not usable (enabled + key required)",
        )

    user_prompt = json.dumps(
        {
            "guidance": guidance,
            "schema_version": RUBRIC_SCHEMA_VERSION,
            "prompt_version": COMPILE_PROMPT_VERSION,
        },
        ensure_ascii=False,
    )
    last_error = ""
    rubric: dict[str, Any] | None = None
    for _attempt in (1, 2):
        if not try_acquire_rubric_compile_call(session, workspace_code):
            raise RubricCompileBudgetError(
                "rubric compile daily cap reached (20 calls per workspace per day)",
            )
        try:
            content = request_chat_completion(config, COMPILE_SYSTEM_PROMPT, user_prompt)
            rubric = validate_rubric(_parse_model_json(content), fingerprint=fingerprint)
            break
        except (RubricValidationError, ValueError, KeyError, TypeError) as exc:
            last_error = str(exc)
            rubric = None
    if rubric is None:
        raise RubricCompileInvalidError(
            "rubric compile output failed schema validation twice",
            detail=last_error,
        )

    session.add(
        RecommendationRubricCompile(
            workspace_code=workspace_code,
            fingerprint=fingerprint,
            guidance_json=guidance,
            rubric_json=rubric,
            prompt_version=COMPILE_PROMPT_VERSION,
            model_called=True,
            created_by=created_by,
        ),
    )
    session.flush()
    return RubricCompileResult(rubric=rubric, fingerprint=fingerprint, cached=False)


def find_activatable_compile(
    session: Session,
    workspace_code: str,
    fingerprint: str,
) -> RecommendationRubricCompile | None:
    """activate 门禁：fingerprint 必须命中本工作台 7 天内的编译记录。"""
    row = session.scalar(
        select(RecommendationRubricCompile).where(
            RecommendationRubricCompile.workspace_code == workspace_code,
            RecommendationRubricCompile.fingerprint == fingerprint,
        ),
    )
    if row is None:
        return None
    created_at = row.created_at
    if created_at.tzinfo is None:
        from datetime import UTC

        created_at = created_at.replace(tzinfo=UTC)
    if created_at < utc_now() - timedelta(days=ACTIVATE_FINGERPRINT_MAX_AGE_DAYS):
        return None
    return row
