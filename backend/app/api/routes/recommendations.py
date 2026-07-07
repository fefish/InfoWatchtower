from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user, require_super_admin
from app.auth.service import write_audit
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.privacy import contains_secret_like_key
from app.llm.budget import PURPOSE_RERANK, current_day_key, generation_calls_used
from app.llm.provider import resolve_generation_config
from app.models.common import utc_now
from app.models.content import (
    FeedbackRollup,
    GeneratedNews,
    NewsItem,
    RecommendationItem,
    RecommendationRubricCompile,
    RecommendationRun,
    RubricRevisionProposal,
)
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem
from app.models.workspace import Workspace
from app.recommendations.policy import (
    ACTIVATE_ONLY_FIELDS,
    DAILY_RERANK_CALL_BUDGET_RANGE,
    EXPLORATION_EPSILON_RANGE,
    FEEDBACK_WORKFLOW_BOOL_KEYS,
    FUSION_WEIGHT_KEYS,
    FUSION_WEIGHTS_SUM_TOLERANCE,
    GUIDANCE_FIELDS,
    GUIDANCE_MAX_LENGTH,
    PATCHABLE_POLICY_FIELDS,
    RERANK_TOP_M_RANGE,
    RERANK_WINDOW_SIZE_RANGE,
    workspace_recommendation_policy,
)
from app.recommendations.rollup import (
    PERIOD_MONTHLY,
    PERIOD_WEEKLY,
    RollupPeriodError,
    previous_monthly_period,
    previous_weekly_period,
    proposal_rubric_fingerprint,
    rollup_workspace_month,
    rollup_workspace_week,
)
from app.recommendations.rubric import (
    RubricCompileBudgetError,
    RubricCompileInvalidError,
    RubricCompileProviderError,
    compile_rubric,
    find_activatable_compile,
    normalize_guidance,
)
from app.recommendations.service import (
    ContentAdmissionPreviewRequest,
    PublishedDailyReportError,
    RecommendationRunRequest,
    WorkspaceNotFoundError,
    preview_content_admission,
    run_daily_recommendation,
)
from app.schemas.recommendations import (
    FeedbackRollupDetailRead,
    FeedbackRollupListRead,
    FeedbackRollupRead,
    FeedbackRollupRunCreate,
    RecommendationItemDailyReportRead,
    RecommendationItemRead,
    RecommendationPolicyRead,
    RecommendationPolicyResolvedRead,
    RecommendationRunCreate,
    RecommendationRunCreateRead,
    RecommendationRunRead,
    RubricActivateCreate,
    RubricCompileRead,
    RubricRevisionProposalListRead,
    RubricRevisionProposalRead,
    RubricRevisionProposalReviewCreate,
    ScorerPolicyRead,
    ScorerPreviewCreate,
    ScorerPreviewRead,
    WorkspaceRecommendationPolicyRead,
)
from app.scoring.content_scorer import build_content_scorer_policy_summary

router = APIRouter(prefix="/api/recommendation", tags=["recommendation"])
# recommendation-policy 系端点挂 /api/workspaces/{code}/... 路径（§11）。
policy_router = APIRouter(prefix="/api", tags=["recommendation"])
SUPER_ADMIN = Depends(require_super_admin)
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)
SETTINGS = Depends(get_settings)


