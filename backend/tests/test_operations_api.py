import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.auth.passwords import hash_password
from app.auth.service import write_audit
from app.main import create_app
from app.models import (
    DailyReport,
    DailyReportItem,
    DataSource,
    EntityMilestone,
    GeneratedNews,
    HistoricalFeedbackItem,
    HistoricalJobRun,
    HistoricalReport,
    NewsItem,
    RawItem,
    Insight,
    Requirement,
    RequirementSourceLink,
    StrategicImplication,
    SyncConflict,
    SyncCursor,
    SyncInbox,
    SyncOutbox,
    SyncRun,
    TopicTask,
    TrackedEntity,
    WeeklyReport,
    WeeklyReportItem,
)
from app.models.identity import Role, User
from app.models.feedback import AuditLog, EditorialAction
from app.models.workspace import Workspace, WorkspaceMembership
from tests.test_auth import make_client


def test_operations_pages_have_real_crud_and_lists(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    requirement = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "跟踪 Agent 工程能力变化",
            "description": "整理日报中可转化为内部工具能力的信号。",
            "priority": "high",
        },
    )
    assert requirement.status_code == 200
    requirement_id = requirement.json()["id"]

    patched = client.patch(f"/api/requirements/{requirement_id}", json={"status": "done"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"

    listed_requirements = client.get("/api/requirements", params={"workspace_code": "planning_intel"})
    assert listed_requirements.status_code == 200
    assert listed_requirements.json()[0]["id"] == requirement_id

    task = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "requirement_id": requirement_id,
            "title": "补充一周 Agent 案例",
        },
    )
    assert task.status_code == 200
    assert task.json()["requirement_id"] == requirement_id

    sync_run = client.post("/api/sync-runs", json={})
    assert sync_run.status_code == 200
    assert sync_run.json()["package_id"].startswith("sync_")

    audit_logs = client.get("/api/audit-logs")
    assert audit_logs.status_code == 200
    actions = {item["action"] for item in audit_logs.json()}
    assert "requirement.create" in actions
    assert "topic_task.create" in actions
    assert "sync_package.export" in actions


def test_audit_logs_are_workspace_scoped_for_workspace_admin(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    workspace_admin = _create_local_user(engine, "audit-workspace-admin", "password-123", workspace_role="admin")
    viewer = _create_local_user(engine, "audit-workspace-viewer", "password-123", workspace_role="viewer")

    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add_all(
            [
                AuditLog(
                    workspace_code="planning_intel",
                    action="daily_report.publish",
                    object_type="daily_report",
                    object_id="planning-report",
                    detail_json={"workspace_code": "planning_intel"},
                ),
                AuditLog(
                    workspace_code="ai_tools",
                    action="daily_report.publish",
                    object_type="daily_report",
                    object_id="ai-tools-report",
                    detail_json={"workspace_code": "ai_tools"},
                ),
            ],
        )
        session.commit()

    admin_client = TestClient(create_app())
    assert admin_client.post(
        "/api/auth/login",
        json={"username": workspace_admin.username, "password": "password-123"},
    ).status_code == 200
    scoped = admin_client.get("/api/audit-logs", params={"workspace_code": "planning_intel"})
    assert scoped.status_code == 200
    assert {row["workspace_code"] for row in scoped.json()} == {"planning_intel"}
    assert {row["object_id"] for row in scoped.json()} == {"planning-report"}
    assert admin_client.get("/api/audit-logs").status_code == 403
    assert admin_client.get("/api/audit-logs", params={"workspace_code": "ai_tools"}).status_code == 403

    viewer_client = TestClient(create_app())
    assert viewer_client.post(
        "/api/auth/login",
        json={"username": viewer.username, "password": "password-123"},
    ).status_code == 200
    assert viewer_client.get("/api/audit-logs", params={"workspace_code": "planning_intel"}).status_code == 403

    global_rows = client.get("/api/audit-logs", params={"action": "daily_report.publish"})
    assert global_rows.status_code == 200
    assert {row["workspace_code"] for row in global_rows.json()} == {"planning_intel", "ai_tools"}


def test_audit_details_redact_secret_like_values(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        write_audit(
            session,
            None,
            "security.redaction.test",
            "sync_package",
            "secret-audit-1",
            {
                "workspace_code": "planning_intel",
                "access_token": "token-value",
                "nested": {
                    "client_secret": "client-secret-value",
                    "safe_value": "kept",
                },
                "items": [{"cookie": "cookie-value"}],
            },
        )
        session.commit()

    with Session() as session:
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "security.redaction.test"))
        assert audit is not None
        assert audit.workspace_code == "planning_intel"
        assert audit.detail_json["access_token"] == "[REDACTED]"
        assert audit.detail_json["nested"]["client_secret"] == "[REDACTED]"
        assert audit.detail_json["nested"]["safe_value"] == "kept"
        assert audit.detail_json["items"][0]["cookie"] == "[REDACTED]"


