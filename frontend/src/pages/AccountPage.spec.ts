import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AccountPage from "./AccountPage.vue";
import { useSessionStore } from "../stores/session";
import type { SessionUser } from "../api/auth";

const routerReplace = vi.hoisted(() => vi.fn());
const authApi = vi.hoisted(() => ({
  changePassword: vi.fn(),
  fetchMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn()
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({
    replace: routerReplace
  })
}));

vi.mock("../api/auth", () => ({
  changePassword: authApi.changePassword,
  fetchMe: authApi.fetchMe,
  login: authApi.login,
  logout: authApi.logout
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

function mountAccountPage(user: SessionUser = userRecord()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const session = useSessionStore();
  session.user = user;
  session.checked = true;
  return mount(AccountPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("AccountPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authApi.changePassword.mockResolvedValue({
      user: userRecord({ status: "active" })
    });
  });

  it("renders local account details and changes the password", async () => {
    const wrapper = mountAccountPage();

    expect(wrapper.text()).toContain("规划部管理员");
    expect(wrapper.text()).toContain("本地账号");
    expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(true);

    const inputs = wrapper.findAll("input");
    await inputs[0].setValue("old-password");
    await inputs[1].setValue("new-password-123");
    await inputs[2].setValue("new-password-123");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(authApi.changePassword).toHaveBeenCalledWith("old-password", "new-password-123");
    expect(routerReplace).toHaveBeenCalledWith("/dashboard");
    expect(wrapper.text()).toContain("密码已更新");
  });

  it("validates local password form before calling the API", async () => {
    const wrapper = mountAccountPage();

    const inputs = wrapper.findAll("input");
    await inputs[1].setValue("short");
    await inputs[2].setValue("short");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(authApi.changePassword).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("新密码至少 8 位");
  });

  it("hides local password fields for externally managed identities", () => {
    const wrapper = mountAccountPage(
      userRecord({
        external_provider: "example_oidc",
        external_id: "oidc-user-1",
        username: "sso.user"
      })
    );

    expect(wrapper.text()).toContain("单点登录账号");
    expect(wrapper.text()).toContain("密码、MFA 和会话策略由外部身份系统管理");
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(false);
  });
});
