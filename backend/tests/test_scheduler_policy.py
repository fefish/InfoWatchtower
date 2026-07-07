"""工作台级调度策略 + 调度心跳（pipeline-jobs-design §8.1-§8.5、§12 断言 1-4/8-10）。

覆盖：
- 断言 1：schedule-policy PATCH/GET/审计/权限/取值域 422。
- 断言 2：实例总闸关死，工作台 enabled=true 也不投递；status API 回显。
- 断言 3：两工作台各自触发时刻恰好各 1 个 scheduler run；tick 重放不重复。
- 断言 4：无策略工作台兼容回归——投递与旧版逐字节一致。
- 断言 8：心跳 >180s / 心跳表空 → heartbeat_stale=true。
- 断言 9：weekly 节拍幂等出草稿（workspace_code+week_key），不自动发布。
- 断言 10：intranet 不投 daily/weekly pipeline job；status API capability_ingestion=false。
"""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth.service import ensure_auth_seed
from app.core.config import get_settings
from app.core.database import Base, get_engine
from app.main import create_app
from app.models.common import utc_now
from app.models.feedback import AuditLog
from app.models.pipeline import PipelineRun, SchedulerHeartbeat
from app.models.reports import WeeklyReport
from app.models.workspace import Workspace
from app.pipeline.daily import run_daily_pipeline_job
from app.pipeline.runs import run_weekly_report_draft_job
from app.sync.pull import run_sync_pull_job
from app.workers.scheduler import SchedulerState, _enqueue_scheduled_job, scheduler_tick

SHANGHAI = ZoneInfo("Asia/Shanghai")

RQ_CONTROL_KWARGS = {"job_timeout", "result_ttl", "failure_ttl"}


