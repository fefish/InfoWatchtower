"""日报发布服务：手动发布与每日流水线自动发布共用一条链路。

设计要点（任务 C：普通用户阅读体验 + 每日自动发布）：
- 工作台级策略 ``report_policy.auto_publish_daily``（默认 true）存放在
  ``workspaces.config_json``，与 label_policy / feedback_policy 同级，可 PATCH。
- 自动发布 actor 为 system（audit user 为空），audit action 固定
  ``daily_report.auto_publish``；手动发布仍是 ``daily_report.publish``。
- 发布即沉淀实体里程碑候选（幂等），并把所有启用格式的 rendition 照常投影，
  游客/viewer 打开日报即可读到成稿，无需 member 权限触发 regenerate。
- rendition 只是采信条目的投影快照，不回写采信状态、generated_news 与公司 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.archive.milestones import extract_candidate_milestones_for_daily_report
from app.auth.service import write_audit
from app.collaboration.notifications import record_daily_report_publish_activity
from app.models.common import utc_now
from app.models.identity import User
from app.models.reports import DailyReport, ReportRendition
from app.models.workspace import Workspace
from app.reports.renditions import (
    build_daily_rendition,
    ensure_report_formats,
    load_daily_report_for_rendition,
)

DEFAULT_WORKSPACE_REPORT_POLICY = {
    "auto_publish_daily": True,
}


def workspace_report_policy(workspace: Workspace) -> dict[str, bool]:
    """工作台报告策略：config_json.report_policy 覆盖默认值（默认自动发布）。"""
    return {
        **DEFAULT_WORKSPACE_REPORT_POLICY,
        **dict((workspace.config_json or {}).get("report_policy") or {}),
    }


def auto_publish_daily_enabled(workspace: Workspace) -> bool:
    return bool(workspace_report_policy(workspace).get("auto_publish_daily"))


@dataclass(frozen=True)
class PublishDailyReportResult:
    report: DailyReport
    was_published: bool
    candidate_milestones_total: int
    renditions_total: int


def publish_daily_report(
    session: Session,
    report: DailyReport,
    *,
    actor: User | None,
    audit_action: str = "daily_report.publish",
) -> PublishDailyReportResult:
    """发布日报（幂等）：置状态、沉淀里程碑候选、写审计、投影 renditions。

    actor 为 None 表示 system 自动发布：审计 user 留空、不触发个人通知。
    只 flush 不 commit，由调用方统一提交。
    """
    was_published = report.status == "published"
    report.status = "published"
    report.published_at = utc_now()
    candidate_milestones = extract_candidate_milestones_for_daily_report(session, report)
    write_audit(
        session,
        actor,
        audit_action,
        "daily_report",
        report.id,
        {
            "day_key": report.day_key,
            "workspace_code": report.workspace_code,
            "candidate_entity_milestones": len(candidate_milestones),
            "actor": actor.username if actor is not None else "system",
        },
    )
    should_notify = (
        actor is not None
        and not was_published
        and _notify_on_publish_enabled(session, report.workspace_code)
    )
    if should_notify:
        record_daily_report_publish_activity(session, actor=actor, report=report)
    renditions = rebuild_daily_report_renditions(session, report)
    session.flush()
    return PublishDailyReportResult(
        report=report,
        was_published=was_published,
        candidate_milestones_total=len(candidate_milestones),
        renditions_total=len(renditions),
    )


def rebuild_daily_report_renditions(
    session: Session,
    report: DailyReport,
) -> list[ReportRendition]:
    """按当前采信态重投影该日报所有启用格式的成稿（发布/发布后修订共用）。"""
    workspace = session.scalar(select(Workspace).where(Workspace.code == report.workspace_code))
    workspace_name = workspace.name if workspace is not None else report.workspace_code
    formats = ensure_report_formats(session, report.workspace_code)
    loaded = load_daily_report_for_rendition(session, report.id) or report
    return [
        build_daily_rendition(session, loaded, fmt, workspace_name)
        for fmt in sorted(formats, key=lambda fmt: (fmt.sort_order, fmt.format_code))
        if fmt.enabled
    ]


def _notify_on_publish_enabled(session: Session, workspace_code: str) -> bool:
    workspace = session.scalar(select(Workspace).where(Workspace.code == workspace_code))
    if workspace is None:
        return False
    policy = {
        "notify_on_publish": False,
        **dict((workspace.config_json or {}).get("feedback_policy") or {}),
    }
    return bool(policy.get("notify_on_publish"))
