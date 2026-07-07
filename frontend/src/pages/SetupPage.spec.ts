import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SetupPage from "./SetupPage.vue";
import { useSessionStore } from "../stores/session";
import { useSetupStore } from "../stores/setup";

const router = vi.hoisted(() => ({
  replace: vi.fn()
}));

const setupApi = vi.hoisted(() => ({
  createSetupAdmin: vi.fn()
}));

const sourcesApi = vi.hoisted(() => ({
  importLegacySources: vi.fn(),
  importTechInsightLoopSources: vi.fn()
}));

vi.mock("vue-router", () => ({
  useRouter: () => router
}));

vi.mock("../api/setup", () => ({
  createSetupAdmin: setupApi.createSetupAdmin
}));

vi.mock("../api/sources", () => ({
  importLegacySources: sourcesApi.importLegacySources,
  importTechInsightLoopSources: sourcesApi.importTechInsightLoopSources
}));

function sessionUser() {
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
    roles: ["super_admin" as const]
  };
}

function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(SetupPage, {
    global: {
      plugins: [pinia]
    }
  });
}

async function fillPasswords(wrapper: ReturnType<typeof mount>, password: string, confirm = password) {
  const passwordInputs = wrapper.findAll('input[type="password"]');
  await passwordInputs[0].setValue(password);
  await passwordInputs[1].setValue(confirm);
}

describe("SetupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi.createSetupAdmin.mockResolvedValue({ user: sessionUser() });
    sourcesApi.importLegacySources.mockResolvedValue({ created: 294, updated: 0, total: 294 });
    sourcesApi.importTechInsightLoopSources.mockResolvedValue({
      created: 363,
      updated: 23,
      total: 386,
      fetchable: 355,
      metadata_only: 31
    });
  });

  it("validates password length before creating the first admin", async () => {
    const wrapper = mountPage();

    await fillPasswords(wrapper, "short");
    await wrapper.find("form").trigger("submit.prevent");

    expect(wrapper.text()).toContain("密码至少 10 位");
    expect(setupApi.createSetupAdmin).not.toHaveBeenCalled();
  });

  it("creates the first admin, runs selected seed imports and enters the dashboard", async () => {
    const wrapper = mountPage();
    const session = useSessionStore();
    const setup = useSetupStore();

    await fillPasswords(wrapper, "strong-password");
    const checkboxes = wrapper.findAll('input[type="checkbox"]');
    await checkboxes[0].setValue(true);
    await checkboxes[1].setValue(true);
    await wrapper.find("form").trigger("submit.prevent");
    await flushPromises();

    expect(setupApi.createSetupAdmin).toHaveBeenCalledWith({
      username: "admin",
      display_name: "系统管理员",
      password: "strong-password"
    });
    expect(sourcesApi.importLegacySources).toHaveBeenCalledTimes(1);
    expect(sourcesApi.importTechInsightLoopSources).toHaveBeenCalledTimes(1);
    expect(session.user?.username).toBe("admin");
    expect(session.checked).toBe(true);
    expect(setup.needsSetup).toBe(false);
    expect(router.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("maps setup-completed errors to a user-facing message", async () => {
    setupApi.createSetupAdmin.mockRejectedValue(new Error("Setup already completed"));
    const wrapper = mountPage();

    await fillPasswords(wrapper, "strong-password");
    await wrapper.find("form").trigger("submit.prevent");
    await flushPromises();

    expect(wrapper.text()).toContain("首次设置已完成，请返回登录页。");
    expect(router.replace).not.toHaveBeenCalled();
  });
});
