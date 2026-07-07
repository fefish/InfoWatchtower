import { apiUrl, requestJson, requestRaw } from "./http";

export type UserRole = "super_admin" | "editor_admin" | "analyst" | "viewer";

export interface SessionUser {
  id: string;
  external_provider: string;
  external_id: string;
  employee_no: string | null;
  username: string;
  display_name: string;
  department: string | null;
  email: string | null;
  status: string;
  is_active: boolean;
  roles: UserRole[];
}

export interface AuthResponse {
  user: SessionUser;
}

export interface InviteWorkspaceTarget {
  code: string;
  workspace_role: string;
}

export interface InviteRecord {
  id: string;
  code: string;
  email: string | null;
  role_code: UserRole;
  workspaces: InviteWorkspaceTarget[];
  invite_url: string;
  status: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

export interface InvitePublicRecord {
  code: string;
  email_hint: string | null;
  role_code: UserRole;
  workspaces: InviteWorkspaceTarget[];
  status: string;
  expires_at: string;
}

async function requestAuth(path: string, init?: RequestInit): Promise<AuthResponse> {
  return requestJson<AuthResponse>(path, init);
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  return requestAuth("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
}

// 游客登录（AUTH_GUEST_ENABLED）：签发共享只读 guest 会话，
// 会话用户 external_provider === "guest"（session store 以此识别游客）。
export async function guestLogin(): Promise<AuthResponse> {
  return requestAuth("/api/auth/guest-login", { method: "POST" });
}

export function startOidcLogin(nextPath = ""): void {
  const nextQuery = nextPath ? `?next=${encodeURIComponent(nextPath)}` : "";
  window.location.assign(apiUrl(`/api/auth/oidc/start${nextQuery}`));
}

export async function forgotPassword(username: string): Promise<void> {
  await requestAuth("/api/auth/password/forgot", {
    method: "POST",
    body: JSON.stringify({ username })
  });
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<AuthResponse> {
  return requestAuth("/api/auth/password/change", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
  });
}

export async function fetchInvite(code: string): Promise<InvitePublicRecord> {
  return requestJson<InvitePublicRecord>(`/api/auth/invites/${code}`);
}

export async function acceptInvite(
  code: string,
  payload: { username: string; display_name: string; password: string }
): Promise<AuthResponse> {
  return requestAuth(`/api/auth/invites/${code}/accept`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function fetchMe(): Promise<AuthResponse> {
  return requestAuth("/api/auth/me");
}

export interface ProfileUpdatePayload {
  display_name?: string;
  department?: string;
  email?: string;
}

/**
 * 本地账号资料自助编辑（identity-access-design §4.4，契约 auth_modes.json
 * profile_self_service）：只有 display_name/department/email 三字段可改；
 * 外部身份后端返回 400「Profile is managed externally」，游客被中央写门禁 403。
 */
export async function updateProfile(payload: ProfileUpdatePayload): Promise<AuthResponse> {
  return requestAuth("/api/auth/me", {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function logout(): Promise<void> {
  // 401 视为已登出，不抛错；其余失败仍上抛，交由调用方提示。
  const response = await requestRaw("/api/auth/logout", { method: "POST" });
  if (!response.ok && response.status !== 401) {
    throw new Error(`Logout failed: ${response.status}`);
  }
}
