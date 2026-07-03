from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.auth.passwords import hash_password
from app.main import create_app
from app.models.content import (
    DataSource,
    DedupeGroup,
    DedupeGroupItem,
    GeneratedNews,
    NewsItem,
    RawItem,
    RecommendationItem,
    RecommendationRun,
)
from app.models.identity import LoginAttempt, PasswordResetToken, Role, User, UserInvite
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.models.workspace import Workspace, WorkspaceMembership
from tests.test_auth import make_client

ROOT = Path(__file__).resolve().parents[2]


def test_invite_accept_creates_user_and_membership(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert _login(client).status_code == 200

    invite = client.post(
        "/api/auth/invites",
        json={
            "email": "editor@example.com",
            "role_code": "editor_admin",
            "workspaces": [{"code": "planning_intel", "workspace_role": "member"}],
        },
    )
    assert invite.status_code == 200
    code = invite.json()["code"]

    public_invite = client.get(f"/api/auth/invites/{code}")
    assert public_invite.status_code == 200
    assert public_invite.json()["email_hint"] == "ed***@example.com"

    accepted = client.post(
        f"/api/auth/invites/{code}/accept",
        json={"username": "editor", "display_name": "Editor", "password": "new-password"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["user"]["roles"] == ["editor_admin"]

    Session = sessionmaker(bind=engine)
    with Session() as session:
        user = session.scalar(select(User).where(User.username == "editor"))
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.workspace_id == workspace.id,
            ),
        )
        invite_row = session.scalar(select(UserInvite).where(UserInvite.code == code))
        assert membership.workspace_role == "member"
        assert invite_row.accepted_by_id == user.id


def test_invite_requires_explicit_workspace_target(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert _login(client).status_code == 200

    response = client.post("/api/auth/invites", json={"role_code": "viewer"})

    assert response.status_code == 400
    assert "workspace target" in response.json()["detail"]


def test_revoked_and_expired_invites_return_gone(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert _login(client).status_code == 200

    invite_payload = {
        "role_code": "viewer",
        "workspaces": [{"code": "planning_intel", "workspace_role": "viewer"}],
    }
    revoked = client.post("/api/auth/invites", json=invite_payload)
    assert revoked.status_code == 200
    revoked_code = revoked.json()["code"]
    assert client.post(f"/api/auth/invites/{revoked_code}/revoke").status_code == 200
    revoked_accept = client.post(
        f"/api/auth/invites/{revoked_code}/accept",
        json={"username": "revoked", "display_name": "Revoked", "password": "new-password"},
    )
    assert revoked_accept.status_code == 410

    expired = client.post("/api/auth/invites", json=invite_payload)
    assert expired.status_code == 200
    expired_code = expired.json()["code"]
    Session = sessionmaker(bind=engine)
    with Session() as session:
        invite = session.scalar(select(UserInvite).where(UserInvite.code == expired_code))
        invite.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()

    expired_accept = client.post(
        f"/api/auth/invites/{expired_code}/accept",
        json={"username": "expired", "display_name": "Expired", "password": "new-password"},
    )
    assert expired_accept.status_code == 410


def test_login_rate_limit_and_success_after_window(monkeypatch, tmp_path):
    client, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")

    for _ in range(5):
        response = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        assert response.status_code == 401
    limited = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert limited.status_code == 429

    Session = sessionmaker(bind=engine)
    with Session() as session:
        for attempt in session.scalars(select(LoginAttempt)).all():
            attempt.created_at = datetime.now(UTC) - timedelta(minutes=20)
        session.commit()

    assert _login(client).status_code == 200


def test_forgot_admin_reset_must_change_and_old_cookie(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    assert _login(admin).status_code == 200
    user = _create_local_user(engine, "writer", "old-password", workspace_role="member")

    forgot = admin.post("/api/auth/password/forgot", json={"username": "writer"})
    assert forgot.status_code == 200
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert session.scalars(select(PasswordResetToken)).all() == []

    reset = admin.post(f"/api/users/{user.id}/reset-password")
    assert reset.status_code == 200
    temp_password = reset.json()["temporary_password"]

    writer = TestClient(create_app())
    assert writer.post("/api/auth/login", json={"username": "writer", "password": "old-password"}).status_code == 401
    login = writer.post("/api/auth/login", json={"username": "writer", "password": temp_password})
    assert login.status_code == 200
    assert login.json()["user"]["status"] == "must_change_password"
    assert writer.get("/api/sources", params={"workspace_code": "planning_intel"}).status_code == 403

    changed = writer.post(
        "/api/auth/password/change",
        json={"current_password": temp_password, "new_password": "final-password"},
    )
    assert changed.status_code == 200
    assert writer.get("/api/sources", params={"workspace_code": "planning_intel"}).status_code == 200

    old_cookie_client = TestClient(create_app())
    old_cookie_client.cookies.set("infowatchtower_session", login.cookies["infowatchtower_session"])
    assert old_cookie_client.get("/api/auth/me").status_code == 401


def test_workspace_membership_controls_daily_item_edit(monkeypatch, tmp_path):
    admin, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    bundle = _create_report_bundle(engine)
    report_item_id = bundle["daily_item_id"]
    _create_local_user(engine, "viewer", "password-123", workspace_role="viewer")
    _create_local_user(engine, "member", "password-123", workspace_role="member")
    _create_local_user(engine, "outsider", "password-123", workspace_role=None)

    viewer = TestClient(create_app())
    assert viewer.post("/api/auth/login", json={"username": "viewer", "password": "password-123"}).status_code == 200
    assert viewer.get(f"/api/daily-reports/{bundle['daily_report_id']}").status_code == 200
    assert viewer.get("/api/news-items", params={"workspace_code": "planning_intel"}).status_code == 200
    assert viewer.get("/api/dedupe-groups", params={"workspace_code": "planning_intel"}).status_code == 200
    assert viewer.get("/api/workspaces/planning_intel/sections").status_code == 200
    assert viewer.get("/api/report-formats", params={"workspace_code": "planning_intel"}).status_code == 200
    assert viewer.post(f"/api/daily-reports/{bundle['daily_report_id']}/publish").status_code == 403
    viewer_patch = viewer.patch(f"/api/daily-report-items/{report_item_id}", json={"editor_title": "Nope"})
    assert viewer_patch.status_code == 403
    assert viewer.post(f"/api/daily-report-items/{report_item_id}/reactions", json={"reaction_type": "like"}).status_code == 403
    assert viewer.post("/api/report-formats", json=_report_format_payload()).status_code == 403
    assert viewer.get("/api/exports").status_code == 403

    member = TestClient(create_app())
    assert member.post("/api/auth/login", json={"username": "member", "password": "password-123"}).status_code == 200
    member_patch = member.patch(f"/api/daily-report-items/{report_item_id}", json={"editor_title": "Updated"})
    assert member_patch.status_code == 200
    assert member_patch.json()["editor_title"] == "Updated"
    assert member.post(f"/api/daily-report-items/{report_item_id}/reactions", json={"reaction_type": "like"}).status_code == 200
    assert member.post(f"/api/daily-report-items/{report_item_id}/ratings", json={"score": 5}).status_code == 200
    assert member.post(f"/api/daily-report-items/{report_item_id}/comments", json={"body": "Looks good"}).status_code == 200
    assert member.patch(f"/api/weekly-report-items/{bundle['weekly_item_id']}", json={"editor_title": "Weekly"}).status_code == 200
    assert member.post(f"/api/daily-reports/{bundle['daily_report_id']}/publish").status_code == 200
    export = member.post(f"/api/exports/company-sql/daily-reports/{bundle['daily_report_id']}")
    assert export.status_code == 200
    export_job_id = export.json()["export_job_id"]

    outsider = TestClient(create_app())
    assert outsider.post("/api/auth/login", json={"username": "outsider", "password": "password-123"}).status_code == 200
    assert outsider.get("/api/sources", params={"workspace_code": "planning_intel"}).status_code == 403
    assert outsider.get(f"/api/daily-reports/{bundle['daily_report_id']}").status_code == 403
    assert outsider.get(f"/api/exports/{export_job_id}/trace").status_code == 403

    assert viewer.get("/api/exports", params={"workspace_code": "planning_intel"}).status_code == 200
    assert viewer.get(f"/api/exports/{export_job_id}/trace").status_code == 200

    assert _login(admin).status_code == 200
    super_patch = admin.patch(f"/api/daily-report-items/{report_item_id}", json={"editor_title": "Admin"})
    assert super_patch.status_code == 200


def test_workspace_admin_can_manage_sources_and_report_formats(monkeypatch, tmp_path):
    _, engine = make_client(monkeypatch, tmp_path, AUTH_MODE="public_password")
    _create_local_user(engine, "workspace-admin", "password-123", workspace_role="admin")
    _create_local_user(engine, "viewer-only", "password-123", workspace_role="viewer")

    viewer = TestClient(create_app())
    assert viewer.post("/api/auth/login", json={"username": "viewer-only", "password": "password-123"}).status_code == 200
    assert viewer.post("/api/sources", json=_source_payload("viewer")).status_code == 403
    assert viewer.post("/api/pipeline/daily-runs", json=_pipeline_payload()).status_code == 403

    workspace_admin = TestClient(create_app())
    login = workspace_admin.post(
        "/api/auth/login",
        json={"username": "workspace-admin", "password": "password-123"},
    )
    assert login.status_code == 200

    created_format = workspace_admin.post("/api/report-formats", json=_report_format_payload())
    assert created_format.status_code == 201
    format_id = created_format.json()["id"]
    updated_format = workspace_admin.patch(
        f"/api/report-formats/{format_id}",
        json={"name": "Weekly Brief Updated", "enabled": False},
    )
    assert updated_format.status_code == 200
    assert updated_format.json()["enabled"] is False

    created_source = workspace_admin.post("/api/sources", json=_source_payload("admin"))
    assert created_source.status_code == 201
    source = created_source.json()["source"]
    assert source["workspace_link_enabled"] is True

    patched_source = workspace_admin.patch(
        f"/api/sources/{source['id']}",
        params={"workspace_code": "planning_intel"},
        json={"name": "Workspace Admin RSS"},
    )
    assert patched_source.status_code == 200
    assert patched_source.json()["name"] == "Workspace Admin RSS"

    patched_link = workspace_admin.patch(
        f"/api/sources/{source['id']}/workspace-link",
        json={"workspace_code": "planning_intel", "enabled": False, "source_weight": 0.5, "daily_limit": 3},
    )
    assert patched_link.status_code == 200
    assert patched_link.json()["workspace_link_enabled"] is False

    assert workspace_admin.get("/api/ingestion/runs").status_code == 403
    assert workspace_admin.get("/api/ingestion/runs", params={"workspace_code": "planning_intel"}).status_code == 200


def test_missing_public_password_secret_fails_startup(tmp_path):
    database_path = tmp_path / "startup.sqlite"
    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "with TestClient(create_app()) as client:\n"
        "    client.get('/healthz')\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "DATABASE_URL": f"sqlite:///{database_path}",
        "AUTH_MODE": "public_password",
        "AUTH_SESSION_SECRET": "",
        "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "password",
    }

    result = subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True, check=False)

    assert result.returncode != 0
    assert "AUTH_SESSION_SECRET is required" in result.stderr


def _login(client: TestClient):
    return client.post("/api/auth/login", json={"username": "admin", "password": "password"})


def _create_local_user(
    engine,
    username: str,
    password: str,
    *,
    workspace_role: str | None,
    workspace_code: str = "planning_intel",
) -> User:
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
        if workspace_role is not None:
            workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
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


def _create_report_item(engine) -> str:
    return _create_report_bundle(engine)["daily_item_id"]


def _create_report_bundle(engine) -> dict[str, str]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.code == "planning_intel"))
        source = DataSource(
            workspace_code="shared",
            source_type="rss",
            name="Example RSS",
            url="https://example.com/feed",
        )
        session.add(source)
        session.flush()
        raw = RawItem(
            data_source_id=source.id,
            workspace_code=workspace.code,
            source_type="rss",
            source_name=source.name,
            entry_key="item-1",
            source_title="Example",
            source_url="https://example.com/news",
            raw_content="body",
            fetched_at=datetime.now(UTC),
            raw_payload_json={"title": "Example"},
        )
        session.add(raw)
        session.flush()
        news = NewsItem(
            raw_item_id=raw.id,
            data_source_id=source.id,
            workspace_code=workspace.code,
            source_type="rss",
            source_name=source.name,
            source_url=raw.source_url,
            canonical_url=raw.source_url,
            source_title="Example",
            normalized_title="example",
            summary="summary",
            content="content",
            focus_id=1,
            dedupe_key="example",
        )
        session.add(news)
        session.flush()
        group = DedupeGroup(workspace_code=workspace.code, dedupe_key="example", winner_news_item_id=news.id)
        session.add(group)
        session.flush()
        group_item = DedupeGroupItem(dedupe_group_id=group.id, news_item_id=news.id, is_winner=True)
        session.add(group_item)
        run = RecommendationRun(workspace_code=workspace.code, run_key="run-1", status="completed")
        session.add(run)
        session.flush()
        recommendation = RecommendationItem(
            workspace_code=workspace.code,
            run_id=run.id,
            dedupe_group_id=group.id,
            dedupe_group_item_id=group_item.id,
            news_item_id=news.id,
            selected=True,
            recommendation_reason="acceptance",
        )
        session.add(recommendation)
        session.flush()
        generated = GeneratedNews(
            workspace_code=workspace.code,
            recommendation_item_id=recommendation.id,
            news_item_id=news.id,
            category="模型",
            title="Generated",
            summary="summary",
            key_points="模型",
            content_json={
                "background": "背景",
                "effects": "效果",
                "eventSummary": "事件",
                "technologyAndInnovation": "技术",
                "valueAndImpact": "价值",
            },
            generated_by="minimax:test",
            generation_status="ready",
        )
        session.add(generated)
        session.flush()
        report = DailyReport(
            workspace_code=workspace.code,
            day_key="2026-07-03",
            title="Daily",
            status="draft",
        )
        session.add(report)
        session.flush()
        item = DailyReportItem(
            workspace_code=workspace.code,
            daily_report_id=report.id,
            generated_news_id=generated.id,
            adoption_status=2,
        )
        session.add(item)
        weekly = WeeklyReport(
            workspace_code=workspace.code,
            week_key="2026-W27",
            title="Weekly",
            status="draft",
        )
        session.add(weekly)
        session.flush()
        weekly_item = WeeklyReportItem(
            workspace_code=workspace.code,
            weekly_report_id=weekly.id,
            daily_report_item_id=item.id,
            generated_news_id=generated.id,
            adoption_status=2,
        )
        session.add(weekly_item)
        session.commit()
        return {
            "daily_report_id": report.id,
            "daily_item_id": item.id,
            "weekly_report_id": weekly.id,
            "weekly_item_id": weekly_item.id,
        }


def _report_format_payload() -> dict:
    return {
        "workspace_code": "planning_intel",
        "format_code": "weekly_brief_v1",
        "name": "Weekly Brief",
        "description": "Workspace-owned weekly report format",
        "group_by": "category",
        "headline_enabled": True,
        "headline_auto_top_n": 3,
        "item_fields": ["summary", "source_link"],
        "export_targets": ["md", "html"],
    }


def _source_payload(suffix: str) -> dict:
    return {
        "workspace_code": "planning_intel",
        "source_type": "rss",
        "name": f"Workspace RSS {suffix}",
        "url": f"https://example.com/{suffix}/feed.xml",
        "source_weight": 1.0,
        "daily_limit": 5,
    }


def _pipeline_payload() -> dict:
    return {
        "workspace_code": "planning_intel",
        "day_key": "2026-07-03",
        "source_types": [],
        "recommendation_limit": 5,
        "source_daily_limit": 5,
        "create_daily_draft": True,
        "run_ingestion": False,
    }
