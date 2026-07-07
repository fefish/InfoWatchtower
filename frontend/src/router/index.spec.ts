import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import { createInfoWatchtowerRouter } from "./index";
import type { RuntimeRecord } from "../api/meta";
import type { SessionUser } from "../api/auth";

const setupApi = vi.hoisted(() => ({
  fetchSetupStatus: vi.fn()
}));

const metaApi = vi.hoisted(() => ({
  fetchRuntime: vi.fn()
}));

const authApi = vi.hoisted(() => ({
  fetchMe: vi.fn()
}));

const workspacesApi = vi.hoisted(() => ({
  fetchWorkspaces: vi.fn(),
  fetchWorkspaceSections: vi.fn(),
  createWorkspace: vi.fn()
}));

vi.mock("../api/setup", () => ({
  fetchSetupStatus: setupApi.fetchSetupStatus
}));

vi.mock("../api/meta", () => ({
  fetchRuntime: metaApi.fetchRuntime
}));

vi.mock("../api/auth", () => ({
  fetchMe: authApi.fetchMe
}));

vi.mock("../api/workspaces", () => workspacesApi);

function runtimeRecord(overrides: Partial<RuntimeRecord> = {}): RuntimeRecord {
  return {
    deploy_mode: "standalone",
    instance_id: "router-test",
    auth_mode: "public_password",
    app_version: "test",
    capabilities: {
      ingestion: true,
      sync_publisher: true,
      sync_consumer: true,
      embedding: true,
      search: true
    },
    auth_membership_mapping: {
      status: "empty",
      default_workspaces: [],
      department_workspaces: []
    },
    ...overrides
  };
}

function sessionUser(overrides: Partial<SessionUser> = {}): SessionUser {
  return {
    id: "user-1",
    external_provider: "local",
    external_id: "admin",
    employee_no: null,
    username: "admin",
    display_name: "系统管理员",
    department: null,
    email: null,
    status: "active",
    is_active: true,
    roles: ["super_admin"],
    ...overrides
  };
}

function workspaceRecord(role: string) {
  return {
    code: "planning_intel",
    name: "规划部情报工作台",
    description: "",
    workspace_type: "intelligence_workspace",
    default_domain_code: "ai",
    enabled: true,
    current_user_workspace_role: role
  };
}

async function navigateTo(path: string) {
  setActivePinia(createPinia());
  const router = createInfoWatchtowerRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  return router;
}

