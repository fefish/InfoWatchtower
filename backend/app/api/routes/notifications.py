from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import assert_workspace_member, get_current_user
from app.core.database import get_db_session
from app.models.content import DedupeGroup
from app.models.common import utc_now
from app.models.feedback import ActivityEvent, Notification, NotificationPreference, ObjectWatcher
from app.models.identity import User
from app.models.reports import DailyReportItem, WeeklyReportItem
from app.schemas.notifications import (
    ActivityEventRead,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    NotificationUnreadCount,
    ObjectWatcherRead,
    ObjectWatcherUpdate,
)

router = APIRouter(prefix="/api", tags=["notifications"])
CURRENT_USER = Depends(get_current_user)
DB_SESSION = Depends(get_db_session)

SUPPORTED_NOTIFICATION_EVENT_TYPES = [
    "comment.created",
    "comment.replied",
    "comment.mentioned",
    "sync_conflict.created",
    "ingestion.failed_source_retry_due",
    "ingestion.failed_source_retry_blocked",
    "daily_report.published",
    "weekly_report.published",
    "weekly_report_item.updated",
    "dedupe_group.adoption_changed",
    "task.assigned",
    "requirement.status_changed",
]

SUPPORTED_WATCHER_OBJECT_TYPES = {"daily_report_item", "weekly_report_item", "dedupe_group"}