def test_insights_and_implications_have_independent_management_api(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    member = _create_local_user(engine, "insight-member", "password-123", workspace_role="member")
    viewer = _create_local_user(engine, "insight-viewer", "password-123", workspace_role="viewer")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="Strategy Source",
            url="https://example.com/feed",
        )
        raw = RawItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name="Strategy Source",
            entry_key="strategy-1",
            source_title="Agent runtime gains memory layer",
            source_url="https://example.com/agent-memory",
            raw_content="raw signal",
            fetched_at=datetime(2026, 7, 5, 8, tzinfo=timezone.utc),
        )
        news = NewsItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            raw_item=raw,
            data_source=source,
            source_type="rss",
            source_name="Strategy Source",
            source_url=raw.source_url,
            source_title=raw.source_title,
            normalized_title="Agent runtime gains memory layer",
            summary="Memory becomes product capability.",
            content="content",
            dedupe_key="strategy-1",
        )
        session.add_all([source, raw, news])
        session.commit()
        news_id = news.id
        raw_id = raw.id

    member_client = TestClient(create_app())
    assert member_client.post(
        "/api/auth/login",
        json={"username": "insight-member", "password": "password-123"},
    ).status_code == 200
    created = member_client.post(
        "/api/insights",
        json={
            "workspace_code": "planning_intel",
            "news_item_id": news_id,
            "title": "Agent 记忆层进入产品化",
            "summary": "需要判断内部工具链是否要引入记忆层。",
            "insight_type": "trend",
            "confidence_score": 0.82,
        },
    )
    assert created.status_code == 200
    insight_payload = created.json()
    insight_id = insight_payload["id"]
    assert insight_payload["raw_item_id"] == raw_id
    assert insight_payload["source_title"] == "Agent runtime gains memory layer"
    assert insight_payload["source_url"] == "https://example.com/agent-memory"
    assert insight_payload["data_source_name"] == "Strategy Source"

    patched = member_client.patch(
        f"/api/insights/{insight_id}",
        json={"status": "confirmed", "summary": "已确认需要持续跟踪。"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "confirmed"

    implication = member_client.post(
        "/api/strategic-implications",
        json={
            "insight_id": insight_id,
            "title": "内部工具链需要记忆能力评估",
            "description": "影响 Agent 编排、权限和长期上下文设计。",
            "implication_type": "opportunity",
        },
    )
    assert implication.status_code == 200
    implication_id = implication.json()["id"]
    assert implication.json()["insight_title"] == "Agent 记忆层进入产品化"

    listed = member_client.get("/api/insights", params={"workspace_code": "planning_intel"})
    assert listed.status_code == 200
    assert listed.json()[0]["implication_count"] == 1

    updated_implication = member_client.patch(
        f"/api/strategic-implications/{implication_id}",
        json={"implication_type": "risk"},
    )
    assert updated_implication.status_code == 200
    assert updated_implication.json()["implication_type"] == "risk"

    viewer_client = TestClient(create_app())
    assert viewer_client.post(
        "/api/auth/login",
        json={"username": "insight-viewer", "password": "password-123"},
    ).status_code == 200
    assert viewer_client.get("/api/insights", params={"workspace_code": "planning_intel"}).status_code == 200
    denied = viewer_client.patch(f"/api/insights/{insight_id}", json={"status": "archived"})
    assert denied.status_code == 403

    with Session() as session:
        actions = {row.action for row in session.scalars(select(AuditLog)).all()}
        assert "insight.create" in actions
        assert "insight.update" in actions
        assert "strategic_implication.create" in actions
        assert "strategic_implication.update" in actions


def test_topic_task_assignment_creates_assignee_notification(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    assignee = _create_local_user(engine, "task-owner", "password-123", workspace_role="member")

    task = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "跟进同步冲突复盘",
            "assignee_user_id": assignee.id,
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    assignee_client = TestClient(create_app())
    assert assignee_client.post(
        "/api/auth/login",
        json={"username": "task-owner", "password": "password-123"},
    ).status_code == 200
    assert assignee_client.get("/api/notifications/unread-count").json()["unread_count"] == 1
    notifications = assignee_client.get("/api/notifications", params={"status": "all"})
    assert notifications.status_code == 200
    notification = notifications.json()[0]
    assert notification["activity_event"]["event_type"] == "task.assigned"
    assert notification["activity_event"]["target_object_type"] == "topic_task"
    assert notification["activity_event"]["target_object_id"] == task_id
    assert notification["activity_event"]["metadata_json"]["assignee_user_id"] == assignee.id


def test_topic_task_assignment_requires_workspace_member(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    outsider = _create_local_user(engine, "task-outsider", "password-123", workspace_role=None)

    response = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "不能指派给工作台外用户",
            "assignee_user_id": outsider.id,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "assignee must be an active workspace member"


def test_workspace_admin_can_assign_topic_task_and_viewer_can_only_read(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    workspace_admin = _create_local_user(engine, "workspace-admin", "password-123", workspace_role="admin")
    viewer = _create_local_user(engine, "workspace-viewer", "password-123", workspace_role="viewer")

    admin_client = TestClient(create_app())
    assert admin_client.post(
        "/api/auth/login",
        json={"username": workspace_admin.username, "password": "password-123"},
    ).status_code == 200
    task = admin_client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "工作台管理员指派任务",
            "assignee_user_id": viewer.id,
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    viewer_client = TestClient(create_app())
    assert viewer_client.post(
        "/api/auth/login",
        json={"username": viewer.username, "password": "password-123"},
    ).status_code == 200
    listed = viewer_client.get("/api/topic-tasks", params={"workspace_code": "planning_intel"})
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == task_id
    updated = viewer_client.patch(f"/api/topic-tasks/{task_id}", json={"status": "done"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"
    forbidden_reassign = viewer_client.patch(
        f"/api/topic-tasks/{task_id}",
        json={"assignee_user_id": workspace_admin.id},
    )
    assert forbidden_reassign.status_code == 403
    assert forbidden_reassign.json()["detail"] == "assignees may only update task status or blocked reason"
    forbidden = viewer_client.post(
        "/api/topic-tasks",
        json={"workspace_code": "planning_intel", "title": "viewer 不能指派"},
    )
    assert forbidden.status_code == 403
    assert viewer_client.get("/api/notifications/unread-count").json()["unread_count"] == 1


def test_topic_task_detail_exposes_requirement_source_trace_with_viewer_gate(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    viewer = _create_local_user(engine, "task-detail-viewer", "password-123", workspace_role="viewer")
    outsider = _create_local_user(engine, "task-detail-outsider", "password-123", workspace_role=None)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="Agent Detail Source",
            url="https://example.com/feed.xml",
        )
        raw = RawItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="task-detail-raw",
            source_title="Agent detail raw signal",
            source_url="https://example.com/agent-detail",
            raw_content="raw payload",
            fetched_at=datetime(2026, 7, 5, 8, tzinfo=timezone.utc),
        )
        news = NewsItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            raw_item=raw,
            data_source=source,
            source_type="rss",
            source_name=source.name,
            source_url=raw.source_url,
            source_title=raw.source_title,
            normalized_title="Agent detail task trace",
            summary="Task detail should trace back to raw.",
            dedupe_key="task-detail-trace",
        )
        generated = GeneratedNews(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            news_item=news,
            title="Agent detail task trace",
            summary="Generated summary.",
            content_json={},
            generation_status="ready",
        )
        report = DailyReport(
            workspace_code="planning_intel",
            domain_code="ai",
            day_key=datetime(2026, 7, 5, tzinfo=timezone.utc),
            title="任务详情测试日报",
            status="published",
        )
        report_item = DailyReportItem(
            daily_report=report,
            generated_news=generated,
            adoption_status=2,
            sort_order=1,
            editor_title="日报里的 Agent 任务信号",
            editor_summary="编辑摘要",
        )
        requirement = Requirement(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="outbox",
            title="评估 Agent 详情链路",
            description="需要从任务回到日报和原始信号。",
            status="accepted",
            owner_user_id=viewer.id,
        )
        session.add_all([source, raw, news, generated, report, report_item, requirement])
        session.flush()
        source_link = RequirementSourceLink(
            requirement_id=requirement.id,
            link_type="evidence",
            note="日报条目触发",
            daily_report_item_id=report_item.id,
            news_item_id=news.id,
            raw_item_id=raw.id,
        )
        task = TopicTask(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="outbox",
            requirement_id=requirement.id,
            assignee_user_id=viewer.id,
            title="补任务详情抽屉",
            description="详情里要能解释来源。",
            status="doing",
            due_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
            metadata_json={"blocked_reason": "等待产品验收口径"},
        )
        session.add_all([source_link, task])
        session.commit()
        task_id = task.id

    viewer_client = TestClient(create_app())
    assert viewer_client.post(
        "/api/auth/login",
        json={"username": viewer.username, "password": "password-123"},
    ).status_code == 200
    detail = viewer_client.get(f"/api/topic-tasks/{task_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == task_id
    assert payload["requirement_title"] == "评估 Agent 详情链路"
    assert payload["blocked_reason"] == "等待产品验收口径"
    assert payload["assignee_name"] == "Task-Detail-Viewer"
    assert payload["requirement_source_count"] == 1
    assert payload["requirement_source_links"][0]["source_object_type"] == "daily_report_item"
    assert payload["requirement_source_links"][0]["source_title"] == "日报里的 Agent 任务信号"
    assert payload["requirement_source_links"][0]["source_url"] == "https://example.com/agent-detail"
    assert payload["requirement_source_links"][0]["data_source_name"] == "Agent Detail Source"

    outsider_client = TestClient(create_app())
    assert outsider_client.post(
        "/api/auth/login",
        json={"username": outsider.username, "password": "password-123"},
    ).status_code == 200
    denied = outsider_client.get(f"/api/topic-tasks/{task_id}")
    assert denied.status_code == 403


def test_topic_task_owner_view_overdue_and_blocked_filters(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    assignee = _create_local_user(engine, "task-owner-filter", "password-123", workspace_role="member")
    other_assignee = _create_local_user(engine, "task-other-filter", "password-123", workspace_role="member")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    overdue = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "我的逾期任务",
            "assignee_user_id": assignee.id,
            "due_at": yesterday,
        },
    )
    assert overdue.status_code == 200
    overdue_id = overdue.json()["id"]
    blocked = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "我的阻塞任务",
            "assignee_user_id": assignee.id,
            "status": "blocked",
            "due_at": tomorrow,
            "metadata_json": {"blocked_reason": "等待外部接口确认"},
        },
    )
    assert blocked.status_code == 200
    blocked_id = blocked.json()["id"]
    other = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "别人的任务",
            "assignee_user_id": other_assignee.id,
            "due_at": yesterday,
        },
    )
    assert other.status_code == 200

    assignee_client = TestClient(create_app())
    assert assignee_client.post(
        "/api/auth/login",
        json={"username": assignee.username, "password": "password-123"},
    ).status_code == 200

    mine = assignee_client.get(
        "/api/topic-tasks",
        params={"workspace_code": "planning_intel", "assigned_to_me": "true"},
    )
    assert mine.status_code == 200
    assert {item["id"] for item in mine.json()} == {overdue_id, blocked_id}

    mine_by_alias = assignee_client.get(
        "/api/topic-tasks",
        params={"workspace_code": "planning_intel", "assignee": "me"},
    )
    assert mine_by_alias.status_code == 200
    assert {item["id"] for item in mine_by_alias.json()} == {overdue_id, blocked_id}
    assert all(item["assignee_user_id"] == assignee.id for item in mine_by_alias.json())

    overdue_items = assignee_client.get(
        "/api/topic-tasks",
        params={"workspace_code": "planning_intel", "assigned_to_me": "true", "due": "overdue"},
    )
    assert overdue_items.status_code == 200
    assert [item["id"] for item in overdue_items.json()] == [overdue_id]
    assert overdue_items.json()[0]["is_overdue"] is True

    blocked_items = assignee_client.get(
        "/api/topic-tasks",
        params={"workspace_code": "planning_intel", "assigned_to_me": "true", "status": "blocked"},
    )
    assert blocked_items.status_code == 200
    assert [item["id"] for item in blocked_items.json()] == [blocked_id]
    assert blocked_items.json()[0]["blocked_reason"] == "等待外部接口确认"

    updated_blocked = assignee_client.patch(
        f"/api/topic-tasks/{overdue_id}",
        json={"status": "blocked", "metadata_json": {"blocked_reason": "等待法务确认"}},
    )
    assert updated_blocked.status_code == 200
    assert updated_blocked.json()["status"] == "blocked"
    assert updated_blocked.json()["blocked_reason"] == "等待法务确认"

    forbidden = assignee_client.patch(
        f"/api/topic-tasks/{overdue_id}",
        json={"metadata_json": {"blocked_reason": "等待法务确认", "private_note": "不应允许"}},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "assignees may only update task status or blocked reason"


def test_topic_task_batch_update_status_and_blocked_reason_permissions(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    assignee = _create_local_user(engine, "task-batch-owner", "password-123", workspace_role="member")
    other_assignee = _create_local_user(engine, "task-batch-other", "password-123", workspace_role="member")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    first = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "批量处理逾期任务 A",
            "assignee_user_id": assignee.id,
            "due_at": yesterday,
        },
    )
    second = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "批量处理逾期任务 B",
            "assignee_user_id": assignee.id,
            "due_at": yesterday,
        },
    )
    third = client.post(
        "/api/topic-tasks",
        json={
            "workspace_code": "planning_intel",
            "title": "他人的任务",
            "assignee_user_id": other_assignee.id,
            "due_at": yesterday,
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    first_id = first.json()["id"]
    second_id = second.json()["id"]
    third_id = third.json()["id"]

    admin_batch = client.post(
        "/api/topic-tasks/batch",
        json={
            "workspace_code": "planning_intel",
            "task_ids": [first_id, second_id],
            "status": "blocked",
            "blocked_reason": "等待外部接口确认",
        },
    )
    assert admin_batch.status_code == 200
    assert admin_batch.json()["updated_count"] == 2
    assert {item["status"] for item in admin_batch.json()["tasks"]} == {"blocked"}
    assert {item["blocked_reason"] for item in admin_batch.json()["tasks"]} == {"等待外部接口确认"}

    assignee_client = TestClient(create_app())
    assert assignee_client.post(
        "/api/auth/login",
        json={"username": assignee.username, "password": "password-123"},
    ).status_code == 200
    own_batch = assignee_client.post(
        "/api/topic-tasks/batch",
        json={
            "workspace_code": "planning_intel",
            "task_ids": [first_id, second_id],
            "status": "done",
        },
    )
    assert own_batch.status_code == 200
    assert own_batch.json()["updated_count"] == 2
    assert {item["status"] for item in own_batch.json()["tasks"]} == {"done"}

    forbidden = assignee_client.post(
        "/api/topic-tasks/batch",
        json={
            "workspace_code": "planning_intel",
            "task_ids": [first_id, third_id],
            "status": "blocked",
            "blocked_reason": "夹带他人任务不应落库",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "assignees may only batch update their own tasks"

    missing_reason = client.post(
        "/api/topic-tasks/batch",
        json={"workspace_code": "planning_intel", "task_ids": [third_id], "status": "blocked"},
    )
    assert missing_reason.status_code == 422

    with sessionmaker(bind=engine)() as session:
        rows = {task.id: task for task in session.scalars(select(TopicTask)).all()}
        assert rows[first_id].status == "done"
        assert rows[second_id].status == "done"
        assert rows[third_id].status == "open"
        assert rows[third_id].metadata_json == {}
        audit_actions = {row.action for row in session.scalars(select(AuditLog)).all()}
        assert "topic_task.batch_update" in audit_actions


def test_requirement_status_change_notifies_owner(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    owner = _create_local_user(engine, "requirement-owner", "password-123", workspace_role="member")
    outsider = _create_local_user(engine, "requirement-outsider", "password-123", workspace_role=None)

    invalid = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "非法 owner",
            "owner_user_id": outsider.id,
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "owner must be an active workspace member"

    requirement = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "跟踪外部信号",
            "owner_user_id": owner.id,
        },
    )
    assert requirement.status_code == 200
    requirement_id = requirement.json()["id"]

    updated = client.patch(f"/api/requirements/{requirement_id}", json={"status": "done"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"

    owner_client = TestClient(create_app())
    assert owner_client.post(
        "/api/auth/login",
        json={"username": owner.username, "password": "password-123"},
    ).status_code == 200
    assert owner_client.get("/api/notifications/unread-count").json()["unread_count"] == 1
    notifications = owner_client.get("/api/notifications", params={"status": "all"})
    assert notifications.status_code == 200
    notification = notifications.json()[0]
    assert notification["activity_event"]["event_type"] == "requirement.status_changed"
    assert notification["activity_event"]["target_object_type"] == "requirement"
    assert notification["activity_event"]["target_object_id"] == requirement_id
    assert notification["activity_event"]["metadata_json"]["requirement_id"] == requirement_id
    assert notification["activity_event"]["metadata_json"]["previous_status"] == "open"
    assert notification["activity_event"]["metadata_json"]["status"] == "done"


def test_requirement_source_links_trace_daily_item_to_external_signal(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="AI 工程源",
            url="https://example.com/feed.xml",
        )
        raw = RawItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="agent-signal-001",
            source_title="Agent 编排能力外部信号",
            source_url="https://example.com/agent-signal",
            raw_content="raw payload",
            fetched_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            raw_payload_json={"title": "Agent 编排能力外部信号"},
        )
        news = NewsItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            raw_item=raw,
            data_source=source,
            source_type="rss",
            source_name=source.name,
            source_url=raw.source_url,
            canonical_url=raw.source_url,
            source_title=raw.source_title,
            normalized_title="Agent 编排能力外部信号",
            summary="外部信号摘要",
            content="外部信号正文",
            published_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            dedupe_key="agent-signal-001",
        )
        generated = GeneratedNews(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            news_item=news,
            category="基础竞争力",
            title="Agent 编排能力进入工程化阶段",
            summary="生成稿摘要",
            source_url=raw.source_url,
            generation_status="ready",
            generated_by="minimax",
        )
        daily_report = DailyReport(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            day_key="2026-07-05",
            title="2026-07-05 日报",
            status="published",
        )
        daily_item = DailyReportItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            daily_report=daily_report,
            generated_news=generated,
            adoption_status=2,
            sort_order=1,
        )
        session.add_all([source, raw, news, generated, daily_report, daily_item])
        session.commit()
        daily_item_id = daily_item.id
        news_item_id = news.id
        raw_item_id = raw.id

    created = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "评估 Agent 编排能力建设",
            "description": "需要把外部信号转成内部建设需求。",
            "source_daily_report_item_id": daily_item_id,
            "source_note": "日报采信项触发",
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    requirement_id = created_payload["id"]
    assert created_payload["source_count"] == 1
    assert created_payload["source_links"][0]["daily_report_item_id"] == daily_item_id
    assert created_payload["source_links"][0]["news_item_id"] == news_item_id
    assert created_payload["source_links"][0]["raw_item_id"] == raw_item_id
    assert created_payload["source_links"][0]["source_object_type"] == "daily_report_item"
    assert created_payload["source_links"][0]["source_title"] == "Agent 编排能力进入工程化阶段"
    assert created_payload["source_links"][0]["source_url"] == "https://example.com/agent-signal"
    assert created_payload["source_links"][0]["data_source_name"] == "AI 工程源"

    linked = client.post(
        f"/api/requirements/{requirement_id}/source-links",
        json={"raw_item_id": raw_item_id, "note": "补充原始 payload 追溯"},
    )
    assert linked.status_code == 200
    assert linked.json()["source_count"] == 2

    listed = client.get("/api/requirements", params={"workspace_code": "planning_intel"})
    assert listed.status_code == 200
    source_links = listed.json()[0]["source_links"]
    assert {item["source_object_type"] for item in source_links} == {"daily_report_item", "raw_item"}
    assert any(item["note"] == "补充原始 payload 追溯" for item in source_links)
    with Session() as session:
        rows = session.scalars(select(RequirementSourceLink)).all()
        assert len(rows) == 2


def test_requirement_source_links_trace_historical_report(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        report = HistoricalReport(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="outbox",
            legacy_system="tech_insight_loop",
            legacy_table="reports",
            legacy_id="history-501",
            report_type="daily",
            title="技术洞察日报 2026-05-01",
            status="published_imported",
            period_start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            content="旧日报正文里的 Agent 线索。",
            source_refs_json={"resolved": [], "unresolved": []},
            metadata_json={},
        )
        session.add(report)
        session.commit()
        report_id = report.id

    created = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "复盘历史日报 Agent 线索",
            "description": "从历史报告沉淀内部需求。",
            "source_historical_report_id": report_id,
            "source_note": "历史报告触发",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["source_count"] == 1
    link = payload["source_links"][0]
    assert link["historical_report_id"] == report_id
    assert link["source_object_type"] == "historical_report"
    assert link["source_title"] == "技术洞察日报 2026-05-01"
    assert link["source_url"] is None
    assert link["data_source_name"] is None

    listed = client.get("/api/requirements", params={"workspace_code": "planning_intel"})
    assert listed.status_code == 200
    assert listed.json()[0]["source_links"][0]["historical_report_id"] == report_id


def test_requirement_source_links_trace_historical_feedback(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="历史质量源",
            url="https://example.com/feed.xml",
        )
        raw = RawItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="legacy-quality-raw",
            source_title="旧系统低质信号",
            source_url="https://example.com/legacy-quality",
            raw_content="legacy raw payload",
            fetched_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
            published_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
            raw_payload_json={"title": "旧系统低质信号"},
        )
        feedback = HistoricalFeedbackItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="outbox",
            legacy_system="tech_insight_loop",
            legacy_table="article_quality_feedback",
            legacy_id="feedback-501",
            legacy_article_id="article-501",
            raw_item=raw,
            feedback_kind="quality_feedback",
            user_name="规划用户",
            feedback_type="source-quality",
            reason="来源质量偏低",
            comment="需要复盘信息源治理策略",
            feedback_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
            metadata_json={},
        )
        session.add_all([source, raw, feedback])
        session.commit()
        feedback_id = feedback.id
        raw_id = raw.id

    created = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "复盘旧质量反馈",
            "description": "从旧质量反馈沉淀信息源治理需求。",
            "source_historical_feedback_item_id": feedback_id,
            "source_note": "历史质量反馈触发",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    link = payload["source_links"][0]
    assert link["historical_feedback_item_id"] == feedback_id
    assert link["raw_item_id"] == raw_id
    assert link["source_object_type"] == "historical_feedback"
    assert link["source_title"] == "历史质量反馈：来源质量偏低"
    assert link["source_url"] == "https://example.com/legacy-quality"
    assert link["data_source_name"] == "历史质量源"


def test_requirement_conclusion_writes_recommendation_feedback(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="反馈源",
            url="https://example.com/feed.xml",
        )
        raw = RawItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="requirement-feedback-001",
            source_title="Agent 记忆评估外部信号",
            source_url="https://example.com/agent-memory-feedback",
            raw_content="raw payload",
            fetched_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
        )
        news = NewsItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            raw_item=raw,
            data_source=source,
            source_type="rss",
            source_name=source.name,
            source_url=raw.source_url,
            canonical_url=raw.source_url,
            source_title=raw.source_title,
            normalized_title="Agent 记忆评估外部信号",
            summary="外部信号摘要",
            content="外部信号正文",
            published_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            dedupe_key="requirement-feedback-001",
        )
        session.add_all([source, raw, news])
        session.commit()
        news_item_id = news.id

    created = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "评估 Agent 记忆能力建设",
            "source_news_item_id": news_item_id,
        },
    )
    assert created.status_code == 200
    requirement_id = created.json()["id"]

    patched = client.patch(
        f"/api/requirements/{requirement_id}",
        json={
            "status": "resolved",
            "metadata_json": {
                "recommendation_feedback": {
                    "outcome": "positive",
                    "reason": "已形成内部建设建议",
                },
            },
        },
    )
    assert patched.status_code == 200
    assert patched.json()["metadata_json"]["recommendation_feedback"]["outcome"] == "positive"

    repeated = client.patch(f"/api/requirements/{requirement_id}", json={"status": "resolved"})
    assert repeated.status_code == 200

    with Session() as session:
        actions = session.scalars(
            select(EditorialAction).where(
                EditorialAction.object_type == "news_item",
                EditorialAction.object_id == news_item_id,
                EditorialAction.action_type == "requirement.feedback_to_recommendation",
            ),
        ).all()
        assert len(actions) == 1
        assert actions[0].after_json["requirement_id"] == requirement_id
        assert actions[0].after_json["outcome"] == "positive"
        assert actions[0].after_json["score_delta"] == 80.0
        assert actions[0].reason == "已形成内部建设建议"
        audit_actions = {row.action for row in session.scalars(select(AuditLog)).all()}
        assert "requirement.feedback_to_recommendation" in audit_actions


