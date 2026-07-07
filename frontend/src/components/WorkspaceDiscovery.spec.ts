import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceDiscovery from "./WorkspaceDiscovery.vue";
import { useSessionStore } from "../stores/session";

const workspaceApi = vi.hoisted(() => ({
  fetchDiscoverableWorkspaces: vi.fn(),
  subscribeWorkspace: vi.fn(),
  unsubscribeWorkspace: vi.fn(),
  fetchWorkspaces: vi.fn(),
  fetchWorkspaceSections: vi.fn(),
  createWorkspace: vi.fn()
}));

vi.mock("../api/workspaces", () => ({
  fetchDiscoverableWorkspaces: workspaceApi.fetchDiscoverableWorkspaces,
  subscribeWorkspace: workspaceApi.subscribeWorkspace,
  unsubscribeWorkspace: workspaceApi.unsubscribeWorkspace,
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
  return mount(WorkspaceDiscovery, { global: { plugins: [pinia] } });
}

async function openDrawer(wrapper: ReturnType<typeof mountDiscovery>) {
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
  });

  it("opens the drawer and lists discoverable workspaces with joined badges", async () => {
    const wrapper = mountDiscovery();

    expect(wrapper.find(".workspace-discovery-button").text()).toContain("发现工作台");
    expect(wrapper.find(".workspace-discovery-panel").exists()).toBe(false);

    await openDrawer(wrapper);

    expect(workspaceApi.fetchDiscoverableWorkspaces).toHaveBeenCalledTimes(1);
    const rows = wrapper.findAll(".workspace-discovery-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("公开情报工作台");
    expect(rows[0].text()).toContain("5 名成员");
    expect(rows[0].find(".workspace-discovery-joined").exists()).toBe(false);
    expect(rows[1].find(".workspace-discovery-joined").text()).toBe("已加入");
  });

  it("subscribes to a workspace and refreshes both the drawer and workspace list", async () => {
    const wrapper = mountDiscovery();
    await openDrawer(wrapper);

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

  it("unsubscribes own viewer membership from the drawer", async () => {
    const wrapper = mountDiscovery();
    await openDrawer(wrapper);

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
    await openDrawer(wrapper);

    expect(wrapper.find(".workspace-discovery-managed").text()).toContain("由管理员管理");
    expect(
      wrapper.findAll(".workspace-discovery-row button").filter((button) => button.text().includes("退订"))
    ).toHaveLength(0);
  });

  it("hides subscribe actions for guest sessions and shows the register hint", async () => {
    const wrapper = mountDiscovery({ guest: true });
    await openDrawer(wrapper);

    expect(wrapper.text()).toContain("注册账号后才能订阅");
    expect(wrapper.findAll(".workspace-discovery-row button")).toHaveLength(0);
    expect(workspaceApi.subscribeWorkspace).not.toHaveBeenCalled();
  });
});
