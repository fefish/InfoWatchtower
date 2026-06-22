from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ContentScorerResult:
    level: str
    score: float
    pool: str
    noise_types: tuple[str, ...]
    positive_reasons: tuple[str, ...]
    reject_reasons: tuple[str, ...] = field(default_factory=tuple)
    expert_routes: tuple[str, ...] = field(default_factory=tuple)
    breakdown: dict[str, Any] = field(default_factory=dict)
    eligible_for_daily: bool = False


class ContentScorer:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", bool(config)))

    def score(
        self,
        news_item: Any,
        *,
        baseline_level: str,
        baseline_score: float,
        baseline_pool: str,
        baseline_noise_types: tuple[str, ...],
        baseline_positive_reasons: tuple[str, ...],
        freshness_score: float,
    ) -> ContentScorerResult:
        if not self.enabled:
            return ContentScorerResult(
                level=baseline_level,
                score=baseline_score,
                pool=baseline_pool,
                noise_types=baseline_noise_types,
                positive_reasons=baseline_positive_reasons,
                eligible_for_daily=baseline_level in {"P0", "P1", "P2"},
                breakdown={"mode": "baseline", "config_loaded": False},
            )

        metadata = _source_metadata(news_item)
        text = _candidate_text(news_item)
        source_tier = str(metadata.get("source_tier") or "")
        source_channel_type = str(metadata.get("source_channel_type") or "")
        board_relevance = _dict_value(metadata.get("board_relevance_json"))
        source_quality = _float(metadata.get("source_score")) or _float(getattr(news_item.data_source, "source_score", 0))

        tier_score = _score_from_map(self.config.get("source_tier_scores"), source_tier)
        channel_score = _score_from_map(self.config.get("source_channel_scores"), source_channel_type)
        topic_breakdown = self._topic_score(board_relevance)
        expert_routes = _string_list(metadata.get("expert_routes"))
        inferred_routes = self._infer_expert_routes(board_relevance)
        route_candidates = expert_routes or inferred_routes
        expert_score = min(float(self.config.get("weights", {}).get("expert_route", 8)), len(route_candidates) * 2.0)
        noise_matches, noise_penalty, direct_reject_noise = self._noise_matches(text)
        noise_types = tuple(dict.fromkeys([*baseline_noise_types, *noise_matches]))
        hard_rules = _dict_value(self.config.get("hard_rules"))
        strong_topic_count = topic_breakdown["strong_topic_count"]
        direct_reject = bool(
            direct_reject_noise
            and not (
                hard_rules.get("direct_reject_requires_no_strong_topic") is True
                and strong_topic_count > 0
            )
        )
        source_quality_component = max(0.0, min(8.0, source_quality / 12.5))
        metadata_score = (
            min(8.0, tier_score)
            + min(8.0, channel_score * 1.6)
            + min(40.0, topic_breakdown["topic_score"])
            + expert_score
            + source_quality_component
            + min(5.0, freshness_score / 20.0)
        )
        combined_score = max(
            baseline_score,
            min(100.0, baseline_score * 0.72 + metadata_score * 0.28 - min(20.0, noise_penalty * 0.25)),
        )

        reject_reasons: list[str] = []
        level = baseline_level
        if source_tier in {"Block", "停用"}:
            level = "R"
            combined_score = min(combined_score, 25.0)
            reject_reasons.append("source_tier_blocked")
        elif direct_reject:
            level = "R"
            combined_score = min(combined_score, 35.0)
            reject_reasons.extend(f"hard_noise:{item}" for item in direct_reject_noise)
        elif level == "R" and topic_breakdown["topic_score"] >= 24 and not direct_reject_noise:
            level = _less_restrictive_level(level, _level_from_thresholds(combined_score, self.config))

        if bool(metadata.get("metadata_only")):
            reject_reasons.append("source_metadata_only")
        if not route_candidates:
            reject_reasons.append("no_expert_route")

        breakdown = {
            "mode": "content_scorer_v2",
            "config_loaded": True,
            "config_version": self.config.get("version", ""),
            "baseline": {
                "level": baseline_level,
                "score": round(baseline_score, 2),
                "pool": baseline_pool,
                "noise_types": list(baseline_noise_types),
                "positive_reasons": list(baseline_positive_reasons),
            },
            "source_tier": source_tier,
            "source_channel_type": source_channel_type,
            "source_quality_score": round(source_quality, 2),
            "source_tier_score": round(tier_score, 2),
            "source_channel_score": round(channel_score, 2),
            "topic_score": round(topic_breakdown["topic_score"], 2),
            "strong_topic_count": strong_topic_count,
            "metadata_score": round(metadata_score, 2),
            "threshold_level": _level_from_thresholds(combined_score, self.config),
            "noise_penalty": round(noise_penalty, 2),
            "direct_reject_noise": list(direct_reject_noise),
            "board_relevance": topic_breakdown["top_boards"],
        }
        return ContentScorerResult(
            level=level,
            score=round(combined_score, 2),
            pool=baseline_pool,
            noise_types=noise_types,
            positive_reasons=baseline_positive_reasons,
            reject_reasons=tuple(dict.fromkeys(reject_reasons)),
            expert_routes=tuple(dict.fromkeys(route_candidates)),
            breakdown=breakdown,
            eligible_for_daily=level in {"P0", "P1", "P2"} and not direct_reject,
        )

    def _topic_score(self, board_relevance: dict[str, Any]) -> dict[str, Any]:
        factors = _dict_value(self.config.get("topic_relevance_factors"))
        weights = _dict_value(self.config.get("topic_weights"))
        topic_score = 0.0
        strong_topic_count = 0
        top_boards: list[dict[str, Any]] = []
        for board, relevance in board_relevance.items():
            relevance_text = str(relevance)
            factor = _float(factors.get(relevance_text)) or 0.0
            weight = _float(weights.get(board)) or 1.0
            score = factor * weight
            if score > 0:
                top_boards.append({"board": board, "relevance": relevance_text, "score": round(score, 3)})
                topic_score += score
            if relevance_text == "强相关":
                strong_topic_count += 1
        top_boards.sort(key=lambda item: float(item["score"]), reverse=True)
        return {
            "topic_score": min(40.0, topic_score),
            "strong_topic_count": strong_topic_count,
            "top_boards": top_boards[:6],
        }

    def _infer_expert_routes(self, board_relevance: dict[str, Any]) -> list[str]:
        route_weights = _dict_value(self.config.get("expert_routes"))
        if not route_weights:
            return []
        factors = _dict_value(self.config.get("topic_relevance_factors"))
        scored_routes: list[tuple[float, str]] = []
        for route, board_weights in route_weights.items():
            if not isinstance(board_weights, dict):
                continue
            score = 0.0
            for board, relevance in board_relevance.items():
                factor = _float(factors.get(str(relevance))) or 0.0
                score += factor * (_float(board_weights.get(board)) or 0.0)
            if score > 0:
                scored_routes.append((score, str(route)))
        scored_routes.sort(reverse=True)
        return [route for _, route in scored_routes[:3]]

    def _noise_matches(self, text: str) -> tuple[list[str], float, list[str]]:
        noise_rules = self.config.get("noise_rules") or []
        if not isinstance(noise_rules, list):
            return [], 0.0, []
        matched: list[str] = []
        direct_reject: list[str] = []
        penalty = 0.0
        for rule in noise_rules:
            if not isinstance(rule, dict):
                continue
            patterns = [str(item).lower() for item in rule.get("patterns") or [] if str(item).strip()]
            if not patterns or not any(_keyword_in_text(text, pattern) for pattern in patterns):
                continue
            rule_type = str(rule.get("type") or "noise")
            matched.append(rule_type)
            penalty += _float(rule.get("penalty")) or 0.0
            if rule.get("direct_reject") is True:
                direct_reject.append(rule_type)
        return matched, penalty, direct_reject


