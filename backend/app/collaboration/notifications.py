from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.content import DedupeGroup, IngestionRun
from app.models.feedback import ActivityEvent, Comment, Notification, NotificationPreference, ObjectWatcher, Rating, Reaction
from app.models.identity import User
from app.models.reports import DailyReport, DailyReportItem, WeeklyReport, WeeklyReportItem
from app.models.strategy import Requirement, TopicTask
from app.models.sync import SyncConflict
from app.models.workspace import Workspace, WorkspaceMembership

MENTION_PATTERN = re.compile(r"@([A-Za-z0-9_.-]{2,64})")


def record_reaction_activity(
    session: Session,
    *,
    actor: User,
    item: DailyReportItem,
    reaction: Reaction,
) -> ActivityEvent:
    return _create_activity_event(
        session,
        actor=actor,
        item=item,
        event_type="reaction.created" if reaction.active else "reaction.removed",
        object_type="daily_report_item",
        object_id=item.id,
        summary=f"{actor.display_name} 点赞了日报条目" if reaction.active else f"{actor.display_name} 取消了点赞",
        metadata_json={"reaction_id": reaction.id, "reaction_type": reaction.reaction_type, "active": reaction.active},
    )


def record_rating_activity(
    session: Session,
    *,
    actor: User,
    item: DailyReportItem,
    rating: Rating,
    created: bool,
) -> ActivityEvent:
    return _create_activity_event(
        session,
        actor=actor,
        item=item,
        event_type="rating.created" if created else "rating.updated",
        object_type="daily_report_item",
        object_id=item.id,
        summary=f"{actor.display_name} 给日报条目评分 {rating.score}",
        metadata_json={"rating_id": rating.id, "dimension": rating.dimension, "score": rating.score},
    )


def record_comment_activity(
    session: Session,
    *,
    actor: User,
    item: DailyReportItem,
    comment: Comment,
    parent: Comment | None,
) -> ActivityEvent:
    mentioned_recipient_ids = _daily_report_comment_mention_recipient_ids(
        session,
        item=item,
        comment=comment,
        actor=actor,
    )
    event = _create_activity_event(
        session,
        actor=actor,
        item=item,
        event_type="comment.replied" if parent else "comment.created",
        object_type="comment",
        object_id=comment.id,
        target_object_type="daily_report_item",
        target_object_id=item.id,
        summary=f"{actor.display_name} 评论了日报条目",
        metadata_json={
            "comment_id": comment.id,
            "daily_report_item_id": item.id,
            "parent_id": parent.id if parent else None,
            "mentioned_user_ids": mentioned_recipient_ids,
        },
    )
    recipient_ids = [
        user_id
        for user_id in sorted(
            set(_daily_report_comment_recipient_ids(session, item=item, actor=actor, parent=parent))
            | set(
                _object_watcher_recipient_ids(
                    session,
                    workspace_code=item.daily_report.workspace_code,
                    object_type="daily_report_item",
                    object_id=item.id,
                    actor=actor,
                ),
            ),
        )
        if user_id not in mentioned_recipient_ids
    ]
    _create_notifications(session, event=event, recipient_ids=recipient_ids)
    if mentioned_recipient_ids:
        mention_event = _create_activity_event(
            session,
            actor=actor,
            item=item,
            event_type="comment.mentioned",
            object_type="comment",
            object_id=comment.id,
            target_object_type="daily_report_item",
            target_object_id=item.id,
            summary=f"{actor.display_name} 在评论中提到了你",
            metadata_json={
                "comment_id": comment.id,
                "daily_report_item_id": item.id,
                "parent_id": parent.id if parent else None,
                "mentioned_user_ids": mentioned_recipient_ids,
            },
        )
        _create_notifications(session, event=mention_event, recipient_ids=mentioned_recipient_ids, priority="important")
    return event