class FakeQueue:
    def __init__(self):
        self.calls = []
        self._sequence = 0

    def enqueue(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        self._sequence += 1
        return SimpleNamespace(id=f"job-{self._sequence}")


def make_settings(**overrides):
    defaults = dict(
        deploy_mode="standalone",
        capability_ingestion=True,
        capability_sync_consumer=False,
        ingestion_scheduler_enabled=True,
        ingestion_scheduler_daily_time="12:00",
        ingestion_scheduler_timezone="Asia/Shanghai",
        ingestion_scheduler_workspace_code="planning_intel",
        ingestion_scheduler_interval_seconds=60 * 60 * 24,
        ingestion_scheduler_limit=None,
        ingestion_concurrency=8,
        ingestion_source_timeout_seconds=25.0,
        ingestion_max_items_per_source=None,
        ingestion_source_type_list=["rss"],
        ingestion_source_type_allowlist=[],
        ingestion_failed_source_auto_retry_effective=False,
        ingestion_failed_source_retry_base_seconds=900,
        sync_pull_effective=False,
        sync_pull_interval_seconds=900,
        sync_failed_inbox_auto_retry_effective=False,
        sync_failed_inbox_retry_base_seconds=300,
        scheduler_job_mode="daily_pipeline",
        daily_pipeline_run_ingestion=True,
        daily_pipeline_create_daily_draft=True,
        daily_pipeline_recommendation_limit=15,
        daily_pipeline_source_daily_limit=2,
        daily_pipeline_day_offset_days=0,
        scheduler_missed_window_seconds=3600,
        effective_instance_id="standalone",
        sync_remote_base_url="",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_session_factory(tmp_path, name="scheduler_policy.sqlite"):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def add_workspace(session, code, schedule_policy=None):
    workspace = Workspace(
        code=code,
        name=code,
        description="",
        config_json={"schedule_policy": schedule_policy} if schedule_policy else {},
    )
    session.add(workspace)
    session.commit()
    return workspace


def shanghai(*args):
    return datetime(*args, tzinfo=SHANGHAI)


# ---------------------------------------------------------------------------
# 断言 3：per-workspace 触发（两工作台各得恰好 1 个 scheduler run，tick 重放不重复）
# ---------------------------------------------------------------------------


def test_two_workspaces_dispatch_exactly_once_each(tmp_path):
    session_factory = make_session_factory(tmp_path)
    with session_factory() as session:
        add_workspace(session, "ws_morning", {"daily_time": "09:00"})
        add_workspace(session, "ws_evening", {"daily_time": "21:00"})

    settings = make_settings()
    queue = FakeQueue()
    state = SchedulerState()

    # 两个时刻之前：不投递。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 8, 0), session_factory=session_factory)
    assert queue.calls == []

    # 跨过 09:00：只投 ws_morning。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 9, 5), session_factory=session_factory)
    assert len(queue.calls) == 1
    function, args, kwargs = queue.calls[0]
    assert function is run_daily_pipeline_job
    assert args[0] == "ws_morning"
    assert kwargs["trigger_type"] == "scheduler"
    assert kwargs["pipeline_run_id"]

    # 同一时刻 tick 重放：不产生第 2 个同 (workspace, day_key) run。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 9, 6), session_factory=session_factory)
    assert len(queue.calls) == 1

    # 跨过 21:00：只补 ws_evening（ws_morning 已投过且超出 missed window）。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 21, 30), session_factory=session_factory)
    assert len(queue.calls) == 2
    assert queue.calls[1][1][0] == "ws_evening"

    with session_factory() as session:
        runs = session.scalars(select(PipelineRun)).all()
        assert len(runs) == 2
        by_workspace = {run.workspace_code: run for run in runs}
        assert set(by_workspace) == {"ws_morning", "ws_evening"}
        for run in runs:
            assert run.trigger_type == "scheduler"
            assert run.status == "queued"
            assert run.day_key == "2026-07-07"
            assert run.attempt == 1
        # 心跳投递证据（job_kind=daily_pipeline 的 per-workspace 行）。
        heartbeats = session.scalars(
            select(SchedulerHeartbeat).where(SchedulerHeartbeat.job_kind == "daily_pipeline"),
        ).all()
        assert {hb.workspace_code for hb in heartbeats if hb.workspace_code} == {
            "ws_morning",
            "ws_evening",
        }


def test_missed_window_skips_stale_trigger(tmp_path):
    """错过窗口超过 SCHEDULER_MISSED_WINDOW_SECONDS 不补跑，只等下一个触发点。"""
    session_factory = make_session_factory(tmp_path)
    with session_factory() as session:
        add_workspace(session, "ws_missed", {"daily_time": "09:00"})

    settings = make_settings(scheduler_missed_window_seconds=3600)
    queue = FakeQueue()
    # 09:00 触发点已经过去 2 小时（模拟 scheduler 停机后重启）。
    scheduler_tick(queue, settings, SchedulerState(), now=shanghai(2026, 7, 7, 11, 1), session_factory=session_factory)
    assert queue.calls == []
    with session_factory() as session:
        assert session.scalars(select(PipelineRun)).all() == []


# ---------------------------------------------------------------------------
# 断言 2：实例总闸关死（工作台策略不能越过）
# ---------------------------------------------------------------------------


def test_instance_master_switch_off_blocks_all_pipeline_dispatch(tmp_path):
    session_factory = make_session_factory(tmp_path)
    with session_factory() as session:
        add_workspace(
            session,
            "ws_wants_on",
            {"enabled": True, "daily_time": "09:00", "weekly": {"enabled": True, "weekly_day": 2, "weekly_time": "09:30"}},
        )

    settings = make_settings(ingestion_scheduler_enabled=False)
    queue = FakeQueue()
    # 2026-07-07 是周二（isoweekday=2），日报/周报触发时刻都已跨过。
    scheduler_tick(queue, settings, SchedulerState(), now=shanghai(2026, 7, 7, 10, 0), session_factory=session_factory)
    assert queue.calls == []
    with session_factory() as session:
        assert session.scalars(select(PipelineRun)).all() == []


# ---------------------------------------------------------------------------
# 断言 4：兼容回归——无策略工作台投递与现状逐字节一致
# ---------------------------------------------------------------------------


def test_compat_mode_dispatch_is_byte_identical_to_legacy(tmp_path):
    session_factory = make_session_factory(tmp_path, "compat.sqlite")
    with session_factory() as session:
        add_workspace(session, "planning_intel", schedule_policy=None)

    settings = make_settings(daily_pipeline_day_offset_days=-1)
    dispatch_now = shanghai(2026, 7, 7, 12, 0, 30)

    reference_queue = FakeQueue()
    _enqueue_scheduled_job(reference_queue, settings, now=dispatch_now)

    queue = FakeQueue()
    state = SchedulerState()
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 11, 59), session_factory=session_factory)
    assert queue.calls == []
    scheduler_tick(queue, settings, state, now=dispatch_now, session_factory=session_factory)

    assert len(queue.calls) == 1
    assert queue.calls == reference_queue.calls  # function/args/kwargs 全部一致

    # 兼容模式不因 tick 重放重复投递（内存节拍 +1 天，与旧版一致）。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 12, 1, 30), session_factory=session_factory)
    assert len(queue.calls) == 1

    # 兼容工作台没有策略：scheduler 不建 per-workspace run 行（由 worker job 落行）。
    with session_factory() as session:
        assert session.scalars(select(PipelineRun)).all() == []


