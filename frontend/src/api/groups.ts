import { requestJson, requestVoid } from "./http";
import type { SessionUser } from "./auth";

export interface UserGroupRecord {
  id: string;
  code: string;
  name: string;
  description: string;
  member_count: number;
}

export interface UserGroupDetailRecord extends UserGroupRecord {
  members: SessionUser[];
}

export interface WorkspaceBulkJoinResult {
  workspace_code: string;
  group_code: string;
  workspace_role: string;
  added_count: number;
  reactivated_count: number;
  skipped_count: number;
  member_count: number;
}

export async function fetchUserGroups(): Promise<UserGroupRecord[]> {
  return requestJson<UserGroupRecord[]>("/api/user-groups");
}

export async function createUserGroup(payload: {
  code: string;
  name: string;
  description?: string;
}): Promise<UserGroupRecord> {
  return requestJson<UserGroupRecord>("/api/user-groups", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchUserGroup(code: string): Promise<UserGroupDetailRecord> {
  return requestJson<UserGroupDetailRecord>(`/api/user-groups/${code}`);
}

export async function deleteUserGroup(code: string): Promise<void> {
  await requestVoid(`/api/user-groups/${code}`, { method: "DELETE" });
}

export async function addUserGroupMember(code: string, userId: string): Promise<UserGroupDetailRecord> {
  return requestJson<UserGroupDetailRecord>(`/api/user-groups/${code}/members`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId })
  });
}

export async function removeUserGroupMember(code: string, userId: string): Promise<void> {
  await requestVoid(`/api/user-groups/${code}/members/${userId}`, { method: "DELETE" });
}

export async function bulkJoinWorkspaceByGroup(
  workspaceCode: string,
  payload: { group_code: string; workspace_role: string }
): Promise<WorkspaceBulkJoinResult> {
  return requestJson<WorkspaceBulkJoinResult>(`/api/workspaces/${workspaceCode}/members/bulk`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
