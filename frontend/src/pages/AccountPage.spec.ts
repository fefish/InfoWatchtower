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
  guestLogin: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  updateProfile: vi.fn()
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({
    replace: routerReplace
  })
}));

vi.mock("../api/auth", () => ({
  changePassword: authApi.changePassword,
  fetchMe: authApi.fetchMe,
  guestLogin: authApi.guestLogin,
  login: authApi.login,
  logout: authApi.logout,
  updateProfile: authApi.updateProfile
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
  return { wrapper: mount(AccountPage, { global: { plugins: [pinia] } }), session };
}

describe("AccountPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authApi.changePassword.mockResolvedValue({
      user: userRecord({ status: "active" })
    });
    authApi.updateProfile.mockResolvedValue({
      user: userRecord({ display_name: "新姓名", department: "战略部", email: "new@example.com" })
    });
  });

  it("renders local account details and changes the password", async () => {
    const { wrapper } = mountAccountPage();

    expect(wrapper.text()).toContain("规划部管理员");
    expect(wrapper.text()).toContain("本地账号");
    expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(true);

    const passwordForm = wrapper.find(".account-password-form");
    await passwordForm.find('input[autocomplete="current-password"]').setValue("old-password");
    const newPasswordInputs = passwordForm.findAll('input[autocomplete="new-password"]');
    await newPasswordInputs[0].setValue("new-password-123");
    await newPasswordInputs[1].setValue("new-password-123");
    await passwordForm.trigger("submit");
    await flushPromises();

    expect(authApi.changePassword).toHaveBeenCalledWith("old-password", "new-password-123");
    expect(routerReplace).toHaveBeenCalledWith("/dashboard");
    expect(wrapper.find(".account-password-form .form-success").text()).toContain("密码已更新");
  });

  it("validates local password form before calling the API", async () => {
    const { wrapper } = mountAccountPage();

    const passwordForm = wrapper.find(".account-password-form");
    const newPasswordInputs = passwordForm.findAll('input[autocomplete="new-password"]');
    await newPasswordInputs[0].setValue("short");
    await newPasswordInputs[1].setValue("short");
    await passwordForm.trigger("submit");
    await flushPromises();

    expect(authApi.changePassword).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("新密码至少 8 位");
  });

  it("提供显式退出登录：调用登出 API 并回到登录页", async () => {
    authApi.logout.mockResolvedValue(undefined);
    const { wrapper } = mountAccountPage();

    const logoutButton = wrapper.findAll("button").find((button) => button.text().includes("退出登录"));
    expect(logoutButton).toBeDefined();

    await logoutButton!.trigger("click");
    await flushPromises();

    expect(authApi.logout).toHaveBeenCalled();
    expect(routerReplace).toHaveBeenCalledWith("/login");
  });

  it("hides local password fields for externally managed identities", () => {
    const { wrapper } = mountAccountPage(
      userRecord({
        external_provider: "example_oidc",
        external_id: "oidc-user-1",
        username: "sso.user"
      })
    );

    expect(wrapper.text()).toContain("单点登录账号");
    expect(wrapper.text()).toContain("密码、MFA 和会话策略由外部身份系统管理");
    expect(wrapper.find(".account-password-form").exists()).toBe(false);
    expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(false);
  });

  // ---------- 资料卡（identity-access-design §4.4 / page-specs §25，WP3-F） ----------

  it("saves the local profile via PATCH /api/auth/me and refreshes the session capsule name", async () => {
    const { wrapper, session } = mountAccountPage();

    const profileForm = wrapper.find(".account-profile-form");
    expect(profileForm.exists()).toBe(true);
    // username 只读并注明不可修改
    const usernameInput = profileForm.find('input[aria-label="登录账号"]');
    expect((usernameInput.element as HTMLInputElement).value).toBe("admin");
    expect(usernameInput.attributes("disabled")).toBeDefined();
    expect(profileForm.text()).toContain("登录账号不可修改");

    await profileForm.find('input[aria-label="姓名"]').setValue("新姓名");
    await profileForm.find('input[aria-label="部门"]').setValue("战略部");
    await profileForm.find('input[aria-label="邮箱"]').setValue("new@example.com");
    await profileForm.trigger("submit");
    await flushPromises();

    expect(authApi.updateProfile).toHaveBeenCalledWith({
      display_name: "新姓名",
      department: "战略部",
      email: "new@example.com"
    });
    // session store 刷新 → 顶部用户胶囊立即显示新姓名
    expect(session.user?.display_name).toBe("新姓名");
    expect(wrapper.find(".account-profile-form .form-success").text()).toContain("资料已保存");
  });

  it("does not send the request when display_name is blank", async () => {
    const { wrapper } = mountAccountPage();

    const profileForm = wrapper.find(".account-profile-form");
    await profileForm.find('input[aria-label="姓名"]').setValue("   ");
    await profileForm.trigger("submit");
    await flushPromises();

    expect(authApi.updateProfile).not.toHaveBeenCalled();
    expect(profileForm.find(".form-error").text()).toContain("姓名不能为空");
  });

  it("shows the backend error instead of a fake success when profile save fails", async () => {
    authApi.updateProfile.mockRejectedValue(new Error("Profile is managed externally"));
    const { wrapper, session } = mountAccountPage();

    const profileForm = wrapper.find(".account-profile-form");
    await profileForm.find('input[aria-label="姓名"]').setValue("新姓名");
    await profileForm.trigger("submit");
    await flushPromises();

    expect(profileForm.find(".form-error").text()).toContain("Profile is managed externally");
    expect(profileForm.find(".form-success").exists()).toBe(false);
    expect(session.user?.display_name).toBe("规划部管理员");
  });

  it("renders a read-only profile card without an edit form for external identities", () => {
    const { wrapper } = mountAccountPage(
      userRecord({
        external_provider: "intranet_header",
        external_id: "e12345",
        username: "e12345"
      })
    );

    expect(wrapper.find(".account-profile-card").exists()).toBe(true);
    expect(wrapper.find(".account-profile-form").exists()).toBe(false);
    expect(wrapper.text()).toContain("资料由外部身份系统管理，登录时自动同步");
    expect(wrapper.text()).toContain("内网门户身份");
  });

  it("does not render the profile card for guest sessions", () => {
    const { wrapper } = mountAccountPage(
      userRecord({
        external_provider: "guest",
        external_id: "guest",
        username: "guest",
        display_name: "游客"
      })
    );

    expect(wrapper.find(".account-profile-card").exists()).toBe(false);
    expect(wrapper.find(".account-profile-form").exists()).toBe(false);
  });

  it("disables the profile form until must_change_password users finish changing the password", () => {
    const { wrapper } = mountAccountPage(userRecord({ status: "must_change_password" }));

    const profileForm = wrapper.find(".account-profile-form");
    expect(profileForm.exists()).toBe(true);
    expect(profileForm.find('input[aria-label="姓名"]').attributes("disabled")).toBeDefined();
    expect(profileForm.find('input[aria-label="部门"]').attributes("disabled")).toBeDefined();
    expect(profileForm.find('input[aria-label="邮箱"]').attributes("disabled")).toBeDefined();
    const saveButton = profileForm.findAll("button").find((item) => item.text().includes("保存资料"));
    expect(saveButton!.attributes("disabled")).toBeDefined();
    expect(profileForm.text()).toContain("请先在下方完成改密");
  });
});
