import type { InviteRecord, SessionUser, UserRole } from "./auth";

export interface RoleRecord {
  id: string;
  code: UserRole;
  name: string;
  description: string;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
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
