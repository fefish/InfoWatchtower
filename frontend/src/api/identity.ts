import type { SessionUser, UserRole } from "./auth";

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

export async function fetchUsers(): Promise<SessionUser[]> {
  return requestJson<SessionUser[]>("/api/users");
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