def test_compat_mode_stored_default_policy_still_byte_identical(tmp_path):
    """存了策略但全部字段等于契约默认 = 行为仍与现状一致（不切遍历模式）。"""
    session_factory = make_session_factory(tmp_path, "compat_default.sqlite")
    with session_factory() as session:
        add_workspace(
            session,
            "planning_intel",
            {
                "enabled": None,
                "daily_time": None,
                "day_offset": None,
                "source_types": None,
                "retry": {"max_attempts": 1, "backoff_seconds": 900},
                "weekly": {"enabled": False, "weekly_day": 5, "weekly_time": "17:00"},
            },
        )

    settings = make_settings()
    dispatch_now = shanghai(2026, 7, 7, 12, 0, 30)
    reference_queue = FakeQueue()
    _enqueue_scheduled_job(reference_queue, settings, now=dispatch_now)

    queue = FakeQueue()
    state = SchedulerState()
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 11, 59), session_factory=session_factory)
    assert queue.calls == []
    scheduler_tick(queue, settings, state, now=dispatch_now, session_factory=session_factory)
    assert queue.calls == reference_queue.calls


# ---------------------------------------------------------------------------
# 断言 9：weekly 节拍——幂等出草稿，不自动发布
# ---------------------------------------------------------------------------


def test_weekly_beat_builds_single_draft_and_never_publishes(tmp_path, monkeypatch):
    database_path = tmp_path / "weekly_beat.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        add_workspace(
            session,
            "planning_intel",
            {"weekly": {"enabled": True, "weekly_day": 2, "weekly_time": "17:00"}},
        )

    settings = make_settings()
    queue = FakeQueue()
    state = SchedulerState()
    now = shanghai(2026, 7, 7, 17, 5)  # 2026-07-07 是周二 isoweekday=2
    scheduler_tick(queue, settings, state, now=now, session_factory=session_factory)

    weekly_calls = [call for call in queue.calls if call[0] is run_weekly_report_draft_job]
    assert len(weekly_calls) == 1
    function, args, kwargs = weekly_calls[0]
    iso = now.isocalendar()
    expected_week_key = f"{iso.year}-W{iso.week:02d}"
    assert args == ("planning_intel", expected_week_key)

    # 执行 job：草稿存在且 status=draft（不自动发布）。
    payload = function(*args, **{k: v for k, v in kwargs.items() if k not in RQ_CONTROL_KWARGS})
    assert payload["status"] == "succeeded"
    with session_factory() as session:
        reports = session.scalars(select(WeeklyReport)).all()
        assert len(reports) == 1
        assert reports[0].week_key == expected_week_key
        assert reports[0].status == "draft"

    # tick 重放：心跳幂等不重复投递。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 17, 6), session_factory=session_factory)
    assert len([call for call in queue.calls if call[0] is run_weekly_report_draft_job]) == 1

    # job 幂等重放（workspace_code + week_key）：仍只有一份草稿。
    function(*args)
    with session_factory() as session:
        assert len(session.scalars(select(WeeklyReport)).all()) == 1