def test_report_items_create_strategy_loop_with_requirement_and_task_trace(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="Agent 源",
            url="https://example.com/feed.xml",
        )
        raw = RawItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="strategy-loop-001",
            source_title="Agent 记忆能力升级",
            source_url="https://example.com/agent-memory",
            raw_content="raw payload",
            fetched_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            raw_payload_json={"title": "Agent 记忆能力升级"},
        )
        news = NewsItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            raw_item=raw,
            data_source=source,
            source_type="rss",
            source_name=source.name,
            source_url=raw.source_url,
            canonical_url=raw.source_url,
            source_title=raw.source_title,
            normalized_title="Agent 记忆能力升级",
            summary="外部信号摘要",
            content="外部信号正文",
            published_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            dedupe_key="strategy-loop-001",
        )
        generated = GeneratedNews(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            news_item=news,
            category="智能体",
            title="Agent 记忆能力升级",
            summary="Agent 长期记忆能力正在产品化。",
            source_url=raw.source_url,
            generation_status="ready",
            generated_by="minimax",
        )
        daily_report = DailyReport(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            day_key="2026-07-05",
            title="2026-07-05 日报",
            status="published",
        )
        daily_item = DailyReportItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            daily_report=daily_report,
            generated_news=generated,
            adoption_status=2,
            sort_order=1,
        )
        weekly_report = WeeklyReport(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            week_key="2026-W27",
            title="2026-W27 周报",
            status="draft",
        )
        weekly_item = WeeklyReportItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            weekly_report=weekly_report,
            daily_report_item=daily_item,
            generated_news=generated,
            adoption_status=2,
            sort_order=1,
        )
        session.add_all([source, raw, news, generated, daily_report, daily_item, weekly_report, weekly_item])
        session.commit()
        daily_item_id = daily_item.id
        weekly_item_id = weekly_item.id
        raw_item_id = raw.id
        news_item_id = news.id

    created = client.post(
        f"/api/daily-report-items/{daily_item_id}/insights",
        json={
            "insight_title": "Agent 记忆变成产品能力",
            "implication_title": "内部工具链需要评估记忆层",
            "requirement_title": "评估 Agent 记忆能力建设",
            "requirement_description": "形成内部能力建设建议。",
            "source_note": "日报条目触发",
            "create_task": True,
            "task_title": "调研 Agent 记忆方案",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["insight"]["source_report_type"] == "daily"
    assert payload["insight"]["source_report_item_id"] == daily_item_id
    assert payload["insight"]["raw_item_id"] == raw_item_id
    assert payload["implication"]["insight_id"] == payload["insight"]["id"]
    assert payload["requirement"]["title"] == "评估 Agent 记忆能力建设"
    assert payload["requirement"]["source_links"][0]["daily_report_item_id"] == daily_item_id
    assert payload["requirement"]["source_links"][0]["news_item_id"] == news_item_id
    assert payload["requirement"]["source_links"][0]["raw_item_id"] == raw_item_id
    assert payload["task"]["requirement_id"] == payload["requirement"]["id"]
    assert payload["task"]["requirement_source_count"] == 1
    assert payload["task"]["requirement_source_links"][0]["source_object_type"] == "daily_report_item"

    weekly_created = client.post(
        f"/api/weekly-report-items/{weekly_item_id}/insights",
        json={
            "requirement_title": "周报复盘 Agent 记忆趋势",
            "source_note": "周报条目触发",
        },
    )
    assert weekly_created.status_code == 200
    weekly_payload = weekly_created.json()
    assert weekly_payload["insight"]["source_report_type"] == "weekly"
    assert weekly_payload["insight"]["source_report_item_id"] == weekly_item_id
    assert weekly_payload["requirement"]["source_links"][0]["weekly_report_item_id"] == weekly_item_id
    assert weekly_payload["requirement"]["source_links"][0]["daily_report_item_id"] == daily_item_id

    tasks = client.get("/api/topic-tasks", params={"workspace_code": "planning_intel"})
    assert tasks.status_code == 200
    assert tasks.json()[0]["title"] == "调研 Agent 记忆方案"
    assert tasks.json()[0]["requirement_source_links"][0]["raw_item_id"] == raw_item_id
    with Session() as session:
        assert session.query(Insight).count() == 2
        assert session.query(StrategicImplication).count() == 2
        assert session.query(Requirement).count() == 2
        assert session.query(RequirementSourceLink).count() == 2
        assert session.query(TopicTask).count() == 1


def test_report_items_create_entity_milestones_with_source_trace(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="Agent 源",
            url="https://example.com/feed.xml",
        )
        raw = RawItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            data_source=source,
            source_type="rss",
            source_name=source.name,
            entry_key="entity-milestone-001",
            source_title="OpenAI 推出企业 Agent 能力",
            source_url="https://example.com/openai-agent",
            raw_content="raw payload",
            fetched_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
            published_at=datetime(2026, 7, 5, 9, tzinfo=timezone.utc),
            raw_payload_json={"title": "OpenAI 推出企业 Agent 能力"},
        )
        news = NewsItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            raw_item=raw,
            data_source=source,
            source_type="rss",
            source_name=source.name,
            source_url=raw.source_url,
            canonical_url=raw.source_url,
            source_title=raw.source_title,
            normalized_title="OpenAI 推出企业 Agent 能力",
            summary="OpenAI 面向企业增强 Agent 能力。",
            content="外部信号正文",
            published_at=datetime(2026, 7, 5, 10, tzinfo=timezone.utc),
            dedupe_key="entity-milestone-001",
        )
        generated = GeneratedNews(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            news_item=news,
            category="智能体",
            title="OpenAI 推出企业 Agent 能力",
            summary="企业 Agent 能力进入产品化阶段。",
            source_url=raw.source_url,
            generation_status="ready",
            generated_by="minimax",
            insight_json={"board": "AI 应用"},
        )
        daily_report = DailyReport(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            day_key="2026-07-05",
            title="2026-07-05 日报",
            status="published",
        )
        daily_item = DailyReportItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            daily_report=daily_report,
            generated_news=generated,
            adoption_status=2,
            sort_order=1,
        )
        weekly_report = WeeklyReport(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            week_key="2026-W27",
            title="2026-W27 周报",
            status="draft",
        )
        weekly_item = WeeklyReportItem(
            workspace_code="planning_intel",
            domain_code="ai",
            visibility_scope="workspace",
            sync_policy="public_to_intranet",
            weekly_report=weekly_report,
            daily_report_item=daily_item,
            generated_news=generated,
            adoption_status=2,
            sort_order=1,
        )
        session.add_all([source, raw, news, generated, daily_report, daily_item, weekly_report, weekly_item])
        session.commit()
        daily_item_id = daily_item.id
        weekly_item_id = weekly_item.id
        raw_item_id = raw.id
        news_item_id = news.id

    created = client.post(
        f"/api/daily-report-items/{daily_item_id}/entity-milestones",
        json={
            "entity_name": "OpenAI",
            "entity_type": "company",
            "event_title": "OpenAI 企业 Agent 产品化",
            "event_brief": "OpenAI 面向企业增强 Agent 能力。",
            "source_note": "日报条目登记",
        },
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["legacy_system"] == "current"
    assert created_payload["entity_name"] == "OpenAI"
    assert created_payload["raw_item_id"] == raw_item_id
    assert created_payload["event_time"].startswith("2026-07-05T10:00:00")
    assert created_payload["board"] == "AI 应用"
    assert created_payload["metadata_json"]["current_refs"]["daily_report_item_id"] == daily_item_id
    assert created_payload["metadata_json"]["current_refs"]["news_item_id"] == news_item_id

    patched = client.patch(
        f"/api/entity-milestones/{created_payload['id']}",
        json={
            "event_title": "OpenAI 企业 Agent 进入人工确认",
            "event_brief": "人工确认后的实体事件摘要。",
            "curation_status": "confirmed",
            "curation_note": "确认进入时间线",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "OpenAI 企业 Agent 进入人工确认"
    assert patched.json()["curation_status"] == "confirmed"
    assert patched.json()["selected_for_timeline"] is True

    requirement = client.post(
        "/api/requirements",
        json={
            "workspace_code": "planning_intel",
            "title": "跟进 OpenAI 企业 Agent",
            "description": "由实体事件触发后续跟踪。",
            "source_entity_milestone_id": created_payload["id"],
            "source_note": "实体事件触发",
        },
    )
    assert requirement.status_code == 200
    requirement_link = requirement.json()["source_links"][0]
    assert requirement_link["entity_milestone_id"] == created_payload["id"]
    assert requirement_link["source_object_type"] == "entity_milestone"
    assert requirement_link["source_title"] == "OpenAI 企业 Agent 进入人工确认"
    assert requirement_link["source_url"] == "https://example.com/openai-agent"

    updated = client.post(
        f"/api/daily-report-items/{daily_item_id}/entity-milestones",
        json={
            "entity_name": "OpenAI",
            "event_title": "OpenAI 企业 Agent 进入产品验证",
            "event_brief": "同一日报条目更新实体事件描述。",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == created_payload["id"]
    assert updated.json()["title"] == "OpenAI 企业 Agent 进入产品验证"

    weekly_created = client.post(
        f"/api/weekly-report-items/{weekly_item_id}/entity-milestones",
        json={
            "entity_name": "OpenAI",
            "event_title": "周报复盘 OpenAI 企业 Agent",
            "source_note": "周报条目登记",
        },
    )
    assert weekly_created.status_code == 200
    weekly_payload = weekly_created.json()
    assert weekly_payload["id"] != created_payload["id"]
    assert weekly_payload["tracked_entity_id"] == created_payload["tracked_entity_id"]
    assert weekly_payload["metadata_json"]["current_refs"]["weekly_report_item_id"] == weekly_item_id
    assert weekly_payload["metadata_json"]["current_refs"]["daily_report_item_id"] == daily_item_id

    with Session() as session:
        assert session.query(TrackedEntity).filter(TrackedEntity.legacy_system == "current").count() == 1
        assert session.query(EntityMilestone).filter(EntityMilestone.legacy_system == "current").count() == 2
        audit_actions = {row.action for row in session.scalars(select(AuditLog)).all()}
        assert "daily_report_item.entity_milestone.create" in audit_actions
        assert "daily_report_item.entity_milestone.update" in audit_actions
        assert "weekly_report_item.entity_milestone.create" in audit_actions
        assert "entity_milestone.update" in audit_actions


def test_sync_package_export_download_and_import_are_auditable(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            SyncOutbox(
                workspace_code="planning_intel",
                domain_code="ai",
                visibility_scope="public",
                sync_policy="public_to_intranet",
                event_id="evt-sync-001",
                object_type="news_items",
                object_id="news-001",
                operation="upsert",
                payload_json={"global_id": "global-news-001", "revision": 2, "title": "同步新闻"},
                payload_hash="",
                status="pending",
            ),
        )
        session.add(
            SyncOutbox(
                workspace_code="planning_intel",
                domain_code="ai",
                visibility_scope="public",
                sync_policy="public_to_intranet",
                event_id="evt-sync-secret-001",
                object_type="data_sources",
                object_id="source-secret-001",
                operation="upsert",
                payload_json={
                    "global_id": "global-source-secret-001",
                    "revision": 1,
                    "name": "不应导出的密钥源",
                    "api_token": "secret-token-value",
                },
                payload_hash="",
                status="pending",
            ),
        )
        session.commit()

    exported = client.post(
        "/api/sync/packages/export",
        json={"source_instance_id": "public", "target_instance_id": "intranet", "limit": 10},
    )
    assert exported.status_code == 200
    export_payload = exported.json()
    package_id = export_payload["package_manifest"]["package_id"]
    assert export_payload["package_manifest"]["record_count"] == 1
    assert export_payload["package_manifest"]["safety"]["secret_blocked_count"] == 1
    assert export_payload["records"][0]["event_id"] == "evt-sync-001"
    assert export_payload["records"][0]["object_global_id"] == "global-news-001"
    assert export_payload["sync_run"]["counts_json"]["exported"] == 1
    assert export_payload["sync_run"]["counts_json"]["secret_blocked"] == 1
    assert export_payload["sync_run"]["counts_json"]["secret_blocked_event_ids"] == ["evt-sync-secret-001"]
    assert "secret-token-value" not in json.dumps(export_payload, ensure_ascii=False)
    with Session() as session:
        blocked = session.scalar(select(SyncOutbox).where(SyncOutbox.event_id == "evt-sync-secret-001"))
        assert blocked is not None
        assert blocked.status == "failed"

    downloaded = client.get(f"/api/sync/packages/{package_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        records = [
            json.loads(line)
            for line in archive.read("records.jsonl").decode("utf-8").splitlines()
            if line.strip()
        ]
    assert manifest["package_id"] == package_id
    assert records[0]["event_id"] == "evt-sync-001"

    imported = client.post(
        "/api/sync/packages/import",
        json={
            "package_manifest": {
                **manifest,
                "package_id": "external-package-001",
                "source_instance_id": "public-other",
                "records_sha256": "",
            },
            "records": [
                {
                    "event_id": "evt-sync-import-001",
                    "object_type": "data_sources",
                    "object_id": "remote-source-001",
                    "object_global_id": "global-source-import-001",
                    "operation": "upsert",
                    "revision": 2,
                    "content_hash": "hash-source-v2",
                    "visibility_scope": "public",
                    "sync_policy": "public_to_intranet",
                    "workspace_code": "shared",
                    "domain_code": "ai",
                    "payload": {
                        "global_id": "global-source-import-001",
                        "workspace_code": "shared",
                        "domain_code": "ai",
                        "visibility_scope": "public",
                        "sync_policy": "public_to_intranet",
                        "source_type": "rss",
                        "name": "同步源",
                        "url": "https://example.com/feed.xml",
                        "enabled": True,
                        "default_focus_id": 1,
                        "backfill_days": 7,
                        "metadata_json": {"origin": "sync"},
                    },
                },
            ],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["applied"] == 1
    assert imported.json()["conflicts"] == 0
    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "global-source-import-001"))
        assert source is not None
        assert source.name == "同步源"
        assert source.url == "https://example.com/feed.xml"
        inbox = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-sync-import-001"))
        assert inbox is not None
        assert inbox.status == "applied"

    repeated = client.post(
        "/api/sync/packages/import",
        json={
            "package_manifest": {
                **manifest,
                "package_id": "external-package-001",
                "source_instance_id": "public-other",
                "records_sha256": "",
            },
            "records": [
                {
                    "event_id": "evt-sync-import-001",
                    "object_type": "data_sources",
                    "object_id": "remote-source-001",
                    "object_global_id": "global-source-import-001",
                    "operation": "upsert",
                    "revision": 2,
                    "content_hash": "hash-source-v2",
                    "visibility_scope": "public",
                    "sync_policy": "public_to_intranet",
                    "workspace_code": "shared",
                    "domain_code": "ai",
                    "payload": {
                        "global_id": "global-source-import-001",
                        "source_type": "rss",
                        "name": "同步源",
                    },
                },
            ],
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["skipped"] == 1

    conflict = client.post(
        "/api/sync/packages/import",
        json={
            "package_manifest": {
                **manifest,
                "package_id": "external-package-002",
                "source_instance_id": "public-other",
                "records_sha256": "",
            },
            "records": [
                {
                    "event_id": "evt-sync-conflict-001",
                    "object_type": "data_sources",
                    "object_id": "remote-source-001",
                    "object_global_id": "global-source-import-001",
                    "operation": "upsert",
                    "revision": 2,
                    "content_hash": "hash-source-v2-conflicting",
                    "visibility_scope": "public",
                    "sync_policy": "public_to_intranet",
                    "workspace_code": "shared",
                    "domain_code": "ai",
                    "payload": {
                        "global_id": "global-source-import-001",
                        "source_type": "rss",
                        "name": "冲突源",
                        "url": "https://example.com/other.xml",
                    },
                },
            ],
        },
    )
    assert conflict.status_code == 200
    assert conflict.json()["status"] == "completed_with_conflicts"
    assert conflict.json()["conflicts"] == 1
    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "global-source-import-001"))
        assert source is not None
        assert source.name == "同步源"
        conflict_row = session.scalar(
            select(SyncConflict).where(SyncConflict.object_id == "global-source-import-001"),
        )
        assert conflict_row is not None
        assert conflict_row.status == "open"
        conflict_id = conflict_row.id

    listed_conflicts = client.get("/api/sync/conflicts", params={"status": "open"})
    assert listed_conflicts.status_code == 200
    conflict_payload = listed_conflicts.json()
    assert [item["id"] for item in conflict_payload] == [conflict_id]
    assert conflict_payload[0]["object_type"] == "data_sources"
    assert conflict_payload[0]["object_id"] == "global-source-import-001"
    assert conflict_payload[0]["conflict_reason"] == "same revision has different content hash"
    assert conflict_payload[0]["package_id"].startswith("external-package-002_import_")

    notifications = client.get("/api/notifications", params={"status": "unread"})
    assert notifications.status_code == 200
    sync_notifications = [
        item
        for item in notifications.json()
        if item["activity_event"]["event_type"] == "sync_conflict.created"
    ]
    assert len(sync_notifications) == 1
    assert sync_notifications[0]["priority"] == "important"
    assert sync_notifications[0]["activity_event"]["object_type"] == "sync_conflict"
    assert sync_notifications[0]["activity_event"]["target_object_type"] == "data_sources"
    assert sync_notifications[0]["activity_event"]["target_object_id"] == "global-source-import-001"

    resolved = client.post(
        f"/api/sync/conflicts/{conflict_id}/resolve",
        json={"strategy": "keep_local", "reason": "保留内网已确认版本"},
    )
    assert resolved.status_code == 200
    resolved_payload = resolved.json()
    assert resolved_payload["status"] == "resolved"
    assert resolved_payload["resolved_by_name"] == "规划部管理员"
    assert resolved_payload["resolved_at"]
    assert resolved_payload["resolution_json"]["strategy"] == "keep_local"
    assert resolved_payload["resolution_json"]["reason"] == "保留内网已确认版本"

    open_after_resolve = client.get("/api/sync/conflicts", params={"status": "open"})
    assert open_after_resolve.status_code == 200
    assert open_after_resolve.json() == []


def test_sync_conflict_use_incoming_and_manual_merge_apply_object_handlers(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            global_id="global-source-resolution-001",
            origin_instance_id="local",
            workspace_code="shared",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="rss",
            name="本地源",
            url="https://example.com/local.xml",
            revision=2,
            content_hash="local-hash-v2",
        )
        run = SyncRun(
            package_id="resolution-package",
            source_instance_id="extranet",
            target_instance_id="intranet",
            direction="import",
            status="completed_with_conflicts",
            counts_json={"conflicts": 2},
        )
        session.add_all([source, run])
        session.flush()
        use_incoming = SyncConflict(
            sync_run_id=run.id,
            object_type="data_sources",
            object_id=source.global_id,
            local_revision=2,
            incoming_revision=3,
            field_name="record",
            local_value_json={"global_id": source.global_id, "name": "本地源", "url": source.url},
            incoming_value_json={
                "global_id": source.global_id,
                "origin_instance_id": "extranet",
                "workspace_code": "shared",
                "domain_code": "ai",
                "visibility_scope": "public",
                "sync_policy": "public_to_intranet",
                "source_type": "rss",
                "name": "外网源",
                "url": "https://example.com/incoming.xml",
                "enabled": True,
            },
            conflict_reason="incoming revision is newer but requires review",
            status="open",
            resolution_json={"reason": "test"},
        )
        manual_merge = SyncConflict(
            sync_run_id=run.id,
            object_type="data_sources",
            object_id=source.global_id,
            local_revision=3,
            incoming_revision=3,
            field_name="record",
            local_value_json={"global_id": source.global_id, "name": "外网源"},
            incoming_value_json={
                "global_id": source.global_id,
                "origin_instance_id": "extranet",
                "workspace_code": "shared",
                "domain_code": "ai",
                "visibility_scope": "public",
                "sync_policy": "public_to_intranet",
                "source_type": "rss",
                "name": "待合并源",
                "url": "https://example.com/remote.xml",
                "enabled": True,
            },
            conflict_reason="same revision has different content hash",
            status="open",
            resolution_json={"reason": "test"},
        )
        session.add_all([use_incoming, manual_merge])
        session.commit()
        use_incoming_id = use_incoming.id
        manual_merge_id = manual_merge.id

    accepted = client.post(
        f"/api/sync/conflicts/{use_incoming_id}/resolve",
        json={"strategy": "use_incoming", "reason": "接受外网 owner 版本"},
    )
    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["status"] == "use_incoming"
    assert accepted_payload["resolution_json"]["apply_result"]["apply_status"] == "applied"
    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "global-source-resolution-001"))
        assert source is not None
        assert source.name == "外网源"
        assert source.url == "https://example.com/incoming.xml"
        assert source.revision == 3

    merged = client.post(
        f"/api/sync/conflicts/{manual_merge_id}/resolve",
        json={
            "strategy": "manual_merge",
            "reason": "保留外网 URL，人工调整名称",
            "merged_json": {
                "name": "人工合并源",
                "url": "https://example.com/manual.xml",
            },
        },
    )
    assert merged.status_code == 200
    merged_payload = merged.json()
    assert merged_payload["status"] == "manual_merge"
    assert merged_payload["resolution_json"]["apply_result"]["applied_revision"] == 4
    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "global-source-resolution-001"))
        assert source is not None
        assert source.name == "人工合并源"
        assert source.url == "https://example.com/manual.xml"
        assert source.revision == 4
        assert source.content_hash


def test_sync_health_reports_cursor_failures_lag_and_conflicts(monkeypatch, tmp_path):
    client, engine = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="public_password",
        CAPABILITY_SYNC_CONSUMER="true",
        SYNC_PULL_ENABLED="false",
        SYNC_PULL_INTERVAL_SECONDS="60",
    )
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)
    with Session() as session:
        run = SyncRun(
            package_id="api_pull_failed_health",
            source_instance_id="extranet",
            target_instance_id="intranet",
            direction="api_pull",
            status="completed_with_errors",
            counts_json={"failed": 1, "conflicts": 1},
            started_at=now - timedelta(minutes=5),
            completed_at=now - timedelta(minutes=4),
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                SyncCursor(
                    object_type="data_sources",
                    cursor="cursor-ok",
                    last_pulled_at=now - timedelta(seconds=30),
                    last_status="ok",
                ),
                SyncCursor(
                    object_type="raw_items",
                    cursor="cursor-failed",
                    last_pulled_at=now - timedelta(seconds=600),
                    last_status="failed",
                    last_error="remote returned 500",
                ),
                SyncConflict(
                    sync_run_id=run.id,
                    object_type="data_sources",
                    object_id="global-source-health-001",
                    local_revision=2,
                    incoming_revision=2,
                    field_name="record",
                    local_value_json={"name": "本地源"},
                    incoming_value_json={"name": "外网源"},
                    conflict_reason="same revision has different content hash",
                    status="open",
                ),
                SyncInbox(
                    event_id="evt-health-failed-inbox-001",
                    source_instance_id="extranet",
                    object_type="raw_items",
                    object_id="raw-health-001",
                    payload_hash="hash-health-raw-1",
                    record_json={
                        "event_id": "evt-health-failed-inbox-001",
                        "object_type": "raw_items",
                        "object_id": "raw-health-001",
                        "object_global_id": "raw-health-001",
                        "operation": "upsert",
                        "payload": {},
                    },
                    status="failed",
                    error_message="missing dependency",
                    attempt_count=1,
                ),
            ],
        )
        session.commit()

    response = client.get("/api/sync/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "critical"
    assert payload["sync_role"] == "consumer"
    assert payload["thresholds"] == {
        "warning_after_seconds": 120,
        "critical_after_seconds": 360,
        "pull_interval_seconds": 60,
    }
    assert payload["cursor_count"] == 2
    assert payload["missing_cursor_count"] == 4
    assert payload["failed_cursor_count"] == 1
    assert payload["failed_inbox_count"] == 1
    assert payload["failed_inbox_by_object_type"] == {"raw_items": 1}
    assert payload["failed_inbox_retry_due_count"] == 1
    assert payload["failed_inbox_retry_blocked_count"] == 0
    assert payload["failed_inbox_next_retry_at"] is None
    assert payload["failed_inbox_retry_policy"]["enabled"] is False
    assert payload["failed_inbox_retry_policy"]["max_attempts"] == 5
    assert payload["open_conflict_count"] == 1
    assert payload["recent_failed_run_count"] == 1
    assert payload["last_run"]["package_id"] == "api_pull_failed_health"
    alert_codes = {item["code"] for item in payload["alerts"]}
    assert {
        "cursor_failed_or_critical_lag",
        "missing_cursors",
        "recent_failed_runs",
        "recent_conflict_runs",
        "open_conflicts",
        "failed_inbox_records",
    }.issubset(alert_codes)
    raw_cursor = next(item for item in payload["cursors"] if item["object_type"] == "raw_items")
    assert raw_cursor["status"] == "critical"
    assert raw_cursor["last_error"] == "remote returned 500"


def test_sync_failed_inbox_retry_api_replays_record(monkeypatch, tmp_path):
    client, engine = make_client(
        monkeypatch,
        tmp_path,
        AUTH_MODE="public_password",
        CAPABILITY_SYNC_CONSUMER="true",
    )
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200
    Session = sessionmaker(bind=engine)
    record = {
        "event_id": "evt-api-retry-source-001",
        "object_type": "data_sources",
        "object_id": "source-api-retry-001",
        "object_global_id": "source-api-retry-001",
        "operation": "upsert",
        "revision": 1,
        "content_hash": "hash-api-retry-source-001",
        "visibility_scope": "public",
        "sync_policy": "public_to_intranet",
        "workspace_code": "shared",
        "domain_code": "ai",
        "payload": {
            "global_id": "source-api-retry-001",
            "origin_instance_id": "extranet",
            "workspace_code": "shared",
            "domain_code": "ai",
            "visibility_scope": "public",
            "sync_policy": "public_to_intranet",
            "source_type": "rss",
            "name": "API 重试源",
            "url": "https://example.com/api-retry.xml",
            "enabled": True,
            "default_focus_id": 1,
            "backfill_days": 7,
        },
    }
    with Session() as session:
        session.add(
            SyncInbox(
                event_id="evt-api-retry-source-001",
                source_instance_id="extranet",
                object_type="data_sources",
                object_id="source-api-retry-001",
                payload_hash="hash-api-retry-source-001",
                record_json=record,
                status="failed",
                error_message="previous apply failed",
                attempt_count=1,
            ),
        )
        session.commit()

    response = client.post("/api/sync/inbox/retry-failed")
    assert response.status_code == 200
    payload = response.json()
    assert payload["direction"] == "inbox_retry"
    assert payload["status"] == "completed"
    assert payload["counts_json"]["selected_failed_inbox"] == 1
    assert payload["counts_json"]["applied"] == 1

    health = client.get("/api/sync/health")
    assert health.status_code == 200
    assert health.json()["failed_inbox_count"] == 0

    with Session() as session:
        source = session.scalar(select(DataSource).where(DataSource.global_id == "source-api-retry-001"))
        inbox = session.scalar(select(SyncInbox).where(SyncInbox.event_id == "evt-api-retry-source-001"))
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "sync_inbox.retry_failed",
                AuditLog.object_id == payload["id"],
            ),
        )
        assert source is not None
        assert source.name == "API 重试源"
        assert inbox is not None
        assert inbox.status == "applied"
        assert inbox.attempt_count == 2
        assert audit is not None


