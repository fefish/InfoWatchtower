export interface WorkspaceRecord {
  code: string;
  name: string;
  description: string;
  workspace_type: string;
  default_domain_code: string;
}

export interface WorkspaceSectionRecord {
  section_key: string;
  name: string;
  section_type: string;
  route_path: string;
  sort_order: number;
}

export interface WorkspaceLabelPolicy {
  workspace_code: string;
  label_set_code: string;
  allowed_primary_categories: string[];
  default_category: string;
  fallback_category: string;
  tagging_stages: string[];
}

export interface WorkspaceLabelPolicyUpdate {
  label_set_code: string;
  allowed_primary_categories: string[];
  default_category: string;
  fallback_category: string;
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

export async function fetchWorkspaces(): Promise<WorkspaceRecord[]> {
  return requestJson<WorkspaceRecord[]>("/api/workspaces");
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
