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

// 可选 q：对 name/description 做大小写不敏感 contains 过滤；过滤范围仍严格限于
// internal_public，private 工作台任何关键词都不出现（workspace-configuration-design §14.1）。
export async function fetchDiscoverableWorkspaces(q?: string): Promise<DiscoverableWorkspaceRecord[]> {
  const keyword = (q ?? "").trim();
  const suffix = keyword ? `?q=${encodeURIComponent(keyword)}` : "";
  return requestJson<DiscoverableWorkspaceRecord[]>(`/api/workspaces/discover${suffix}`);
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

// --- 工作台加入码（workspace-configuration-design §14，契约 workspace_model.json join_code） ---
// 与全局邀请码互补：加入码面向已注册用户的团队自助入台，只授 viewer/member、
// 不建号、不改全局角色；每台至多一个 active 码，「轮换」= 旧码即刻失效 + 新码生成。

export interface WorkspaceJoinCodeRecord {
  code: string;
  default_role: string;
  expires_at: string | null;
  max_uses: number | null;
  use_count: number;
  created_at: string;
  created_by: string | null;
}

export interface WorkspaceJoinCodeCreatePayload {
  default_role?: "viewer" | "member";
  expires_in_days?: number | null;
  max_uses?: number | null;
}

/** 当前 active 加入码；无码时后端返回 null（workspace admin/owner 可读）。 */
export async function fetchWorkspaceJoinCode(
  workspaceCode: string
): Promise<WorkspaceJoinCodeRecord | null> {
  return requestJson<WorkspaceJoinCodeRecord | null>(`/api/workspaces/${workspaceCode}/join-code`);
}

/** 生成加入码；已有 active 码时视为轮换（旧码同事务置 disabled，UI 需先确认）。 */
export async function createWorkspaceJoinCode(
  workspaceCode: string,
  payload: WorkspaceJoinCodeCreatePayload = {}
): Promise<WorkspaceJoinCodeRecord> {
  return requestJson<WorkspaceJoinCodeRecord>(`/api/workspaces/${workspaceCode}/join-code`, {
    method: "POST",
    body: JSON.stringify({ default_role: payload.default_role ?? "viewer", ...payload })
  });
}

/** 幂等停用当前 active 码（无 active 码同样 204）。 */
export async function disableWorkspaceJoinCode(workspaceCode: string): Promise<void> {
  await requestVoid(`/api/workspaces/${workspaceCode}/join-code`, { method: "DELETE" });
}

export interface WorkspaceJoinByCodeRecord {
  workspace_code: string;
  workspace_name: string;
  workspace_role: string;
  // 本次是否真实新增或重新启用 membership（已是 enabled 成员时 false，幂等不降级）
  joined: boolean;
}

/** 凭码加入：失效码统一 400「加入码无效或已失效」（防枚举），连续失败 429 限流。 */
export async function joinWorkspaceByCode(code: string): Promise<WorkspaceJoinByCodeRecord> {
  return requestJson<WorkspaceJoinByCodeRecord>("/api/workspaces/join-by-code", {
    method: "POST",
    body: JSON.stringify({ code })
  });
}