def test_historical_reports_are_listed_and_read_only(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        first = HistoricalReport(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="reports",
            legacy_id="201",
            report_type="daily",
            title="技术洞察日报 2026-05-01",
            status="published_imported",
            period_start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            period_end_at=datetime(2026, 5, 1, 23, 59, 59, tzinfo=timezone.utc),
            content="body with Agent memory details",
            source_refs_json={
                "resolved": [{"legacy_ref": "101", "raw_item_id": "raw_101"}],
                "unresolved": ["999"],
                "resolved_count": 1,
                "unresolved_count": 1,
            },
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:report:test-201",
            origin_instance_id="tech_insight_loop",
        )
        second = HistoricalReport(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="reports",
            legacy_id="202",
            report_type="weekly",
            title="技术洞察周报 2026-W18",
            status="imported",
            period_start_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
            period_end_at=datetime(2026, 5, 10, 23, 59, 59, tzinfo=timezone.utc),
            content="weekly body",
            source_refs_json={"resolved": [], "unresolved": [], "resolved_count": 0, "unresolved_count": 0},
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:report:test-202",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([first, second])
        session.commit()
        first_id = first.id

    summary = client.get("/api/historical-reports/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["total"] == 2
    assert summary_payload["by_report_type"] == {"daily": 1, "weekly": 1}
    assert summary_payload["unresolved_report_count"] == 1
    assert summary_payload["unresolved_ref_count"] == 1

    unresolved = client.get(
        "/api/historical-reports",
        params={"workspace_code": "legacy_tech_insight_loop", "has_unresolved_refs": True},
    )
    assert unresolved.status_code == 200
    unresolved_payload = unresolved.json()
    assert len(unresolved_payload) == 1
    assert unresolved_payload[0]["legacy_id"] == "201"
    assert unresolved_payload[0]["unresolved_ref_count"] == 1
    assert "content" not in unresolved_payload[0]

    weekly = client.get(
        "/api/historical-reports",
        params={"workspace_code": "legacy_tech_insight_loop", "report_type": "weekly", "q": "周报"},
    )
    assert weekly.status_code == 200
    assert [item["legacy_id"] for item in weekly.json()] == ["202"]

    detail = client.get(f"/api/historical-reports/{first_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["content"] == "body with Agent memory details"
    assert detail_payload["source_refs_json"]["unresolved"] == ["999"]
    assert detail_payload["metadata_json"]["legacy_import"]["company_sql_eligible"] is False


def test_legacy_import_summary_and_gaps(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            name="Tech Insight Loop Legacy Archive",
            enabled=False,
            global_id="til:archive-source:test",
            content_hash="source-hash",
        )
        session.add(source)
        session.flush()
        raw = RawItem(
            data_source_id=source.id,
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            source_name="Legacy",
            entry_key="legacy-101",
            source_title="Legacy article",
            raw_content="raw",
            fetched_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            raw_payload_json={"legacy_tech_insight_loop": {"id": 101}},
            global_id="til:article:test-101",
            content_hash="raw-hash",
        )
        report = HistoricalReport(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="reports",
            legacy_id="201",
            report_type="daily",
            title="技术洞察日报 2026-05-01",
            status="published_imported",
            period_start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            period_end_at=datetime(2026, 5, 1, 23, 59, 59, tzinfo=timezone.utc),
            content="body",
            source_refs_json={
                "resolved": [{"legacy_ref": "101", "raw_item_id": raw.id}],
                "unresolved": ["999"],
                "resolved_count": 1,
                "unresolved_count": 1,
            },
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:report:test-201",
            origin_instance_id="tech_insight_loop",
        )
        entity = TrackedEntity(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="ai_entities",
            legacy_id="301",
            name="OpenAI",
            entity_type="AI模型厂商",
            rank="A",
            aliases_json=[],
            influence_score=95,
            global_id="til:entity:test-301",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([raw, report, entity])
        session.flush()
        milestone = EntityMilestone(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="entity_milestones",
            legacy_id="401",
            tracked_entity_id=entity.id,
            legacy_entity_id="301",
            legacy_article_id="999",
            legacy_report_id="201",
            historical_report_id=report.id,
            event_time=datetime(2026, 5, 1, 10, tzinfo=timezone.utc),
            event_type="产品/模型发布",
            title="OpenAI 发布新模型",
            source_name="Legacy",
            board="AI模型",
            importance_score=90,
            importance_level="high",
            event_dedupe_key="event-401",
            metadata_json={
                "legacy_refs": {
                    "article_id": "999",
                    "report_id": "201",
                    "article_ref_resolved": False,
                    "report_ref_resolved": True,
                },
            },
            global_id="til:milestone:test-401",
            origin_instance_id="tech_insight_loop",
        )
        session.add(milestone)
        session.commit()

    summary = client.get("/api/legacy-import/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["workspace_code"] == "legacy_tech_insight_loop"
    metrics = {item["key"]: item for item in payload["metrics"]}
    assert metrics["articles"]["actual"] == 1
    assert metrics["articles"]["expected"] == 14834
    assert metrics["articles"]["status"] == "partial"
    assert metrics["historical_reports"]["actual"] == 1
    assert metrics["tracked_entities"]["actual"] == 1
    assert metrics["entity_milestones"]["actual"] == 1
    assert payload["report_refs"] == {"total": 2, "resolved": 1, "unresolved": 1}
    assert payload["milestone_article_refs"] == {"total": 1, "resolved": 0, "unresolved": 1}
    assert payload["milestone_report_refs"] == {"total": 1, "resolved": 1, "unresolved": 0}
    assert payload["total_unresolved_refs"] == 2
    assert payload["gap_item_count"] == 2

    gaps = client.get("/api/legacy-import/gaps", params={"workspace_code": "legacy_tech_insight_loop"})
    assert gaps.status_code == 200
    gap_payload = gaps.json()
    assert {item["kind"] for item in gap_payload} == {"historical_reports", "entity_milestones"}
    report_gap = next(item for item in gap_payload if item["kind"] == "historical_reports")
    assert report_gap["legacy_id"] == "201"
    assert report_gap["unresolved_refs"] == ["999"]
    milestone_gap = next(item for item in gap_payload if item["kind"] == "entity_milestones")
    assert milestone_gap["legacy_id"] == "401"
    assert milestone_gap["unresolved_refs"] == [{"ref_type": "article_id", "legacy_ref": "999"}]


def test_quality_archive_summary_feedback_and_job_runs(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        source = DataSource(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            name="Tech Insight Loop Legacy Archive",
            enabled=False,
            global_id="til:archive-source:quality",
            content_hash="source-hash-quality",
        )
        session.add(source)
        session.flush()
        raw = RawItem(
            data_source_id=source.id,
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            source_type="legacy_tech_insight_loop",
            source_name="Legacy",
            entry_key="legacy-101",
            source_title="Legacy article",
            raw_content="raw",
            fetched_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            raw_payload_json={"legacy_tech_insight_loop": {"id": 101}},
            global_id="til:article:quality-101",
            content_hash="raw-hash-quality",
        )
        session.add(raw)
        session.flush()
        feedback = HistoricalFeedbackItem(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            legacy_system="tech_insight_loop",
            legacy_table="feedback",
            legacy_id="501",
            legacy_article_id="999",
            feedback_kind="feedback",
            user_name="analyst",
            feedback_type="not_relevant",
            reason="wrong board",
            comment="should not enter report",
            feedback_at=datetime(2026, 5, 2, 9, tzinfo=timezone.utc),
            metadata_json={
                "legacy_refs": {
                    "article_id": "999",
                    "article_ref_resolved": False,
                },
            },
            global_id="til:feedback:test-501",
            origin_instance_id="tech_insight_loop",
        )
        quality = HistoricalFeedbackItem(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            legacy_system="tech_insight_loop",
            legacy_table="article_quality_feedback",
            legacy_id="601",
            legacy_article_id="101",
            raw_item_id=raw.id,
            feedback_kind="quality_feedback",
            user_name="reviewer",
            feedback_type="low_quality",
            reason="source_noise",
            comment="marketing language",
            feedback_at=datetime(2026, 5, 3, 9, tzinfo=timezone.utc),
            metadata_json={
                "legacy_refs": {
                    "article_id": "101",
                    "article_ref_resolved": True,
                },
            },
            global_id="til:quality-feedback:test-601",
            origin_instance_id="tech_insight_loop",
        )
        job = HistoricalJobRun(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            visibility_scope="public",
            sync_policy="public_to_intranet",
            legacy_system="tech_insight_loop",
            legacy_table="jobs",
            legacy_id="701",
            job_type="rss_fetch",
            status="failed",
            message="timeout",
            started_at=datetime(2026, 5, 4, 9, tzinfo=timezone.utc),
            ended_at=datetime(2026, 5, 4, 9, 1, tzinfo=timezone.utc),
            total_sources=10,
            processed_sources=8,
            inserted_count=6,
            failed_count=2,
            details_json={"failed_sources": ["source-a"]},
            global_id="til:job:test-701",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([feedback, quality, job])
        session.commit()

    summary = client.get("/api/quality-archive/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total_feedback"] == 1
    assert payload["total_quality_feedback"] == 1
    assert payload["total_job_runs"] == 1
    assert payload["unresolved_feedback_count"] == 1
    assert payload["unresolved_feedback_ref_count"] == 1
    assert payload["total_job_failures"] == 2
    assert payload["by_feedback_type"] == {"not_relevant": 1, "low_quality": 1}
    assert payload["by_quality_reason"] == {"source_noise": 1}
    assert payload["by_job_type"] == {"rss_fetch": 1}
    assert payload["by_job_status"] == {"failed": 1}

    unresolved_feedback = client.get(
        "/api/historical-feedback-items",
        params={"workspace_code": "legacy_tech_insight_loop", "has_unresolved_refs": True},
    )
    assert unresolved_feedback.status_code == 200
    unresolved_payload = unresolved_feedback.json()
    assert [item["legacy_id"] for item in unresolved_payload] == ["501"]
    assert unresolved_payload[0]["article_ref_resolved"] is False

    quality_feedback = client.get(
        "/api/historical-feedback-items",
        params={"workspace_code": "legacy_tech_insight_loop", "feedback_kind": "quality_feedback", "q": "marketing"},
    )
    assert quality_feedback.status_code == 200
    assert [item["legacy_id"] for item in quality_feedback.json()] == ["601"]
    assert quality_feedback.json()[0]["article_ref_resolved"] is True

    gaps = client.get(
        "/api/legacy-import/gaps",
        params={"workspace_code": "legacy_tech_insight_loop", "kind": "historical_feedback"},
    )
    assert gaps.status_code == 200
    assert gaps.json()[0]["kind"] == "historical_feedback"
    assert gaps.json()[0]["unresolved_refs"] == [{"ref_type": "article_id", "legacy_ref": "999"}]

    jobs = client.get(
        "/api/historical-job-runs",
        params={"workspace_code": "legacy_tech_insight_loop", "status": "failed", "q": "timeout"},
    )
    assert jobs.status_code == 200
    job_payload = jobs.json()
    assert [item["legacy_id"] for item in job_payload] == ["701"]
    assert job_payload[0]["details_json"] == {"failed_sources": ["source-a"]}


def test_entity_timeline_is_listed_and_read_only(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "password"}).status_code == 200

    Session = sessionmaker(bind=engine)
    with Session() as session:
        entity = TrackedEntity(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="ai_entities",
            legacy_id="301",
            name="OpenAI",
            entity_type="AI模型厂商",
            rank="A",
            aliases_json=["GPT", "ChatGPT"],
            influence_score=95,
            notes="legacy entity",
            metadata_json={"legacy_import": {"company_sql_eligible": False}},
            global_id="til:entity:test-301",
            origin_instance_id="tech_insight_loop",
        )
        session.add(entity)
        session.flush()
        linked = EntityMilestone(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="entity_milestones",
            legacy_id="401",
            tracked_entity_id=entity.id,
            legacy_entity_id="301",
            legacy_article_id="101",
            legacy_report_id="201",
            raw_item_id=None,
            historical_report_id=None,
            event_time=datetime(2026, 5, 1, 10, tzinfo=timezone.utc),
            event_type="产品/模型发布",
            title="OpenAI 发布新模型",
            event_content="event content",
            impact="impact",
            event_brief="brief",
            impact_brief="impact brief",
            timeline_brief="timeline",
            source_url="https://example.com/openai",
            source_name="Example",
            board="AI模型",
            selected_for_timeline=True,
            confidence_score=88,
            importance_score=90,
            importance_level="high",
            event_dedupe_key="2026-05-01|release|openai",
            metadata_json={
                "legacy_refs": {
                    "article_id": "101",
                    "report_id": "201",
                    "article_ref_resolved": True,
                    "report_ref_resolved": True,
                },
                "legacy_import": {"recommendation_eligible": False},
            },
            global_id="til:milestone:test-401",
            origin_instance_id="tech_insight_loop",
        )
        unresolved = EntityMilestone(
            workspace_code="legacy_tech_insight_loop",
            domain_code="ai",
            legacy_system="tech_insight_loop",
            legacy_table="entity_milestones",
            legacy_id="402",
            tracked_entity_id=entity.id,
            legacy_entity_id="301",
            legacy_article_id="999",
            legacy_report_id=None,
            event_time=datetime(2026, 5, 2, 10, tzinfo=timezone.utc),
            event_type="战略变化",
            title="OpenAI 调整战略",
            event_content="strategy",
            impact="impact",
            source_url="https://example.com/openai-2",
            source_name="Example",
            board="AI安全、可信与治理",
            selected_for_timeline=True,
            confidence_score=70,
            importance_score=80,
            importance_level="medium",
            event_dedupe_key="2026-05-02|strategy|openai",
            metadata_json={
                "legacy_refs": {
                    "article_id": "999",
                    "article_ref_resolved": False,
                    "report_ref_resolved": None,
                },
                "legacy_import": {"recommendation_eligible": False},
            },
            global_id="til:milestone:test-402",
            origin_instance_id="tech_insight_loop",
        )
        session.add_all([linked, unresolved])
        session.commit()
        linked_id = linked.id

    summary = client.get("/api/entity-timeline/summary", params={"workspace_code": "legacy_tech_insight_loop"})
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["total_entities"] == 1
    assert summary_payload["total_milestones"] == 2
    assert summary_payload["unresolved_milestone_count"] == 1
    assert summary_payload["by_entity_type"] == {"AI模型厂商": 1}

    entities = client.get("/api/tracked-entities", params={"workspace_code": "legacy_tech_insight_loop", "q": "OpenAI"})
    assert entities.status_code == 200
    entity_payload = entities.json()[0]
    assert entity_payload["name"] == "OpenAI"
    assert entity_payload["milestone_count"] == 2
    assert entity_payload["aliases_json"] == ["GPT", "ChatGPT"]

    unresolved_response = client.get(
        "/api/entity-milestones",
        params={"workspace_code": "legacy_tech_insight_loop", "has_unresolved_refs": True},
    )
    assert unresolved_response.status_code == 200
    unresolved_payload = unresolved_response.json()
    assert [item["legacy_id"] for item in unresolved_payload] == ["402"]
    assert unresolved_payload[0]["article_ref_resolved"] is False

    event_type_response = client.get(
        "/api/entity-milestones",
        params={"workspace_code": "legacy_tech_insight_loop", "event_type": "产品/模型发布"},
    )
    assert event_type_response.status_code == 200
    assert [item["legacy_id"] for item in event_type_response.json()] == ["401"]

    detail = client.get(f"/api/entity-milestones/{linked_id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["event_content"] == "event content"
    assert detail_payload["legacy_refs"]["article_ref_resolved"] is True
    assert detail_payload["metadata_json"]["legacy_import"]["recommendation_eligible"] is False


def _create_local_user(engine, username: str, password: str, *, workspace_role: str | None) -> User:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        role = session.scalar(select(Role).where(Role.code == "viewer"))
        user = User(
            external_provider="local",
            external_id=username,
            username=username,
            display_name=username.title(),
            password_hash=hash_password(password),
            status="active",
            roles=[role],
        )
        session.add(user)
        session.flush()
        if workspace_role:
            workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    workspace_role=workspace_role,
                    enabled=True,
                ),
            )
        session.commit()
        session.refresh(user)
        return user
