"""run 级自动重试链（pipeline-jobs-design §3.1/§6.1-§6.2、§12 断言 5-7）。

覆盖：
- 断言 5：failed（可重试）+ retry.max_attempts=2 → backoff 到期出现
  trigger_type=retry/attempt=2/retry_of_run_id 链；耗尽后不再产生新 run 并发
  ingestion.pipeline_retry_exhausted important 通知。
- 断言 6：published_report_conflict / invalid_parameters / workspace_not_found
  等不可重试 error_code 不写 next_retry_at、不产生自动重试。
- 断言 7：同 day_key 手动重跑成功（succeeded run 或已发布日报）后，自动重试
  让位落 skipped + skip_reason=superseded。
- partial 永不触发 run 级重试（两级重试分工 §6.1）。
- 请求级 retry_max_attempts=0 覆盖：本次不自动重试、不发耗尽告警。
"""

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.models.feedback import ActivityEvent, AuditLog, Notification
from app.models.pipeline import PipelineRun, SchedulerHeartbeat
from app.models.reports import DailyReport
from app.models.workspace import Workspace
from app.pipeline.daily import DailyPipelineRequest, DailyPipelineResult, run_daily_pipeline_job
from app.pipeline.runs import (
    create_pipeline_run,
    ensure_aware,
    execute_pipeline_run,
)
from app.recommendations.service import PublishedDailyReportError
from app.workers.scheduler import SchedulerState, scheduler_tick
from tests.test_scheduler_policy import RQ_CONTROL_KWARGS, FakeQueue, make_settings

DAY_KEY = "2026-07-06"


def make_env(monkeypatch, tmp_path, name):
    database_path = tmp_path / name
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "password")
    monkeypatch.setenv(
        "LEGACY_SEED_ROOT",
        str(Path(__file__).resolve().parents[2] / "config" / "seeds" / "legacy"),
    )
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        ensure_auth_seed(session, get_settings())
    return session_factory


def set_schedule_policy(session_factory, workspace_code, policy):
    with session_factory() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
        config = dict(workspace.config_json or {})
        config["schedule_policy"] = policy
        workspace.config_json = config
        session.commit()


def patch_failing_pipeline(monkeypatch, exception_factory):
    async def _failing(session, request, registry=None):
        raise exception_factory()

    monkeypatch.setattr("app.pipeline.runs.run_daily_pipeline", _failing)


def make_manual_request(day_key=DAY_KEY):
    return DailyPipelineRequest(workspace_code="planning_intel", day_key=day_key)


def run_failed_pipeline(session_factory, *, retry_max_attempts_override=None):
    with session_factory() as session:
        run = create_pipeline_run(
            session,
            request=make_manual_request(),
            trigger_type="manual",
            triggered_by="tester",
            retry_max_attempts_override=retry_max_attempts_override,
        )
        session.commit()
        run_id = run.id
        payload = asyncio.run(execute_pipeline_run(session, run))
    return run_id, payload


def get_run(session_factory, run_id):
    with session_factory() as session:
        run = session.get(PipelineRun, run_id)
        session.expunge(run)
        return run


def invoke_enqueued(call):
    function, args, kwargs = call
    job_kwargs = {k: v for k, v in kwargs.items() if k not in RQ_CONTROL_KWARGS}
    return function(*args, **job_kwargs)


# ---------------------------------------------------------------------------
# 断言 5：重试链 attempt 1 → 2 → 3，耗尽后发通知不再重投
# ---------------------------------------------------------------------------


