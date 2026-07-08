"""工作台每日模型调用预算运行时（purpose 四桶）。

事实源：docs/backend/generation-provider-design.md §3.2、
docs/backend/recommendation-scoring-design.md §9.1 与
docs/backend/feedback-heat-scoring.md §17 第 5 条——计数按
(workspace_code, day_key, purpose) 统计当日模型调用（成功+失败都计，含重试与
模板增量字段生成）。四桶配额互不挤占：

- ``generation``：generation_policy.daily_generation_budget（现状语义不变）；
- ``rerank``：recommendation_policy.daily_rerank_call_budget（默认 60）；
- ``rubric_compile``：固定 20 次/工作台/日，不可配（防滥用）；
- ``feedback_rollup``：固定 4 次/工作台/日，不可配（周 rollup 提案生成专用）。

超出预算后由调用方走降级路径（generation 按 fallback_behavior；rerank 按
recommendation-scoring-design §9.3 skipped/partial）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.provider import ResolvedGenerationConfig
from app.models.common import utc_now
from app.models.content import GenerationUsage

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

PURPOSE_GENERATION = "generation"
PURPOSE_RERANK = "rerank"
PURPOSE_RUBRIC_COMPILE = "rubric_compile"
PURPOSE_FEEDBACK_ROLLUP = "feedback_rollup"
# rubric 编译日固定上限（recommendation-scoring-design §9.1，不可配）。
RUBRIC_COMPILE_DAILY_CAP = 20
# 反馈回哺提案生成日固定上限（feedback-heat-scoring §17 第 5 条，不可配）：
# 自动周任务不复用 rubric_compile 交互桶，四桶互不挤占。
FEEDBACK_ROLLUP_DAILY_CAP = 4


def current_day_key(now: datetime | None = None) -> str:
    """预算口径的“当日”：北京时区自然日（与日报 day_key 口径一致）。"""
    moment = now or utc_now()
    return moment.astimezone(BEIJING_TZ).date().isoformat()


def generation_calls_used(
    session: Session,
    workspace_code: str,
    day_key: str,
    purpose: str = PURPOSE_GENERATION,
) -> int:
    usage = session.scalar(
        select(GenerationUsage).where(
            GenerationUsage.workspace_code == workspace_code,
            GenerationUsage.day_key == day_key,
            GenerationUsage.purpose == purpose,
        ),
    )
    return usage.calls_total if usage is not None else 0


def record_generation_call(
    session: Session,
    workspace_code: str,
    day_key: str,
    purpose: str = PURPOSE_GENERATION,
) -> int:
    """登记一次模型调用（成功+失败都计），返回登记后该 purpose 桶的当日累计。"""
    usage = session.scalar(
        select(GenerationUsage).where(
            GenerationUsage.workspace_code == workspace_code,
            GenerationUsage.day_key == day_key,
            GenerationUsage.purpose == purpose,
        ),
    )
    if usage is None:
        usage = GenerationUsage(
            workspace_code=workspace_code,
            day_key=day_key,
            purpose=purpose,
            calls_total=0,
        )
        session.add(usage)
    usage.calls_total += 1
    session.flush()
    return usage.calls_total


def try_acquire_rubric_compile_call(
    session: Session,
    workspace_code: str,
    day_key: str | None = None,
) -> bool:
    """rubric 编译预算闸门：purpose=rubric_compile 桶，固定 20 次/工作台/日。

    True 表示已登记本次调用可以外呼；False 表示当日已达上限（调用方拒绝编译，
    不影响 generation / rerank 桶）。
    """
    day = day_key or current_day_key()
    used = generation_calls_used(session, workspace_code, day, purpose=PURPOSE_RUBRIC_COMPILE)
    if used >= RUBRIC_COMPILE_DAILY_CAP:
        return False
    record_generation_call(session, workspace_code, day, purpose=PURPOSE_RUBRIC_COMPILE)
    return True


def try_acquire_feedback_rollup_call(
    session: Session,
    workspace_code: str,
    day_key: str | None = None,
) -> bool:
    """反馈回哺提案生成预算闸门：purpose=feedback_rollup 桶，固定 4 次/工作台/日。

    True 表示已登记本次调用可以外呼；False 表示当日已达上限（调用方走
    skipped_budget 降级，不影响 generation / rerank / rubric_compile 三桶）。
    """
    day = day_key or current_day_key()
    used = generation_calls_used(session, workspace_code, day, purpose=PURPOSE_FEEDBACK_ROLLUP)
    if used >= FEEDBACK_ROLLUP_DAILY_CAP:
        return False
    record_generation_call(session, workspace_code, day, purpose=PURPOSE_FEEDBACK_ROLLUP)
    return True


@dataclass
class GenerationRuntime:
    """一次生成链路（pipeline run / regenerate / rendition 补齐）的调用闸门。

    - provider 未启用或未配 key：不外呼、不计预算（现状规则降级语义不变）；
    - 预算耗尽：不外呼，budget_exhausted_total += 1，由调用方按
      fallback_behavior 处理。
    """

    session: Session
    workspace_code: str
    config: ResolvedGenerationConfig
    day_key: str = ""
    budget_exhausted_total: int = 0
    calls_attempted_total: int = 0
    _extras: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.day_key:
            self.day_key = current_day_key()

    @property
    def provider_usable(self) -> bool:
        return self.config.enabled and self.config.key_configured

    def try_acquire_call(self) -> bool:
        """申请一次模型调用额度；True 表示可以外呼（并已登记本次调用）。"""
        if not self.provider_usable:
            return False
        budget = self.config.daily_generation_budget
        if budget is not None:
            used = generation_calls_used(
                self.session,
                self.workspace_code,
                self.day_key,
                purpose=PURPOSE_GENERATION,
            )
            if used >= budget:
                self.budget_exhausted_total += 1
                return False
        record_generation_call(
            self.session,
            self.workspace_code,
            self.day_key,
            purpose=PURPOSE_GENERATION,
        )
        self.calls_attempted_total += 1
        return True


@dataclass
class RerankRuntime:
    """L3 精排调用闸门（GenerationRuntime 的同构延伸，purpose=rerank 桶）。

    预算来源：recommendation_policy.daily_rerank_call_budget（null=不限）；
    每窗调用与重试都计数（成功+失败），与 generation 口径一致但互不挤占。
    """

    session: Session
    workspace_code: str
    config: ResolvedGenerationConfig
    budget: int | None
    day_key: str = ""
    budget_exhausted_total: int = 0
    calls_attempted_total: int = 0

    def __post_init__(self) -> None:
        if not self.day_key:
            self.day_key = current_day_key()

    @property
    def provider_usable(self) -> bool:
        return self.config.enabled and self.config.key_configured

    @property
    def calls_used_today(self) -> int:
        return generation_calls_used(
            self.session,
            self.workspace_code,
            self.day_key,
            purpose=PURPOSE_RERANK,
        )

    @property
    def budget_exhausted(self) -> bool:
        return self.budget is not None and self.calls_used_today >= self.budget

    def try_acquire_call(self) -> bool:
        """申请一次精排模型调用额度；True 表示可以外呼（并已登记本次调用）。"""
        if not self.provider_usable:
            return False
        if self.budget is not None and self.calls_used_today >= self.budget:
            self.budget_exhausted_total += 1
            return False
        record_generation_call(
            self.session,
            self.workspace_code,
            self.day_key,
            purpose=PURPOSE_RERANK,
        )
        self.calls_attempted_total += 1
        return True
