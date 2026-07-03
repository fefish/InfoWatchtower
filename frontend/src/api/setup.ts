import type { AuthResponse } from "./auth";

export interface SetupStatus {
  needs_setup: boolean;
}

export interface SetupCreatePayload {
  username: string;
  display_name: string;
  password: string;
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

export async function fetchSetupStatus(): Promise<SetupStatus> {
  return requestJson<SetupStatus>("/api/setup/status");
}

export async function createSetupAdmin(payload: SetupCreatePayload): Promise<AuthResponse> {
  return requestJson<AuthResponse>("/api/setup", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
