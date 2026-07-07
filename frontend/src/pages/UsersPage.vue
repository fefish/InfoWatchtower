<script setup lang="ts">
import { Ban, Copy, KeyRound, Plus, RefreshCw, RotateCcw, Save, ShieldCheck, Trash2, UserPlus } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";

import type { InviteRecord, SessionUser, UserRole } from "../api/auth";
import {
  createInvite,
  fetchPermissionChanges,
  fetchInvites,
  fetchRoles,
  fetchUsers,
  patchUser,
  rollbackPermissionChanges,
  resetUserPassword,
  revokeInvite,
  updateUserRoles,
  type PermissionChangeRecord,
  type RoleRecord
} from "../api/identity";
import { fetchAuditLogs, type AuditLogRecord } from "../api/operations";
import {
  fetchWorkspaceAuthMembershipMapping,
  fetchWorkspaceFeedbackPolicy,
  fetchWorkspaceMembers,
  removeWorkspaceMember,
  updateWorkspaceAuthMembershipMapping,
  type WorkspaceAuthMembershipMapping,
  updateWorkspaceFeedbackPolicy,
  type WorkspaceDepartmentMembershipTarget,
  type WorkspaceFeedbackPolicy,
  type WorkspaceFeedbackPolicyUpdate,
  upsertWorkspaceMember,
  type WorkspaceMemberRecord
} from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const session = useSessionStore();
const runtime = useRuntimeStore();
const workspace = useWorkspaceStore();
const users = ref<SessionUser[]>([]);
const roles = ref<RoleRecord[]>([]);
const invites = ref<InviteRecord[]>([]);
const members = ref<WorkspaceMemberRecord[]>([]);
const auditLogs = ref<AuditLogRecord[]>([]);
const permissionChanges = ref<PermissionChangeRecord[]>([]);
const selectedPermissionRollbackIds = ref<string[]>([]);
const selectedRoles = reactive<Record<string, Set<UserRole>>>({});
const memberRoleDrafts = reactive<Record<string, string>>({});
const dangerousMemberConfirmations = reactive<Record<string, boolean>>({});
const activeTab = ref<"users" | "invites" | "members" | "policies">("users");
const loading = ref(false);
const savingUserId = ref("");
const error = ref("");
const notice = ref("");
const temporaryPassword = ref("");
const savingMember = ref(false);
const savingFeedbackPolicy = ref(false);
const savingAuthMapping = ref(false);
const rollingBackPermissions = ref(false);
const feedbackPolicyConfirmed = ref(false);
const authMappingConfirmed = ref(false);
const rollbackConfirmDangerous = ref(false);
const inviteForm = reactive({
  email: "",
  role_code: "viewer" as UserRole,
  workspace_code: "",
  workspace_role: "member",
  expires_in_days: 7
});
const memberForm = reactive({
  user_id: "",
  workspace_role: "member"
});
const feedbackPolicy = reactive<WorkspaceFeedbackPolicyUpdate>({
  viewer_can_react: true,
  viewer_can_rate: true,
  viewer_can_comment: true,
  viewer_can_edit: false,
  notify_on_comment: true,
  notify_on_publish: false
});
const lastSavedFeedbackPolicy = ref<WorkspaceFeedbackPolicyUpdate | null>(null);
const authMappingRows = ref<WorkspaceDepartmentMembershipTarget[]>([]);
const lastSavedAuthMappingRows = ref<WorkspaceDepartmentMembershipTarget[]>([]);
const authMappingForm = reactive({
  department: "",
  workspace_role: "viewer"
});
const isSuperAdmin = computed(() => session.user?.roles.includes("super_admin") ?? false);
const memberUserOptions = computed(() =>
  users.value.filter((user) => !members.value.some((member) => member.user.id === user.id))
);
const authModeLabel = computed(() => {
  const labels: Record<string, string> = {
    local: "本地开发账号",
    public_password: "公网账号密码",
    oidc: "OIDC / SSO",
    intranet_header: "内网可信 Header"
  };
  return labels[runtime.authMode] || runtime.authMode || "未加载";
});
const noticeMessage = computed(() => (notice.value.startsWith("http") ? `邀请链接：${notice.value}` : notice.value));
const globalRoleRows = computed(() => {
  if (roles.value.length > 0) {
    return roles.value.map((role) => ({
      code: role.code,
      name: role.name,
      description: role.description
    }));
  }
  return [
    { code: "super_admin", name: "super_admin", description: "实例级管理、用户权限、部署同步 token、全局审计。" },
    { code: "editor_admin", name: "editor_admin", description: "内容生产管理者，可被加入多个工作台。" },
    { code: "analyst", name: "analyst", description: "分析成员，可参与内容研判。" },
    { code: "viewer", name: "viewer", description: "浏览者，默认只读。" }
  ];
});
const workspaceRoleRows = [
  { role: "owner", scope: "工作台最高权限，可管理成员和策略。", min: "owner" },
  { role: "admin", scope: "工作台配置、源管理、抓取、推荐、发布。", min: "admin" },
  { role: "member", scope: "采编协作、日报/周报编辑、评论、评分。", min: "member" },
  { role: "viewer", scope: "只读；反馈能力由当前工作台 feedback_policy 控制。", min: "viewer" }
];
const workspaceRoleImpactRows: Record<string, { title: string; description: string }> = {
  owner: {
    title: "owner 会获得工作台最高权限",
    description: "可管理成员、策略和工作台关键配置；至少保留 1 名 owner。"
  },
  admin: {
    title: "admin 可管理工作台生产配置",
    description: "可维护源、抓取、推荐、发布和工作台策略，但不能移除最后 owner。"
  },
  member: {
    title: "member 可参与采编协作",
    description: "可编辑日报/周报、评论、评分和处理采信，不具备成员管理权限。"
  },
  viewer: {
    title: "viewer 默认只读",
    description: "可浏览内容；评论、点赞、评分取决于当前工作台 feedback_policy。"
  }
};
const policyGapRows = [
  "OIDC claims 字段名仍由部署配置管理，真实 provider 接入需要保留验收证据。",
  "跨实例同步环境下，权限回滚只作用于当前本地库，不进入公网/内网 feed。"
];
const inviteStatusLabels: Record<string, string> = {
  accepted: "已接受",
  expired: "已过期",
  pending: "待接受",
  revoked: "已撤销"
};
const ownerCount = computed(() => members.value.filter((member) => member.workspace_role === "owner").length);
const selectedWorkspaceRoleImpact = computed(
  () => workspaceRoleImpactRows[memberForm.workspace_role] ?? workspaceRoleImpactRows.member
);
const authDefaultWorkspaceRows = computed(() => runtime.authMembershipMapping.default_workspaces);
const authDepartmentWorkspaceRows = computed(() => runtime.authMembershipMapping.department_workspaces);
const hasAuthMembershipMapping = computed(
  () => authDefaultWorkspaceRows.value.length > 0 || authDepartmentWorkspaceRows.value.length > 0
);
const currentWorkspaceRole = computed(() => {
  if (isSuperAdmin.value) {
    return "super_admin";
  }
  return members.value.find((member) => member.user.id === session.user?.id)?.workspace_role ?? "";
});
const canEditFeedbackPolicy = computed(
  () => isSuperAdmin.value || ["owner", "admin"].includes(currentWorkspaceRole.value)
);
const feedbackPolicyDirty = computed(() => {
  if (!lastSavedFeedbackPolicy.value) {
    return false;
  }
  return JSON.stringify(feedbackPolicyPayload()) !== JSON.stringify(lastSavedFeedbackPolicy.value);
});
const authMappingDirty = computed(
  () => JSON.stringify(authMappingRows.value) !== JSON.stringify(lastSavedAuthMappingRows.value)
);
const feedbackPolicyImpactLine = computed(() => {
  const disabled = [
    !feedbackPolicy.viewer_can_react ? "点赞" : "",
    !feedbackPolicy.viewer_can_rate ? "评分" : "",
    !feedbackPolicy.viewer_can_comment ? "评论" : ""
  ].filter(Boolean);
  if (disabled.length === 0) {
    return "viewer 可继续点赞、评分和评论；member 及以上不受影响。";
  }
  return `保存后 viewer 将不能${disabled.join("、")}；member 及以上仍可协作，后端会同步按策略拦截。`;
});
const identityAuditActions = [
  "invite.accept",
  "invite.create",
  "invite.revoke",
  "password.admin_reset",
  "password.change",
  "password.forgot",
  "password.reset",
  "workspace.auth_membership_mapping.update",
  "identity.permission_rollback",
  "users.patch",
  "users.roles.update",
  "workspace.feedback_policy.update",
  "workspace.member.remove",
  "workspace.member.upsert"
];
const identityAuditLogs = computed(() =>
  auditLogs.value
    .filter((log) => identityAuditActions.includes(log.action))
    .slice(0, 6)
);

