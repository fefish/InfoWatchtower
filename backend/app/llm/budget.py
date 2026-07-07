"""工作台每日生成预算（generation_policy.daily_generation_budget）运行时。

事实源：docs/backend/generation-provider-design.md §3.2——计数按
(workspace_code, day_key) 统计当日模型调用（成功+失败都计，含模板增量字段
生成，见 report-renditions-design §10.4.3）；超出预算后本日剩余条目按
fallback_behavior 处理，run summary 记 generation_budget_exhausted 计数。
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


def current_day_key(now: datetime | None = None) -> str:
    """预算口径的“当日”：北京时区自然日（与日报 day_key 口径一致）。"""
    moment = now or utc_now()
    return moment.astimezone(BEIJING_TZ).date().isoformat()


def generation_calls_used(session: Session, workspace_code: str, day_key: str) -> int:
    usage = session.scalar(
        select(GenerationUsage).where(
            GenerationUsage.workspace_code == workspace_code,
            GenerationUsage.day_key == day_key,
        ),
    )
    return usage.calls_total if usage is not None else 0


def record_generation_call(session: Session, workspace_code: str, day_key: str) -> int:
    """登记一次模型调用（成功+失败都计），返回登记后的当日累计。"""
    usage = session.scalar(
        select(GenerationUsage).where(
            GenerationUsage.workspace_code == workspace_code,
            GenerationUsage.day_key == day_key,
        ),
    )
    if usage is None:
        usage = GenerationUsage(workspace_code=workspace_code, day_key=day_key, calls_total=0)
        session.add(usage)
    usage.calls_total += 1
    session.flush()
    return usage.calls_total


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
            used = generation_calls_used(self.session, self.workspace_code, self.day_key)
            if used >= budget:
                self.budget_exhausted_total += 1
                return False
        record_generation_call(self.session, self.workspace_code, self.day_key)
        self.calls_attempted_total += 1
        return True
