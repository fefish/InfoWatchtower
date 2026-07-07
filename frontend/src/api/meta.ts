import { requestJson } from "./http";

export type DeployMode = "standalone" | "cloud" | "intranet" | "extranet";

export interface RuntimeCapabilities {
  ingestion: boolean;
  sync_publisher: boolean;
  sync_consumer: boolean;
  embedding: boolean;
  search: boolean;
}

export interface AuthWorkspaceTarget {
  workspace_code: string;
  workspace_role: string;
}

export interface AuthDepartmentWorkspaceTarget extends AuthWorkspaceTarget {
  department: string;
}

export interface AuthMembershipMapping {
  status: "empty" | "configured" | "invalid";
  default_workspaces: AuthWorkspaceTarget[];
  department_workspaces: AuthDepartmentWorkspaceTarget[];
  error?: string;
}

export interface RuntimeRecord {
  deploy_mode: DeployMode;
  instance_id: string;
  capabilities: RuntimeCapabilities;
  auth_mode: string;
  auth_membership_mapping: AuthMembershipMapping;
  app_version: string;
}

export async function fetchRuntime(): Promise<RuntimeRecord> {
  return requestJson<RuntimeRecord>("/api/meta/runtime");
}