@router.get("/activity-events", response_model=list[ActivityEventRead])
def list_activity_events(
    workspace_code: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[ActivityEventRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    events = session.scalars(
        select(ActivityEvent)
        .options(selectinload(ActivityEvent.actor))
        .where(ActivityEvent.workspace_code == workspace_code)
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .limit(limit),
    ).all()
    return [_activity_event_to_read(event) for event in events]


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications(
    status_filter: str = Query(default="unread", alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[NotificationRead]:
    if status_filter not in {"unread", "read", "archived", "all"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported notification status filter")
    statement = (
        select(Notification)
        .options(selectinload(Notification.activity_event).selectinload(ActivityEvent.actor))
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    if status_filter == "all":
        statement = statement.where(Notification.status != "archived")
    else:
        statement = statement.where(Notification.status == status_filter)
    notifications = session.scalars(statement).all()
    return [_notification_to_read(notification) for notification in notifications]


@router.get("/notification-preferences", response_model=list[NotificationPreferenceRead])
def list_notification_preferences(
    workspace_code: str = Query(...),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> list[NotificationPreferenceRead]:
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    rows = session.scalars(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id,
            NotificationPreference.workspace_code == workspace_code,
        ),
    ).all()
    rows_by_event = {row.event_type: row for row in rows}
    return [
        _notification_preference_to_read(
            rows_by_event.get(event_type),
            workspace_code=workspace_code,
            event_type=event_type,
        )
        for event_type in SUPPORTED_NOTIFICATION_EVENT_TYPES
    ]


@router.patch("/notification-preferences", response_model=NotificationPreferenceRead)
def update_notification_preference(
    payload: NotificationPreferenceUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> NotificationPreferenceRead:
    if payload.event_type not in SUPPORTED_NOTIFICATION_EVENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported notification event type")
    assert_workspace_member(session, current_user, payload.workspace_code, min_role="viewer")
    preference = session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id,
            NotificationPreference.workspace_code == payload.workspace_code,
            NotificationPreference.event_type == payload.event_type,
        ),
    )
    if preference is None:
        preference = NotificationPreference(
            user_id=current_user.id,
            workspace_code=payload.workspace_code,
            event_type=payload.event_type,
        )
        session.add(preference)
    preference.in_app_enabled = payload.in_app_enabled
    preference.email_enabled = payload.email_enabled
    session.commit()
    session.refresh(preference)
    return _notification_preference_to_read(
        preference,
        workspace_code=payload.workspace_code,
        event_type=payload.event_type,
    )


@router.get("/object-watchers", response_model=ObjectWatcherRead)
def get_object_watcher(
    object_type: str = Query(...),
    object_id: str = Query(...),
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ObjectWatcherRead:
    workspace_code = _object_workspace_code(session, object_type, object_id)
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    return _object_watcher_to_read(
        session,
        current_user=current_user,
        workspace_code=workspace_code,
        object_type=object_type,
        object_id=object_id,
    )


@router.patch("/object-watchers", response_model=ObjectWatcherRead)
def update_object_watcher(
    payload: ObjectWatcherUpdate,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> ObjectWatcherRead:
    workspace_code = _object_workspace_code(session, payload.object_type, payload.object_id)
    assert_workspace_member(session, current_user, workspace_code, min_role="viewer")
    watcher = session.scalar(
        select(ObjectWatcher).where(
            ObjectWatcher.user_id == current_user.id,
            ObjectWatcher.workspace_code == workspace_code,
            ObjectWatcher.object_type == payload.object_type,
            ObjectWatcher.object_id == payload.object_id,
        ),
    )
    if watcher is None:
        watcher = ObjectWatcher(
            user_id=current_user.id,
            workspace_code=workspace_code,
            object_type=payload.object_type,
            object_id=payload.object_id,
            active=payload.watching,
        )
        session.add(watcher)
    else:
        watcher.active = payload.watching
    session.commit()
    return _object_watcher_to_read(
        session,
        current_user=current_user,
        workspace_code=workspace_code,
        object_type=payload.object_type,
        object_id=payload.object_id,
    )


@router.get("/notifications/unread-count", response_model=NotificationUnreadCount)
def unread_count(
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> NotificationUnreadCount:
    return NotificationUnreadCount(unread_count=_unread_count(session, current_user.id))


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> NotificationRead:
    notification = session.scalar(
        select(Notification)
        .options(selectinload(Notification.activity_event).selectinload(ActivityEvent.actor))
        .where(Notification.id == notification_id, Notification.user_id == current_user.id),
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.status = "read"
    notification.read_at = utc_now()
    session.commit()
    session.refresh(notification)
    return _notification_to_read(notification)


@router.post("/notifications/{notification_id}/archive", response_model=NotificationRead)
def archive_notification(
    notification_id: str,
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> NotificationRead:
    notification = session.scalar(
        select(Notification)
        .options(selectinload(Notification.activity_event).selectinload(ActivityEvent.actor))
        .where(Notification.id == notification_id, Notification.user_id == current_user.id),
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.status = "archived"
    if notification.read_at is None:
        notification.read_at = utc_now()
    session.commit()
    session.refresh(notification)
    return _notification_to_read(notification)


@router.post("/notifications/read-all", response_model=NotificationUnreadCount)
def mark_all_notifications_read(
    current_user: User = CURRENT_USER,
    session: Session = DB_SESSION,
) -> NotificationUnreadCount:
    notifications = session.scalars(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.status == "unread",
        ),
    ).all()
    now = utc_now()
    for notification in notifications:
        notification.status = "read"
        notification.read_at = now
    session.commit()
    return NotificationUnreadCount(unread_count=0)


def _unread_count(session: Session, user_id: str) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.status == "unread"),
    )
    return int(value or 0)


def _notification_to_read(notification: Notification) -> NotificationRead:
    target_label, target_path = _notification_target(notification.activity_event)
    return NotificationRead(
        id=notification.id,
        workspace_code=notification.workspace_code,
        status=notification.status,
        priority=notification.priority,
        delivery_channel=notification.delivery_channel,
        target_label=target_label,
        target_path=target_path,
        read_at=notification.read_at,
        created_at=notification.created_at,
        activity_event=_activity_event_to_read(notification.activity_event),
    )


def _notification_preference_to_read(
    preference: NotificationPreference | None,
    *,
    workspace_code: str,
    event_type: str,
) -> NotificationPreferenceRead:
    if preference is None:
        return NotificationPreferenceRead(
            workspace_code=workspace_code,
            event_type=event_type,
            in_app_enabled=True,
            email_enabled=False,
        )
    return NotificationPreferenceRead(
        workspace_code=preference.workspace_code,
        event_type=preference.event_type,
        in_app_enabled=preference.in_app_enabled,
        email_enabled=preference.email_enabled,
    )


def _object_workspace_code(session: Session, object_type: str, object_id: str) -> str:
    if object_type not in SUPPORTED_WATCHER_OBJECT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported watcher object type")
    if object_type == "daily_report_item":
        item = session.scalar(
            select(DailyReportItem)
            .options(selectinload(DailyReportItem.daily_report))
            .where(DailyReportItem.id == object_id),
        )
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watch target not found")
        return item.daily_report.workspace_code
    if object_type == "dedupe_group":
        group = session.scalar(
            select(DedupeGroup).where(DedupeGroup.id == object_id),
        )
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watch target not found")
        return group.workspace_code
    item = session.scalar(
        select(WeeklyReportItem)
        .options(selectinload(WeeklyReportItem.weekly_report))
        .where(WeeklyReportItem.id == object_id),
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watch target not found")
    return item.weekly_report.workspace_code


def _object_watcher_to_read(
    session: Session,
    *,
    current_user: User,
    workspace_code: str,
    object_type: str,
    object_id: str,
) -> ObjectWatcherRead:
    watching = session.scalar(
        select(ObjectWatcher.active).where(
            ObjectWatcher.user_id == current_user.id,
            ObjectWatcher.workspace_code == workspace_code,
            ObjectWatcher.object_type == object_type,
            ObjectWatcher.object_id == object_id,
        ),
    )
    watcher_count = session.scalar(
        select(func.count())
        .select_from(ObjectWatcher)
        .where(
            ObjectWatcher.workspace_code == workspace_code,
            ObjectWatcher.object_type == object_type,
            ObjectWatcher.object_id == object_id,
            ObjectWatcher.active.is_(True),
        ),
    )
    return ObjectWatcherRead(
        object_type=object_type,
        object_id=object_id,
        workspace_code=workspace_code,
        watching=bool(watching),
        watcher_count=int(watcher_count or 0),
    )


def _activity_event_to_read(event: ActivityEvent) -> ActivityEventRead:
    return ActivityEventRead(
        id=event.id,
        workspace_code=event.workspace_code,
        domain_code=event.domain_code,
        actor_user_id=event.actor_user_id,
        actor_name=event.actor.display_name if event.actor else None,
        event_type=event.event_type,
        object_type=event.object_type,
        object_id=event.object_id,
        target_object_type=event.target_object_type,
        target_object_id=event.target_object_id,
        summary=event.summary,
        metadata_json=event.metadata_json,
        sync_policy=event.sync_policy,
        created_at=event.created_at,
    )


def _notification_target(event: ActivityEvent) -> tuple[str, str]:
    metadata = event.metadata_json or {}
    if event.target_object_type == "daily_report_item" or event.object_type == "daily_report_item":
        item_id = _metadata_string(metadata, "daily_report_item_id") or _event_target_id(event, "daily_report_item")
        query = {"item_id": item_id}
        comment_id = _metadata_string(metadata, "comment_id") or (event.object_id if event.object_type == "comment" else "")
        if comment_id:
            query["comment_id"] = comment_id
        return "进入日报", _query_path("/daily-reports", query)

    if event.target_object_type == "daily_report" or event.object_type == "daily_report":
        report_id = _metadata_string(metadata, "daily_report_id") or _event_target_id(event, "daily_report")
        return "进入日报", _query_path("/daily-reports", {"report_id": report_id})

    if event.target_object_type == "weekly_report_item" or event.object_type == "weekly_report_item":
        item_id = _metadata_string(metadata, "weekly_report_item_id") or _event_target_id(event, "weekly_report_item")
        return "进入周报条目", _query_path("/weekly-reports", {"item_id": item_id})

    if event.target_object_type == "weekly_report" or event.object_type == "weekly_report":
        report_id = _metadata_string(metadata, "weekly_report_id") or _event_target_id(event, "weekly_report")
        return "进入周报", _query_path("/weekly-reports", {"report_id": report_id})

    if event.event_type == "sync_conflict.created" or event.object_type == "sync_conflict":
        conflict_id = _metadata_string(metadata, "sync_conflict_id") or event.object_id
        return "查看同步", _query_path("/sync", {"conflict_id": conflict_id})

    if event.event_type.startswith("ingestion.failed_source_retry_") or event.target_object_type == "ingestion_run":
        run_id = _metadata_string(metadata, "ingestion_run_id") or _event_target_id(event, "ingestion_run")
        return "查看抓取", _query_path("/ingestion-runs", {"run_id": run_id})

    if event.event_type == "task.assigned" or event.target_object_type == "topic_task":
        task_id = _metadata_string(metadata, "topic_task_id") or _event_target_id(event, "topic_task")
        return "查看任务", _query_path("/tasks", {"task_id": task_id})

    if event.event_type == "requirement.status_changed" or event.target_object_type == "requirement":
        requirement_id = _metadata_string(metadata, "requirement_id") or _event_target_id(event, "requirement")
        return "查看需求", _query_path("/requirements", {"requirement_id": requirement_id})

    if event.event_type == "dedupe_group.adoption_changed" or event.target_object_type == "dedupe_group":
        group_id = _metadata_string(metadata, "dedupe_group_id") or _event_target_id(event, "dedupe_group")
        return "查看候选", _query_path("/news", {"dedupe_group_id": group_id})

    return "查看工作台", "/dashboard"


def _event_target_id(event: ActivityEvent, object_type: str) -> str:
    if event.target_object_type == object_type:
        return event.target_object_id
    if event.object_type == object_type:
        return event.object_id
    return event.target_object_id or event.object_id


def _metadata_string(metadata: dict, key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""


def _query_path(path: str, query: dict[str, str]) -> str:
    encoded = urlencode({key: value for key, value in query.items() if value})
    return f"{path}?{encoded}" if encoded else path
