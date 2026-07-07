import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import InvitePage from "./InvitePage.vue";
import type { AuthResponse, InvitePublicRecord } from "../api/auth";
import { useSessionStore } from "../stores/session";

const routerReplace = vi.hoisted(() => vi.fn());
const routeState = vi.hoisted(() => ({
  params: { code: "INVITE1" } as Record<string, string>
}));
const authApi = vi.hoisted(() => ({
  acceptInvite: vi.fn(),
  fetchInvite: vi.fn()
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState,
  useRouter: () => ({
    replace: routerReplace
  })
}));

vi.mock("../api/auth", () => ({
  acceptInvite: authApi.acceptInvite,
  fetchInvite: authApi.fetchInvite
}));

const routerLinkStub = {
  props: ["to"],
  template: `<a :href="typeof to === 'string' ? to : to.path"><slot /></a>`
};

function inviteRecord(overrides: Partial<InvitePublicRecord> = {}): InvitePublicRecord {
  return {
    code: "INVITE1",
    email_hint: "ed***@example.com",
    role_code: "editor_admin",
    workspaces: [{ code: "planning_intel", workspace_role: "member" }],
    status: "pending",
    expires_at: "2026-07-12T09:00:00Z",
    ...overrides
  };
}

function authResponse(): AuthResponse {
  return {
    user: {
      id: "user-1",
      external_provider: "local",
      external_id: "editor",
      employee_no: null,
      username: "editor",
      display_name: "Editor",
      department: null,
      email: "editor@example.com",
      status: "active",
      is_active: true,
      roles: ["editor_admin"]
    }
  };
}

function mountInvitePage(
  invite: InvitePublicRecord | null = inviteRecord(),
  options: { acceptError?: Error } = {}
) {
  const pinia = createPinia();
  setActivePinia(pinia);
  if (invite) {
    authApi.fetchInvite.mockResolvedValue(invite);
  }
  if (options.acceptError) {
    authApi.acceptInvite.mockRejectedValue(options.acceptError);
  } else {
    authApi.acceptInvite.mockResolvedValue(authResponse());
  }
  return mount(InvitePage, {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: routerLinkStub
      }
    }
  });
}

describe("InvitePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.params = { code: "INVITE1" };
  });

  it("loads a pending invite, validates fields, and accepts it", async () => {
    const wrapper = mountInvitePage();
    await flushPromises();

    expect(authApi.fetchInvite).toHaveBeenCalledWith("INVITE1");
    expect(wrapper.text()).toContain("待接受");
    expect(wrapper.text()).toContain("ed***@example.com");
    expect(wrapper.text()).toContain("planning_intel · member");

    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(authApi.acceptInvite).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("请填写账号");

    const inputs = wrapper.findAll("input");
    await inputs[0].setValue("editor");
    await inputs[1].setValue("Editor");
    await inputs[2].setValue("new-password");
    await inputs[3].setValue("new-password");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(authApi.acceptInvite).toHaveBeenCalledWith("INVITE1", {
      username: "editor",
      display_name: "Editor",
      password: "new-password"
    });
    expect(useSessionStore().user?.username).toBe("editor");
    expect(routerReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("shows readable expired, revoked, and accepted invite states without the form", async () => {
    const cases = [
      ["expired", "这条邀请已经超过有效期"],
      ["revoked", "管理员已经撤销这条邀请"],
      ["accepted", "这条邀请已经被使用"]
    ] as const;

    for (const [status, hint] of cases) {
      const wrapper = mountInvitePage(inviteRecord({ status }));
      await flushPromises();

      expect(wrapper.find("form").exists()).toBe(false);
      expect(wrapper.text()).toContain(hint);
      wrapper.unmount();
    }
  });

  it("maps accept API errors to user-facing messages", async () => {
    const wrapper = mountInvitePage(inviteRecord(), {
      acceptError: new Error("Username already exists")
    });
    await flushPromises();

    const inputs = wrapper.findAll("input");
    await inputs[0].setValue("editor");
    await inputs[1].setValue("Editor");
    await inputs[2].setValue("new-password");
    await inputs[3].setValue("new-password");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.text()).toContain("账号已存在");
  });

  it("shows a friendly message when the invite link cannot be loaded", async () => {
    authApi.fetchInvite.mockRejectedValue(new Error("Invite not found"));
    const wrapper = mountInvitePage(null);
    await flushPromises();

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.text()).toContain("邀请不存在或链接已失效");
  });
});
