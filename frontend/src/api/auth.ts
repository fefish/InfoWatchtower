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
  roles: UserRole[];
}

export interface AuthResponse {
  user: SessionUser;
}

async function requestAuth(path: string, init?: RequestInit): Promise<AuthResponse> {
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
  return response.json() as Promise<AuthResponse>;
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  return requestAuth("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
}

export async function fetchMe(): Promise<AuthResponse> {
  return requestAuth("/api/auth/me");
}

export async function logout(): Promise<void> {
  const response = await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin"
  });
  if (!response.ok && response.status !== 401) {
    throw new Error(`Logout failed: ${response.status}`);
  }
}