@lru_cache
def load_content_scorer(config_path: str) -> ContentScorer:
    path = Path(config_path)
    if not path.exists():
        return ContentScorer()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ContentScorer()
    return ContentScorer(config)


def _source_metadata(news_item: Any) -> dict[str, Any]:
    data_source = getattr(news_item, "data_source", None)
    metadata = getattr(data_source, "metadata_json", None) if data_source is not None else {}
    return metadata if isinstance(metadata, dict) else {}


def _candidate_text(news_item: Any) -> str:
    return " ".join(
        [
            str(getattr(news_item, "source_title", "") or ""),
            str(getattr(news_item, "summary", "") or ""),
            str(getattr(news_item, "content", "") or ""),
        ],
    ).lower()


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _score_from_map(score_map: Any, key: str) -> float:
    if not isinstance(score_map, dict) or not key:
        return 0.0
    return _float(score_map.get(key)) or 0.0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _level_from_thresholds(score: float, config: dict[str, Any]) -> str:
    thresholds = _dict_value(config.get("thresholds"))
    ordered = [
        ("P0", _float(thresholds.get("P0")) or 96.0),
        ("P1", _float(thresholds.get("P1")) or 84.0),
        ("P2", _float(thresholds.get("P2")) or 56.0),
        ("P3", _float(thresholds.get("P3")) or 40.0),
    ]
    for level, threshold in ordered:
        if score >= threshold:
            return level
    return "R"


def _less_restrictive_level(left: str, right: str) -> str:
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "R": 4}
    return left if order.get(left, 9) <= order.get(right, 9) else right


def _keyword_in_text(text: str, keyword: str) -> bool:
    normalized = keyword.lower()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9+._-]*", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None
    return normalized in text