async function loadData() {
  loading.value = true;
  error.value = "";
  try {
    await workspace.loadWorkspaces();
    await runtime.load();
    if (!isSuperAdmin.value && !["members", "policies"].includes(activeTab.value)) {
      activeTab.value = "members";
    }
    const [
      nextUsers,
      nextRoles,
      nextInvites,
      nextMembers,
      nextFeedbackPolicy,
      nextAuthMapping,
      nextPermissionChanges
    ] = await Promise.all([
      fetchUsers(isSuperAdmin.value ? undefined : workspace.currentCode),
      isSuperAdmin.value ? fetchRoles() : Promise.resolve([]),
      isSuperAdmin.value ? fetchInvites() : Promise.resolve([]),
      workspace.currentCode ? fetchWorkspaceMembers(workspace.currentCode) : Promise.resolve([]),
      workspace.currentCode ? fetchWorkspaceFeedbackPolicy(workspace.currentCode) : Promise.resolve(null),
      isSuperAdmin.value && workspace.currentCode
        ? fetchWorkspaceAuthMembershipMapping(workspace.currentCode)
        : Promise.resolve(null),
      isSuperAdmin.value ? fetchPermissionChanges(workspace.currentCode || undefined) : Promise.resolve([])
    ]);
    auditLogs.value = isSuperAdmin.value ? await fetchAuditLogs({ limit: 80 }) : [];
    users.value = nextUsers;
    roles.value = nextRoles;
    invites.value = nextInvites;
    members.value = nextMembers;
    applyMemberRoleDrafts(nextMembers);
    applyFeedbackPolicy(nextFeedbackPolicy);
    applyAuthMembershipMapping(nextAuthMapping);
    permissionChanges.value = nextPermissionChanges;
    selectedPermissionRollbackIds.value = selectedPermissionRollbackIds.value.filter((id) =>
      nextPermissionChanges.some((change) => change.id === id && change.rollback_available)
    );
    rollbackConfirmDangerous.value = false;
    for (const user of nextUsers) {
      selectedRoles[user.id] = new Set(user.roles);
    }
    if (!memberUserOptions.value.some((user) => user.id === memberForm.user_id)) {
      memberForm.user_id = memberUserOptions.value[0]?.id ?? "";
    }
    if (!workspace.options.some((item) => item.code === inviteForm.workspace_code)) {
      inviteForm.workspace_code = workspace.currentCode;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载用户权限失败";
  } finally {
    loading.value = false;
  }
}

async function loadWorkspaceMembers() {
  if (!workspace.currentCode) {
    members.value = [];
    return;
  }
  const [nextUsers, nextMembers] = await Promise.all([
    fetchUsers(isSuperAdmin.value ? undefined : workspace.currentCode),
    fetchWorkspaceMembers(workspace.currentCode)
  ]);
  users.value = nextUsers;
  members.value = nextMembers;
  applyMemberRoleDrafts(nextMembers);
  if (!memberUserOptions.value.some((user) => user.id === memberForm.user_id)) {
    memberForm.user_id = memberUserOptions.value[0]?.id ?? "";
  }
}

function applyMemberRoleDrafts(nextMembers: WorkspaceMemberRecord[]) {
  for (const member of nextMembers) {
    memberRoleDrafts[member.user.id] = member.workspace_role;
    dangerousMemberConfirmations[member.user.id] = false;
  }
}

function toggleRole(userId: string, role: UserRole, checked: boolean) {
  const current = selectedRoles[userId] ?? new Set<UserRole>();
  if (checked) {
    current.add(role);
  } else {
    current.delete(role);
  }
  selectedRoles[userId] = current;
}

async function saveUser(user: SessionUser) {
  savingUserId.value = user.id;
  error.value = "";
  try {
    const updated = await updateUserRoles(user.id, Array.from(selectedRoles[user.id] ?? []));
    users.value = users.value.map((item) => (item.id === updated.id ? updated : item));
    selectedRoles[updated.id] = new Set(updated.roles);
    await refreshPermissionChanges();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存角色失败";
  } finally {
    savingUserId.value = "";
  }
}

async function submitInvite() {
  error.value = "";
  notice.value = "";
  if (!inviteForm.workspace_code) {
    error.value = "请选择工作台";
    return;
  }
  try {
    const invite = await createInvite({
      email: inviteForm.email.trim() || undefined,
      role_code: inviteForm.role_code,
      workspaces: [{ code: inviteForm.workspace_code, workspace_role: inviteForm.workspace_role }],
      expires_in_days: Number(inviteForm.expires_in_days)
    });
    invites.value = [invite, ...invites.value];
    notice.value = invite.invite_url;
    await copyText(invite.invite_url);
    inviteForm.email = "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建邀请失败";
  }
}

async function revokeInviteRow(invite: InviteRecord) {
  error.value = "";
  try {
    const updated = await revokeInvite(invite.code);
    invites.value = invites.value.map((item) => (item.id === updated.id ? updated : item));
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "撤销邀请失败";
  }
}

async function resetPassword(user: SessionUser) {
  error.value = "";
  temporaryPassword.value = "";
  try {
    const result = await resetUserPassword(user.id);
    temporaryPassword.value = result.temporary_password;
    users.value = users.value.map((item) =>
      item.id === user.id ? { ...item, status: "must_change_password" } : item
    );
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "重置密码失败";
  }
}

async function toggleActive(user: SessionUser) {
  error.value = "";
  try {
    const updated = await patchUser(user.id, { is_active: !user.is_active });
    users.value = users.value.map((item) => (item.id === updated.id ? updated : item));
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新用户失败";
  }
}

async function submitMember() {
  if (!workspace.currentCode || !memberForm.user_id) {
    return;
  }
  savingMember.value = true;
  error.value = "";
  try {
    await upsertWorkspaceMember(workspace.currentCode, {
      user_id: memberForm.user_id,
      workspace_role: memberForm.workspace_role
    });
    await loadWorkspaceMembers();
    await refreshPermissionChanges();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存成员失败";
  } finally {
    savingMember.value = false;
  }
}

async function removeMember(member: WorkspaceMemberRecord) {
  if (!workspace.currentCode) {
    return;
  }
  if (isLastOwner(member)) {
    error.value = "最后一个 owner 不能移出工作台";
    return;
  }
  if (member.workspace_role === "owner" && !dangerousMemberConfirmations[member.user.id]) {
    error.value = "移出 owner 前请先确认危险权限变更";
    return;
  }
  savingMember.value = true;
  error.value = "";
  try {
    await removeWorkspaceMember(workspace.currentCode, member.user.id, {
      confirmDangerousChange: member.workspace_role === "owner"
    });
    await loadWorkspaceMembers();
    await refreshPermissionChanges();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "移除成员失败";
  } finally {
    savingMember.value = false;
  }
}

async function saveMemberRole(member: WorkspaceMemberRecord) {
  if (!workspace.currentCode) {
    return;
  }
  const nextRole = memberRoleDrafts[member.user.id] || member.workspace_role;
  if (nextRole === member.workspace_role) {
    return;
  }
  if (member.workspace_role === "owner" && nextRole !== "owner" && ownerCount.value <= 1) {
    error.value = "最后一个 owner 不能降权";
    return;
  }
  if (member.workspace_role === "owner" && nextRole !== "owner" && !dangerousMemberConfirmations[member.user.id]) {
    error.value = "调整 owner 角色前请先确认危险权限变更";
    return;
  }
  savingMember.value = true;
  error.value = "";
  try {
    await upsertWorkspaceMember(workspace.currentCode, {
      user_id: member.user.id,
      workspace_role: nextRole,
      confirm_dangerous_change: member.workspace_role === "owner" && nextRole !== "owner"
    });
    await loadWorkspaceMembers();
    await refreshPermissionChanges();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存成员角色失败";
  } finally {
    savingMember.value = false;
  }
}

function isLastOwner(member: WorkspaceMemberRecord) {
  return member.workspace_role === "owner" && ownerCount.value <= 1;
}

function isDangerousMemberChange(member: WorkspaceMemberRecord) {
  return member.workspace_role === "owner" && (memberRoleDrafts[member.user.id] || member.workspace_role) !== "owner";
}

function inviteStatusLabel(status: string) {
  return inviteStatusLabels[status] ?? status;
}

function inviteStatusHint(invite: InviteRecord) {
  if (invite.accepted_at) {
    return `接受于 ${invite.accepted_at}`;
  }
  if (invite.revoked_at) {
    return `撤销于 ${invite.revoked_at}`;
  }
  return `有效期至 ${invite.expires_at}`;
}

function auditDetailLine(log: AuditLogRecord) {
  const detail = JSON.stringify(log.detail_json || {});
  return detail === "{}" ? `${log.object_type} · ${log.object_id}` : detail;
}

function feedbackPolicyPayload(): WorkspaceFeedbackPolicyUpdate {
  return {
    viewer_can_react: feedbackPolicy.viewer_can_react,
    viewer_can_rate: feedbackPolicy.viewer_can_rate,
    viewer_can_comment: feedbackPolicy.viewer_can_comment,
    viewer_can_edit: false,
    notify_on_comment: feedbackPolicy.notify_on_comment,
    notify_on_publish: feedbackPolicy.notify_on_publish
  };
}

function applyFeedbackPolicy(policy: WorkspaceFeedbackPolicy | null) {
  if (!policy) {
    lastSavedFeedbackPolicy.value = null;
    return;
  }
  feedbackPolicy.viewer_can_react = policy.viewer_can_react;
  feedbackPolicy.viewer_can_rate = policy.viewer_can_rate;
  feedbackPolicy.viewer_can_comment = policy.viewer_can_comment;
  feedbackPolicy.viewer_can_edit = false;
  feedbackPolicy.notify_on_comment = policy.notify_on_comment;
  feedbackPolicy.notify_on_publish = policy.notify_on_publish;
  lastSavedFeedbackPolicy.value = feedbackPolicyPayload();
  feedbackPolicyConfirmed.value = false;
}

function normalizeAuthMappingRows(rows: WorkspaceDepartmentMembershipTarget[]) {
  const rank: Record<string, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };
  const byDepartment = new Map<string, WorkspaceDepartmentMembershipTarget>();
  for (const row of rows) {
    const department = row.department.trim().replace(/\s+/g, " ");
    if (!department) {
      continue;
    }
    const workspaceRole = row.workspace_role || "viewer";
    const existing = byDepartment.get(department);
    if (!existing || rank[workspaceRole] > rank[existing.workspace_role]) {
      byDepartment.set(department, { department, workspace_role: workspaceRole });
    }
  }
  return Array.from(byDepartment.values()).sort((left, right) =>
    left.department.localeCompare(right.department, "zh-CN")
  );
}