def test_retry_chain_backoff_and_exhaustion_notification(monkeypatch, tmp_path):
    session_factory = make_env(monkeypatch, tmp_path, "retry_chain.sqlite")
    set_schedule_policy(
        session_factory,
        "planning_intel",
        {"enabled": False, "retry": {"max_attempts": 2, "backoff_seconds": 600}},
    )
    patch_failing_pipeline(monkeypatch, lambda: RuntimeError("redis connection refused"))

    # 首跑失败：可重试 error_code + backoff 首个间隔 600s。
    run1_id, payload1 = run_failed_pipeline(session_factory)
    assert payload1["status"] == "failed"
    assert payload1["error_code"] == "pipeline_execution_error"
    run1 = get_run(session_factory, run1_id)
    assert run1.status == "failed"
    assert run1.attempt == 1
    assert run1.max_attempts == 3  # retry.max_attempts=2 + 首跑
    assert run1.next_retry_at is not None
    assert run1.retry_reason == "pipeline_execution_error"
    expected_first_retry = ensure_aware(run1.finished_at) + timedelta(seconds=600)
    assert abs((ensure_aware(run1.next_retry_at) - expected_first_retry).total_seconds()) < 1

    settings = make_settings()
    queue = FakeQueue()
    state = SchedulerState()

    # backoff 未到期：不投递。
    scheduler_tick(
        queue,
        settings,
        state,
        now=ensure_aware(run1.next_retry_at) - timedelta(seconds=30),
        session_factory=session_factory,
    )
    assert queue.calls == []

    # backoff 到期：出现 trigger_type=retry / attempt=2 / retry_of_run_id=首跑。
    scheduler_tick(
        queue,
        settings,
        state,
        now=ensure_aware(run1.next_retry_at) + timedelta(seconds=1),
        session_factory=session_factory,
    )
    assert len(queue.calls) == 1
    function, args, kwargs = queue.calls[0]
    assert function is run_daily_pipeline_job
    assert kwargs["trigger_type"] == "retry"
    assert kwargs["attempt"] == 2
    assert kwargs["retry_of_run_id"] == run1_id
    run2_id = kwargs["pipeline_run_id"]
    run2 = get_run(session_factory, run2_id)
    assert run2.trigger_type == "retry"
    assert run2.attempt == 2
    assert run2.retry_of_run_id == run1_id
    assert run2.status == "queued"
    assert run2.day_key == DAY_KEY
    # 待重试标记被消费：同一 tick 重放不重复投递。
    assert get_run(session_factory, run1_id).next_retry_at is None
    scheduler_tick(
        queue,
        settings,
        state,
        now=ensure_aware(run1.finished_at) + timedelta(seconds=700),
        session_factory=session_factory,
    )
    assert len(queue.calls) == 1

    # 投递证据：审计 pipeline.run.auto_retry（run id 链）+ 心跳 job_kind=pipeline_retry。
    with session_factory() as session:
        audit = session.scalars(
            select(AuditLog).where(AuditLog.action == "pipeline.run.auto_retry"),
        ).all()
        assert len(audit) == 1
        assert audit[0].detail_json["run_id_chain"] == [run1_id, run2_id]
        assert audit[0].detail_json["attempt"] == 2
        assert audit[0].detail_json["error_code"] == "pipeline_execution_error"
        heartbeat = session.scalars(
            select(SchedulerHeartbeat).where(
                SchedulerHeartbeat.job_kind == "pipeline_retry",
                SchedulerHeartbeat.workspace_code == "planning_intel",
            ),
        ).all()
        assert len(heartbeat) == 1
        assert heartbeat[0].last_enqueued_at is not None

    # 执行重试 job：再次失败 → attempt=2 失败、退避翻倍。
    payload2 = invoke_enqueued(queue.calls[0])
    assert payload2["status"] == "failed"
    run2 = get_run(session_factory, run2_id)
    assert run2.status == "failed"
    assert run2.next_retry_at is not None
    expected_second_retry = ensure_aware(run2.finished_at) + timedelta(seconds=1200)
    assert abs((ensure_aware(run2.next_retry_at) - expected_second_retry).total_seconds()) < 1

    # 第 3 次尝试（最后一次允许的 attempt）。
    scheduler_tick(
        queue,
        settings,
        state,
        now=ensure_aware(run2.next_retry_at) + timedelta(seconds=1),
        session_factory=session_factory,
    )
    assert len(queue.calls) == 2
    run3_id = queue.calls[1][2]["pipeline_run_id"]
    assert queue.calls[1][2]["attempt"] == 3
    payload3 = invoke_enqueued(queue.calls[1])
    assert payload3["status"] == "failed"
    run3 = get_run(session_factory, run3_id)
    assert run3.attempt == 3
    assert run3.status == "failed"
    # 达到上限：不再写 next_retry_at。
    assert run3.next_retry_at is None

    # 耗尽通知：ingestion.pipeline_retry_exhausted（important，链路可回溯）。
    with session_factory() as session:
        events = session.scalars(
            select(ActivityEvent).where(
                ActivityEvent.event_type == "ingestion.pipeline_retry_exhausted",
            ),
        ).all()
        assert len(events) == 1
        metadata = events[0].metadata_json
        assert metadata["run_id_chain"] == [run1_id, run2_id, run3_id]
        assert metadata["attempt"] == 3
        assert metadata["error_code"] == "pipeline_execution_error"
        assert metadata["day_key"] == DAY_KEY
        assert metadata["pipeline_run_id"] == run3_id
        notifications = session.scalars(
            select(Notification).where(Notification.activity_event_id == events[0].id),
        ).all()
        assert notifications, "super_admin 应收到耗尽站内通知"
        assert all(item.priority == "important" for item in notifications)
        assert all(item.delivery_channel == "in_app" for item in notifications)

    # 耗尽后 tick：不再产生第 4 个 run。
    scheduler_tick(
        queue,
        settings,
        state,
        now=ensure_aware(run3.finished_at) + timedelta(days=1),
        session_factory=session_factory,
    )
    assert len(queue.calls) == 2
    with session_factory() as session:
        assert len(session.scalars(select(PipelineRun)).all()) == 3


