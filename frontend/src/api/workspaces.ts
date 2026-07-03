export interface WorkspaceRecord {
  code: string;
  name: string;
  description: string;
  workspace_type: string;
  default_domain_code: string;
  enabled: boolean;
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
  payload: { user_id: string; workspace_role: string }
): Promise<WorkspaceMemberRecord> {
  return requestJson<WorkspaceMemberRecord>(`/api/workspaces/${workspaceCode}/members`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function removeWorkspaceMember(workspaceCode: string, userId: string): Promise<void> {
  const response = await fetch(`/api/workspaces/${workspaceCode}/members/${userId}`, {
    method: "DELETE",
    credentials: "same-origin"
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
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