function applyAuthMembershipMapping(mapping: WorkspaceAuthMembershipMapping | null) {
  const rows = normalizeAuthMappingRows(mapping?.department_workspaces ?? []);
  authMappingRows.value = rows;
  lastSavedAuthMappingRows.value = rows.map((row) => ({ ...row }));
  authMappingConfirmed.value = false;
}

function touchAuthMapping() {
  authMappingConfirmed.value = false;
  notice.value = "";
}

function addAuthMappingRow() {
  const department = authMappingForm.department.trim();
  if (!department) {
    error.value = "请填写部门名称";
    return;
  }
  authMappingRows.value = normalizeAuthMappingRows([
    ...authMappingRows.value,
    { department, workspace_role: authMappingForm.workspace_role }
  ]);
  authMappingForm.department = "";
  authMappingForm.workspace_role = "viewer";
  touchAuthMapping();
}

function removeAuthMappingRow(index: number) {
  authMappingRows.value = authMappingRows.value.filter((_, rowIndex) => rowIndex !== index);
  touchAuthMapping();
}

async function saveAuthMembershipMapping() {
  if (!workspace.currentCode || !isSuperAdmin.value || !authMappingDirty.value) {
    return;
  }
  error.value = "";
  notice.value = "";
  if (!authMappingConfirmed.value) {
    error.value = "请先确认部门自动开通规则影响";
    return;
  }
  savingAuthMapping.value = true;
  try {
    const updated = await updateWorkspaceAuthMembershipMapping(workspace.currentCode, {
      department_workspaces: normalizeAuthMappingRows(authMappingRows.value)
    });
    applyAuthMembershipMapping(updated);
    notice.value = "部门自动开通规则已保存";
    auditLogs.value = await fetchAuditLogs({ limit: 80 });
    await refreshPermissionChanges();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存部门自动开通规则失败";
  } finally {
    savingAuthMapping.value = false;
  }
}