describe("router guards", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi.fetchSetupStatus.mockResolvedValue({ needs_setup: false });
    metaApi.fetchRuntime.mockResolvedValue(runtimeRecord());
    authApi.fetchMe.mockRejectedValue(new Error("unauthenticated"));
    workspacesApi.fetchWorkspaces.mockResolvedValue([workspaceRecord("member")]);
    workspacesApi.fetchWorkspaceSections.mockResolvedValue([]);
  });

  it("redirects protected routes to setup while first-run setup is required", async () => {
    setupApi.fetchSetupStatus.mockResolvedValue({ needs_setup: true });

    const router = await navigateTo("/dashboard");

    expect(router.currentRoute.value.path).toBe("/setup");
    expect(authApi.fetchMe).not.toHaveBeenCalled();
  });

  it("keeps the setup route available while first-run setup is required", async () => {
    setupApi.fetchSetupStatus.mockResolvedValue({ needs_setup: true });

    const router = await navigateTo("/setup");

    expect(router.currentRoute.value.path).toBe("/setup");
    expect(authApi.fetchMe).not.toHaveBeenCalled();
  });

  it("redirects setup to login after setup is already complete", async () => {
    const router = await navigateTo("/setup");

    expect(router.currentRoute.value.path).toBe("/login");
  });

  it("preserves the original target as redirect query for unauthenticated protected routes", async () => {
    const router = await navigateTo("/exports?export_job_id=job-1");

    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe("/exports?export_job_id=job-1");
  });

  it("redirects to login with the redirect query when the session cookie has expired (HTTP 401)", async () => {
    // 会话 cookie 过期后 /api/auth/me 返回 401：导航守卫应把用户带回登录页并保留回跳地址。
    authApi.fetchMe.mockRejectedValue(new Error("HTTP 401"));

    const router = await navigateTo("/daily-reports");

    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe("/daily-reports");
  });

  it("sends authenticated users away from login to the dashboard", async () => {
    authApi.fetchMe.mockResolvedValue({ user: sessionUser() });

    const router = await navigateTo("/login?redirect=/exports");

    expect(router.currentRoute.value.path).toBe("/dashboard");
  });

  it("forces users with must_change_password status into the account page", async () => {
    authApi.fetchMe.mockResolvedValue({ user: sessionUser({ status: "must_change_password" }) });

    const router = await navigateTo("/dashboard");

    expect(router.currentRoute.value.path).toBe("/account");
  });

  it("lands workspace viewers on the daily reports page after login", async () => {
    // 受邀 viewer（游客）登录：默认落地日报阅读页，而不是管理员的 dashboard。
    authApi.fetchMe.mockResolvedValue({ user: sessionUser({ roles: ["viewer"] }) });
    workspacesApi.fetchWorkspaces.mockResolvedValue([workspaceRecord("viewer")]);

    const router = await navigateTo("/login");

    expect(router.currentRoute.value.path).toBe("/daily-reports");
  });

  it("redirects workspace viewers from management routes to daily reports", async () => {
    authApi.fetchMe.mockResolvedValue({ user: sessionUser({ roles: ["viewer"] }) });
    workspacesApi.fetchWorkspaces.mockResolvedValue([workspaceRecord("viewer")]);

    for (const managementPath of [
      "/dashboard",
      "/sources",
      "/news",
      "/exports",
      "/users",
      "/audit-logs",
      "/workspace-settings"
    ]) {
      const router = await navigateTo(managementPath);
      expect(router.currentRoute.value.path).toBe("/daily-reports");
    }
  });

  it("keeps workspace admins on the workspace settings route", async () => {
    authApi.fetchMe.mockResolvedValue({ user: sessionUser({ roles: ["viewer"] }) });
    workspacesApi.fetchWorkspaces.mockResolvedValue([workspaceRecord("admin")]);

    const router = await navigateTo("/workspace-settings");

    expect(router.currentRoute.value.path).toBe("/workspace-settings");
  });

  it("keeps viewer-readable routes accessible for workspace viewers", async () => {
    authApi.fetchMe.mockResolvedValue({ user: sessionUser({ roles: ["viewer"] }) });
    workspacesApi.fetchWorkspaces.mockResolvedValue([workspaceRecord("viewer")]);

    for (const readablePath of ["/weekly-reports", "/historical-reports", "/entity-milestones", "/account"]) {
      const router = await navigateTo(readablePath);
      expect(router.currentRoute.value.path).toBe(readablePath);
    }
  });

  it("keeps workspace members on management routes", async () => {
    authApi.fetchMe.mockResolvedValue({ user: sessionUser({ roles: ["viewer"] }) });
    workspacesApi.fetchWorkspaces.mockResolvedValue([workspaceRecord("member")]);

    const router = await navigateTo("/sources");

    expect(router.currentRoute.value.path).toBe("/sources");
  });

  it("never redirects global admins even with a viewer membership", async () => {
    authApi.fetchMe.mockResolvedValue({ user: sessionUser({ roles: ["super_admin"] }) });
    workspacesApi.fetchWorkspaces.mockResolvedValue([workspaceRecord("viewer")]);

    const router = await navigateTo("/sources");

    expect(router.currentRoute.value.path).toBe("/sources");
    // 全局管理员不触发工作台角色侦查，导航不被 viewer 规则拦截。
    expect(workspacesApi.fetchWorkspaces).not.toHaveBeenCalled();
  });
});