# ---------------------------------------------------------------------------
# 断言 10：intranet 不投 daily/weekly pipeline job，sync 类任务保留
# ---------------------------------------------------------------------------


def test_intranet_dispatches_no_pipeline_jobs_but_keeps_sync(tmp_path):
    session_factory = make_session_factory(tmp_path, "intranet.sqlite")
    with session_factory() as session:
        add_workspace(
            session,
            "ws_intranet",
            {"daily_time": "09:00", "weekly": {"enabled": True, "weekly_day": 2, "weekly_time": "09:30"}},
        )

    settings = make_settings(
        deploy_mode="intranet",
        capability_ingestion=False,
        capability_sync_consumer=True,
        sync_pull_effective=True,
        sync_remote_base_url="https://extranet.example.com",
    )
    queue = FakeQueue()
    scheduler_tick(queue, settings, SchedulerState(), now=shanghai(2026, 7, 7, 10, 0), session_factory=session_factory)

    functions = [call[0] for call in queue.calls]
    assert run_daily_pipeline_job not in functions
    assert run_weekly_report_draft_job not in functions
    assert functions == [run_sync_pull_job]
    with session_factory() as session:
        assert session.scalars(select(PipelineRun)).all() == []


# ---------------------------------------------------------------------------
# 断言 1：schedule-policy API（校验/审计/resolved 预览/权限）
# ---------------------------------------------------------------------------


def make_client(monkeypatch, tmp_path, **env):
    database_path = tmp_path / "schedule_policy_api.sqlite"
    base_env = {
        "DATABASE_URL": f"sqlite:///{database_path}",
        "AUTH_MODE": "public_password",
        "AUTH_SESSION_SECRET": "test-session-secret",
        "AUTH_BOOTSTRAP_ADMIN_USERNAME": "admin",
        "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "password",
        "LEGACY_SEED_ROOT": str(Path(__file__).resolve().parents[2] / "config" / "seeds" / "legacy"),
        "INGESTION_SCHEDULER_ENABLED": "true",
        "INGESTION_SCHEDULER_DAILY_TIME": "12:00",
        "INGESTION_SCHEDULER_TIMEZONE": "Asia/Shanghai",
    }
    base_env.update(env)
    for key, value in base_env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        ensure_auth_seed(session, get_settings())
    return TestClient(create_app()), session_factory


def _invite_member(admin_client, *, role_code, workspace_role, username):
    invite = admin_client.post(
        "/api/auth/invites",
        json={
            "role_code": role_code,
            "workspaces": [{"code": "planning_intel", "workspace_role": workspace_role}],
            "expires_in_days": 7,
        },
    )
    assert invite.status_code == 200
    member = TestClient(create_app())
    accepted = member.post(
        f"/api/auth/invites/{invite.json()['code']}/accept",
        json={"username": username, "display_name": username, "password": "strong-password"},
    )
    assert accepted.status_code == 200
    return member


