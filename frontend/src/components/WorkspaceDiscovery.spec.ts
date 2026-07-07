import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceDiscovery from "./WorkspaceDiscovery.vue";
import { useSessionStore } from "../stores/session";

const workspaceApi = vi.hoisted(() => ({
  fetchDiscoverableWorkspaces: vi.fn(),
  subscribeWorkspace: vi.fn(),
  unsubscribeWorkspace: vi.fn(),
  joinWorkspaceByCode: vi.fn(),
  fetchWorkspaces: vi.fn(),
  fetchWorkspaceSections: vi.fn(),
  createWorkspace: vi.fn()
}));

vi.mock("../api/workspaces", () => ({
  fetchDiscoverableWorkspaces: workspaceApi.fetchDiscoverableWorkspaces,
  subscribeWorkspace: workspaceApi.subscribeWorkspace,
  unsubscribeWorkspace: workspaceApi.unsubscribeWorkspace,
  joinWorkspaceByCode: workspaceApi.joinWorkspaceByCode,
  fetchWorkspaces: workspaceApi.fetchWorkspaces,
  fetchWorkspaceSections: workspaceApi.fetchWorkspaceSections,
  createWorkspace: workspaceApi.createWorkspace
}));

function discoverableWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    code: "open_intel",
    name: "公开情报工作台",
    description: "组织内公开的工作台",
    member_count: 5,
    joined: false,
    workspace_role: null,
    ...overrides
  };
}

function sessionUser(overrides: Record<string, unknown> = {}) {
  return {
    id: "user-1",
    external_provider: "local",
    external_id: "reader",
    employee_no: null,
    username: "reader",
    display_name: "读者",
    department: null,
    email: null,
    status: "active",
    is_active: true,
    roles: ["viewer"],
    ...overrides
  };
}

let activeWrapper: ReturnType<typeof mount> | null = null;

function mountDiscovery(options: { guest?: boolean } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const session = useSessionStore();
  session.user = sessionUser(
    options.guest
      ? { external_provider: "guest", external_id: "guest", username: "guest", display_name: "游客" }
      : {}
  ) as never;
  session.checked = true;
  // teleport stub：AppModal 的 Teleport 内容改为就地渲染，便于 wrapper 内断言；
  // Modal 自身行为（Esc/遮罩/焦点圈定）由 AppModal.spec.ts 看护。
  activeWrapper = mount(WorkspaceDiscovery, {
    global: { plugins: [pinia], stubs: { teleport: true } }
  });
  return activeWrapper;
}

async function openModal(wrapper: ReturnType<typeof mountDiscovery>) {
  await wrapper.find(".workspace-discovery-button").trigger("click");
  await flushPromises();
}

