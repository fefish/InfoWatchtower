"""L3 LLM listwise 分窗精排引擎（recommendation-scoring-design §4.4/§6/§9）。

协议要点（写死，契约 `pipeline_layers.l3_llm_rerank`）：
- 输入集：L1 后 admission ∈ {P0,P1,P2} 按 coarse_score 降序前 M 条（R/P3 永不进）;
- 分窗：W=rerank_window_size（默认 12）、锚点重叠 A=2、步长 W-A，末窗可不满；
- 位置偏差规避：窗口内顺序以 sha256(run_key + ":" + window_index) 确定性洗牌，
  输出按候选 id 对齐（同 run_key 重放可完全复现——契约断言 window_deterministic）;
- 跨窗锚点线性校准：delta_0=0，delta_k=mean(prev_calibrated - raw)，锚点缺失/
  前窗失败时 delta 沿用上一窗；锚点最终分取先到窗口的校准值；
- 失败与重试：解析失败/id 不齐 → 同窗重试 1 次（计预算）；仍失败 →
  window_failed 退 coarse；失败窗 > 1/2 → 整 run failed 全量退回；
- 预算：purpose=rerank 桶（RerankRuntime），运行中耗尽 → partial；
- 结果缓存：同 news_item_id + rubric_version + rerank_prompt_v1 7 天内 scored
  分数复用为 cached，计 0 次调用；
- 硬排除：severity=hard 的 exclusion 命中 → llm_relevance_score 封顶 20
  （只压排序分，准入不动）；
- 漂移监控：std<5 → low_variance；与最近 7 个 scored run 均值偏差 >15 →
  drift_alert（v1 只告警不整形）。

边界：本层只产排序信号，不改 admission_level/admission_pool/noise_types/
reject_reasons，不写 raw/news/dedupe。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from datetime import timedelta
from statistics import mean, pstdev
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import RerankRuntime
from app.llm.provider import ResolvedGenerationConfig, request_chat_completion
from app.models.common import utc_now
from app.models.content import RecommendationItem, RecommendationRun
from app.recommendations.reaggregate import latest_effective_topic_weights
from app.recommendations.rubric import hard_exclusion_codes

if TYPE_CHECKING:  # 仅类型引用，避免与 service 的运行时循环导入
    from app.recommendations.service import ScoredCandidate

RERANK_PROMPT_VERSION = "rerank_prompt_v1"
RERANK_ANCHOR_OVERLAP = 2
RERANK_ELIGIBLE_LEVELS = ("P0", "P1", "P2")
RESULT_CACHE_DAYS = 7
SUMMARY_TRUNCATE_CHARS = 300
REASON_MAX_CHARS = 60
HARD_EXCLUSION_SCORE_CAP = 20
LOW_VARIANCE_STD_THRESHOLD = 5.0
DRIFT_ALERT_MEAN_DEVIATION = 15.0
DRIFT_BASELINE_RUNS = 7

RERANK_SYSTEM_PROMPT_PREFIX = """你是情报工作台的相关性精排器。依据给定的内容导向 rubric，
对候选窗口内的每条候选打 0-100 的相关性整数分（越符合导向越高），并给出命中的 rubric code
（topics/exclusions/boost_signals 的 code）与一句话理由（不超过 60 字）。

规则：
- 命中 severity=hard 的排除规则时给低分并在 rubric_hits 里写上该 exclusion code；
- 只输出严格 JSON 数组，元素形如
  {"id": "候选id", "relevance_score": 0-100整数, "rubric_hits": ["code"...], "reason": "一句话"}；
