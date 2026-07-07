"""WP4-G rubric 修订提案验收（feedback-heat-scoring §13.5/§16.2/§18、
config/contracts/recommendation_ranking.json `feedback_workflow`）。

覆盖契约断言（acceptance_assertions）：
- rollup_idempotent（断言 2 提案面）：本窗口已有提案（任意状态）不重复生成；
- pending_proposal_no_effect（断言 3）：pending 提案对 active_rubric /
  rubric_version / effective weights 零影响，推荐 run 行为逐位一致；
- accept_uses_activate_chain（断言 4）：accept 走既有 compile+activate 链
  （版本 +1、model_called=false 编译记录、activate 与 review 双审计）；
- stale_proposal_guard（断言 5）：base_rubric_version 不匹配 accept 422、
  reject 不动 policy、新提案 supersede 存量 pending、超 30 天置 expired；
- budget_bucket_isolated（断言 6）：提案生成（含重试）只计
  purpose=feedback_rollup 桶，4 次/日耗尽走 skipped_budget 且 rollup 照常成功。
LLM 调用全部走 app.llm.provider.TRANSPORT 的 MockTransport。
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.llm.budget import (
    FEEDBACK_ROLLUP_DAILY_CAP,
    PURPOSE_FEEDBACK_ROLLUP,
    PURPOSE_GENERATION,
    PURPOSE_RERANK,
    PURPOSE_RUBRIC_COMPILE,
    current_day_key,
    record_generation_call,
)
from app.models.common import utc_now
from app.models.content import (
    RecommendationRubricCompile,
    RubricRevisionProposal,
    RubricTopicPrior,
)
from app.models.feedback import AuditLog
from app.models.workspace import Workspace
from app.recommendations.rollup import (
    rollup_workspace_week,
    supersede_other_pending_proposals,
)
from tests.test_feedback_rollup import (
    FIXTURE_RUBRIC,
    current_week_key,
    epsilon_zero_fixture,
    make_session,
    run_recommendation,
    seed_daily_report,
    seed_news,
    seed_rec_item,
    seed_rec_run,
    set_recommendation_policy,
)
from tests.test_news_normalization import seed_source, seed_workspace
from tests.test_recommendation_policy import (
    DEFAULT_RUBRIC,
    install_provider,
    make_client,
    usage_total,
)

ROLLUP_RUN_URL = "/api/workspaces/planning_intel/feedback-rollups/run"
PROPOSALS_URL = "/api/workspaces/planning_intel/rubric-revision-proposals"
POLICY_URL = "/api/workspaces/planning_intel/recommendation-policy"


def build_proposal_payload(base_rubric: dict) -> dict:
    """从 base rubric 派生一份合法提案输出（调一个 topic 权重）。"""
    proposed = copy.deepcopy(base_rubric)
    topic = proposed["topics"][0]
    from_weight = float(topic["weight"])
    to_weight = from_weight - 0.5 if from_weight >= 4.5 else from_weight + 0.5
    topic["weight"] = to_weight
    return {
        "proposed_rubric": proposed,
        "change_summary": [
            {
                "op": "adjust_topic_weight",
                "target_code": topic["code"],
                "from": from_weight,
                "to": to_weight,
                "rationale": "采信集中于该主题",
            },
        ],
    }


class ProposalHandler:
    """按 responder 序列回包并计数（默认回合法提案）。"""

    def __init__(self, responses=None):
        self.calls = 0
        self.responses = list(responses or [])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.responses:
            content = self.responses.pop(0)
        else:
            content = json.dumps(build_proposal_payload(DEFAULT_RUBRIC), ensure_ascii=False)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )


def activate_fixture_rubric(session_factory, rubric=None, version: int = 1):
    with session_factory() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        config = dict(workspace.config_json or {})
        policy = dict(config.get("recommendation_policy") or {})
        policy.update(
            {
                "active_rubric": rubric or DEFAULT_RUBRIC,
                "rubric_status": "active",
                "rubric_version": version,
            },
        )
        config["recommendation_policy"] = policy
        workspace.config_json = config
        session.commit()


def seed_strong_signals(session_factory, adopted: int = 6, rejected: int = 6):
    """窗口内 daily_adopt + daily_reject >= 10（提案触发强信号门槛）。"""
    with session_factory() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        source = seed_source(session, workspace, name="Signal Source")
        run = seed_rec_run(session, workspace)
        entries = []
        total = adopted + rejected
        for index in range(1, total + 1):
            news = seed_news(session, workspace, source, f"signal-{index}")
            seed_rec_item(session, run, news, rank=index, final=100.0 - index)
            entries.append((news, index, 2 if index <= adopted else 3, False))
        seed_daily_report(session, workspace, entries)
        session.commit()


def proposal_rows(session_factory):
    with session_factory() as session:
        return session.scalars(
            select(RubricRevisionProposal).order_by(RubricRevisionProposal.created_at),
        ).all()


# ---------------------------------------------------------------------------
# 生成链路 + 断言 2（提案面）/ 断言 6（预算桶）
# ---------------------------------------------------------------------------


def test_weekly_rollup_generates_proposal_once_per_window(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = ProposalHandler()
    install_provider(monkeypatch, handler)
    activate_fixture_rubric(session_factory)
    seed_strong_signals(session_factory)

    first = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert first.status_code == 200
    assert first.json()["proposal_status"] == "generated"
    assert first.json()["status"] == "succeeded"
    assert handler.calls == 1

    listed = client.get(f"{PROPOSALS_URL}?status=pending_review")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    proposal = items[0]
    assert proposal["base_rubric_version"] == 1
    assert proposal["prompt_version"] == "revision_prompt_v1"
    assert proposal["change_summary"][0]["op"] == "adjust_topic_weight"
    assert proposal["rollup_period_key"] == first.json()["period_key"]
    assert proposal["sample_refs"]["adopted"]

    # 断言 6：提案生成只计 feedback_rollup 桶，三个既有桶不动。
    assert usage_total(session_factory, PURPOSE_FEEDBACK_ROLLUP) == 1
    assert usage_total(session_factory, PURPOSE_GENERATION) == 0
    assert usage_total(session_factory, PURPOSE_RERANK) == 0
    assert usage_total(session_factory, PURPOSE_RUBRIC_COMPILE) == 0

    # 断言 2（提案面）：同窗口重跑不重复生成（任意状态的存量提案都算）。
    second = client.post(
        ROLLUP_RUN_URL,
        json={"period_type": "weekly", "period_key": first.json()["period_key"]},
    )
    assert second.status_code == 200
    assert second.json()["proposal_status"] == "generated"
    assert handler.calls == 1
    assert len(proposal_rows(session_factory)) == 1

    # 驳回后同窗口重跑仍不再生成（窗口级幂等覆盖任意状态）。
    review = client.post(
        f"{PROPOSALS_URL}/{proposal['id']}/review",
        json={"action": "reject", "comment": "方向不对"},
    )
    assert review.status_code == 200
    third = client.post(
        ROLLUP_RUN_URL,
        json={"period_type": "weekly", "period_key": first.json()["period_key"]},
    )
    assert third.status_code == 200
    assert handler.calls == 1
    assert len(proposal_rows(session_factory)) == 1


def test_proposal_retry_counts_budget_and_double_failure_marks_failed(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    # 第一次回不合法 JSON、第二次回合法提案 -> 重试成功且计 2 次预算。
    handler = ProposalHandler(
        responses=["not-json", json.dumps(build_proposal_payload(DEFAULT_RUBRIC), ensure_ascii=False)],
    )
    install_provider(monkeypatch, handler)
    activate_fixture_rubric(session_factory)
    seed_strong_signals(session_factory)

    response = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert response.status_code == 200
    assert response.json()["proposal_status"] == "generated"
    assert handler.calls == 2
    assert usage_total(session_factory, PURPOSE_FEEDBACK_ROLLUP) == 2

    # 两次都失败 -> proposal_status=failed，rollup 本身照常 succeeded。
    second_dir = tmp_path.joinpath("f2")
    second_dir.mkdir()
    client2, session_factory2 = make_client(monkeypatch, second_dir)
    handler2 = ProposalHandler(responses=["not-json", "still-not-json"])
    install_provider(monkeypatch, handler2)
    activate_fixture_rubric(session_factory2)
    seed_strong_signals(session_factory2)
    failed = client2.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert failed.status_code == 200
    assert failed.json()["proposal_status"] == "failed"
    assert failed.json()["status"] == "succeeded"
    assert handler2.calls == 2
    assert len(proposal_rows(session_factory2)) == 0


def test_budget_exhaustion_skips_proposal_and_rollup_succeeds(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = ProposalHandler()
    install_provider(monkeypatch, handler)
    activate_fixture_rubric(session_factory)
    seed_strong_signals(session_factory)
    with session_factory() as session:
        for _ in range(FEEDBACK_ROLLUP_DAILY_CAP):
            record_generation_call(
                session,
                "planning_intel",
                current_day_key(),
                purpose=PURPOSE_FEEDBACK_ROLLUP,
            )
        session.commit()

    response = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert response.status_code == 200
    assert response.json()["proposal_status"] == "skipped_budget"
    assert response.json()["status"] == "succeeded"
    assert handler.calls == 0
    assert usage_total(session_factory, PURPOSE_FEEDBACK_ROLLUP) == FEEDBACK_ROLLUP_DAILY_CAP


def test_proposal_skip_reasons(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = ProposalHandler()
    install_provider(monkeypatch, handler)

    # skipped_no_rubric：无 active rubric。
    seed_strong_signals(session_factory)
    response = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert response.json()["proposal_status"] == "skipped_no_rubric"

    # skipped_disabled：开关关闭。
    activate_fixture_rubric(session_factory)
    patched = client.patch(
        POLICY_URL,
        json={"feedback_workflow": {"proposal_generation_enabled": False}},
    )
    assert patched.status_code == 200
    response = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert response.json()["proposal_status"] == "skipped_disabled"

    # skipped_pending_exists：存量 pending 提案（挂在别的窗口）挡住新生成。
    client.patch(POLICY_URL, json={"feedback_workflow": {"proposal_generation_enabled": True}})
    other = client.post(
        ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": "2026-W01"}
    )
    assert other.status_code == 200
    with session_factory() as session:
        session.add(
            RubricRevisionProposal(
                workspace_code="planning_intel",
                rollup_id=other.json()["id"],
                base_rubric_version=1,
                proposed_rubric_json=DEFAULT_RUBRIC,
                change_summary_json=[],
                status="pending_review",
            ),
        )
        session.commit()
    response = client.post(
        ROLLUP_RUN_URL,
        json={"period_type": "weekly", "period_key": current_week_key()},
    )
    assert response.json()["proposal_status"] == "skipped_pending_exists"
    assert handler.calls == 0


def test_low_data_skip_without_strong_signals(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = ProposalHandler()
    install_provider(monkeypatch, handler)
    activate_fixture_rubric(session_factory)
    seed_strong_signals(session_factory, adopted=3, rejected=3)  # 6 < 10
    response = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert response.json()["proposal_status"] == "skipped_low_data"
    assert handler.calls == 0


# ---------------------------------------------------------------------------
# 断言 3：提案未审阅不影响现行 rubric 与推荐行为
# ---------------------------------------------------------------------------


def test_pending_proposal_has_zero_effect_on_policy_and_runs():
    session = make_session()
    workspace = epsilon_zero_fixture(session)
    set_recommendation_policy(
        session,
        workspace,
        active_rubric=FIXTURE_RUBRIC,
        rubric_status="active",
        rubric_version=1,
    )
    baseline = run_recommendation(session)
    baseline_rows = sorted(
        (item.news_item.source_url or "", item.rank, item.selected)
        for item in baseline.run.items
    )
    policy_before = dict(workspace.config_json["recommendation_policy"])
    priors_before = [
        (row.topic_code, row.effective_weight)
        for row in session.scalars(select(RubricTopicPrior)).all()
    ]

    rollup = rollup_workspace_week(session, workspace, current_week_key())
    session.add(
        RubricRevisionProposal(
            workspace_code=workspace.code,
            rollup_id=rollup.id,
            base_rubric_version=1,
            proposed_rubric_json=build_proposal_payload(FIXTURE_RUBRIC)["proposed_rubric"],
            change_summary_json=[],
            status="pending_review",
        ),
    )
    session.flush()

    # active_rubric / rubric_version / effective weights 全部不变。
    policy_after = dict(workspace.config_json["recommendation_policy"])
    assert policy_after["active_rubric"] == policy_before["active_rubric"]
    assert policy_after["rubric_version"] == policy_before["rubric_version"]
    priors_after = [
        (row.topic_code, row.effective_weight)
        for row in session.scalars(select(RubricTopicPrior)).all()
    ]
    assert priors_after == priors_before
    # 推荐 run 行为与无提案时逐位一致。
    rerun = run_recommendation(session)
    rerun_rows = sorted(
        (item.news_item.source_url or "", item.rank, item.selected)
        for item in rerun.run.items
    )
    assert rerun_rows == baseline_rows


# ---------------------------------------------------------------------------
# 断言 4：accept 走既有 activate 链（原子 + 双审计）
# ---------------------------------------------------------------------------


def accept_fixture(monkeypatch, tmp_path):
    client, session_factory = make_client(monkeypatch, tmp_path)
    handler = ProposalHandler()
    install_provider(monkeypatch, handler)
    activate_fixture_rubric(session_factory)
    seed_strong_signals(session_factory)
    run = client.post(ROLLUP_RUN_URL, json={"period_type": "weekly", "period_key": current_week_key()})
    assert run.json()["proposal_status"] == "generated"
    listed = client.get(f"{PROPOSALS_URL}?status=pending_review")
    proposal = listed.json()["items"][0]
    return client, session_factory, proposal


def test_accept_runs_existing_activate_chain(monkeypatch, tmp_path):
    client, session_factory, proposal = accept_fixture(monkeypatch, tmp_path)
    accepted = client.post(
        f"{PROPOSALS_URL}/{proposal['id']}/review",
        json={"action": "accept", "comment": "看过 diff，采纳"},
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["status"] == "accepted"
    assert body["compile_fingerprint"].startswith("sha256:")

    policy = client.get(POLICY_URL).json()["policy"]
    # rubric_version + 1，active_rubric 换成提案 rubric。
    assert policy["rubric_version"] == 2
    assert policy["rubric_status"] == "active"
    assert (
        policy["active_rubric"]["topics"][0]["weight"]
        == proposal["proposed_rubric"]["topics"][0]["weight"]
    )

    with session_factory() as session:
        compile_row = session.scalar(
            select(RecommendationRubricCompile).where(
                RecommendationRubricCompile.fingerprint == body["compile_fingerprint"],
            ),
        )
        assert compile_row is not None
        assert compile_row.model_called is False
        assert compile_row.prompt_version == "revision_proposal_v1"
        activate_audits = session.scalars(
            select(AuditLog).where(
                AuditLog.action == "workspace.recommendation_rubric.activate",
            ),
        ).all()
        review_audits = session.scalars(
            select(AuditLog).where(
                AuditLog.action == "workspace.rubric_revision_proposal.review",
            ),
        ).all()
        assert len(activate_audits) == 1
        assert len(review_audits) == 1
        assert review_audits[0].detail_json["action"] == "accept"

    # accept 后不再 pending：重复 accept 422。
    again = client.post(
        f"{PROPOSALS_URL}/{proposal['id']}/review",
        json={"action": "accept", "comment": ""},
    )
    assert again.status_code == 422


# ---------------------------------------------------------------------------
# 断言 5：stale 防护 / reject / supersede / expired
# ---------------------------------------------------------------------------


def test_stale_proposal_accept_answers_422(monkeypatch, tmp_path):
    client, session_factory, proposal = accept_fixture(monkeypatch, tmp_path)
    # 生成后 rubric 被人工改版（版本推进）：提案作废。
    activate_fixture_rubric(session_factory, version=2)
    stale = client.post(
        f"{PROPOSALS_URL}/{proposal['id']}/review",
        json={"action": "accept", "comment": ""},
    )
    assert stale.status_code == 422
    with session_factory() as session:
        row = session.scalar(select(RubricRevisionProposal))
        assert row.status == "pending_review"  # 状态不变，可驳回或重新生成


def test_reject_leaves_policy_untouched(monkeypatch, tmp_path):
    client, session_factory, proposal = accept_fixture(monkeypatch, tmp_path)
    policy_before = client.get(POLICY_URL).json()["policy"]
    rejected = client.post(
        f"{PROPOSALS_URL}/{proposal['id']}/review",
        json={"action": "reject", "comment": "证据不足"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["review_comment"] == "证据不足"
    policy_after = client.get(POLICY_URL).json()["policy"]
    assert policy_after == policy_before
    with session_factory() as session:
        review_audits = session.scalars(
            select(AuditLog).where(
                AuditLog.action == "workspace.rubric_revision_proposal.review",
            ),
        ).all()
        assert len(review_audits) == 1
        assert review_audits[0].detail_json["action"] == "reject"


def test_new_proposal_supersedes_leftover_pending():
    session = make_session()
    workspace = seed_workspace(session)
    rollup = rollup_workspace_week(session, workspace, current_week_key())
    old = RubricRevisionProposal(
        workspace_code=workspace.code,
        rollup_id=rollup.id,
        base_rubric_version=1,
        proposed_rubric_json={},
        change_summary_json=[],
        status="pending_review",
    )
    new = RubricRevisionProposal(
        workspace_code=workspace.code,
        rollup_id=rollup.id,
        base_rubric_version=1,
        proposed_rubric_json={},
        change_summary_json=[],
        status="pending_review",
    )
    session.add_all([old, new])
    session.flush()
    superseded = supersede_other_pending_proposals(session, workspace.code, keep_id=new.id)
    assert superseded == 1
    assert old.status == "superseded"
    assert new.status == "pending_review"


def test_pending_older_than_30_days_expired_by_weekly_job():
    session = make_session()
    workspace = seed_workspace(session)
    rollup = rollup_workspace_week(session, workspace, "2026-W01")
    stale = RubricRevisionProposal(
        workspace_code=workspace.code,
        rollup_id=rollup.id,
        base_rubric_version=1,
        proposed_rubric_json={},
        change_summary_json=[],
        status="pending_review",
    )
    session.add(stale)
    session.flush()
    stale.created_at = utc_now() - timedelta(days=31)
    session.flush()
    rollup_workspace_week(session, workspace, current_week_key())
    assert stale.status == "expired"
