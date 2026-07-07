import { requestJson } from "./http";
import type { AuthResponse } from "./auth";

export interface SetupStatus {
  needs_setup: boolean;
}

export interface SetupCreatePayload {
  username: string;
  display_name: string;
  password: string;
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