function touchFeedbackPolicy() {
  feedbackPolicyConfirmed.value = false;
  notice.value = "";
}

async function saveFeedbackPolicy() {
  if (!workspace.currentCode || !canEditFeedbackPolicy.value || !feedbackPolicyDirty.value) {
    return;
  }
  error.value = "";
  notice.value = "";
  if (!feedbackPolicyConfirmed.value) {
    error.value = "请先确认反馈策略变更影响";
    return;
  }
  savingFeedbackPolicy.value = true;
  try {
    const updated = await updateWorkspaceFeedbackPolicy(workspace.currentCode, feedbackPolicyPayload());
    applyFeedbackPolicy(updated);
    notice.value = "反馈策略已保存";
    if (isSuperAdmin.value) {
      auditLogs.value = await fetchAuditLogs({ limit: 80 });
      await refreshPermissionChanges();
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存反馈策略失败";
  } finally {
    savingFeedbackPolicy.value = false;
  }
}

async function copyText(value: string) {
  try {
    await navigator.clipboard?.writeText(value);
  } catch {
    // Clipboard is optional in non-secure local contexts.
  }
}

async function refreshPermissionChanges() {
  if (!isSuperAdmin.value) {
    permissionChanges.value = [];
    selectedPermissionRollbackIds.value = [];
    return;
  }
  permissionChanges.value = await fetchPermissionChanges(workspace.currentCode || undefined);
  selectedPermissionRollbackIds.value = selectedPermissionRollbackIds.value.filter((id) =>
    permissionChanges.value.some((change) => change.id === id && change.rollback_available)
  );
}

function isPermissionRollbackSelected(change: PermissionChangeRecord) {
  return selectedPermissionRollbackIds.value.includes(change.id);
}

function togglePermissionRollback(change: PermissionChangeRecord, checked: boolean) {
  if (!change.rollback_available) {
    return;
  }
  if (checked) {
    selectedPermissionRollbackIds.value = Array.from(new Set([...selectedPermissionRollbackIds.value, change.id]));
  } else {
    selectedPermissionRollbackIds.value = selectedPermissionRollbackIds.value.filter((id) => id !== change.id);
  }
  notice.value = "";
}

function permissionDiffValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join("、") : "无";
  }
  if (typeof value === "boolean") {
    return value ? "开启" : "关闭";
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  if (value === null || value === undefined || value === "") {
    return "无";
  }
  return String(value);
}

