import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UsersPage from "./UsersPage.vue";
import type { InviteRecord, SessionUser, UserRole } from "../api/auth";
import type { AuditLogRecord } from "../api/operations";
import { useRuntimeStore } from "../stores/runtime";
import { useSessionStore } from "../stores/session";

const identityApi = vi.hoisted(() => ({
  createInvite: vi.fn(),
  fetchPermissionChanges: vi.fn(),
  fetchInvites: vi.fn(),
  fetchRoles: vi.fn(),
  fetchUsers: vi.fn(),
  patchUser: vi.fn(),
  rollbackPermissionChanges: vi.fn(),
  resetUserPassword: vi.fn(),
  revokeInvite: vi.fn(),
  updateUserRoles: vi.fn()
}));

const workspaceApi = vi.hoisted(() => ({
  fetchWorkspaceAuthMembershipMapping: vi.fn(),
  fetchWorkspaceFeedbackPolicy: vi.fn(),
  fetchWorkspaces: vi.fn(),
  fetchWorkspaceSections: vi.fn(),
  fetchWorkspaceMembers: vi.fn(),
  removeWorkspaceMember: vi.fn(),
  updateWorkspaceAuthMembershipMapping: vi.fn(),
  updateWorkspaceFeedbackPolicy: vi.fn(),
  upsertWorkspaceMember: vi.fn()
}));

const operationsApi = vi.hoisted(() => ({
  fetchAuditLogs: vi.fn()
}));

vi.mock("../api/identity", () => ({
  createInvite: identityApi.createInvite,
  fetchPermissionChanges: identityApi.fetchPermissionChanges,
  fetchInvites: identityApi.fetchInvites,
  fetchRoles: identityApi.fetchRoles,
  fetchUsers: identityApi.fetchUsers,
  patchUser: identityApi.patchUser,
  rollbackPermissionChanges: identityApi.rollbackPermissionChanges,
  resetUserPassword: identityApi.resetUserPassword,
  revokeInvite: identityApi.revokeInvite,
  updateUserRoles: identityApi.updateUserRoles
}));

vi.mock("../api/workspaces", () => ({
  fetchWorkspaceAuthMembershipMapping: workspaceApi.fetchWorkspaceAuthMembershipMapping,
  fetchWorkspaceFeedbackPolicy: workspaceApi.fetchWorkspaceFeedbackPolicy,
  fetchWorkspaces: workspaceApi.fetchWorkspaces,
  fetchWorkspaceSections: workspaceApi.fetchWorkspaceSections,
  fetchWorkspaceMembers: workspaceApi.fetchWorkspaceMembers,
  removeWorkspaceMember: workspaceApi.removeWorkspaceMember,
  updateWorkspaceAuthMembershipMapping: workspaceApi.updateWorkspaceAuthMembershipMapping,
  updateWorkspaceFeedbackPolicy: workspaceApi.updateWorkspaceFeedbackPolicy,
  upsertWorkspaceMember: workspaceApi.upsertWorkspaceMember
}));

vi.mock("../api/operations", () => ({
  fetchAuditLogs: operationsApi.fetchAuditLogs
}));

function userRecord(overrides: Partial<SessionUser> = {}): SessionUser {
  return {
    id: "user-1",
    external_provider: "local",
    external_id: "admin",
    employee_no: null,
    username: "admin",
    display_name: "规划部管理员",
    department: "规划部",
    email: "admin@example.com",
    status: "active",
    is_active: true,
    roles: ["super_admin"],
    ...overrides
  };
}

function roleRecord(code: UserRole, name: string, description: string) {
  return {
    id: `role-${code}`,
    code,
    name,
    description
  };
}

function inviteRecord(overrides: Partial<InviteRecord> = {}): InviteRecord {
  return {
    id: "invite-1",
    code: "INVITE1",
    email: "invitee@example.com",
    role_code: "viewer",
    workspaces: [{ code: "planning_intel", workspace_role: "viewer" }],
    invite_url: "https://app.example.com/invite/INVITE1",
    status: "pending",
    expires_at: "2026-07-12T00:00:00Z",
    accepted_at: null,
    revoked_at: null,
    ...overrides
  };
}

function auditLogRecord(overrides: Partial<AuditLogRecord> = {}): AuditLogRecord {
  return {
    id: "audit-1",
    user_id: "user-1",
    user_name: "规划部管理员",
    workspace_code: "planning_intel",
    action: "workspace.member.upsert",
    object_type: "workspace",
    object_id: "planning_intel",
    ip_address: "",
    user_agent: "",
    detail_json: { workspace_code: "planning_intel", workspace_role: "member" },
    created_at: "2026-07-06T11:00:00Z",
    ...overrides
  };
}