def record_sync_conflict_activity(
    session: Session,
    *,
    conflict: SyncConflict,
    workspace_code: str,
    domain_code: str = "ai",
) -> ActivityEvent:
    event = ActivityEvent(
        workspace_code=workspace_code,
        domain_code=domain_code,
        actor_user_id=None,
        event_type="sync_conflict.created",
        object_type="sync_conflict",
        object_id=conflict.id,
        target_object_type=conflict.object_type,
        target_object_id=conflict.object_id,
        summary=f"同步冲突需要处置：{conflict.object_type} {conflict.object_id}",
        metadata_json={
            "sync_conflict_id": conflict.id,
            "sync_run_id": conflict.sync_run_id,
            "object_type": conflict.object_type,
            "object_id": conflict.object_id,
            "reason": conflict.conflict_reason or (conflict.resolution_json or {}).get("reason", ""),
        },
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    recipient_ids = _sync_conflict_recipient_ids(session, workspace_code=workspace_code)
    _create_notifications(session, event=event, recipient_ids=recipient_ids, priority="important")
    return event


def record_ingestion_failed_source_retry_alert_activity(
    session: Session,
    *,
    run: IngestionRun,
    event_type: str,
    failed_source_count: int,
    attempt_count: int,
    next_retry_at: datetime,
    latest_retry_run: IngestionRun | None = None,
) -> ActivityEvent | None:
    if event_type not in {"ingestion.failed_source_retry_due", "ingestion.failed_source_retry_blocked"}:
        raise ValueError(f"unsupported ingestion retry alert event type: {event_type}")
    if _has_retry_alert_event(session, run=run, event_type=event_type, attempt_count=attempt_count):
        return None

    alert_state = "blocked" if event_type.endswith("_blocked") else "due"
    event = ActivityEvent(
        workspace_code=run.workspace_code,
        domain_code=run.domain_code,
        actor_user_id=None,
        event_type=event_type,
        object_type="ingestion_run",
        object_id=run.id,
        target_object_type="ingestion_run",
        target_object_id=run.id,
        summary=(
            f"失败源自动重试{'已阻塞' if alert_state == 'blocked' else '已到期'}："
            f"{run.run_key}，{failed_source_count} 个失败源"
        ),
        metadata_json={
            "ingestion_run_id": run.id,
            "run_key": run.run_key,
            "run_type": run.run_type,
            "status": run.status,
            "failed_source_count": failed_source_count,
            "attempt_count": attempt_count,
            "next_retry_at": _iso_datetime(next_retry_at),
            "latest_retry_run_id": latest_retry_run.id if latest_retry_run else None,
            "latest_retry_run_key": latest_retry_run.run_key if latest_retry_run else None,
            "alert_state": alert_state,
        },
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    recipient_ids = _sync_conflict_recipient_ids(session, workspace_code=run.workspace_code)
    _create_notifications(session, event=event, recipient_ids=recipient_ids, priority="important")
    return event


def record_daily_report_publish_activity(
    session: Session,
    *,
    actor: User,
    report: DailyReport,
) -> ActivityEvent:
    event = ActivityEvent(
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        actor_user_id=actor.id,
        event_type="daily_report.published",
        object_type="daily_report",
        object_id=report.id,
        target_object_type="daily_report",
        target_object_id=report.id,
        summary=f"{actor.display_name} 发布了日报：{report.title}",
        metadata_json={"daily_report_id": report.id, "day_key": report.day_key},
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    recipient_ids = _workspace_notification_recipient_ids(session, workspace_code=report.workspace_code, actor=actor)
    _create_notifications(session, event=event, recipient_ids=recipient_ids)
    return event


def record_weekly_report_publish_activity(
    session: Session,
    *,
    actor: User,
    report: WeeklyReport,
) -> ActivityEvent:
    event = ActivityEvent(
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        actor_user_id=actor.id,
        event_type="weekly_report.published",
        object_type="weekly_report",
        object_id=report.id,
        target_object_type="weekly_report",
        target_object_id=report.id,
        summary=f"{actor.display_name} 发布了周报：{report.title}",
        metadata_json={"weekly_report_id": report.id, "week_key": report.week_key},
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    recipient_ids = _workspace_notification_recipient_ids(session, workspace_code=report.workspace_code, actor=actor)
    _create_notifications(session, event=event, recipient_ids=recipient_ids)
    return event


def record_weekly_report_item_updated_activity(
    session: Session,
    *,
    actor: User,
    item: WeeklyReportItem,
    before_json: dict,
    after_json: dict,
) -> ActivityEvent | None:
    changed_fields = sorted(
        key
        for key in set(before_json) | set(after_json)
        if before_json.get(key) != after_json.get(key)
    )
    if not changed_fields:
        return None

    report = item.weekly_report
    event = ActivityEvent(
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        actor_user_id=actor.id,
        event_type="weekly_report_item.updated",
        object_type="weekly_report_item",
        object_id=item.id,
        target_object_type="weekly_report_item",
        target_object_id=item.id,
        summary=f"{actor.display_name} 更新了周报条目",
        metadata_json={
            "weekly_report_item_id": item.id,
            "weekly_report_id": report.id,
            "week_key": report.week_key,
            "changed_fields": changed_fields,
            "before": before_json,
            "after": after_json,
        },
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    recipient_ids = _workspace_notification_recipient_ids(session, workspace_code=report.workspace_code, actor=actor)
    _create_notifications(session, event=event, recipient_ids=recipient_ids)
    return event


def record_dedupe_group_adoption_changed_activity(
    session: Session,
    *,
    actor: User,
    group: DedupeGroup,
    daily_report_item: DailyReportItem,
    action_type: str,
) -> ActivityEvent | None:
    recipient_ids = _object_watcher_recipient_ids(
        session,
        workspace_code=group.workspace_code,
        object_type="dedupe_group",
        object_id=group.id,
        actor=actor,
    )
    if not recipient_ids:
        return None
    status_label = "采信" if daily_report_item.adoption_status == 2 else "剔除"
    event = ActivityEvent(
        workspace_code=group.workspace_code,
        domain_code=group.domain_code,
        actor_user_id=actor.id,
        event_type="dedupe_group.adoption_changed",
        object_type="dedupe_group",
        object_id=group.id,
        target_object_type="dedupe_group",
        target_object_id=group.id,
        summary=f"{actor.display_name} 将候选{status_label}到日报：{group.winner_news_item_id or group.dedupe_key}",
        metadata_json={
            "dedupe_group_id": group.id,
            "winner_news_item_id": group.winner_news_item_id,
            "daily_report_id": daily_report_item.daily_report_id,
            "daily_report_item_id": daily_report_item.id,
            "generated_news_id": daily_report_item.generated_news_id,
            "day_key": daily_report_item.daily_report.day_key if daily_report_item.daily_report else "",
            "adoption_status": daily_report_item.adoption_status,
            "action_type": action_type,
        },
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    _create_notifications(session, event=event, recipient_ids=recipient_ids)
    return event


def record_topic_task_assigned_activity(
    session: Session,
    *,
    actor: User,
    task: TopicTask,
) -> ActivityEvent:
    event = ActivityEvent(
        workspace_code=task.workspace_code,
        domain_code=task.domain_code,
        actor_user_id=actor.id,
        event_type="task.assigned",
        object_type="topic_task",
        object_id=task.id,
        target_object_type="topic_task",
        target_object_id=task.id,
        summary=f"{actor.display_name} 指派了任务：{task.title}",
        metadata_json={
            "topic_task_id": task.id,
            "requirement_id": task.requirement_id,
            "assignee_user_id": task.assignee_user_id,
        },
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    recipient_ids = _topic_task_assignee_recipient_ids(session, task=task, actor=actor)
    _create_notifications(session, event=event, recipient_ids=recipient_ids)
    return event


def record_requirement_status_changed_activity(
    session: Session,
    *,
    actor: User,
    requirement: Requirement,
    previous_status: str,
) -> ActivityEvent:
    event = ActivityEvent(
        workspace_code=requirement.workspace_code,
        domain_code=requirement.domain_code,
        actor_user_id=actor.id,
        event_type="requirement.status_changed",
        object_type="requirement",
        object_id=requirement.id,
        target_object_type="requirement",
        target_object_id=requirement.id,
        summary=f"{actor.display_name} 更新了需求状态：{requirement.title}",
        metadata_json={
            "requirement_id": requirement.id,
            "owner_user_id": requirement.owner_user_id,
            "previous_status": previous_status,
            "status": requirement.status,
        },
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    recipient_ids = _requirement_owner_recipient_ids(session, requirement=requirement, actor=actor)
    _create_notifications(session, event=event, recipient_ids=recipient_ids)
    return event


def _create_activity_event(
    session: Session,
    *,
    actor: User,
    item: DailyReportItem,
    event_type: str,
    object_type: str,
    object_id: str,
    summary: str,
    metadata_json: dict,
    target_object_type: str = "",
    target_object_id: str = "",
) -> ActivityEvent:
    report = item.daily_report
    event = ActivityEvent(
        workspace_code=report.workspace_code,
        domain_code=report.domain_code,
        actor_user_id=actor.id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        summary=summary,
        metadata_json=metadata_json,
        sync_policy="local_only",
    )
    session.add(event)
    session.flush()
    return event


def _has_retry_alert_event(
    session: Session,
    *,
    run: IngestionRun,
    event_type: str,
    attempt_count: int,
) -> bool:
    events = session.scalars(
        select(ActivityEvent).where(
            ActivityEvent.workspace_code == run.workspace_code,
            ActivityEvent.event_type == event_type,
            ActivityEvent.object_type == "ingestion_run",
            ActivityEvent.object_id == run.id,
        ),
    ).all()
    return any((event.metadata_json or {}).get("attempt_count") == attempt_count for event in events)


def _daily_report_comment_recipient_ids(
    session: Session,
    *,
    item: DailyReportItem,
    actor: User,
    parent: Comment | None,
) -> list[str]:
    recipient_ids = {
        user_id
        for user_id in session.scalars(
            select(Comment.user_id).where(
                Comment.daily_report_item_id == item.id,
                Comment.status == "visible",
                Comment.user_id != actor.id,
            ),
        ).all()
    }
    if parent is not None and parent.user_id != actor.id:
        recipient_ids.add(parent.user_id)
    return sorted(recipient_ids)


def _daily_report_comment_mention_recipient_ids(
    session: Session,
    *,
    item: DailyReportItem,
    comment: Comment,
    actor: User,
) -> list[str]:
    identifiers = sorted({match.group(1).lower() for match in MENTION_PATTERN.finditer(comment.body or "")})
    if not identifiers:
        return []
    mentioned_users = session.scalars(
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            Workspace.code == item.daily_report.workspace_code,
            Workspace.enabled.is_(True),
            WorkspaceMembership.enabled.is_(True),
            User.is_active.is_(True),
            User.status == "active",
            User.id != actor.id,
            or_(
                func.lower(User.username).in_(identifiers),
                func.lower(User.employee_no).in_(identifiers),
                func.lower(User.external_id).in_(identifiers),
            ),
        ),
    ).all()
    return sorted({user.id for user in mentioned_users})


def _sync_conflict_recipient_ids(session: Session, *, workspace_code: str) -> list[str]:
    recipient_ids: set[str] = set()
    users = session.scalars(
        select(User)
        .options(selectinload(User.roles))
        .where(
            User.is_active.is_(True),
            User.status == "active",
        ),
    ).all()
    for user in users:
        if "super_admin" in {role.code for role in user.roles}:
            recipient_ids.add(user.id)

    workspace_memberships = session.scalars(
        select(WorkspaceMembership)
        .join(Workspace)
        .where(
            Workspace.code == workspace_code,
            WorkspaceMembership.enabled.is_(True),
            WorkspaceMembership.workspace_role.in_(["owner", "admin"]),
        ),
    ).all()
    recipient_ids.update(membership.user_id for membership in workspace_memberships)
    return sorted(recipient_ids)


def _workspace_notification_recipient_ids(session: Session, *, workspace_code: str, actor: User) -> list[str]:
    memberships = session.scalars(
        select(WorkspaceMembership)
        .join(Workspace)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            Workspace.code == workspace_code,
            WorkspaceMembership.enabled.is_(True),
            WorkspaceMembership.user_id != actor.id,
            User.is_active.is_(True),
            User.status == "active",
        ),
    ).all()
    return sorted({membership.user_id for membership in memberships})


def _object_watcher_recipient_ids(
    session: Session,
    *,
    workspace_code: str,
    object_type: str,
    object_id: str,
    actor: User,
) -> list[str]:
    watchers = session.scalars(
        select(ObjectWatcher)
        .join(User, User.id == ObjectWatcher.user_id)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == ObjectWatcher.user_id)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            ObjectWatcher.workspace_code == workspace_code,
            ObjectWatcher.object_type == object_type,
            ObjectWatcher.object_id == object_id,
            ObjectWatcher.active.is_(True),
            ObjectWatcher.user_id != actor.id,
            Workspace.code == workspace_code,
            WorkspaceMembership.enabled.is_(True),
            User.is_active.is_(True),
            User.status == "active",
        ),
    ).all()
    return sorted({watcher.user_id for watcher in watchers})


def _topic_task_assignee_recipient_ids(session: Session, *, task: TopicTask, actor: User) -> list[str]:
    if not task.assignee_user_id or task.assignee_user_id == actor.id:
        return []
    assignee = session.get(User, task.assignee_user_id)
    if assignee is None or not assignee.is_active or assignee.status != "active":
        return []
    return [assignee.id]


def _requirement_owner_recipient_ids(session: Session, *, requirement: Requirement, actor: User) -> list[str]:
    if not requirement.owner_user_id or requirement.owner_user_id == actor.id:
        return []
    owner = session.get(User, requirement.owner_user_id)
    if owner is None or not owner.is_active or owner.status != "active":
        return []
    membership = session.scalar(
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            Workspace.code == requirement.workspace_code,
            WorkspaceMembership.user_id == requirement.owner_user_id,
            WorkspaceMembership.enabled.is_(True),
        ),
    )
    if membership is None:
        return []
    return [owner.id]


def _create_notifications(
    session: Session,
    *,
    event: ActivityEvent,
    recipient_ids: list[str],
    priority: str = "normal",
) -> None:
    for user_id in recipient_ids:
        if not _in_app_notification_enabled(session, event=event, user_id=user_id):
            continue
        session.add(
            Notification(
                user_id=user_id,
                workspace_code=event.workspace_code,
                activity_event=event,
                status="unread",
                priority=priority,
                delivery_channel="in_app",
            ),
        )


def _in_app_notification_enabled(session: Session, *, event: ActivityEvent, user_id: str) -> bool:
    preference = session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.workspace_code == event.workspace_code,
            NotificationPreference.event_type == event.event_type,
        ),
    )
    return True if preference is None else preference.in_app_enabled


def _iso_datetime(value: datetime) -> str:
    return value.isoformat()