- 数组必须覆盖窗口内全部候选 id，不多不少；不要输出 Markdown 代码块或解释文字。"""


@dataclass
class ItemRerank:
    """单候选的精排产物（写入 recommendation_items 的解释字段）。"""

    status: str = "not_run"  # not_run/scored/cached/window_failed/skipped/disabled
    score: float | None = None
    reason: str = ""
    rubric_hits: list[str] = field(default_factory=list)


@dataclass
class RerankOutcome:
    """run 级精排结果（summary_json.llm_rerank 块 + per-item 映射）。"""

    status: str  # scored/partial/skipped/disabled/failed
    skip_reason: str | None = None
    windows_total: int = 0
    windows_failed: int = 0
    calls_used: int = 0
    rubric_version: int = 0
    llm_score_mean: float | None = None
    llm_score_std: float | None = None
    low_variance: bool = False
    drift_alert: bool = False
    per_item: dict[str, ItemRerank] = field(default_factory=dict)

    @property
    def engaged(self) -> bool:
        """是否有任何候选拿到可用 LLM 分（决定展示序是否切 final desc）。"""
        return any(entry.status in ("scored", "cached") for entry in self.per_item.values())

    def summary_block(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "skip_reason": self.skip_reason,
            "windows_total": self.windows_total,
            "windows_failed": self.windows_failed,
            "calls_used": self.calls_used,
            "rubric_version": self.rubric_version,
            "prompt_version": RERANK_PROMPT_VERSION,
            "llm_score_mean": self.llm_score_mean,
            "llm_score_std": self.llm_score_std,
            "low_variance": self.low_variance,
            "drift_alert": self.drift_alert,
        }


def disabled_outcome(reason: str | None = None) -> RerankOutcome:
    return RerankOutcome(status="disabled", skip_reason=reason)


def skipped_outcome(reason: str, rubric_version: int = 0) -> RerankOutcome:
    return RerankOutcome(status="skipped", skip_reason=reason, rubric_version=rubric_version)


def rerank_window_partition(count: int, window_size: int, anchor_overlap: int = RERANK_ANCHOR_OVERLAP) -> list[tuple[int, int]]:
    """窗口划分（含端点 [start, end)）：步长 = W-A，直到覆盖全部 count 条。"""
    if count <= 0:
        return []
    window_size = max(1, window_size)
    stride = max(1, window_size - anchor_overlap)
    windows: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + window_size, count)
        windows.append((start, end))
        if end >= count:
            break
        start += stride
    return windows


def window_shuffle(run_key: str, window_index: int, ids: list[str]) -> list[str]:
    """确定性洗牌：seed = sha256(run_key + ":" + window_index)。"""
    digest = hashlib.sha256(f"{run_key}:{window_index}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    shuffled = list(ids)
    rng.shuffle(shuffled)
    return shuffled


def _truncate(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit]


def _parse_window_output(content: str, expected_ids: set[str]) -> dict[str, dict[str, Any]]:
    """解析窗口输出：严格 JSON 数组、候选 id 必须不多不少；失败抛 ValueError。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("window output must be a JSON array")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("window entries must be objects")
        entry_id = str(entry.get("id") or "")
        score = entry.get("relevance_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ValueError(f"relevance_score missing for id {entry_id!r}")
        hits = entry.get("rubric_hits") or []
        if not isinstance(hits, list):
            raise ValueError(f"rubric_hits must be a list for id {entry_id!r}")
        by_id[entry_id] = {
            "score": max(0.0, min(100.0, float(score))),
            "rubric_hits": [str(item) for item in hits],
            "reason": _truncate(str(entry.get("reason") or ""), REASON_MAX_CHARS),
        }
    if set(by_id) != expected_ids:
        raise ValueError("window output ids do not match window candidates")
    return by_id


def _rubric_prompt_payload(
    session: Session,
    workspace_code: str,
    rubric: dict[str, Any],
    rubric_version: int,
) -> dict[str, Any]:
    """rubric 进 prompt 的形态：authored weight 保留，附 §8.2 effective weights。

    active_rubric 的 authored 字段永不被改写——effective_weight 只出现在
    prompt 载荷副本里。
    """
    effective = latest_effective_topic_weights(session, workspace_code, rubric_version)
    payload = json.loads(json.dumps(rubric, ensure_ascii=False))
    for topic in payload.get("topics") or []:
        code = str(topic.get("code") or "")
        topic["effective_weight"] = round(
            float(effective.get(code, float(topic.get("weight") or 0.0))),
            4,
        )
    return payload


def _candidate_payload(handle: str, candidate: ScoredCandidate) -> dict[str, Any]:
    news_item = candidate.news_item
    published_at = news_item.published_at or news_item.created_at
    return {
        "id": handle,
        "title": _truncate(news_item.source_title, 200),
        "summary": _truncate(news_item.summary or news_item.content, SUMMARY_TRUNCATE_CHARS),
        "source_name": news_item.source_name,
        "published_at": published_at.isoformat() if published_at else None,
        "admission_pool": candidate.admission_pool,
    }


def _load_cached_scores(
    session: Session,
    workspace_code: str,
    news_item_ids: list[str],
    rubric_version: int,
) -> dict[str, ItemRerank]:
    """7 天结果缓存：同 news_item + rubric_version + prompt_version 的 scored 分。"""
    if not news_item_ids:
        return {}
    cutoff = utc_now() - timedelta(days=RESULT_CACHE_DAYS)
    rows = session.execute(
        select(RecommendationItem, RecommendationRun.summary_json)
        .join(RecommendationRun, RecommendationRun.id == RecommendationItem.run_id)
        .where(
            RecommendationItem.workspace_code == workspace_code,
            RecommendationItem.news_item_id.in_(news_item_ids),
            RecommendationItem.rubric_version == rubric_version,
            RecommendationItem.llm_rerank_status == "scored",
            RecommendationItem.created_at >= cutoff,
        )
        .order_by(RecommendationItem.created_at.desc()),
    ).all()
    cached: dict[str, ItemRerank] = {}
    for item, summary_json in rows:
        if item.news_item_id in cached or item.llm_relevance_score is None:
            continue
        prompt_version = ((summary_json or {}).get("llm_rerank") or {}).get("prompt_version")
        if prompt_version != RERANK_PROMPT_VERSION:
            continue
        cached[item.news_item_id] = ItemRerank(
            status="cached",
            score=float(item.llm_relevance_score),
            reason=item.llm_rerank_reason or "",
            rubric_hits=[str(code) for code in item.rubric_hits_json or []],
        )
    return cached


def _recent_scored_run_means(session: Session, workspace_code: str) -> list[float]:
    runs = session.scalars(
        select(RecommendationRun)
        .where(RecommendationRun.workspace_code == workspace_code)
        .order_by(RecommendationRun.created_at.desc())
        .limit(50),
    ).all()
    means: list[float] = []
    for run in runs:
        block = (run.summary_json or {}).get("llm_rerank") or {}
        value = block.get("llm_score_mean")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            means.append(float(value))
        if len(means) >= DRIFT_BASELINE_RUNS:
            break
    return means


def execute_llm_rerank(
    session: Session,
    *,
    workspace_code: str,
    run_key: str,
    scored: list[ScoredCandidate],
    rubric: dict[str, Any],
    rubric_version: int,
    config: ResolvedGenerationConfig,
    rerank_top_m: int,
    rerank_window_size: int,
    daily_budget: int | None,
) -> RerankOutcome:
    """执行 L3 精排；任何失败/预算路径都不抛异常（降级是一等路径）。"""
    runtime = RerankRuntime(
        session=session,
        workspace_code=workspace_code,
        config=config,
        budget=daily_budget,
    )
    outcome = RerankOutcome(status="scored", rubric_version=rubric_version)

    # 输入集：P0/P1/P2 按 coarse 降序前 M（并列按 news_item_id 稳定）。
    eligible = [c for c in scored if c.admission_level in RERANK_ELIGIBLE_LEVELS]
    eligible.sort(key=lambda c: (-c.coarse_score, c.news_item.id))
    top_m = eligible[: max(0, rerank_top_m)]
    if not top_m:
        return outcome

    # run 开始前预算已尽：零外呼，纯粗排（§9.3）。
    if runtime.budget_exhausted:
        return skipped_outcome("budget_exhausted", rubric_version)

    # 结果缓存命中的候选不再进窗（计 0 次调用）。
    cached = _load_cached_scores(
        session,
        workspace_code,
        [c.news_item.id for c in top_m],
        rubric_version,
    )
    for news_item_id, entry in cached.items():
        outcome.per_item[news_item_id] = entry
    pending = [c for c in top_m if c.news_item.id not in cached]

    windows = rerank_window_partition(len(pending), rerank_window_size)
    outcome.windows_total = len(windows)
    hard_codes = hard_exclusion_codes(rubric)
    rubric_payload = _rubric_prompt_payload(session, workspace_code, rubric, rubric_version)
    system_prompt = (
        f"{RERANK_SYSTEM_PROMPT_PREFIX}\n\n内容导向 rubric"
        f"（topics 的 effective_weight 为反馈再估计后的生效权重）：\n"
        f"{json.dumps(rubric_payload, ensure_ascii=False)}"
    )

    # 候选短句柄：按 pending 全局序号（窗口无关、可复现）。
    handle_by_id = {c.news_item.id: f"c{index}" for index, c in enumerate(pending, start=1)}
    id_by_handle = {handle: news_id for news_id, handle in handle_by_id.items()}

    # calibrated_raw：锚点簿记用未封顶校准值；封顶只作用于落库分。
    calibrated_raw: dict[str, float] = {}
    delta_prev = 0.0
    previous_window_ok = True
    budget_exhausted_mid_run = False

    for window_index, (start, end) in enumerate(windows):
        window_candidates = pending[start:end]
        window_ids = [c.news_item.id for c in window_candidates]
        window_by_id = {c.news_item.id: c for c in window_candidates}
        window_handles = {handle_by_id[news_id] for news_id in window_ids}
        anchors = (
            [news_id for news_id in window_ids[:RERANK_ANCHOR_OVERLAP] if news_id in calibrated_raw]
            if window_index > 0
            else []
        )

        raw_scores: dict[str, dict[str, Any]] | None = None
        for _attempt in (1, 2):
            if not runtime.try_acquire_call():
                budget_exhausted_mid_run = True
                break
            outcome.calls_used = runtime.calls_attempted_total
            shuffled_handles = window_shuffle(
                run_key,
                window_index,
                [handle_by_id[news_id] for news_id in window_ids],
            )
            user_prompt = json.dumps(
                {
                    "window_index": window_index,
                    "candidates": [
                        _candidate_payload(handle, window_by_id[id_by_handle[handle]])
                        for handle in shuffled_handles
                    ],
                },
                ensure_ascii=False,
            )
            try:
                content = request_chat_completion(config, system_prompt, user_prompt)
                raw_scores = _parse_window_output(content, window_handles)
                break
            except Exception:  # noqa: BLE001 - 单窗失败走重试/降级，不阻断 run
                raw_scores = None
        if budget_exhausted_mid_run:
            # 运行中预算尽：已 scored 窗口保留，本窗及其后候选退 coarse（skipped）。
            for candidate in pending[start:]:
                news_id = candidate.news_item.id
                if news_id not in outcome.per_item or outcome.per_item[news_id].status == "not_run":
                    outcome.per_item[news_id] = ItemRerank(status="skipped")
            # 锚点候选已在前窗拿到 scored 分，保持不变。
            outcome.status = "partial"
            outcome.skip_reason = "budget_exhausted"
            break

        if raw_scores is None:
            # 同窗重试 1 次后仍失败：该窗候选退回 coarse。
            outcome.windows_failed += 1
            previous_window_ok = False
            for news_id in window_ids:
                if news_id in calibrated_raw:
                    continue  # 锚点保留先到窗口的分
                outcome.per_item[news_id] = ItemRerank(status="window_failed")
            continue

        # 跨窗锚点线性校准。
        if window_index == 0:
            delta_k = 0.0
        elif anchors and previous_window_ok:
            diffs = [
                calibrated_raw[news_id] - raw_scores[handle_by_id[news_id]]["score"]
                for news_id in anchors
                if handle_by_id[news_id] in raw_scores
            ]
            delta_k = mean(diffs) if diffs else delta_prev
        else:
            delta_k = delta_prev

        for news_id in window_ids:
            if news_id in calibrated_raw:
                continue  # 锚点：最终分取先到窗口（k-1）的校准值
            entry = raw_scores[handle_by_id[news_id]]
            calibrated = max(0.0, min(100.0, float(round(entry["score"] + delta_k))))
            calibrated_raw[news_id] = calibrated
            stored = calibrated
            hits = entry["rubric_hits"]
            if hard_codes and any(code in hard_codes for code in hits):
                stored = min(stored, float(HARD_EXCLUSION_SCORE_CAP))
            outcome.per_item[news_id] = ItemRerank(
                status="scored",
                score=stored,
                reason=entry["reason"],
                rubric_hits=hits,
            )
        delta_prev = delta_k
        previous_window_ok = True

    outcome.calls_used = runtime.calls_attempted_total

    # 失败窗过半：整 run failed，全部候选退回 coarse（含缓存分）。
    if outcome.windows_total and outcome.windows_failed * 2 > outcome.windows_total:
        outcome.status = "failed"
        outcome.skip_reason = None
        for candidate in top_m:
            outcome.per_item[candidate.news_item.id] = ItemRerank(status="window_failed")
        return outcome

    # 漂移监控（v1 只告警不整形）。
    llm_scores = [
        entry.score
        for entry in outcome.per_item.values()
        if entry.status in ("scored", "cached") and entry.score is not None
    ]
    if llm_scores:
        outcome.llm_score_mean = round(mean(llm_scores), 2)
        outcome.llm_score_std = round(pstdev(llm_scores), 2)
        outcome.low_variance = outcome.llm_score_std < LOW_VARIANCE_STD_THRESHOLD
        baseline = _recent_scored_run_means(session, workspace_code)
        if baseline and abs(outcome.llm_score_mean - mean(baseline)) > DRIFT_ALERT_MEAN_DEVIATION:
            outcome.drift_alert = True
    return outcome
