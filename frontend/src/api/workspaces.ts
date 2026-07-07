import { requestJson, requestVoid } from "./http";

export interface WorkspaceRecord {
  code: string;
  name: string;
  description: string;
  workspace_type: string;
  default_domain_code: string;
  enabled: boolean;
  // private（仅成员可见）| internal_public（可被发现/订阅，游客可只读浏览）
  visibility?: string;
  current_user_workspace_role?: string | null;
}

export interface WorkspaceSectionRecord {
  section_key: string;
  name: string;
  section_type: string;
  route_path: string;
  sort_order: number;
  group: string;
  // 分区可见的最低工作台角色（viewer/member/admin/owner）：
  // 阅读分区（日报/周报/历史报告/实体大事记）为 viewer，管理分区默认 member。
  min_role: string;
}

export interface WorkspaceReportPolicy {
  workspace_code: string;
  auto_publish_daily: boolean;
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

// 导航分区管理视图（workspace admin+）：包含已停用可选模块与核心分区标记，
// 供工作台配置中心的启停 UI 使用。
export interface WorkspaceSectionManageRecord {
  section_key: string;
  name: string;
  group: string;
  sort_order: number;
  enabled: boolean;
  core: boolean;
}

export async function fetchWorkspaceSectionsManage(
  workspaceCode: string
): Promise<WorkspaceSectionManageRecord[]> {
  return requestJson<WorkspaceSectionManageRecord[]>(`/api/workspaces/${workspaceCode}/sections/manage`);
}

export async function updateWorkspaceSection(
  workspaceCode: string,
  sectionKey: string,
  payload: { enabled: boolean }
): Promise<{ section_key: string; name: string; enabled: boolean }> {
  return requestJson<{ section_key: string; name: string; enabled: boolean }>(
    `/api/workspaces/${workspaceCode}/sections/${sectionKey}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload)
    }
  );
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

export async function fetchWorkspaceReportPolicy(workspaceCode: string): Promise<WorkspaceReportPolicy> {
  return requestJson<WorkspaceReportPolicy>(`/api/workspaces/${workspaceCode}/report-policy`);
}

export async function updateWorkspaceReportPolicy(
  workspaceCode: string,
  payload: { auto_publish_daily: boolean }
): Promise<WorkspaceReportPolicy> {
  return requestJson<WorkspaceReportPolicy>(`/api/workspaces/${workspaceCode}/report-policy`, {
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

// --- 工作台发现与自助订阅（visibility=internal_public） ---

export interface DiscoverableWorkspaceRecord {
  code: string;
  name: string;
  description: string;
  member_count: number;
  // 当前用户是否已有 membership（游客恒为 false：游客按隐式 viewer 视角浏览）
  joined: boolean;
  workspace_role: string | null;
}

export async function fetchDiscoverableWorkspaces(): Promise<DiscoverableWorkspaceRecord[]> {
  return requestJson<DiscoverableWorkspaceRecord[]>("/api/workspaces/discover");
}

export interface WorkspaceSubscriptionRecord {
  workspace_code: string;
  workspace_role: string;
  subscribed: boolean;
}

export async function subscribeWorkspace(workspaceCode: string): Promise<WorkspaceSubscriptionRecord> {
  return requestJson<WorkspaceSubscriptionRecord>(`/api/workspaces/${workspaceCode}/subscribe`, {
    method: "POST"
  });
}

export async function unsubscribeWorkspace(workspaceCode: string): Promise<void> {
  await requestVoid(`/api/workspaces/${workspaceCode}/subscribe`, { method: "DELETE" });
}

export async function updateWorkspaceVisibility(
  workspaceCode: string,
  visibility: "private" | "internal_public"
): Promise<WorkspaceRecord> {
  return requestJson<WorkspaceRecord>(`/api/workspaces/${workspaceCode}/visibility`, {
    method: "PATCH",
    body: JSON.stringify({ visibility })
  });
}
