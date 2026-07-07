import { requestJson } from "./http";
import type { InviteRecord, SessionUser, UserRole } from "./auth";

export interface RoleRecord {
  id: string;
  code: UserRole;
  name: string;
  description: string;
}

export interface PermissionChangeDiff {
  field: string;
  label: string;
  before: unknown;
  after: unknown;
  explanation: string;
}

export interface PermissionChangeRecord {
  id: string;
  action: string;
  object_type: string;
  object_id: string;
  actor_name: string | null;
  created_at: string;
  scope: string;
  title: string;
  summary: string;
  rollback_available: boolean;
  rollback_reason: string | null;
  diffs: PermissionChangeDiff[];
}

export interface PermissionRollbackResultItem {
  audit_log_id: string;
  status: string;
  message: string;
}

export async function fetchUsers(workspaceCode?: string): Promise<SessionUser[]> {
  const params = workspaceCode ? `?${new URLSearchParams({ workspace_code: workspaceCode }).toString()}` : "";
  return requestJson<SessionUser[]>(`/api/users${params}`);
}

export async function fetchRoles(): Promise<RoleRecord[]> {
  return requestJson<RoleRecord[]>("/api/roles");
}

export async function updateUserRoles(userId: string, roleCodes: UserRole[]): Promise<SessionUser> {
  return requestJson<SessionUser>(`/api/users/${userId}/roles`, {
    method: "PATCH",
    body: JSON.stringify({ role_codes: roleCodes })
  });
}

export async function fetchPermissionChanges(workspaceCode?: string): Promise<PermissionChangeRecord[]> {
  const params = new URLSearchParams({ limit: "30" });
  if (workspaceCode) {
    params.set("workspace_code", workspaceCode);
  }
  return requestJson<PermissionChangeRecord[]>(`/api/identity/permission-changes?${params.toString()}`);
}

export async function rollbackPermissionChanges(payload: {
  audit_log_ids: string[];
  confirm_dangerous_change?: boolean;
}): Promise<{ results: PermissionRollbackResultItem[] }> {
  return requestJson<{ results: PermissionRollbackResultItem[] }>("/api/identity/permission-rollbacks", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function patchUser(
  userId: string,
  payload: { is_active?: boolean; display_name?: string; department?: string; email?: string }
): Promise<SessionUser> {
  return requestJson<SessionUser>(`/api/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function resetUserPassword(userId: string): Promise<{ temporary_password: string }> {
  return requestJson<{ temporary_password: string }>(`/api/users/${userId}/reset-password`, {
    method: "POST"
  });
}

export async function fetchInvites(): Promise<InviteRecord[]> {
  return requestJson<InviteRecord[]>("/api/auth/invites");
}

export async function createInvite(payload: {
  email?: string;
  role_code: UserRole;
  workspaces: { code: string; workspace_role: string }[];
  expires_in_days: number;
}): Promise<InviteRecord> {
  return requestJson<InviteRecord>("/api/auth/invites", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function revokeInvite(code: string): Promise<InviteRecord> {
  return requestJson<InviteRecord>(`/api/auth/invites/${code}/revoke`, {
    method: "POST"
  });
}