# ---------------------------------------------------------------------------
# 断言 6：不可重试 error_code 直接终态
# ---------------------------------------------------------------------------


def test_non_retryable_error_codes_go_terminal(monkeypatch, tmp_path):
    session_factory = make_env(monkeypatch, tmp_path, "non_retryable.sqlite")

    # published_report_conflict（409 类）。
    patch_failing_pipeline(
        monkeypatch,
        lambda: PublishedDailyReportError("Daily report is already published: r-1"),
    )
    run_id, payload = run_failed_pipeline(session_factory)
    assert payload["error_code"] == "published_report_conflict"
    run = get_run(session_factory, run_id)
    assert run.status == "failed"
    assert run.next_retry_at is None

    # invalid_parameters（ValueError 类）。
    patch_failing_pipeline(monkeypatch, lambda: ValueError("week_key must use ISO format"))
    run_id2, payload2 = run_failed_pipeline(session_factory)
    assert payload2["error_code"] == "invalid_parameters"
    assert get_run(session_factory, run_id2).next_retry_at is None

    # workspace_not_found：真实链路（不打补丁）也归为不可重试。
    monkeypatch.undo()
    monkeypatch.setenv("DATABASE_URL", get_settings().database_url)
    with session_factory() as session:
        missing = create_pipeline_run(
            session,
            request=DailyPipelineRequest(workspace_code="ghost_ws", day_key=DAY_KEY),
            trigger_type="manual",
            triggered_by="tester",
        )
        session.commit()
        payload3 = asyncio.run(execute_pipeline_run(session, missing))
    assert payload3["error_code"] == "workspace_not_found"
    assert get_run(session_factory, missing.id).next_retry_at is None

    # 不可重试失败不投递、不发耗尽告警。
    queue = FakeQueue()
    scheduler_tick(queue, make_settings(), SchedulerState(), session_factory=session_factory)
    assert queue.calls == []
    with session_factory() as session:
        assert (
            session.scalars(
                select(ActivityEvent).where(
                    ActivityEvent.event_type == "ingestion.pipeline_retry_exhausted",
                ),
            ).all()
            == []
        )


# ---------------------------------------------------------------------------
# 断言 7：superseded 让位
# ---------------------------------------------------------------------------


def test_superseded_retry_skips_without_overwriting_manual_result(monkeypatch, tmp_path):
    session_factory = make_env(monkeypatch, tmp_path, "superseded.sqlite")
    patch_failing_pipeline(monkeypatch, lambda: RuntimeError("db down"))
    run1_id, _payload = run_failed_pipeline(session_factory)
    run1 = get_run(session_factory, run1_id)
    assert run1.next_retry_at is not None

    # 首跑失败后管理员手动重跑成功（同 day_key succeeded run）。
    with session_factory() as session:
        manual = create_pipeline_run(
            session,
            request=make_manual_request(),
            trigger_type="manual",
            triggered_by="admin",
        )
        manual.status = "succeeded"
        session.commit()
        manual_id = manual.id

    queue = FakeQueue()
    scheduler_tick(
        queue,
        make_settings(),
        SchedulerState(),
        now=ensure_aware(run1.next_retry_at) + timedelta(seconds=1),
        session_factory=session_factory,
    )
    # 自动重试让位：不投递 job。
    assert queue.calls == []
    with session_factory() as session:
        skipped = session.scalars(
            select(PipelineRun).where(PipelineRun.status == "skipped"),
        ).all()
        assert len(skipped) == 1
        assert skipped[0].skip_reason == "superseded"
        assert skipped[0].trigger_type == "retry"
        assert skipped[0].retry_of_run_id == run1_id
        assert skipped[0].attempt == 2
        # 手动成功 run 不被覆盖。
        assert session.get(PipelineRun, manual_id).status == "succeeded"
        assert session.get(PipelineRun, run1_id).next_retry_at is None


