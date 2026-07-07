from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ActivityEventRead(BaseModel):
    id: str
    workspace_code: str
    domain_code: str
    actor_user_id: str | None
    actor_name: str | None
    event_type: str
    object_type: str
    object_id: str
    target_object_type: str
    target_object_id: str
    summary: str
    metadata_json: dict[str, Any]
    sync_policy: str
    created_at: datetime


class NotificationRead(BaseModel):
    id: str
    workspace_code: str
    status: str
    priority: str
    delivery_channel: str
    target_label: str
    target_path: str
    read_at: datetime | None
    created_at: datetime
    activity_event: ActivityEventRead


class NotificationUnreadCount(BaseModel):
    unread_count: int


class NotificationPreferenceRead(BaseModel):
    workspace_code: str
    event_type: str
    in_app_enabled: bool
    email_enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    workspace_code: str
    event_type: str
    in_app_enabled: bool
    email_enabled: bool = False


class ObjectWatcherRead(BaseModel):
    object_type: str
    object_id: str
    workspace_code: str
    watching: bool
    watcher_count: int


class ObjectWatcherUpdate(BaseModel):
    object_type: str
    object_id: str
    watching: bool
