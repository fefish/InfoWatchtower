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

vi.mock("../api/setup", () => ({
  fetchSetupStatus: setupApi.fetchSetupStatus
}));

vi.mock("../api/meta", () => ({
  fetchRuntime: metaApi.fetchRuntime
}));

vi.mock("../api/auth", () => ({
  fetchMe: authApi.fetchMe
}));

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
});