def test_schedule_policy_patch_get_audit_and_permission(monkeypatch, tmp_path):
    admin, session_factory = make_client(monkeypatch, tmp_path)
    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    workspace_admin = _invite_member(admin, role_code="viewer", workspace_role="admin", username="ws-admin")
    viewer = _invite_member(admin, role_code="viewer", workspace_role="viewer", username="ws-viewer")

    updated = workspace_admin.patch(
        "/api/workspaces/planning_intel/schedule-policy",
        json={"daily_time": "09:30", "retry": {"max_attempts": 2, "backoff_seconds": 600}},
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["workspace_code"] == "planning_intel"
    assert payload["policy"]["daily_time"] == "09:30"
    assert payload["policy"]["retry"] == {"max_attempts": 2, "backoff_seconds": 600}
    assert payload["resolved"]["policy_source"] == "workspace"
    assert payload["resolved"]["effective_daily_time"] == "09:30"
    assert payload["resolved"]["effective_enabled"] is True
    assert payload["resolved"]["next_run_at"] is not None
    assert "T09:30:00+08:00" in payload["resolved"]["next_run_at"]

    # 落库 + 审计（before/after 快照）。
    with session_factory() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        stored = workspace.config_json["schedule_policy"]
        assert stored["daily_time"] == "09:30"
        assert stored["retry"] == {"max_attempts": 2, "backoff_seconds": 600}
        audit = session.scalars(
            select(AuditLog).where(AuditLog.action == "workspace.schedule_policy.update"),
        ).all()
        assert len(audit) == 1
        detail = audit[0].detail_json
        assert detail["workspace_code"] == "planning_intel"
        assert detail["before"] == {}
        assert detail["after"]["daily_time"] == "09:30"

    # viewer 可读（返回 resolved 预览），写 403。
    read = viewer.get("/api/workspaces/planning_intel/schedule-policy")
    assert read.status_code == 200
    assert read.json()["resolved"]["policy_source"] == "workspace"
    forbidden = viewer.patch(
        "/api/workspaces/planning_intel/schedule-policy",
        json={"daily_time": "10:00"},
    )
    assert forbidden.status_code == 403

    # 非法取值域 422。
    for bad_payload in (
        {"daily_time": "25:00"},
        {"retry": {"max_attempts": 9}},
        {"retry": {"backoff_seconds": 30}},
        {"day_offset": -8},
        {"day_offset": 1},
        {"weekly": {"enabled": True, "weekly_day": 8}},
        {"weekly": {"weekly_time": "24:61"}},
        {"source_types": ["not_a_type"]},
    ):
        response = workspace_admin.patch(
            "/api/workspaces/planning_intel/schedule-policy",
            json=bad_payload,
        )
        assert response.status_code == 422, bad_payload


def test_schedule_policy_enabled_true_cannot_override_disabled_instance(monkeypatch, tmp_path):
    admin, _session_factory = make_client(monkeypatch, tmp_path, INGESTION_SCHEDULER_ENABLED="false")
    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    updated = admin.patch(
        "/api/workspaces/planning_intel/schedule-policy",
        json={"enabled": True, "daily_time": "09:00"},
    )
    assert updated.status_code == 200
    payload = updated.json()
    # 总闸关：工作台 enabled=true 不能越过（effective_enabled=false，无 next_run_at）。
    assert payload["policy"]["enabled"] is True
    assert payload["resolved"]["effective_enabled"] is False
    assert payload["resolved"]["next_run_at"] is None
    assert payload["instance"]["scheduler_enabled"] is False


# ---------------------------------------------------------------------------
# 断言 2/8/10：GET /api/pipeline/scheduler/status（心跳 stale/总闸/能力开关）
# ---------------------------------------------------------------------------


def test_scheduler_status_empty_heartbeats_reports_stale(monkeypatch, tmp_path):
    admin, _session_factory = make_client(monkeypatch, tmp_path)
    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    response = admin.get("/api/pipeline/scheduler/status")
    assert response.status_code == 200
    payload = response.json()
    # scheduler 未部署（心跳表空）：heartbeat_at=null 且 stale=true（§8.5）。
    assert payload["heartbeat_at"] is None
    assert payload["heartbeat_stale"] is True
    assert payload["instance_enabled"] is True
    assert payload["deploy_mode"] == "standalone"
    assert payload["capability_ingestion"] is True
    assert payload["timezone"] == "Asia/Shanghai"
    codes = [item["workspace_code"] for item in payload["workspaces"]]
    assert "planning_intel" in codes


def test_scheduler_status_heartbeat_stale_after_180_seconds(monkeypatch, tmp_path):
    admin, session_factory = make_client(monkeypatch, tmp_path)
    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    with session_factory() as session:
        session.add(
            SchedulerHeartbeat(
                scheduler_instance="standalone:scheduler:1",
                job_kind="daily_pipeline",
                workspace_code="",
                last_tick_at=utc_now(),
            ),
        )
        session.commit()

    fresh = admin.get("/api/pipeline/scheduler/status").json()
    assert fresh["heartbeat_stale"] is False
    assert fresh["heartbeat_at"] is not None

    with session_factory() as session:
        heartbeat = session.scalars(select(SchedulerHeartbeat)).one()
        heartbeat.last_tick_at = utc_now() - timedelta(seconds=400)
        session.commit()

    stale = admin.get("/api/pipeline/scheduler/status").json()
    # 停掉 scheduler >180s：必须回报离线，前端不得渲染成在线绿色。
    assert stale["heartbeat_stale"] is True


def test_scheduler_status_disabled_instance_reports_ineffective_workspaces(monkeypatch, tmp_path):
    admin, _session_factory = make_client(monkeypatch, tmp_path, INGESTION_SCHEDULER_ENABLED="false")
    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200

    patched = admin.patch(
        "/api/workspaces/planning_intel/schedule-policy",
        json={"enabled": True, "daily_time": "09:00"},
    )
    assert patched.status_code == 200

    payload = admin.get("/api/pipeline/scheduler/status").json()
    assert payload["instance_enabled"] is False
    assert payload["workspaces"], "super_admin 应看到全部 enabled 工作台"
    assert all(item["effective_enabled"] is False for item in payload["workspaces"])


def test_scheduler_status_filters_by_membership(monkeypatch, tmp_path):
    admin, session_factory = make_client(monkeypatch, tmp_path)
    login = admin.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    with session_factory() as session:
        add_workspace(session, "ws_private")

    member = _invite_member(admin, role_code="viewer", workspace_role="viewer", username="status-member")
    payload = member.get("/api/pipeline/scheduler/status").json()
    codes = [item["workspace_code"] for item in payload["workspaces"]]
    assert codes == ["planning_intel"]

    admin_payload = admin.get("/api/pipeline/scheduler/status").json()
    admin_codes = [item["workspace_code"] for item in admin_payload["workspaces"]]
    assert "ws_private" in admin_codes


def test_scheduler_status_intranet_reports_capability_off(monkeypatch, tmp_path):
    client, _session_factory = make_client(
        monkeypatch,
        tmp_path,
        DEPLOY_MODE="intranet",
        AUTH_MODE="intranet_header",
        AUTH_CSRF_ENABLED="false",
        AUTH_AUTO_PROVISION="true",
        AUTH_DEFAULT_WORKSPACE_CODES="planning_intel:viewer",
        SYNC_REMOTE_BASE_URL="https://extranet.example.com",
        SYNC_REMOTE_TOKEN="pull-token",
        INGESTION_SCHEDULER_ENABLED="true",
    )
    headers = {"X-Employee-No": "E100", "X-Employee-Name": "intranet-user"}
    response = client.get("/api/pipeline/scheduler/status", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    # intranet：capability_ingestion=false，工作台全部不生效（现有能力开关回归）。
    assert payload["capability_ingestion"] is False
    assert all(item["effective_enabled"] is False for item in payload["workspaces"])


def test_interval_jobs_dispatch_on_freshly_booted_machine(tmp_path, monkeypatch):
    """回归：time.monotonic() 零点是开机时刻。刚启动的机器（CI 虚拟机/重启后的生产主机）
    monotonic 值小于任务间隔，旧版 0.0 哨兵会让 sync pull 等 interval 任务空等一个完整
    间隔；None 哨兵语义下"从未投递过"必须首个 tick 立即投递。"""
    monkeypatch.setattr("app.workers.scheduler.time.monotonic", lambda: 5.0)
    session_factory = make_session_factory(tmp_path, "fresh_boot.sqlite")
    settings = make_settings(
        deploy_mode="intranet",
        capability_ingestion=False,
        capability_sync_consumer=True,
        sync_pull_effective=True,
        sync_remote_base_url="https://extranet.example.com",
    )
    queue = FakeQueue()
    scheduler_tick(queue, settings, SchedulerState(), now=shanghai(2026, 7, 7, 10, 0), session_factory=session_factory)

    functions = [call[0] for call in queue.calls]
    assert run_sync_pull_job in functions


# ---------------------------------------------------------------------------
# WP4-A：feedback_reaggregate 每日 job（recommendation-scoring-design §8）
# 02:00 Asia/Shanghai 触发、心跳判重不重复投递、超 missed window 不补跑、
# intranet（capability_ingestion=false）不投递。
# ---------------------------------------------------------------------------


def test_feedback_reaggregate_dispatches_once_at_daily_trigger(tmp_path):
    from app.recommendations.reaggregate import run_feedback_reaggregate_daily_job

    session_factory = make_session_factory(tmp_path, "feedback_reaggregate.sqlite")
    settings = make_settings()
    queue = FakeQueue()
    state = SchedulerState()

    # 触发点之前：只初始化节拍，不投递。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 1, 59), session_factory=session_factory)
    assert all(call[0] is not run_feedback_reaggregate_daily_job for call in queue.calls)

    # 跨过 02:00：投递恰 1 次并记心跳。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 2, 5), session_factory=session_factory)
    reaggregate_calls = [call for call in queue.calls if call[0] is run_feedback_reaggregate_daily_job]
    assert len(reaggregate_calls) == 1

    # 同触发点 tick 重放：节拍已推进到明天，不产生第 2 次投递。
    scheduler_tick(queue, settings, state, now=shanghai(2026, 7, 7, 2, 6), session_factory=session_factory)
    reaggregate_calls = [call for call in queue.calls if call[0] is run_feedback_reaggregate_daily_job]
    assert len(reaggregate_calls) == 1

    # 第二个 scheduler 实例同样跨过触发点：心跳表按触发点判重（跨实例幂等）。
    second_state = SchedulerState()
    scheduler_tick(queue, settings, second_state, now=shanghai(2026, 7, 7, 1, 58), session_factory=session_factory)
    scheduler_tick(queue, settings, second_state, now=shanghai(2026, 7, 7, 2, 10), session_factory=session_factory)
    reaggregate_calls = [call for call in queue.calls if call[0] is run_feedback_reaggregate_daily_job]
    assert len(reaggregate_calls) == 1

    with session_factory() as session:
        heartbeat = session.scalar(
            select(SchedulerHeartbeat).where(SchedulerHeartbeat.job_kind == "feedback_reaggregate"),
        )
        assert heartbeat is not None
        assert heartbeat.last_enqueued_at is not None


def test_feedback_reaggregate_respects_missed_window_and_intranet(tmp_path):
    from app.recommendations.reaggregate import run_feedback_reaggregate_daily_job

    session_factory = make_session_factory(tmp_path, "feedback_reaggregate_missed.sqlite")
    # 重启不补跑：10:00 冷启动（已过今天 02:00）只把节拍指向明天，不投递。
    queue = FakeQueue()
    state = SchedulerState()
    scheduler_tick(queue, make_settings(), state, now=shanghai(2026, 7, 7, 10, 0), session_factory=session_factory)
    assert all(call[0] is not run_feedback_reaggregate_daily_job for call in queue.calls)
    assert state.next_feedback_reaggregate_at == shanghai(2026, 7, 8, 2, 0)

    # intranet pull-only（capability_ingestion=false）：不投递。
    intranet_queue = FakeQueue()
    intranet_settings = make_settings(deploy_mode="intranet", capability_ingestion=False)
    scheduler_tick(
        intranet_queue,
        intranet_settings,
        SchedulerState(),
        now=shanghai(2026, 7, 7, 2, 5),
        session_factory=session_factory,
    )
    assert all(call[0] is not run_feedback_reaggregate_daily_job for call in intranet_queue.calls)