function setupApiMocks() {
  workspaceApi.fetchWorkspaces.mockResolvedValue([
    {
      code: "planning_intel",
      name: "规划部情报工作台",
      description: "行业信号、日报周报、专题洞察和内部需求闭环。",
      workspace_type: "intelligence_workspace",
      default_domain_code: "ai",
      enabled: true
    }
  ]);
  workspaceApi.fetchWorkspaceSections.mockResolvedValue([]);
  workspaceApi.fetchWorkspaceMembers.mockResolvedValue([
    {
      user: userRecord(),
      workspace_role: "owner",
      enabled: true
    }
  ]);
  workspaceApi.fetchWorkspaceFeedbackPolicy.mockResolvedValue({
    workspace_code: "planning_intel",
    viewer_can_react: true,
    viewer_can_rate: true,
    viewer_can_comment: true,
    viewer_can_edit: false,
    notify_on_comment: true,
    notify_on_publish: false
  });
  workspaceApi.updateWorkspaceFeedbackPolicy.mockImplementation((_workspaceCode, payload) =>
    Promise.resolve({
      workspace_code: "planning_intel",
      ...payload
    })
  );
  workspaceApi.fetchWorkspaceAuthMembershipMapping.mockResolvedValue({
    workspace_code: "planning_intel",
    department_workspaces: [{ department: "规划部", workspace_role: "viewer" }]
  });
  workspaceApi.updateWorkspaceAuthMembershipMapping.mockImplementation((_workspaceCode, payload) =>
    Promise.resolve({
      workspace_code: "planning_intel",
      ...payload
    })
  );
  identityApi.fetchUsers.mockResolvedValue([userRecord()]);
  identityApi.fetchRoles.mockResolvedValue([
    roleRecord("super_admin", "超级管理员", "实例级管理、用户权限、部署同步 token、全局审计。"),
    roleRecord("editor_admin", "采编管理员", "内容生产管理者，可被加入多个工作台。"),
    roleRecord("analyst", "分析员", "分析成员，可参与内容研判。"),
    roleRecord("viewer", "浏览者", "浏览者，默认只读。")
  ]);
  identityApi.fetchInvites.mockResolvedValue([]);
  identityApi.fetchPermissionChanges.mockResolvedValue([
    {
      id: "permission-change-1",
      action: "workspace.feedback_policy.update",
      object_type: "workspace",
      object_id: "workspace-1",
      actor_name: "规划部管理员",
      created_at: "2026-07-06T12:00:00Z",
      scope: "planning_intel",
      title: "Viewer 反馈策略变更",
      summary: "viewer 评论",
      rollback_available: true,
      rollback_reason: null,
      diffs: [
        {
          field: "viewer_can_comment",
          label: "viewer 评论",
          before: true,
          after: false,
          explanation: "viewer 评论从 开启 调整为 关闭。"
        }
      ]
    }
  ]);
  identityApi.rollbackPermissionChanges.mockResolvedValue({
    results: [
      {
        audit_log_id: "permission-change-1",
        status: "rolled_back",
        message: "已恢复 planning_intel 的反馈策略"
      }
    ]
  });
  operationsApi.fetchAuditLogs.mockResolvedValue([
    auditLogRecord(),
    auditLogRecord({ id: "audit-2", action: "daily_report.publish", object_type: "daily_report" })
  ]);
}

function mountUsersPage(currentUser: SessionUser) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const session = useSessionStore();
  session.user = currentUser;
  session.checked = true;

  const runtime = useRuntimeStore();
  runtime.checked = true;
  runtime.deployMode = "cloud";
  runtime.instanceId = "test-instance";
  runtime.authMode = "oidc";
  runtime.authMembershipMapping = {
    status: "configured",
    default_workspaces: [{ workspace_code: "planning_intel", workspace_role: "viewer" }],
    department_workspaces: [{ department: "战略部", workspace_code: "ai_tools", workspace_role: "member" }]
  };
  runtime.capabilities = {
    ingestion: true,
    sync_publisher: false,
    sync_consumer: false,
    embedding: false,
    search: true
  };

  return mount(UsersPage, {
    global: {
      plugins: [pinia]
    }
  });
}

function tabTexts(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll(".policy-tabs button").map((button) => button.text());
}

async function clickTab(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll(".policy-tabs button").find((item) => item.text() === text);
  if (!button) {
    throw new Error(`Tab not found: ${text}`);
  }
  await button.trigger("click");
  await flushPromises();
}