function permissionChangeTime(change: PermissionChangeRecord) {
  return new Date(change.created_at).toLocaleString("zh-CN", { hour12: false });
}

async function rollbackSelectedPermissionChanges() {
  if (selectedPermissionRollbackIds.value.length === 0) {
    return;
  }
  error.value = "";
  notice.value = "";
  rollingBackPermissions.value = true;
  try {
    const result = await rollbackPermissionChanges({
      audit_log_ids: selectedPermissionRollbackIds.value,
      confirm_dangerous_change: rollbackConfirmDangerous.value
    });
    notice.value = result.results.map((item) => item.message).join("；");
    selectedPermissionRollbackIds.value = [];
    rollbackConfirmDangerous.value = false;
    await loadData();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "权限回滚失败";
  } finally {
    rollingBackPermissions.value = false;
  }
}

watch(
  () => workspace.currentCode,
  () => {
    if (activeTab.value === "members" || activeTab.value === "policies") {
      void loadData();
    }
  }
);

onMounted(loadData);
</script>

<template>
  <section class="toolbar-band">
    <div>
      <p class="eyebrow">Identity</p>
      <h2>用户权限</h2>
      <p>公网账号和内网身份最终都落到本地用户，再由这里的角色决定权限。</p>
    </div>
    <div class="topbar-tools">
      <button type="button" class="icon-button" :disabled="loading" @click="loadData" title="刷新">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
    </div>
  </section>

  <div class="policy-tabs">
    <button v-if="isSuperAdmin" type="button" :class="{ active: activeTab === 'users' }" @click="activeTab = 'users'">用户</button>
    <button v-if="isSuperAdmin" type="button" :class="{ active: activeTab === 'invites' }" @click="activeTab = 'invites'">邀请</button>
    <button type="button" :class="{ active: activeTab === 'members' }" @click="activeTab = 'members'">工作台成员</button>
    <button type="button" :class="{ active: activeTab === 'policies' }" @click="activeTab = 'policies'">策略</button>
  </div>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="temporaryPassword" class="empty-state">临时密码：{{ temporaryPassword }}</p>
  <p v-if="notice" class="empty-state">{{ noticeMessage }}</p>

  <section v-if="activeTab === 'users'" class="data-table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th>用户</th>
          <th>身份来源</th>
          <th>部门</th>
          <th>状态</th>
          <th>角色</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="user in users" :key="user.id">
          <td>
            <strong>{{ user.display_name }}</strong>
            <span>{{ user.username }}</span>
          </td>
          <td>
            <strong>{{ user.external_provider }}</strong>
            <span>{{ user.employee_no || user.external_id }}</span>
          </td>
          <td>{{ user.department || "-" }}</td>
          <td>{{ user.status }}</td>
          <td>
            <div class="role-checks">
              <label v-for="role in roles" :key="role.code">
                <input
                  type="checkbox"
                  :checked="selectedRoles[user.id]?.has(role.code)"
                  @change="toggleRole(user.id, role.code, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ role.name }}</span>
              </label>
            </div>
          </td>
          <td>
            <button
              type="button"
              class="icon-button"
              :disabled="savingUserId === user.id"
              @click="saveUser(user)"
              title="保存角色"
            >
              <Save :size="16" />
              <span>{{ savingUserId === user.id ? "保存中" : "保存" }}</span>
            </button>
            <button type="button" class="icon-button secondary" @click="resetPassword(user)" title="重置密码">
              <KeyRound :size="16" />
              <span>重置</span>
            </button>
            <button type="button" class="icon-button secondary" @click="toggleActive(user)" title="启停用户">
              <Ban :size="16" />
              <span>{{ user.is_active ? "停用" : "启用" }}</span>
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && users.length === 0" class="empty-state">暂无用户，可通过邀请链接创建第一个协作者账号。</p>
  </section>

  <section v-else-if="activeTab === 'invites'" class="data-table-wrap">
    <form class="form-grid-two" @submit.prevent="submitInvite">
      <label>
        <span>邮箱</span>
        <input v-model="inviteForm.email" type="email" />
      </label>
      <label>
        <span>全局角色</span>
        <select v-model="inviteForm.role_code">
          <option v-for="role in roles" :key="role.code" :value="role.code">{{ role.name }}</option>
        </select>
      </label>
      <label>
        <span>工作台</span>
        <select v-model="inviteForm.workspace_code">
          <option v-for="item in workspace.options" :key="item.code" :value="item.code">{{ item.name }}</option>
        </select>
      </label>
      <label>
        <span>工作台角色</span>
        <select v-model="inviteForm.workspace_role">
          <option value="viewer">viewer</option>
          <option value="member">member</option>
          <option value="admin">admin</option>
          <option value="owner">owner</option>
        </select>
      </label>
      <label>
        <span>有效天数</span>
        <input v-model.number="inviteForm.expires_in_days" type="number" min="1" max="30" />
      </label>
      <button type="submit" class="icon-button">
        <Plus :size="16" />
        <span>创建邀请</span>
      </button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>邀请</th>
          <th>角色</th>
          <th>工作台</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="invite in invites" :key="invite.id">
          <td>
            <strong>{{ invite.email || invite.code }}</strong>
            <span>{{ invite.invite_url }}</span>
          </td>
          <td>{{ invite.role_code }}</td>
          <td>
            <span v-for="target in invite.workspaces" :key="target.code">
              {{ target.code }} · {{ target.workspace_role }}
            </span>
          </td>
          <td>
            <strong>{{ inviteStatusLabel(invite.status) }}</strong>
            <span>{{ inviteStatusHint(invite) }}</span>
          </td>
          <td>
            <button type="button" class="icon-button secondary" @click="copyText(invite.invite_url)" title="复制链接">
              <Copy :size="16" />
              <span>复制</span>
            </button>
            <button
              type="button"
              class="icon-button secondary"
              :disabled="invite.status !== 'pending'"
              @click="revokeInviteRow(invite)"
              title="撤销邀请"
            >
              <Ban :size="16" />
              <span>撤销</span>
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && invites.length === 0" class="empty-state">暂无邀请，选择角色和工作台后生成邀请链接。</p>
  </section>

  <section v-else-if="activeTab === 'members'" class="data-table-wrap">
    <form class="form-grid-two" @submit.prevent="submitMember">
      <label>
        <span>工作台</span>
        <input :value="workspace.current?.name || workspace.currentCode" disabled />
      </label>
      <label>
        <span>用户</span>
        <select v-model="memberForm.user_id">
          <option v-for="user in memberUserOptions" :key="user.id" :value="user.id">
            {{ user.display_name }} · {{ user.username }}
          </option>
        </select>
      </label>
      <label>
        <span>工作台角色</span>
        <select v-model="memberForm.workspace_role">
          <option value="viewer">viewer</option>
          <option value="member">member</option>
          <option value="admin">admin</option>
          <option value="owner">owner</option>
        </select>
      </label>
      <button type="submit" class="icon-button" :disabled="savingMember || !memberForm.user_id">
        <UserPlus :size="16" />
        <span>加入工作台</span>
      </button>
    </form>

    <div class="policy-summary-grid">
      <article>
        <p class="eyebrow">变更影响</p>
        <h3>{{ selectedWorkspaceRoleImpact.title }}</h3>
        <span>{{ selectedWorkspaceRoleImpact.description }}</span>
      </article>
      <article>
        <p class="eyebrow">Owner Guard</p>
        <h3>当前 owner {{ ownerCount }} 人</h3>
        <span>最后一个 owner 不能移出工作台，后端和前端都会拦截。</span>
      </article>
      <article>
        <p class="eyebrow">Audit</p>
        <h3>成员变更会写审计</h3>
        <span>加入、改角色、移出都会进入 workspace.member.* 审计动作。</span>
      </article>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>成员</th>
          <th>全局角色</th>
          <th>工作台角色</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="member in members" :key="member.user.id">
          <td>
            <strong>{{ member.user.display_name }}</strong>
            <span>{{ member.user.username }}</span>
          </td>
          <td>{{ member.user.roles.join(", ") || "-" }}</td>
          <td>
            <select v-model="memberRoleDrafts[member.user.id]" class="compact-select">
              <option value="viewer">viewer</option>
              <option value="member">member</option>
              <option value="admin">admin</option>
              <option value="owner">owner</option>
            </select>
            <span v-if="isLastOwner(member)">最后 owner 不可移出</span>
            <label v-if="isDangerousMemberChange(member)" class="danger-confirm-line">
              <input v-model="dangerousMemberConfirmations[member.user.id]" type="checkbox" />
              <span>确认调整 owner 权限</span>
            </label>
          </td>
          <td>{{ member.user.status }}</td>
          <td>
            <button
              type="button"
              class="icon-button"
              :disabled="savingMember || memberRoleDrafts[member.user.id] === member.workspace_role"
              @click="saveMemberRole(member)"
              title="保存工作台角色"
            >
              <Save :size="16" />
              <span>保存</span>
            </button>
            <button
              type="button"
              class="icon-button secondary"
              :disabled="savingMember || isLastOwner(member)"
              @click="removeMember(member)"
              title="移出工作台"
            >
              <Trash2 :size="16" />
              <span>移出</span>
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && members.length === 0" class="empty-state">暂无成员，从上方选择用户并加入当前工作台。</p>
  </section>

  <section v-else class="data-table-wrap permission-policy-panel">
    <div class="policy-summary-grid">
      <article>
        <p class="eyebrow">Auth Mode</p>
        <h3>{{ authModeLabel }}</h3>
        <span>{{ runtime.deployMode }} · {{ runtime.instanceId || "local-instance" }}</span>
      </article>
      <article>
        <p class="eyebrow">Workspace</p>
        <h3>{{ workspace.current?.name || workspace.currentCode }}</h3>
        <span>{{ workspace.currentCode }} · 成员 {{ members.length }}</span>
      </article>
      <article>
        <p class="eyebrow">Boundary</p>
        <h3>本地 RBAC</h3>
        <span>外部身份只证明是谁，业务权限仍由本地角色决定。</span>
      </article>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>全局角色</h3>
      </div>
      <div class="permission-card-grid">
        <article v-for="role in globalRoleRows" :key="role.code" class="permission-card">
          <strong>{{ role.name }}</strong>
          <span>{{ role.code }}</span>
          <p>{{ role.description || "角色说明待补充。" }}</p>
        </article>
      </div>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>工作台角色矩阵</h3>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>角色</th>
            <th>能力边界</th>
            <th>最低等级</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in workspaceRoleRows" :key="row.role">
            <td><strong>{{ row.role }}</strong></td>
            <td>{{ row.scope }}</td>
            <td>{{ row.min }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>Viewer 反馈策略</h3>
      </div>
      <div class="policy-summary-grid">
        <article>
          <p class="eyebrow">Impact</p>
          <h3>{{ feedbackPolicyDirty ? "待确认变更" : "当前策略已同步" }}</h3>
          <span>{{ feedbackPolicyImpactLine }}</span>
        </article>
        <article>
          <p class="eyebrow">Audit</p>
          <h3>保存写入审计</h3>
          <span>后端记录 workspace.feedback_policy.update，并继续以 403 兜底。</span>
        </article>
        <article>
          <p class="eyebrow">Scope</p>
          <h3>仅影响 viewer</h3>
          <span>member、admin、owner 的采编协作能力不由这里降权。</span>
        </article>
      </div>
      <form class="feedback-policy-form" @submit.prevent="saveFeedbackPolicy">
        <label class="switch-row compact">
          <input
            v-model="feedbackPolicy.viewer_can_react"
            type="checkbox"
            :disabled="!canEditFeedbackPolicy"
            aria-label="允许 viewer 点赞"
            @change="touchFeedbackPolicy"
          />
          <span>允许 viewer 点赞</span>
        </label>
        <label class="switch-row compact">
          <input
            v-model="feedbackPolicy.viewer_can_rate"
            type="checkbox"
            :disabled="!canEditFeedbackPolicy"
            aria-label="允许 viewer 评分"
            @change="touchFeedbackPolicy"
          />
          <span>允许 viewer 评分</span>
        </label>
        <label class="switch-row compact">
          <input
            v-model="feedbackPolicy.viewer_can_comment"
            type="checkbox"
            :disabled="!canEditFeedbackPolicy"
            aria-label="允许 viewer 评论"
            @change="touchFeedbackPolicy"
          />
          <span>允许 viewer 评论</span>
        </label>
        <label class="switch-row compact">
          <input
            v-model="feedbackPolicy.notify_on_comment"
            type="checkbox"
            :disabled="!canEditFeedbackPolicy"
            aria-label="评论通知"
            @change="touchFeedbackPolicy"
          />
          <span>评论写入通知流</span>
        </label>
        <label class="switch-row compact">
          <input
            v-model="feedbackPolicy.notify_on_publish"
            type="checkbox"
            :disabled="!canEditFeedbackPolicy"
            aria-label="发布通知"
            @change="touchFeedbackPolicy"
          />
          <span>发布通知预留开关</span>
        </label>
        <label class="switch-row compact locked">
          <input :checked="false" type="checkbox" disabled aria-label="viewer 编辑权限" />
          <span>viewer 编辑日报：固定关闭</span>
        </label>
        <label class="feedback-policy-confirm">
          <input
            v-model="feedbackPolicyConfirmed"
            type="checkbox"
            :disabled="!canEditFeedbackPolicy || !feedbackPolicyDirty"
            aria-label="确认反馈策略影响"
          />
          <span>已确认该策略只影响 viewer 反馈入口，并接受后端审计记录。</span>
        </label>
        <button
          type="submit"
          class="icon-button"
          :disabled="!canEditFeedbackPolicy || !feedbackPolicyDirty || savingFeedbackPolicy"
        >
          <Save :size="16" />
          <span>{{ savingFeedbackPolicy ? "保存中" : "保存反馈策略" }}</span>
        </button>
      </form>
      <p v-if="!canEditFeedbackPolicy" class="empty-state">
        仅工作台 owner/admin 或 super_admin 可修改反馈策略。
      </p>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>部署层自动开通规则</h3>
      </div>
      <p v-if="runtime.authMembershipMapping.status === 'invalid'" class="form-warning">
        {{ runtime.authMembershipMapping.error || "自动开通规则配置无效" }}
      </p>
      <table v-else-if="hasAuthMembershipMapping" class="data-table">
        <thead>
          <tr>
            <th>来源</th>
            <th>工作台</th>
            <th>角色</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="target in authDefaultWorkspaceRows" :key="`default-${target.workspace_code}`">
            <td><strong>默认</strong></td>
            <td>{{ target.workspace_code }}</td>
            <td>{{ target.workspace_role }}</td>
          </tr>
          <tr
            v-for="target in authDepartmentWorkspaceRows"
            :key="`${target.department}-${target.workspace_code}`"
          >
            <td><strong>部门：{{ target.department }}</strong></td>
            <td>{{ target.workspace_code }}</td>
            <td>{{ target.workspace_role }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">未配置默认工作台或部门映射。</p>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>当前工作台部门开通规则</h3>
      </div>
      <div class="policy-summary-grid">
        <article>
          <p class="eyebrow">Scope</p>
          <h3>{{ workspace.currentCode }}</h3>
          <span>匹配部门的 OIDC/Header 用户登录时会自动加入当前工作台。</span>
        </article>
        <article>
          <p class="eyebrow">Guard</p>
          <h3>只升级不降级</h3>
          <span>自动规则只新增或升级 membership，不会降低人工已授予的角色。</span>
        </article>
        <article>
          <p class="eyebrow">Audit</p>
          <h3>保存写入审计</h3>
          <span>动作记录为 workspace.auth_membership_mapping.update。</span>
        </article>
      </div>

      <form v-if="isSuperAdmin" class="form-grid-two" @submit.prevent="addAuthMappingRow">
        <label>
          <span>部门名称</span>
          <input v-model="authMappingForm.department" placeholder="例如：规划部" />
        </label>
        <label>
          <span>自动授予角色</span>
          <select v-model="authMappingForm.workspace_role">
            <option value="viewer">viewer</option>
            <option value="member">member</option>
            <option value="admin">admin</option>
            <option value="owner">owner</option>
          </select>
        </label>
        <button type="submit" class="icon-button">
          <Plus :size="16" />
          <span>加入规则</span>
        </button>
      </form>

      <table v-if="authMappingRows.length > 0" class="data-table">
        <thead>
          <tr>
            <th>部门</th>
            <th>工作台</th>
            <th>角色</th>
            <th v-if="isSuperAdmin">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in authMappingRows" :key="`${row.department}-${row.workspace_role}`">
            <td><strong>{{ row.department }}</strong></td>
            <td>{{ workspace.currentCode }}</td>
            <td>{{ row.workspace_role }}</td>
            <td v-if="isSuperAdmin">
              <button type="button" class="icon-button secondary" @click="removeAuthMappingRow(index)">
                <Trash2 :size="16" />
                <span>移除</span>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">当前工作台未配置数据库部门开通规则。</p>

      <form v-if="isSuperAdmin" class="feedback-policy-form" @submit.prevent="saveAuthMembershipMapping">
        <label class="feedback-policy-confirm">
          <input
            v-model="authMappingConfirmed"
            type="checkbox"
            :disabled="!authMappingDirty"
            aria-label="确认部门开通规则影响"
          />
          <span>已确认这些部门用户后续登录会自动加入当前工作台，并接受审计记录。</span>
        </label>
        <button
          type="submit"
          class="icon-button"
          :disabled="!authMappingDirty || savingAuthMapping"
        >
          <Save :size="16" />
          <span>{{ savingAuthMapping ? "保存中" : "保存部门规则" }}</span>
        </button>
      </form>
      <p v-else class="empty-state">只有 super_admin 可以编辑部门自动开通规则。</p>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>权限差异解释与回滚</h3>
      </div>
      <div class="policy-summary-grid">
        <article>
          <p class="eyebrow">Diff</p>
          <h3>后端解释差异</h3>
          <span>角色、成员、反馈策略和部门开通规则都按审计 before/after 展示。</span>
        </article>
        <article>
          <p class="eyebrow">Rollback</p>
          <h3>{{ selectedPermissionRollbackIds.length }} 条待回滚</h3>
          <span>回滚会再次写入 identity.permission_rollback 审计记录。</span>
        </article>
        <article>
          <p class="eyebrow">Guard</p>
          <h3>保留管理员兜底</h3>
          <span>最后 super_admin 和最后 workspace owner 不会被回滚掉。</span>
        </article>
      </div>
      <table v-if="permissionChanges.length > 0" class="data-table permission-change-table">
        <thead>
          <tr>
            <th>选择</th>
            <th>变更</th>
            <th>差异解释</th>
            <th>操作者</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="change in permissionChanges" :key="change.id">
            <td>
              <input
                type="checkbox"
                :checked="isPermissionRollbackSelected(change)"
                :disabled="!change.rollback_available"
                :aria-label="`选择回滚 ${change.title}`"
                @change="togglePermissionRollback(change, ($event.target as HTMLInputElement).checked)"
              />
            </td>
            <td>
              <strong>{{ change.title }}</strong>
              <span>{{ change.scope }} · {{ change.action }}</span>
              <span v-if="!change.rollback_available">{{ change.rollback_reason }}</span>
            </td>
            <td>
              <ul class="permission-diff-list">
                <li v-for="diff in change.diffs" :key="`${change.id}-${diff.field}`">
                  <strong>{{ diff.label }}</strong>
                  <span>{{ permissionDiffValue(diff.before) }} → {{ permissionDiffValue(diff.after) }}</span>
                  <em>{{ diff.explanation }}</em>
                </li>
              </ul>
              <span v-if="change.diffs.length === 0">{{ change.summary }}</span>
            </td>
            <td>{{ change.actor_name || "system" }}</td>
            <td>{{ permissionChangeTime(change) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">暂无可解释的权限变更记录，调整成员角色或工作台成员资格后，这里会展示每次变更的字段差异与原因。</p>
      <form v-if="permissionChanges.length > 0" class="feedback-policy-form" @submit.prevent="rollbackSelectedPermissionChanges">
        <label class="feedback-policy-confirm">
          <input v-model="rollbackConfirmDangerous" type="checkbox" aria-label="确认危险权限回滚" />
          <span>确认本次回滚可能涉及 owner 或 super_admin 降权，由后端继续执行最后管理员保护。</span>
        </label>
        <button
          type="submit"
          class="icon-button"
          :disabled="selectedPermissionRollbackIds.length === 0 || rollingBackPermissions"
        >
          <RotateCcw :size="16" />
          <span>{{ rollingBackPermissions ? "回滚中" : "回滚选中变更" }}</span>
        </button>
      </form>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>权限审计摘要</h3>
      </div>
      <table v-if="identityAuditLogs.length > 0" class="data-table">
        <thead>
          <tr>
            <th>动作</th>
            <th>对象</th>
            <th>操作者</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in identityAuditLogs" :key="log.id">
            <td><strong>{{ log.action }}</strong></td>
            <td>{{ auditDetailLine(log) }}</td>
            <td>{{ log.user_name || log.user_id || "system" }}</td>
            <td>{{ new Date(log.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="isSuperAdmin" class="empty-state">暂无身份权限相关审计记录，请先完成邀请、角色调整或反馈策略变更后再查看。</p>
      <p v-else class="empty-state">权限审计摘要仅 super_admin 可见。</p>
    </div>

    <div class="permission-policy-section">
      <div class="section-heading-row">
        <ShieldCheck :size="18" />
        <h3>后续治理项</h3>
      </div>
      <ul class="policy-gap-list">
        <li v-for="item in policyGapRows" :key="item">{{ item }}</li>
      </ul>
    </div>
  </section>
</template>
