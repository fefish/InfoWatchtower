import { requestJson, requestVoid } from "./http";

export interface WorkspaceRecord {
  code: string;
  name: string;
  description: string;
  workspace_type: string;
  default_domain_code: string;
  enabled: boolean;
  current_user_workspace_role?: string | null;
}

export interface WorkspaceSectionRecord {
  section_key: string;
  name: string;
  section_type: string;
  route_path: string;
  sort_order: number;
  group: string;
}

export interface WorkspaceLabelPolicy {
  workspace_code: string;
  label_set_code: string;
  news_format_code: string;
  export_category_mode: string;
  required_content_fields: string[];
  allowed_primary_categories: string[];
  secondary_labels_by_primary: Record<string, string[]>;
  default_category: string;
  fallback_category: string;
  tagging_stages: string[];
}

export interface WorkspaceLabelPolicyUpdate {
  label_set_code: string;
  news_format_code: string;
  export_category_mode: string;
  required_content_fields: string[];
  allowed_primary_categories: string[];
  secondary_labels_by_primary: Record<string, string[]>;
  default_category: string;
  fallback_category: string;
}

export interface WorkspaceFeedbackPolicy {
  workspace_code: string;
  viewer_can_react: boolean;
  viewer_can_rate: boolean;
  viewer_can_comment: boolean;
  viewer_can_edit: boolean;
  notify_on_comment: boolean;
  notify_on_publish: boolean;
}

export interface WorkspaceFeedbackPolicyUpdate {
  viewer_can_react: boolean;
  viewer_can_rate: boolean;
  viewer_can_comment: boolean;
  viewer_can_edit: boolean;
  notify_on_comment: boolean;
  notify_on_publish: boolean;
}

export interface WorkspaceDepartmentMembershipTarget {
  department: string;
  workspace_role: string;
}

export interface WorkspaceAuthMembershipMapping {
  workspace_code: string;
  department_workspaces: WorkspaceDepartmentMembershipTarget[];
}

export interface WorkspaceUpdatePayload {
  name?: string;
  description?: string;
  enabled?: boolean;
  default_domain_code?: string;
}

export interface WorkspaceMemberRecord {
  user: {
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
    roles: string[];
  };
  workspace_role: string;
  enabled: boolean;
}

export interface WorkspaceCreatePayload {
  code: string;
  name: string;
  description: string;
  workspace_type?: string;
  default_domain_code?: string;
}

export async function fetchWorkspaces(): Promise<WorkspaceRecord[]> {
  return requestJson<WorkspaceRecord[]>("/api/workspaces");
}

export async function createWorkspace(payload: WorkspaceCreatePayload): Promise<WorkspaceRecord> {
  return requestJson<WorkspaceRecord>("/api/workspaces", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function updateWorkspace(
  workspaceCode: string,
  payload: WorkspaceUpdatePayload
): Promise<WorkspaceRecord> {
  return requestJson<WorkspaceRecord>(`/api/workspaces/${workspaceCode}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function fetchWorkspaceMembers(workspaceCode: string): Promise<WorkspaceMemberRecord[]> {
  return requestJson<WorkspaceMemberRecord[]>(`/api/workspaces/${workspaceCode}/members`);
}

export async function upsertWorkspaceMember(
  workspaceCode: string,
  payload: { user_id: string; workspace_role: string; confirm_dangerous_change?: boolean }
): Promise<WorkspaceMemberRecord> {
  return requestJson<WorkspaceMemberRecord>(`/api/workspaces/${workspaceCode}/members`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function removeWorkspaceMember(
  workspaceCode: string,
  userId: string,
  options: { confirmDangerousChange?: boolean } = {}
): Promise<void> {
  const params = new URLSearchParams();
  if (options.confirmDangerousChange) {
    params.set("confirm_dangerous_change", "true");
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  await requestVoid(`/api/workspaces/${workspaceCode}/members/${userId}${suffix}`, {
    method: "DELETE"
  });
}

export async function fetchWorkspaceAuthMembershipMapping(
  workspaceCode: string
): Promise<WorkspaceAuthMembershipMapping> {
  return requestJson<WorkspaceAuthMembershipMapping>(`/api/workspaces/${workspaceCode}/auth-membership-mapping`);
}

export async function updateWorkspaceAuthMembershipMapping(
  workspaceCode: string,
  payload: { department_workspaces: WorkspaceDepartmentMembershipTarget[] }
): Promise<WorkspaceAuthMembershipMapping> {
  return requestJson<WorkspaceAuthMembershipMapping>(`/api/workspaces/${workspaceCode}/auth-membership-mapping`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function fetchWorkspaceSections(workspaceCode: string): Promise<WorkspaceSectionRecord[]> {
  return requestJson<WorkspaceSectionRecord[]>(`/api/workspaces/${workspaceCode}/sections`);
}

export async function fetchWorkspaceLabelPolicy(workspaceCode: string): Promise<WorkspaceLabelPolicy> {
  return requestJson<WorkspaceLabelPolicy>(`/api/workspaces/${workspaceCode}/label-policy`);
}

export async function updateWorkspaceLabelPolicy(
  workspaceCode: string,
  payload: WorkspaceLabelPolicyUpdate
): Promise<WorkspaceLabelPolicy> {
  return requestJson<WorkspaceLabelPolicy>(`/api/workspaces/${workspaceCode}/label-policy`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function fetchWorkspaceFeedbackPolicy(workspaceCode: string): Promise<WorkspaceFeedbackPolicy> {
  return requestJson<WorkspaceFeedbackPolicy>(`/api/workspaces/${workspaceCode}/feedback-policy`);
}

export async function updateWorkspaceFeedbackPolicy(
  workspaceCode: string,
  payload: WorkspaceFeedbackPolicyUpdate
): Promise<WorkspaceFeedbackPolicy> {
  return requestJson<WorkspaceFeedbackPolicy>(`/api/workspaces/${workspaceCode}/feedback-policy`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}
