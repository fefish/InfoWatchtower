import { requestJson } from "./http";

export type WatchableObjectType = "daily_report_item" | "weekly_report_item" | "dedupe_group";

export interface ObjectWatcherRecord {
  object_type: WatchableObjectType;
  object_id: string;
  workspace_code: string;
  watching: boolean;
  watcher_count: number;
}

export async function fetchObjectWatcher(
  objectType: WatchableObjectType,
  objectId: string
): Promise<ObjectWatcherRecord> {
  const params = new URLSearchParams({
    object_type: objectType,
    object_id: objectId
  });
  return requestJson<ObjectWatcherRecord>(`/api/object-watchers?${params.toString()}`);
}

export async function updateObjectWatcher(
  objectType: WatchableObjectType,
  objectId: string,
  watching: boolean
): Promise<ObjectWatcherRecord> {
  return requestJson<ObjectWatcherRecord>("/api/object-watchers", {
    method: "PATCH",
    body: JSON.stringify({
      object_type: objectType,
      object_id: objectId,
      watching
    })
  });
}