def test_published_daily_report_also_supersedes_retry(monkeypatch, tmp_path):
    session_factory = make_env(monkeypatch, tmp_path, "superseded_published.sqlite")
    patch_failing_pipeline(monkeypatch, lambda: RuntimeError("db down"))
    run1_id, _payload = run_failed_pipeline(session_factory)
    run1 = get_run(session_factory, run1_id)

    with session_factory() as session:
        session.add(
            DailyReport(
                workspace_code="planning_intel",
                day_key=DAY_KEY,
                title=f"{DAY_KEY} 日报",
                status="published",
            ),
        )
        session.commit()

    queue = FakeQueue()
    scheduler_tick(
        queue,
        make_settings(),
        SchedulerState(),
        now=ensure_aware(run1.next_retry_at) + timedelta(seconds=1),
        session_factory=session_factory,
    )
    assert queue.calls == []
    with session_factory() as session:
        skipped = session.scalars(
            select(PipelineRun).where(PipelineRun.status == "skipped"),
        ).one()
        assert skipped.skip_reason == "superseded"


# ---------------------------------------------------------------------------
# partial 永不触发 run 级重试（§6.1 两级重试分工）
# ---------------------------------------------------------------------------


def test_partial_run_never_triggers_run_level_retry(monkeypatch, tmp_path):
    session_factory = make_env(monkeypatch, tmp_path, "partial.sqlite")

    async def _partial_pipeline(session, request, registry=None):
        return DailyPipelineResult(
            ingestion_run=SimpleNamespace(id="ing-1", status="partial", source_failed=2),
            normalization=SimpleNamespace(
                raw_scanned=3,
                news_created=1,
                news_updated=0,
                raw_skipped=0,
                dedupe_groups_updated=1,
            ),
            recommendation=SimpleNamespace(
                run=SimpleNamespace(
                    id="rec-1",
                    workspace_code="planning_intel",
                    params_json={"day_key": DAY_KEY},
                ),
                daily_report=None,
                candidates_total=1,
                selected_total=1,
                generated_total=1,
            ),
            auto_published=False,
        )

    monkeypatch.setattr("app.pipeline.runs.run_daily_pipeline", _partial_pipeline)
    run_id, payload = run_failed_pipeline(session_factory)
    assert payload["pipeline_run_status"] == "partial"
    run = get_run(session_factory, run_id)
    assert run.status == "partial"
    assert run.next_retry_at is None
    assert run.error_code == ""

    queue = FakeQueue()
    scheduler_tick(queue, make_settings(), SchedulerState(), session_factory=session_factory)
    assert queue.calls == []


# ---------------------------------------------------------------------------
# 请求级 retry_max_attempts=0 覆盖：本次不自动重试，也不发耗尽告警
# ---------------------------------------------------------------------------


def test_request_override_zero_disables_auto_retry(monkeypatch, tmp_path):
    session_factory = make_env(monkeypatch, tmp_path, "override_zero.sqlite")
    set_schedule_policy(
        session_factory,
        "planning_intel",
        {"retry": {"max_attempts": 3, "backoff_seconds": 600}},
    )
    patch_failing_pipeline(monkeypatch, lambda: RuntimeError("provider down"))

    run_id, payload = run_failed_pipeline(session_factory, retry_max_attempts_override=0)
    assert payload["status"] == "failed"
    run = get_run(session_factory, run_id)
    assert run.max_attempts == 1
    assert run.next_retry_at is None
    with session_factory() as session:
        assert (
            session.scalars(
                select(ActivityEvent).where(
                    ActivityEvent.event_type == "ingestion.pipeline_retry_exhausted",
                ),
            ).all()
            == []
        )