@router.get("/scorer-policy", response_model=ScorerPolicyRead)
def get_scorer_policy(
    workspace_code: str = Query(...),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ScorerPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    summary = build_content_scorer_policy_summary(get_settings().content_scorer_config_path)
    return ScorerPolicyRead(workspace_code=workspace_code, **summary)


@router.post("/scorer-preview", response_model=ScorerPreviewRead)
def preview_scorer(
    payload: ScorerPreviewCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ScorerPreviewRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        result = preview_content_admission(
            session,
            ContentAdmissionPreviewRequest(
                workspace_code=payload.workspace_code,
                source_title=payload.source_title.strip(),
                summary=payload.summary,
                content=payload.content,
                source_type=payload.source_type,
                source_name=payload.source_name,
                source_url=payload.source_url,
                source_tier=payload.source_tier,
                source_channel_type=payload.source_channel_type,
                source_score=payload.source_score,
                source_tags=tuple(payload.source_tags),
                source_secondary_tags=tuple(payload.source_secondary_tags),
                board_relevance_json=payload.board_relevance_json,
                freshness_score=payload.freshness_score,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    admission = result.admission
    return ScorerPreviewRead(
        workspace_code=result.workspace_code,
        source_title=result.source_title,
        admission_level=admission.level,
        admission_score=admission.score,
        admission_pool=admission.pool,
        eligible_for_daily=admission.eligible_for_daily,
        noise_types=list(admission.noise_types),
        reject_reasons=list(admission.reject_reasons),
        positive_reasons=list(admission.positive_reasons),
        expert_routes=list(admission.expert_routes),
        scorer_breakdown=admission.scorer_breakdown,
    )


@router.post("/runs", response_model=RecommendationRunCreateRead)
def create_recommendation_run(
    payload: RecommendationRunCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RecommendationRunCreateRead:
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="admin")
    try:
        result = run_daily_recommendation(
            session,
            RecommendationRunRequest(
                workspace_code=payload.workspace_code,
                day_key=payload.day_key,
                limit=payload.limit,
                source_daily_limit=payload.source_daily_limit,
                create_daily_draft=payload.create_daily_draft,
                generation_timeout_seconds=payload.generation_timeout_seconds,
            ),
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PublishedDailyReportError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    session.commit()
    run = _load_run(session, result.run.id)
    return RecommendationRunCreateRead(
        run=_run_to_read(run, session),
        daily_report_id=result.daily_report.id if result.daily_report else None,
        candidates_total=result.candidates_total,
        selected_total=result.selected_total,
        generated_total=result.generated_total,
    )


@router.get("/runs", response_model=list[RecommendationRunRead])
def list_recommendation_runs(
    workspace_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[RecommendationRunRead]:
    if workspace_code:
        assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    else:
        require_super_admin(current_user)
    statement = select(RecommendationRun).order_by(RecommendationRun.created_at.desc()).limit(limit)
    if workspace_code:
        statement = statement.where(RecommendationRun.workspace_code == workspace_code)
    runs = session.scalars(statement).all()
    return [_run_to_read(run, session, include_items=False) for run in runs]


@router.get("/runs/{run_id}", response_model=RecommendationRunRead)
def get_recommendation_run(
    run_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RecommendationRunRead:
    run = _load_run(session, run_id)
    assert_workspace_member(session, current_user, run.workspace_code, min_role="viewer")
    return _run_to_read(run, session)


def _load_run(session: Session, run_id: str) -> RecommendationRun:
    run = session.scalar(
        select(RecommendationRun)
        .options(
            selectinload(RecommendationRun.items)
            .selectinload(RecommendationItem.news_item)
            .selectinload(NewsItem.raw_item),
        )
        .where(RecommendationRun.id == run_id),
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation run not found",
        )
    return run


def _run_to_read(run: RecommendationRun, session: Session, include_items: bool = True) -> RecommendationRunRead:
    items = sorted(run.items, key=lambda item: item.rank) if include_items else []
    daily_report_by_item = _daily_report_trace_for_items(session, [item.id for item in items])
    return RecommendationRunRead(
        id=run.id,
        run_key=run.run_key,
        workspace_code=run.workspace_code,
        domain_code=run.domain_code,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        params_json=run.params_json or {},
        summary_json=run.summary_json or {},
        items=[
            RecommendationItemRead(
                id=item.id,
                news_item_id=item.news_item_id,
                dedupe_group_id=item.dedupe_group_id,
                rank=item.rank,
                quality_score=item.quality_score,
                topic_score=item.topic_score,
                freshness_score=item.freshness_score,
                feedback_score=item.feedback_score,
                diversity_score=item.diversity_score,
                source_score=item.source_score,
                heat_score=item.heat_score,
                final_score=item.final_score,
                coarse_score=item.coarse_score,
                llm_relevance_score=item.llm_relevance_score,
                llm_rerank_status=item.llm_rerank_status or "not_run",
                llm_rerank_reason=item.llm_rerank_reason or "",
                rubric_hits=_string_list(item.rubric_hits_json),
                rubric_version=item.rubric_version or 0,
                selected=item.selected,
                recommendation_reason=item.recommendation_reason,
                admission_level=item.admission_level,
                admission_score=item.admission_score,
                admission_pool=item.admission_pool,
                noise_types=_string_list(item.noise_types_json),
                reject_reasons=_string_list(item.reject_reasons_json),
                scorer_breakdown=dict(item.scorer_breakdown_json or {}),
                expert_routes=_string_list(item.expert_routes_json),
                source_title=item.news_item.source_title,
                source_name=item.news_item.source_name,
                source_url=item.news_item.source_url,
                daily_report=daily_report_by_item.get(item.id),
            )
            for item in items
        ],
    )


def _daily_report_trace_for_items(
    session: Session,
    recommendation_item_ids: list[str],
) -> dict[str, RecommendationItemDailyReportRead]:
    if not recommendation_item_ids:
        return {}
    rows = session.execute(
        select(
            GeneratedNews.recommendation_item_id,
            GeneratedNews.id.label("generated_news_id"),
            GeneratedNews.generation_status,
            DailyReport.id.label("daily_report_id"),
            DailyReportItem.id.label("daily_report_item_id"),
            DailyReport.day_key,
            DailyReport.status.label("report_status"),
            DailyReportItem.adoption_status,
        )
        .join(DailyReportItem, DailyReportItem.generated_news_id == GeneratedNews.id)
        .join(DailyReport, DailyReport.id == DailyReportItem.daily_report_id)
        .where(GeneratedNews.recommendation_item_id.in_(recommendation_item_ids))
        .order_by(desc(DailyReport.day_key), desc(DailyReportItem.updated_at)),
    ).all()
    traces: dict[str, RecommendationItemDailyReportRead] = {}
    for row in rows:
        if row.recommendation_item_id in traces:
            continue
        traces[row.recommendation_item_id] = RecommendationItemDailyReportRead(
            daily_report_id=row.daily_report_id,
            daily_report_item_id=row.daily_report_item_id,
            day_key=row.day_key,
            report_status=row.report_status,
            adoption_status=row.adoption_status,
            generated_news_id=row.generated_news_id,
            generation_status=row.generation_status,
        )
    return traces


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


# ---------------------------------------------------------------------------
# recommendation-policy（recommendation-scoring-design §5/§11、契约
# recommendation_ranking.json `recommendation_policy`/`rubric_compile`/
# `rubric_activate`）
# ---------------------------------------------------------------------------


def _get_enabled_workspace(session: Session, workspace_code: str) -> Workspace:
    workspace = session.scalar(
        select(Workspace).where(Workspace.code == workspace_code, Workspace.enabled.is_(True)),
    )
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


def _validation_error(field: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=[{"loc": ["body", field], "msg": message, "type": "value_error"}],
    )


def _assert_no_secret_like_payload(payload: Any) -> None:
    """密钥边界（§17 D3）：policy/compile payload 命中 secret-like 检测一律 422。"""
    if contains_secret_like_key(payload):
        raise _validation_error(
            "__root__",
            "secret-like keys are not allowed in recommendation_policy "
            "(keys live in llm provider credentials / instance env only)",
        )


def _validate_guidance_patch(value: Any, current: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise _validation_error("guidance", "guidance must be an object")
    unknown = sorted(set(value) - set(GUIDANCE_FIELDS))
    if unknown:
        raise _validation_error("guidance", f"unknown guidance fields: {', '.join(unknown)}")
    guidance = dict(current)
    for key in GUIDANCE_FIELDS:
        if key not in value:
            continue
        text = value[key]
        if text is None:
            text = ""
        if not isinstance(text, str) or len(text) > GUIDANCE_MAX_LENGTH:
            raise _validation_error(
                "guidance",
                f"guidance.{key} must be a string of <= {GUIDANCE_MAX_LENGTH} chars",
            )
        guidance[key] = text
    return guidance


def _validate_policy_patch(payload: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """取值域校验（§5.1）；返回只含合法字段的增量。"""
    if not isinstance(payload, dict):
        raise _validation_error("__root__", "payload must be a JSON object")
    _assert_no_secret_like_payload(payload)
    activate_only = sorted(set(payload) & ACTIVATE_ONLY_FIELDS)
    if activate_only:
        raise _validation_error(
            activate_only[0],
            "active_rubric/rubric_version/rubric_status are writable only via "
            "the activate-rubric action",
        )
    unknown = sorted(set(payload) - PATCHABLE_POLICY_FIELDS)
    if unknown:
        raise _validation_error(
            unknown[0],
            f"unknown recommendation_policy fields: {', '.join(unknown)}",
        )

    updates: dict[str, Any] = {}
    if "guidance" in payload:
        updates["guidance"] = _validate_guidance_patch(payload["guidance"], current["guidance"])
    for flag in ("llm_rerank_enabled", "semantic_layer_enabled"):
        if flag in payload:
            if not isinstance(payload[flag], bool):
                raise _validation_error(flag, f"{flag} must be a boolean")
            updates[flag] = payload[flag]
    for field, (low, high) in (
        ("rerank_top_m", RERANK_TOP_M_RANGE),
        ("rerank_window_size", RERANK_WINDOW_SIZE_RANGE),
    ):
        if field in payload:
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise _validation_error(field, f"{field} must be an integer within {low}..{high}")
            updates[field] = value
    if "daily_rerank_call_budget" in payload:
        budget = payload["daily_rerank_call_budget"]
        if budget is not None:
            low, high = DAILY_RERANK_CALL_BUDGET_RANGE
            if isinstance(budget, bool) or not isinstance(budget, int) or not low <= budget <= high:
                raise _validation_error(
                    "daily_rerank_call_budget",
                    f"daily_rerank_call_budget must be null or an integer within {low}..{high}",
                )
        updates["daily_rerank_call_budget"] = budget
    if "fusion_weights" in payload:
        weights = payload["fusion_weights"]
        if not isinstance(weights, dict) or set(weights) != set(FUSION_WEIGHT_KEYS):
            raise _validation_error(
                "fusion_weights",
                "fusion_weights must be an object with exactly llm and coarse",
            )
        parsed: dict[str, float] = {}
        for key in FUSION_WEIGHT_KEYS:
            value = weights[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _validation_error("fusion_weights", f"fusion_weights.{key} must be a number")
            value = float(value)
            if not 0.0 <= value <= 1.0:
                raise _validation_error(
                    "fusion_weights",
                    f"fusion_weights.{key} must be within 0..1",
                )
            parsed[key] = value
        if abs(parsed["llm"] + parsed["coarse"] - 1.0) > FUSION_WEIGHTS_SUM_TOLERANCE:
            raise _validation_error("fusion_weights", "fusion weights must sum to 1.0")
        updates["fusion_weights"] = parsed
    if "feedback_workflow" in payload:
        updates["feedback_workflow"] = _validate_feedback_workflow_patch(
            payload["feedback_workflow"],
            current["feedback_workflow"],
        )
    return updates


def _validate_feedback_workflow_patch(
    value: Any,
    current: dict[str, Any],
) -> dict[str, Any]:
    """feedback_workflow 取值域校验（feedback-heat-scoring §15/§16.1）：
    三开关 bool；exploration_epsilon float 0..0.1（越界 422）。"""
    if not isinstance(value, dict):
        raise _validation_error("feedback_workflow", "feedback_workflow must be an object")
    allowed = set(FEEDBACK_WORKFLOW_BOOL_KEYS) | {"exploration_epsilon"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _validation_error(
            "feedback_workflow",
            f"unknown feedback_workflow fields: {', '.join(unknown)}",
        )
    workflow = dict(current)
    for key in FEEDBACK_WORKFLOW_BOOL_KEYS:
        if key in value:
            if not isinstance(value[key], bool):
                raise _validation_error("feedback_workflow", f"{key} must be a boolean")
            workflow[key] = value[key]
    if "exploration_epsilon" in value:
        epsilon = value["exploration_epsilon"]
        low, high = EXPLORATION_EPSILON_RANGE
        if (
            isinstance(epsilon, bool)
            or not isinstance(epsilon, (int, float))
            or not low <= float(epsilon) <= high
        ):
            raise _validation_error(
                "feedback_workflow",
                f"exploration_epsilon must be a number within {low}..{high}",
            )
        workflow["exploration_epsilon"] = float(epsilon)
    return workflow


def _policy_read(policy: dict[str, Any]) -> RecommendationPolicyRead:
    return RecommendationPolicyRead(**policy)


def _resolved_read(
    session: Session,
    settings: Settings,
    workspace: Workspace,
    policy: dict[str, Any],
) -> RecommendationPolicyResolvedRead:
    config = resolve_generation_config(settings, workspace=workspace)
    provider_usable = config.enabled and config.key_configured
    budget = policy["daily_rerank_call_budget"]
    calls_used = generation_calls_used(
        session,
        workspace.code,
        current_day_key(),
        purpose=PURPOSE_RERANK,
    )
    llm_rerank_available = (
        bool(policy["llm_rerank_enabled"])
        and policy["rubric_status"] == "active"
        and provider_usable
        and (budget is None or calls_used < budget)
    )
    semantic_layer_available = bool(policy["semantic_layer_enabled"]) and bool(
        getattr(settings, "embedding_enabled", False),
    )
    return RecommendationPolicyResolvedRead(
        llm_rerank_available=llm_rerank_available,
        provider_usable=provider_usable,
        rerank_calls_used_today=calls_used,
        rerank_budget=budget,
        active_rubric_version=int(policy["rubric_version"]),
        semantic_layer_available=semantic_layer_available,
    )


def _workspace_policy_read(
    session: Session,
    settings: Settings,
    workspace: Workspace,
) -> WorkspaceRecommendationPolicyRead:
    policy = workspace_recommendation_policy(workspace)
    return WorkspaceRecommendationPolicyRead(
        workspace_code=workspace.code,
        policy=_policy_read(policy),
        resolved=_resolved_read(session, settings, workspace, policy),
    )


@policy_router.get(
    "/workspaces/{workspace_code}/recommendation-policy",
    response_model=WorkspaceRecommendationPolicyRead,
)
def get_workspace_recommendation_policy(
    workspace_code: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
    settings: Settings = SETTINGS,
) -> WorkspaceRecommendationPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    workspace = _get_enabled_workspace(session, workspace_code)
    return _workspace_policy_read(session, settings, workspace)


@policy_router.patch(
    "/workspaces/{workspace_code}/recommendation-policy",
    response_model=WorkspaceRecommendationPolicyRead,
)
def update_workspace_recommendation_policy(
    workspace_code: str,
    payload: dict[str, Any] = Body(...),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
    settings: Settings = SETTINGS,
) -> WorkspaceRecommendationPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    before = workspace_recommendation_policy(workspace)
    updates = _validate_policy_patch(payload, before)

    policy = {**before, **updates}
    config_json = dict(workspace.config_json or {})
    config_json["recommendation_policy"] = policy
    workspace.config_json = config_json
    write_audit(
        session,
        current_user,
        action="workspace.recommendation_policy.update",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "before": before,
            "after": policy,
        },
    )
    session.commit()
    session.refresh(workspace)
    return _workspace_policy_read(session, settings, workspace)


@policy_router.post(
    "/workspaces/{workspace_code}/recommendation-policy/compile-rubric",
    response_model=RubricCompileRead,
)
def compile_workspace_rubric(
    workspace_code: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RubricCompileRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    if not isinstance(payload, dict):
        raise _validation_error("__root__", "payload must be a JSON object")
    _assert_no_secret_like_payload(payload)
    unknown = sorted(set(payload) - {"guidance"})
    if unknown:
        raise _validation_error(unknown[0], f"unknown compile fields: {', '.join(unknown)}")
    policy = workspace_recommendation_policy(workspace)
    guidance = policy["guidance"]
    if "guidance" in payload:
        guidance = _validate_guidance_patch(payload["guidance"], policy["guidance"])

    try:
        result = compile_rubric(
            session,
            workspace,
            normalize_guidance(guidance),
            created_by=current_user.id,
        )
    except RubricCompileBudgetError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except RubricCompileProviderError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except RubricCompileInvalidError as exc:
        # schema 两次不合法 → 502，active rubric 不变（§5.3）。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{exc} ({exc.detail})" if exc.detail else str(exc),
        ) from exc
    session.commit()
    return RubricCompileRead(
        rubric=result.rubric,
        fingerprint=result.fingerprint,
        persistence="not_persisted",
        cached=result.cached,
    )


@policy_router.post(
    "/workspaces/{workspace_code}/recommendation-policy/activate-rubric",
    response_model=WorkspaceRecommendationPolicyRead,
)
def activate_workspace_rubric(
    workspace_code: str,
    payload: RubricActivateCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
    settings: Settings = SETTINGS,
) -> WorkspaceRecommendationPolicyRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    compile_row = find_activatable_compile(session, workspace.code, payload.fingerprint)
    if compile_row is None:
        # 未知或超 7 天的陈旧产物一律 422（防陈旧生效，§5.4）。
        raise _validation_error(
            "fingerprint",
            "fingerprint does not match a compile record of this workspace "
            "created within 7 days",
        )

    _apply_rubric_activation(session, workspace, compile_row, current_user)
    session.commit()
    session.refresh(workspace)
    return _workspace_policy_read(session, settings, workspace)


# ---------------------------------------------------------------------------
# 反馈回哺（feedback-heat-scoring §16.2、契约 feedback_workflow.api）：
# rollups 读 + 手动触发 + 提案审阅，全部 workspace admin+。
# ---------------------------------------------------------------------------

ROLLUP_PERIOD_TYPES = (PERIOD_WEEKLY, PERIOD_MONTHLY)
PROPOSAL_STATUSES = ("pending_review", "accepted", "rejected", "superseded", "expired")


def _rollup_read(rollup: FeedbackRollup, *, detail: bool = False) -> FeedbackRollupRead:
    base = {
        "id": rollup.id,
        "workspace_code": rollup.workspace_code,
        "period_type": rollup.period_type,
        "period_key": rollup.period_key,
        "window_start": rollup.window_start,
        "window_end": rollup.window_end,
        "status": rollup.status,
        "proposal_status": rollup.proposal_status,
        "metrics": dict(rollup.metrics_json or {}),
        "computed_at": rollup.computed_at,
    }
    if not detail:
        return FeedbackRollupRead(**base)
    return FeedbackRollupDetailRead(
        **base,
        source_breakdown=dict(rollup.source_breakdown_json or {}),
        topic_breakdown=dict(rollup.topic_breakdown_json or {}),
        sample_refs=dict(rollup.sample_refs_json or {}),
    )


@policy_router.get(
    "/workspaces/{workspace_code}/feedback-rollups",
    response_model=FeedbackRollupListRead,
)
def list_feedback_rollups(
    workspace_code: str,
    period_type: str | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=50),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> FeedbackRollupListRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    _get_enabled_workspace(session, workspace_code)
    if period_type is not None and period_type not in ROLLUP_PERIOD_TYPES:
        raise _validation_error("period_type", "period_type must be weekly or monthly")
    statement = select(FeedbackRollup).where(FeedbackRollup.workspace_code == workspace_code)
    if period_type is not None:
        statement = statement.where(FeedbackRollup.period_type == period_type)
    rows = session.scalars(statement.order_by(FeedbackRollup.period_key.desc())).all()
    return FeedbackRollupListRead(
        items=[_rollup_read(rollup) for rollup in rows[:limit]],
        total=len(rows),
    )


@policy_router.get(
    "/workspaces/{workspace_code}/feedback-rollups/{rollup_id}",
    response_model=FeedbackRollupDetailRead,
)
def get_feedback_rollup(
    workspace_code: str,
    rollup_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> FeedbackRollupDetailRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    _get_enabled_workspace(session, workspace_code)
    rollup = session.scalar(
        select(FeedbackRollup).where(
            FeedbackRollup.id == rollup_id,
            FeedbackRollup.workspace_code == workspace_code,
        ),
    )
    if rollup is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback rollup not found",
        )
    return _rollup_read(rollup, detail=True)


@policy_router.post(
    "/workspaces/{workspace_code}/feedback-rollups/run",
    response_model=FeedbackRollupDetailRead,
)
def run_feedback_rollup_manually(
    workspace_code: str,
    payload: FeedbackRollupRunCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> FeedbackRollupDetailRead:
    """手动触发（§16.2）：同步执行、幂等覆盖同 period_key 行、审计 manual_run。"""
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    _assert_no_secret_like_payload(payload.model_dump())
    if payload.period_type not in ROLLUP_PERIOD_TYPES:
        raise _validation_error("period_type", "period_type must be weekly or monthly")
    try:
        if payload.period_type == PERIOD_WEEKLY:
            period_key = payload.period_key or previous_weekly_period()
            rollup = rollup_workspace_week(session, workspace, period_key)
        else:
            period_key = payload.period_key or previous_monthly_period()
            rollup = rollup_workspace_month(session, workspace, period_key)
    except RollupPeriodError as exc:
        raise _validation_error("period_key", str(exc)) from exc
    write_audit(
        session,
        current_user,
        action="workspace.feedback_rollup.manual_run",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "period_type": payload.period_type,
            "period_key": period_key,
            "trigger": "manual",
            "status": rollup.status,
            "proposal_status": rollup.proposal_status,
        },
    )
    session.commit()
    session.refresh(rollup)
    return _rollup_read(rollup, detail=True)


def _proposal_read(
    proposal: RubricRevisionProposal,
    rollup_period_keys: dict[str, str],
) -> RubricRevisionProposalRead:
    return RubricRevisionProposalRead(
        id=proposal.id,
        workspace_code=proposal.workspace_code,
        rollup_id=proposal.rollup_id,
        rollup_period_key=rollup_period_keys.get(proposal.rollup_id, ""),
        base_rubric_version=proposal.base_rubric_version,
        prompt_version=proposal.prompt_version,
        proposed_rubric=dict(proposal.proposed_rubric_json or {}),
        change_summary=list(proposal.change_summary_json or []),
        sample_refs=dict(proposal.sample_refs_json or {}),
        status=proposal.status,
        review_comment=proposal.review_comment or "",
        reviewed_at=proposal.reviewed_at,
        compile_fingerprint=proposal.compile_fingerprint or "",
        created_at=proposal.created_at,
    )


def _rollup_period_keys(session: Session, proposals: list[RubricRevisionProposal]) -> dict[str, str]:
    rollup_ids = sorted({proposal.rollup_id for proposal in proposals})
    if not rollup_ids:
        return {}
    rows = session.execute(
        select(FeedbackRollup.id, FeedbackRollup.period_key).where(
            FeedbackRollup.id.in_(rollup_ids),
        ),
    ).all()
    return dict(rows)


@policy_router.get(
    "/workspaces/{workspace_code}/rubric-revision-proposals",
    response_model=RubricRevisionProposalListRead,
)
def list_rubric_revision_proposals(
    workspace_code: str,
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RubricRevisionProposalListRead:
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    _get_enabled_workspace(session, workspace_code)
    if status_filter is not None and status_filter not in PROPOSAL_STATUSES:
        raise _validation_error(
            "status",
            f"status must be one of {', '.join(PROPOSAL_STATUSES)}",
        )
    statement = select(RubricRevisionProposal).where(
        RubricRevisionProposal.workspace_code == workspace_code,
    )
    if status_filter is not None:
        statement = statement.where(RubricRevisionProposal.status == status_filter)
    proposals = list(
        session.scalars(statement.order_by(RubricRevisionProposal.created_at.desc())).all(),
    )
    period_keys = _rollup_period_keys(session, proposals)
    return RubricRevisionProposalListRead(
        items=[_proposal_read(proposal, period_keys) for proposal in proposals],
    )


@policy_router.post(
    "/workspaces/{workspace_code}/rubric-revision-proposals/{proposal_id}/review",
    response_model=RubricRevisionProposalRead,
)
def review_rubric_revision_proposal(
    workspace_code: str,
    proposal_id: str,
    payload: RubricRevisionProposalReviewCreate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> RubricRevisionProposalRead:
    """提案审阅（§16.2）：accept 服务端原子走既有 compile+activate 链；
    非 pending_review / base_rubric_version 不匹配一律 422（stale 防护）。"""
    assert_workspace_member(session, current_user, workspace_code, min_role="admin")
    workspace = _get_enabled_workspace(session, workspace_code)
    _assert_no_secret_like_payload(payload.model_dump())
    proposal = session.scalar(
        select(RubricRevisionProposal).where(
            RubricRevisionProposal.id == proposal_id,
            RubricRevisionProposal.workspace_code == workspace_code,
        ),
    )
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rubric revision proposal not found",
        )
    if proposal.status != "pending_review":
        raise _validation_error(
            "action",
            f"proposal is not pending_review (status={proposal.status})",
        )

    if payload.action == "reject":
        proposal.status = "rejected"
        proposal.review_comment = payload.comment
        proposal.reviewed_by = current_user.id
        proposal.reviewed_at = utc_now()
        write_audit(
            session,
            current_user,
            action="workspace.rubric_revision_proposal.review",
            object_type="rubric_revision_proposal",
            object_id=proposal.id,
            detail={
                "workspace_code": workspace.code,
                "action": "reject",
                "base_rubric_version": proposal.base_rubric_version,
            },
        )
        session.commit()
        session.refresh(proposal)
        return _proposal_read(proposal, _rollup_period_keys(session, [proposal]))

    # accept：stale 防护——生成后 rubric 已被人工改版则提案作废（§18 断言 5）。
    policy = workspace_recommendation_policy(workspace)
    current_version = int(policy["rubric_version"])
    if proposal.base_rubric_version != current_version:
        raise _validation_error(
            "base_rubric_version",
            "proposal is stale: base_rubric_version "
            f"{proposal.base_rubric_version} != current rubric_version {current_version}; "
            "regenerate the proposal",
        )
    proposed_rubric = dict(proposal.proposed_rubric_json or {})
    fingerprint = str(
        proposed_rubric.get("source_guidance_fingerprint")
        or proposal_rubric_fingerprint(proposed_rubric),
    )
    # 原子链第一步：登记 compile 记录（model_called=false，零模型调用）。
    compile_row = session.scalar(
        select(RecommendationRubricCompile).where(
            RecommendationRubricCompile.workspace_code == workspace.code,
            RecommendationRubricCompile.fingerprint == fingerprint,
        ),
    )
    if compile_row is None:
        compile_row = RecommendationRubricCompile(
            workspace_code=workspace.code,
            fingerprint=fingerprint,
            guidance_json=dict(policy["guidance"]),
            rubric_json=proposed_rubric,
            prompt_version="revision_proposal_v1",
            model_called=False,
            created_by=current_user.id,
        )
        session.add(compile_row)
        session.flush()
    # 原子链第二步：走既有 activate 链（rubric_version += 1 + activate 审计）。
    _apply_rubric_activation(session, workspace, compile_row, current_user)
    proposal.status = "accepted"
    proposal.review_comment = payload.comment
    proposal.reviewed_by = current_user.id
    proposal.reviewed_at = utc_now()
    proposal.compile_fingerprint = fingerprint
    write_audit(
        session,
        current_user,
        action="workspace.rubric_revision_proposal.review",
        object_type="rubric_revision_proposal",
        object_id=proposal.id,
        detail={
            "workspace_code": workspace.code,
            "action": "accept",
            "base_rubric_version": proposal.base_rubric_version,
            "compile_fingerprint": fingerprint,
        },
    )
    session.commit()
    session.refresh(proposal)
    return _proposal_read(proposal, _rollup_period_keys(session, [proposal]))


def _apply_rubric_activation(
    session: Session,
    workspace: Workspace,
    compile_row: RecommendationRubricCompile,
    current_user: User,
) -> dict[str, Any]:
    """既有 activate 链（§5.4）：rubric_version += 1 + 审计；提案 accept 复用。"""
    before_policy = workspace_recommendation_policy(workspace)
    before_rubric = before_policy.get("active_rubric") or {}
    policy = {
        **before_policy,
        "active_rubric": dict(compile_row.rubric_json or {}),
        "rubric_version": int(before_policy["rubric_version"]) + 1,
        "rubric_status": "active",
    }
    config_json = dict(workspace.config_json or {})
    config_json["recommendation_policy"] = policy
    workspace.config_json = config_json
    write_audit(
        session,
        current_user,
        action="workspace.recommendation_rubric.activate",
        object_type="workspace",
        object_id=workspace.id,
        detail={
            "workspace_code": workspace.code,
            "before": {
                "rubric_version": before_policy["rubric_version"],
                "fingerprint": before_rubric.get("source_guidance_fingerprint"),
            },
            "after": {
                "rubric_version": policy["rubric_version"],
                "fingerprint": compile_row.fingerprint,
            },
        },
    )
    return policy
