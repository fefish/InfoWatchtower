import { requestJson } from "./http";

export interface ActivityEventRecord {
  id: string;
  workspace_code: string;
  domain_code: string;
  actor_user_id: string | null;
  actor_name: string | null;
  event_type: string;
  object_type: string;
  object_id: string;
  target_object_type: string;
  target_object_id: string;
  summary: string;
  metadata_json: Record<string, unknown>;
  sync_policy: string;
  created_at: string;
}

export interface NotificationRecord {
  id: string;
  workspace_code: string;
  status: string;
  priority: string;
  delivery_channel: string;
  target_label: string;
  target_path: string;
  read_at: string | null;
  created_at: string;
  activity_event: ActivityEventRecord;
}

export interface NotificationUnreadCount {
  unread_count: number;
}

export interface NotificationPreferenceRecord {
  workspace_code: string;
  event_type: string;
  in_app_enabled: boolean;
  email_enabled: boolean;
}

export type NotificationStatusFilter = "unread" | "read" | "archived" | "all";

export async function fetchActivityEvents(workspaceCode: string, limit = 50): Promise<ActivityEventRecord[]> {
  const params = new URLSearchParams({
    workspace_code: workspaceCode,
    limit: String(limit)
  });
  return requestJson<ActivityEventRecord[]>(`/api/activity-events?${params.toString()}`);
}

export async function fetchNotifications(
  status: NotificationStatusFilter = "unread",
  limit = 20
): Promise<NotificationRecord[]> {
  const params = new URLSearchParams({
    status,
    limit: String(limit)
  });
  return requestJson<NotificationRecord[]>(`/api/notifications?${params.toString()}`);
}

export async function fetchUnreadNotificationCount(): Promise<NotificationUnreadCount> {
  return requestJson<NotificationUnreadCount>("/api/notifications/unread-count");
}

export async function markNotificationRead(notificationId: string): Promise<NotificationRecord> {
  return requestJson<NotificationRecord>(`/api/notifications/${notificationId}/read`, {
    method: "POST"
  });
}

export async function archiveNotification(notificationId: string): Promise<NotificationRecord> {
  return requestJson<NotificationRecord>(`/api/notifications/${notificationId}/archive`, {
    method: "POST"
  });
}

export async function markAllNotificationsRead(): Promise<NotificationUnreadCount> {
  return requestJson<NotificationUnreadCount>("/api/notifications/read-all", {
    method: "POST"
  });
}

export async function fetchNotificationPreferences(workspaceCode: string): Promise<NotificationPreferenceRecord[]> {
  const params = new URLSearchParams({ workspace_code: workspaceCode });
  return requestJson<NotificationPreferenceRecord[]>(`/api/notification-preferences?${params.toString()}`);
}

export async function updateNotificationPreference(
  payload: NotificationPreferenceRecord
): Promise<NotificationPreferenceRecord> {
  return requestJson<NotificationPreferenceRecord>("/api/notification-preferences", {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}
