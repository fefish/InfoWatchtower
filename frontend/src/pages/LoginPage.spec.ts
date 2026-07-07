import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./LoginPage.vue";
import { useRuntimeStore } from "../stores/runtime";

const routerPush = vi.hoisted(() => vi.fn());
const routeState = vi.hoisted(() => ({ query: {} as Record<string, string | string[]> }));
const api = vi.hoisted(() => ({
  forgotPassword: vi.fn(),
  startOidcLogin: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  fetchMe: vi.fn(),
  changePassword: vi.fn()
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: routerPush })
}));

vi.mock("../api/auth", () => ({
  forgotPassword: api.forgotPassword,
  startOidcLogin: api.startOidcLogin,
  login: api.login,
  logout: api.logout,
  fetchMe: api.fetchMe,
  changePassword: api.changePassword
}));

function mountLoginPage(authMode: string, redirect = "", query: Record<string, string | string[]> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const runtime = useRuntimeStore();
  runtime.checked = true;
  runtime.authMode = authMode;
  routeState.query = { ...(redirect ? { redirect } : {}), ...query };

  return mount(LoginPage, {
    global: {
      plugins: [pinia]
    }
  });
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll("button").find((item) => item.text().includes(text));
  if (!button) {
    throw new Error(`Button not found: ${text}`);
  }
  return button;
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    api.login.mockResolvedValue({
      user: {
        id: "u1",
        external_provider: "local",
        external_id: "admin",
        employee_no: null,
        username: "admin",
        display_name: "管理员",
        department: null,
        email: null,
        status: "active",
        is_active: true,
        roles: ["super_admin"]
      }
    });
  });

  it("shows the password login form for public password auth", () => {
    const wrapper = mountLoginPage("public_password");

    expect(wrapper.text()).toContain("账号");
    expect(wrapper.text()).toContain("密码");
    expect(wrapper.text()).toContain("忘记密码");
    expect(wrapper.text()).not.toContain("使用单点登录");
  });

  it("shows the SSO entry and starts OIDC login for oidc auth", async () => {
    const wrapper = mountLoginPage("oidc");

    expect(wrapper.text()).toContain("使用单点登录");
    expect(wrapper.find('input[autocomplete="username"]').exists()).toBe(false);
    expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(false);

    await buttonByText(wrapper, "使用单点登录").trigger("click");

    expect(api.startOidcLogin).toHaveBeenCalledWith("/dashboard");
    expect(api.login).not.toHaveBeenCalled();
  });

  it("passes the guarded redirect target to OIDC login", async () => {
    const wrapper = mountLoginPage("oidc", "/daily-reports?day=2026-07-05");

    await buttonByText(wrapper, "使用单点登录").trigger("click");

    expect(api.startOidcLogin).toHaveBeenCalledWith("/daily-reports?day=2026-07-05");
  });

  it("shows a friendly OIDC callback error on the login page", () => {
    const wrapper = mountLoginPage("oidc", "", { auth_error: "state_mismatch" });

    expect(wrapper.text()).toContain("单点登录状态已失效，请重新发起登录。");
    expect(wrapper.text()).toContain("使用单点登录");
  });

  it("shows an SSO configuration error without exposing backend details", () => {
    const wrapper = mountLoginPage("oidc", "", { auth_error: "oidc_not_configured" });

    expect(wrapper.text()).toContain("单点登录服务尚未配置完成");
    expect(wrapper.text()).not.toContain("OIDC_CLIENT_SECRET");
  });

  it("returns to the guarded redirect target after password login", async () => {
    const wrapper = mountLoginPage("public_password", "/weekly-reports");

    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(api.login).toHaveBeenCalledWith("admin", "password");
    expect(routerPush).toHaveBeenCalledWith("/weekly-reports");
  });

  it("sends must-change-password users to the account page after login", async () => {
    api.login.mockResolvedValueOnce({
      user: {
        id: "u1",
        external_provider: "local",
        external_id: "admin",
        employee_no: null,
        username: "admin",
        display_name: "管理员",
        department: null,
        email: null,
        status: "must_change_password",
        is_active: true,
        roles: ["super_admin"]
      }
    });
    const wrapper = mountLoginPage("public_password", "/weekly-reports");

    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(routerPush).toHaveBeenCalledWith("/account");
  });

  it("does not show local password login for intranet header auth", () => {
    const wrapper = mountLoginPage("intranet_header");

    expect(wrapper.text()).toContain("当前内网部署由门户登录态接入");
    expect(wrapper.find('input[autocomplete="username"]').exists()).toBe(false);
    expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("使用单点登录");
  });
});