describe("WorkspaceDiscovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    workspaceApi.fetchDiscoverableWorkspaces.mockResolvedValue([
      discoverableWorkspace(),
      discoverableWorkspace({
        code: "planning_intel",
        name: "规划部情报工作台",
        member_count: 9,
        joined: true,
        workspace_role: "viewer"
      })
    ]);
    workspaceApi.fetchWorkspaces.mockResolvedValue([]);
    workspaceApi.fetchWorkspaceSections.mockResolvedValue([]);
    workspaceApi.subscribeWorkspace.mockResolvedValue({
      workspace_code: "open_intel",
      workspace_role: "viewer",
      subscribed: true
    });
    workspaceApi.unsubscribeWorkspace.mockResolvedValue(undefined);
    workspaceApi.joinWorkspaceByCode.mockResolvedValue({
      workspace_code: "secret_intel",
      workspace_name: "保密情报工作台",
      workspace_role: "member",
      joined: true
    });
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.useRealTimers();
  });

  it("opens as a centered modal dialog and lists discoverable workspaces with joined badges", async () => {
    const wrapper = mountDiscovery();

    expect(wrapper.find(".workspace-discovery-button").text()).toContain("发现工作台");
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    await openModal(wrapper);

    // 居中 Modal 基座（产品设计 §10.3：发现工作台迁 Modal md，不再用右上浮层）
    const dialog = wrapper.find('[role="dialog"]');
    expect(dialog.exists()).toBe(true);
    expect(dialog.attributes("aria-modal")).toBe("true");
    expect(dialog.classes()).toContain("modal");
    expect(dialog.classes()).toContain("modal-md");
    expect(wrapper.find(".modal-backdrop").exists()).toBe(true);
    expect(wrapper.find(".config-panel").exists()).toBe(false);

    expect(workspaceApi.fetchDiscoverableWorkspaces).toHaveBeenCalledTimes(1);
    const rows = wrapper.findAll(".workspace-discovery-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("公开情报工作台");
    expect(rows[0].text()).toContain("5 名成员");
    expect(rows[0].find(".workspace-discovery-joined").exists()).toBe(false);
    expect(rows[1].find(".workspace-discovery-joined").text()).toBe("已加入");
  });

  it("debounces the search box into discover?q= and shows the join-code hint on empty results", async () => {
    vi.useFakeTimers();
    const wrapper = mountDiscovery();
    await wrapper.find(".workspace-discovery-button").trigger("click");
    await vi.runAllTimersAsync();

    workspaceApi.fetchDiscoverableWorkspaces.mockResolvedValue([]);
    const search = wrapper.find('input[aria-label="搜索公开工作台"]');
    await search.setValue("半导体");
    await search.trigger("input");
    // 去抖：输入后未到时间不请求
    expect(workspaceApi.fetchDiscoverableWorkspaces).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(300);
    await vi.runAllTimersAsync();

    expect(workspaceApi.fetchDiscoverableWorkspaces).toHaveBeenLastCalledWith("半导体");
    // 空结果文案（产品设计 §12.1）
    expect(wrapper.text()).toContain("没有匹配的公开工作台，若你有工作台加入码可在下方凭码加入");
  });

  it("searches immediately on enter", async () => {
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    const search = wrapper.find('input[aria-label="搜索公开工作台"]');
    await search.setValue("情报");
    await search.trigger("keydown.enter");
    await flushPromises();

    expect(workspaceApi.fetchDiscoverableWorkspaces).toHaveBeenLastCalledWith("情报");
  });

  it("subscribes to a workspace and refreshes both the modal list and workspace switcher", async () => {
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    const subscribeButton = wrapper
      .findAll(".workspace-discovery-row button")
      .find((button) => button.text().includes("订阅"));
    expect(subscribeButton).toBeDefined();
    await subscribeButton!.trigger("click");
    await flushPromises();

    expect(workspaceApi.subscribeWorkspace).toHaveBeenCalledWith("open_intel");
    // 订阅成功后同步刷新工作台切换器与发现列表
    expect(workspaceApi.fetchWorkspaces).toHaveBeenCalled();
    expect(workspaceApi.fetchDiscoverableWorkspaces).toHaveBeenCalledTimes(2);
  });

  it("unsubscribes own viewer membership from the modal", async () => {
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    const unsubscribeButton = wrapper
      .findAll(".workspace-discovery-row button")
      .find((button) => button.text().includes("退订"));
    expect(unsubscribeButton).toBeDefined();
    await unsubscribeButton!.trigger("click");
    await flushPromises();

    expect(workspaceApi.unsubscribeWorkspace).toHaveBeenCalledWith("planning_intel");
  });

  it("marks roles above viewer as admin-managed instead of offering unsubscribe", async () => {
    workspaceApi.fetchDiscoverableWorkspaces.mockResolvedValue([
      discoverableWorkspace({ joined: true, workspace_role: "owner" })
    ]);
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    expect(wrapper.find(".workspace-discovery-managed").text()).toContain("由管理员管理");
    expect(
      wrapper.findAll(".workspace-discovery-row button").filter((button) => button.text().includes("退订"))
    ).toHaveLength(0);
  });

  // ---------- 凭码加入（workspace-configuration-design §14.3，产品设计 §12.2） ----------

  it("joins a workspace by code and refreshes the switcher", async () => {
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    await wrapper.find('input[aria-label="工作台加入码"]').setValue("7F2KQ9XN");
    const joinButton = wrapper.findAll("button").find((button) => button.text().includes("凭码加入"));
    expect(joinButton).toBeDefined();
    await joinButton!.trigger("click");
    await flushPromises();

    expect(workspaceApi.joinWorkspaceByCode).toHaveBeenCalledWith("7F2KQ9XN");
    expect(wrapper.text()).toContain("已加入「保密情报工作台」（角色 member）");
    expect(workspaceApi.fetchWorkspaces).toHaveBeenCalled();
  });

  it("reports idempotent join without downgrading the existing role", async () => {
    workspaceApi.joinWorkspaceByCode.mockResolvedValue({
      workspace_code: "secret_intel",
      workspace_name: "保密情报工作台",
      workspace_role: "admin",
      joined: false
    });
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    await wrapper.find('input[aria-label="工作台加入码"]').setValue("7F2KQ9XN");
    await wrapper.find('input[aria-label="工作台加入码"]').trigger("keydown.enter");
    await flushPromises();

    expect(wrapper.text()).toContain("你已是「保密情报工作台」成员（保持原角色 admin）");
  });

  it("surfaces the backend's unified invalid-code message verbatim (anti-enumeration)", async () => {
    workspaceApi.joinWorkspaceByCode.mockRejectedValue(new Error("加入码无效或已失效"));
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    await wrapper.find('input[aria-label="工作台加入码"]').setValue("WRONGCOD");
    await wrapper.find('input[aria-label="工作台加入码"]').trigger("keydown.enter");
    await flushPromises();

    // 统一 400 文案原样透传：不改写、不区分「不存在/停用/过期/用尽」
    expect(wrapper.find(".workspace-discovery-joincode .form-error").text()).toBe("加入码无效或已失效");
    expect(wrapper.find(".form-success").exists()).toBe(false);
  });

  it("does not call the API when the code input is blank", async () => {
    const wrapper = mountDiscovery();
    await openModal(wrapper);

    await wrapper.find('input[aria-label="工作台加入码"]').trigger("keydown.enter");
    await flushPromises();

    expect(workspaceApi.joinWorkspaceByCode).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("请输入加入码");
  });

  it("hides subscribe and join-by-code for guest sessions and shows the register hint", async () => {
    const wrapper = mountDiscovery({ guest: true });
    await openModal(wrapper);

    expect(wrapper.text()).toContain("注册账号后才能订阅或凭码加入");
    expect(wrapper.findAll(".workspace-discovery-row button")).toHaveLength(0);
    expect(wrapper.find(".workspace-discovery-joincode").exists()).toBe(false);
    expect(workspaceApi.subscribeWorkspace).not.toHaveBeenCalled();
    expect(workspaceApi.joinWorkspaceByCode).not.toHaveBeenCalled();
  });
});