describe("UsersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApiMocks();
  });

  it("shows all four identity operation areas for super admins", async () => {
    const wrapper = mountUsersPage(userRecord());
    await flushPromises();

    expect(tabTexts(wrapper)).toEqual(["用户", "邀请", "工作台成员", "策略"]);
    expect(identityApi.fetchUsers).toHaveBeenCalledWith(undefined);
    expect(identityApi.fetchRoles).toHaveBeenCalledTimes(1);
    expect(identityApi.fetchInvites).toHaveBeenCalledTimes(1);
    expect(workspaceApi.fetchWorkspaceFeedbackPolicy).toHaveBeenCalledWith("planning_intel");
    expect(identityApi.fetchPermissionChanges).toHaveBeenCalledWith("planning_intel");
    expect(operationsApi.fetchAuditLogs).toHaveBeenCalledWith({ limit: 80 });

    await clickTab(wrapper, "策略");

    expect(wrapper.text()).toContain("OIDC / SSO");
    expect(wrapper.text()).toContain("cloud · test-instance");
    expect(wrapper.text()).toContain("全局角色");
    expect(wrapper.text()).toContain("工作台角色矩阵");
    expect(wrapper.text()).toContain("部署层自动开通规则");
    expect(wrapper.text()).toContain("当前工作台部门开通规则");
    expect(wrapper.text()).toContain("planning_intel");
    expect(wrapper.text()).toContain("部门：战略部");
    expect(wrapper.text()).toContain("ai_tools");
    expect(wrapper.text()).toContain("规划部");
    expect(wrapper.text()).toContain("保存部门规则");
    expect(wrapper.text()).toContain("超级管理员");
    expect(wrapper.text()).toContain("权限审计摘要");
    expect(wrapper.text()).toContain("workspace.member.upsert");
    expect(wrapper.text()).toContain("\"workspace_role\":\"member\"");
    expect(wrapper.text()).not.toContain("daily_report.publish");
    expect(wrapper.text()).toContain("Viewer 反馈策略");
    expect(wrapper.text()).toContain("允许 viewer 评论");
    expect(wrapper.text()).toContain("保存反馈策略");
    expect(wrapper.text()).toContain("权限差异解释与回滚");
    expect(wrapper.text()).toContain("Viewer 反馈策略变更");
    expect(wrapper.text()).toContain("viewer 评论从 开启 调整为 关闭。");
    expect(wrapper.text()).toContain("OIDC claims 字段名仍由部署配置管理");
    expect(wrapper.text()).not.toContain("保存策略");
  });

  it("limits non-super users to workspace members and read-only policy context", async () => {
    const workspaceAdmin = userRecord({
      id: "user-2",
      username: "workspace-admin",
      display_name: "工作台管理员",
      roles: ["editor_admin"]
    });
    const wrapper = mountUsersPage(workspaceAdmin);
    await flushPromises();

    expect(tabTexts(wrapper)).toEqual(["工作台成员", "策略"]);
    expect(identityApi.fetchUsers).toHaveBeenCalledWith("planning_intel");
    expect(identityApi.fetchRoles).not.toHaveBeenCalled();
    expect(identityApi.fetchInvites).not.toHaveBeenCalled();
    expect(operationsApi.fetchAuditLogs).not.toHaveBeenCalled();
    expect(identityApi.fetchPermissionChanges).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("加入工作台");

    await clickTab(wrapper, "策略");

    expect(wrapper.text()).toContain("本地 RBAC");
    expect(wrapper.text()).toContain("工作台角色矩阵");
    expect(wrapper.text()).toContain("仅工作台 owner/admin 或 super_admin 可修改反馈策略");
    expect(wrapper.text()).toContain("只有 super_admin 可以编辑部门自动开通规则");
    expect(wrapper.text()).not.toContain("创建邀请");
    expect(wrapper.text()).not.toContain("保存策略");
  });

  it("edits current workspace department auto-membership rules only after confirmation", async () => {
    const wrapper = mountUsersPage(userRecord());
    await flushPromises();

    await clickTab(wrapper, "策略");

    const departmentInput = wrapper.find('input[placeholder="例如：规划部"]');
    await departmentInput.setValue("硬件部");
    const roleSelect = wrapper.findAll("select").find((select) => select.text().includes("admin"));
    if (!roleSelect) {
      throw new Error("Department role select not found");
    }
    await roleSelect.setValue("admin");
    await wrapper.find("form.form-grid-two").trigger("submit");
    await flushPromises();

    expect(wrapper.text()).toContain("硬件部");
    await wrapper.findAll("form.feedback-policy-form")[1].trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("请先确认部门自动开通规则影响");
    expect(workspaceApi.updateWorkspaceAuthMembershipMapping).not.toHaveBeenCalled();

    await wrapper.find('input[aria-label="确认部门开通规则影响"]').setValue(true);
    await wrapper.findAll("form.feedback-policy-form")[1].trigger("submit");
    await flushPromises();

    expect(workspaceApi.updateWorkspaceAuthMembershipMapping).toHaveBeenCalledWith(
      "planning_intel",
      {
        department_workspaces: [
          { department: "规划部", workspace_role: "viewer" },
          { department: "硬件部", workspace_role: "admin" }
        ]
      }
    );
    expect(wrapper.text()).toContain("部门自动开通规则已保存");
  });

  it("edits feedback policy only after impact confirmation", async () => {
    const wrapper = mountUsersPage(userRecord());
    await flushPromises();

    await clickTab(wrapper, "策略");

    const commentSwitch = wrapper.find('input[aria-label="允许 viewer 评论"]');
    await commentSwitch.setValue(false);
    await flushPromises();

    expect(wrapper.text()).toContain("保存后 viewer 将不能评论");
    const saveButton = wrapper.findAll("button").find((button) => button.text().includes("保存反馈策略"));
    if (!saveButton) {
      throw new Error("Save feedback policy button not found");
    }
    await wrapper.find("form.feedback-policy-form").trigger("submit");
    await flushPromises();

    expect(wrapper.text()).toContain("请先确认反馈策略变更影响");
    expect(workspaceApi.updateWorkspaceFeedbackPolicy).not.toHaveBeenCalled();

    await wrapper.find('input[aria-label="确认反馈策略影响"]').setValue(true);
    await wrapper.find("form.feedback-policy-form").trigger("submit");
    await flushPromises();

    expect(workspaceApi.updateWorkspaceFeedbackPolicy).toHaveBeenCalledWith(
      "planning_intel",
      expect.objectContaining({
        viewer_can_comment: false,
        viewer_can_edit: false
      })
    );
    expect(wrapper.text()).toContain("反馈策略已保存");
  });

  it("rolls back selected permission changes from the policy panel", async () => {
    const wrapper = mountUsersPage(userRecord());
    await flushPromises();

    await clickTab(wrapper, "策略");

    await wrapper.find('input[aria-label="选择回滚 Viewer 反馈策略变更"]').setValue(true);
    await wrapper.find('input[aria-label="确认危险权限回滚"]').setValue(true);
    const rollbackForm = wrapper.findAll("form.feedback-policy-form").at(-1);
    if (!rollbackForm) {
      throw new Error("Rollback form not found");
    }
    await rollbackForm.trigger("submit");
    await flushPromises();

    expect(identityApi.rollbackPermissionChanges).toHaveBeenCalledWith({
      audit_log_ids: ["permission-change-1"],
      confirm_dangerous_change: true
    });
    expect(wrapper.text()).toContain("已恢复 planning_intel 的反馈策略");
  });

  it("explains workspace role impact and prevents removing the last owner", async () => {
    const wrapper = mountUsersPage(userRecord());
    await flushPromises();

    await clickTab(wrapper, "工作台成员");

    expect(wrapper.text()).toContain("member 可参与采编协作");
    expect(wrapper.text()).toContain("当前 owner 1 人");
    expect(wrapper.text()).toContain("最后 owner 不可移出");
    expect(wrapper.text()).toContain("成员变更会写审计");

    const removeButton = wrapper.findAll("button").find((button) => button.text().includes("移出"));
    expect(removeButton?.attributes("disabled")).toBeDefined();
    expect(workspaceApi.removeWorkspaceMember).not.toHaveBeenCalled();
  });

  it("shows readable invite states and only allows revoking pending invites", async () => {
    identityApi.fetchInvites.mockResolvedValue([
      inviteRecord({ id: "pending", code: "PENDING", status: "pending", email: "pending@example.com" }),
      inviteRecord({
        id: "accepted",
        code: "ACCEPTED",
        status: "accepted",
        email: "accepted@example.com",
        accepted_at: "2026-07-06T09:00:00Z"
      }),
      inviteRecord({
        id: "revoked",
        code: "REVOKED",
        status: "revoked",
        email: "revoked@example.com",
        revoked_at: "2026-07-06T10:00:00Z"
      }),
      inviteRecord({ id: "expired", code: "EXPIRED", status: "expired", email: "expired@example.com" })
    ]);
    const wrapper = mountUsersPage(userRecord());
    await flushPromises();

    await clickTab(wrapper, "邀请");

    expect(wrapper.text()).toContain("待接受");
    expect(wrapper.text()).toContain("已接受");
    expect(wrapper.text()).toContain("接受于 2026-07-06T09:00:00Z");
    expect(wrapper.text()).toContain("已撤销");
    expect(wrapper.text()).toContain("撤销于 2026-07-06T10:00:00Z");
    expect(wrapper.text()).toContain("已过期");

    const revokeButtons = wrapper.findAll("button").filter((button) => button.text().includes("撤销"));
    expect(revokeButtons).toHaveLength(4);
    expect(revokeButtons[0].attributes("disabled")).toBeUndefined();
    expect(revokeButtons[1].attributes("disabled")).toBeDefined();
    expect(revokeButtons[2].attributes("disabled")).toBeDefined();
    expect(revokeButtons[3].attributes("disabled")).toBeDefined();
  });
});
