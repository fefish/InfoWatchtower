import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TopicTasksPage from "./TopicTasksPage.vue";
import type { TopicTaskRecord } from "../api/operations";
import type { WorkspaceMemberRecord } from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  batchUpdateTopicTasks: vi.fn(),
  createTopicTask: vi.fn(),
  fetchTopicTask: vi.fn(),
  fetchTopicTasks: vi.fn(),
  updateTopicTask: vi.fn()
}));

const workspacesApi = vi.hoisted(() => ({
  fetchWorkspaceMembers: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/operations", () => ({
  batchUpdateTopicTasks: operationsApi.batchUpdateTopicTasks,
  createTopicTask: operationsApi.createTopicTask,
  fetchTopicTask: operationsApi.fetchTopicTask,
  fetchTopicTasks: operationsApi.fetchTopicTasks,
  updateTopicTask: operationsApi.updateTopicTask
}));

vi.mock("../api/workspaces", () => ({
  fetchWorkspaceMembers: workspacesApi.fetchWorkspaceMembers
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function topicTask(overrides: Partial<TopicTaskRecord> = {}): TopicTaskRecord {
  return {
    id: "task-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    requirement_id: null,
    requirement_title: null,
    title: "跟进同步冲突复盘",
    description: "整理冲突根因和后续动作",
    status: "open",
    due_at: null,
    is_overdue: false,
    blocked_reason: "",
    assignee_user_id: "user-3",
    assignee_name: "Task Owner",
    requirement_source_count: 0,
    requirement_source_links: [],
    metadata_json: {},
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function workspaceMember(overrides: Partial<WorkspaceMemberRecord> = {}): WorkspaceMemberRecord {
  return {
    user: {
      id: "user-3",
      external_provider: "local",
      external_id: "task-owner",
      employee_no: null,
      username: "task-owner",
      display_name: "Task Owner",
      department: "规划部",
      email: null,
      status: "active",
      is_active: true,
      roles: ["viewer"]
    },
    workspace_role: "member",
    enabled: true,
    ...overrides
  };
}

function mountPage(options: { userId?: string; role?: "super_admin" | "viewer"; workspaceRole?: string } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const session = useSessionStore();
  session.user = {
    id: options.userId ?? "admin-user",
    external_provider: "local",
    external_id: options.userId ?? "admin",
    employee_no: null,
    username: options.userId ?? "admin",
    display_name: options.userId ?? "Admin",
    department: "规划部",
    email: null,
    status: "active",
    is_active: true,
    roles: [options.role ?? "super_admin"]
  };

  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  workspace.options = [
    {
      code: "planning_intel",
      name: "规划部情报工作台",
      description: "",
      workspace_type: "intelligence_workspace",
      default_domain_code: "ai",
      enabled: true,
      current_user_workspace_role: options.workspaceRole ?? "owner"
    }
  ];

  return mount(TopicTasksPage, {
    global: {
      plugins: [pinia],
      stubs: {
        // AppModal 通过 Teleport 挂到 body；stub 后就地渲染，wrapper.find 可直查。
        teleport: true
      }
    }
  });
}

describe("TopicTasksPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    operationsApi.fetchTopicTasks.mockResolvedValue([topicTask()]);
    operationsApi.fetchTopicTask.mockResolvedValue(topicTask());
    operationsApi.batchUpdateTopicTasks.mockResolvedValue({ updated_count: 1, tasks: [topicTask({ status: "done" })] });
    operationsApi.createTopicTask.mockResolvedValue(topicTask({ id: "task-new" }));
    operationsApi.updateTopicTask.mockResolvedValue(topicTask({ status: "done" }));
    workspacesApi.fetchWorkspaceMembers.mockResolvedValue([workspaceMember()]);
  });

  it("highlights a task from a notification anchor", async () => {
    routeState.query = { task_id: "task-2" };
    operationsApi.fetchTopicTask.mockResolvedValue(
      topicTask({
        id: "task-2",
        title: "被指派的任务",
        description: "来自任务通知"
      })
    );
    operationsApi.fetchTopicTasks.mockResolvedValue([
      topicTask(),
      topicTask({
        id: "task-2",
        title: "被指派的任务",
        description: "来自任务通知"
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const anchored = wrapper.find(".topic-task-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("被指派的任务");
    expect(anchored.text()).toContain("来自任务通知");
    expect(operationsApi.fetchTopicTask).toHaveBeenCalledWith("task-2");
  });

  it("creates a task with an assignee from workspace members", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find("input").setValue("跟进任务通知闭环");
    const selects = wrapper.findAll("form select");
    await selects[1].setValue("user-3");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(workspacesApi.fetchWorkspaceMembers).toHaveBeenCalledWith("planning_intel");
    expect(operationsApi.fetchTopicTasks).toHaveBeenCalledWith("planning_intel", {});
    expect(operationsApi.createTopicTask).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        title: "跟进任务通知闭环",
        assignee_user_id: "user-3"
      })
    );
  });

  it("updates a task assignee from the task row", async () => {
    operationsApi.updateTopicTask.mockResolvedValue(
      topicTask({
        assignee_user_id: "user-3",
        assignee_name: "Task Owner"
      })
    );
    const wrapper = mountPage();
    await flushPromises();

    const rowAssigneeSelect = wrapper.find(".topic-task-row .compact-field select");
    await rowAssigneeSelect.setValue("user-3");
    await flushPromises();

    expect(operationsApi.updateTopicTask).toHaveBeenCalledWith("task-1", { assignee_user_id: "user-3" });
    expect(wrapper.text()).toContain("Task Owner");
    expect(wrapper.text()).toContain("已指派给 Task Owner，对方会收到站内通知");
  });

  it("shows immediate feedback when clearing a task assignee", async () => {
    operationsApi.updateTopicTask.mockResolvedValue(
      topicTask({
        assignee_user_id: null,
        assignee_name: null
      })
    );
    const wrapper = mountPage();
    await flushPromises();

    const rowAssigneeSelect = wrapper.find(".topic-task-row .assignee-field select");
    await rowAssigneeSelect.setValue("");
    await flushPromises();

    expect(operationsApi.updateTopicTask).toHaveBeenCalledWith("task-1", { assignee_user_id: null });
    expect(wrapper.text()).toContain("已取消指派");
  });

  it("lets an assignee update status without exposing assignment controls", async () => {
    operationsApi.fetchTopicTasks.mockResolvedValue([topicTask({ assignee_user_id: "user-3" })]);
    const wrapper = mountPage({ userId: "user-3", role: "viewer", workspaceRole: "viewer" });
    await flushPromises();

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.find(".assignee-field select").exists()).toBe(false);
    const completeButton = wrapper.findAll(".topic-task-row .mini-action").find((button) => button.text().includes("完成"));
    expect(completeButton).toBeTruthy();
    await completeButton!.trigger("click");
    await flushPromises();

    expect(workspacesApi.fetchWorkspaceMembers).not.toHaveBeenCalled();
    expect(operationsApi.updateTopicTask).toHaveBeenCalledWith("task-1", { status: "done" });
  });

  it("shows requirement and source trace links for tasks created from report items", async () => {
    operationsApi.fetchTopicTasks.mockResolvedValue([
      topicTask({
        requirement_id: "req-1",
        requirement_title: "评估 Agent 记忆能力建设",
        requirement_source_count: 1,
        requirement_source_links: [
          {
            id: "link-1",
            link_type: "evidence",
            note: "日报条目触发",
            insight_id: "insight-1",
            daily_report_item_id: "daily-item-1",
            weekly_report_item_id: null,
            entity_milestone_id: null,
            historical_report_id: null,
            historical_feedback_item_id: null,
            news_item_id: "news-1",
            raw_item_id: "raw-1",
            source_object_type: "daily_report_item",
            source_title: "Agent 记忆能力升级",
            source_url: "https://example.com/agent-memory",
            data_source_name: "Agent 源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("评估 Agent 记忆能力建设");
    expect(wrapper.text()).toContain("日报条目");
    expect(wrapper.text()).toContain("Agent 记忆能力升级");
    expect(wrapper.find('a[href="/requirements?requirement_id=req-1"]').exists()).toBe(true);
    expect(wrapper.find('a[href="https://example.com/agent-memory"]').exists()).toBe(true);
  });

  it("opens a read-only task detail drawer from the detail API", async () => {
    operationsApi.fetchTopicTasks.mockResolvedValue([
      topicTask({
        requirement_id: "req-1",
        requirement_title: "评估 Agent 记忆能力建设",
        requirement_source_count: 1
      })
    ]);
    operationsApi.fetchTopicTask.mockResolvedValue(
      topicTask({
        requirement_id: "req-1",
        requirement_title: "评估 Agent 记忆能力建设",
        title: "补齐 Agent 记忆专题跟踪",
        description: "确认来源证据并拆解后续行动",
        status: "blocked",
        is_overdue: true,
        blocked_reason: "等待业务方确认",
        requirement_source_count: 1,
        requirement_source_links: [
          {
            id: "link-1",
            link_type: "evidence",
            note: "日报条目触发",
            insight_id: "insight-1",
            daily_report_item_id: "daily-item-1",
            weekly_report_item_id: null,
            entity_milestone_id: null,
            historical_report_id: null,
            historical_feedback_item_id: null,
            news_item_id: "news-1",
            raw_item_id: "raw-1",
            source_object_type: "daily_report_item",
            source_title: "Agent 记忆能力升级",
            source_url: "https://example.com/agent-memory",
            data_source_name: "Agent 源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    );
    const wrapper = mountPage();
    await flushPromises();

    const detailButton = wrapper.findAll(".topic-task-row .mini-action").find((button) => button.text().includes("详情"));
    expect(detailButton).toBeTruthy();
    await detailButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.fetchTopicTask).toHaveBeenCalledWith("task-1");
    // §10.3 迁移清单第 8 项：任务详情归入 AppModal lg 档（旧 report-modal-backdrop 私有基座收编）。
    const dialog = wrapper.find('.modal-backdrop .modal.modal-lg[role="dialog"]');
    expect(dialog.exists()).toBe(true);
    expect(dialog.attributes("aria-modal")).toBe("true");
    expect(dialog.text()).toContain("补齐 Agent 记忆专题跟踪");
    expect(dialog.text()).toContain("等待业务方确认");
    expect(dialog.text()).toContain("评估 Agent 记忆能力建设");
    expect(dialog.text()).toContain("Agent 记忆能力升级");
    expect(dialog.find('a[href="/daily-reports?daily_report_item_id=daily-item-1"]').exists()).toBe(true);
    expect(dialog.find('a[href="/requirements?requirement_id=req-1"]').exists()).toBe(true);

    // 只读详情非脏表单：Esc 直接关闭（AppModal 基座行为，§10.1）。
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    await flushPromises();
    expect(wrapper.find(".modal").exists()).toBe(false);
  });

  it("shows historical feedback source links in task requirement traces", async () => {
    operationsApi.fetchTopicTasks.mockResolvedValue([
      topicTask({
        requirement_id: "req-1",
        requirement_title: "复盘历史反馈来源质量",
        requirement_source_count: 1,
        requirement_source_links: [
          {
            id: "link-feedback-1",
            link_type: "evidence",
            note: "历史质量反馈触发",
            insight_id: null,
            daily_report_item_id: null,
            weekly_report_item_id: null,
            entity_milestone_id: null,
            historical_report_id: null,
            historical_feedback_item_id: "feedback-1",
            news_item_id: "news-1",
            raw_item_id: "raw-1",
            source_object_type: "historical_feedback",
            source_title: "历史质量反馈：来源质量偏低",
            source_url: null,
            data_source_name: "历史质量源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("复盘历史反馈来源质量");
    expect(wrapper.text()).toContain("历史反馈");
    expect(wrapper.text()).toContain("历史质量反馈：来源质量偏低");
    expect(wrapper.find('a[href="/quality-archive?feedback_id=feedback-1"]').exists()).toBe(true);
  });

  it("loads owner, overdue and blocked task views through API filters", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const buttons = wrapper.findAll(".coverage-filter button");
    await buttons[1].trigger("click");
    await flushPromises();
    await buttons[2].trigger("click");
    await flushPromises();
    await buttons[3].trigger("click");
    await flushPromises();

    expect(operationsApi.fetchTopicTasks).toHaveBeenNthCalledWith(1, "planning_intel", {});
    expect(operationsApi.fetchTopicTasks).toHaveBeenNthCalledWith(2, "planning_intel", { assignedToMe: true });
    expect(operationsApi.fetchTopicTasks).toHaveBeenNthCalledWith(3, "planning_intel", { due: "overdue" });
    expect(operationsApi.fetchTopicTasks).toHaveBeenNthCalledWith(4, "planning_intel", { status: "blocked" });
  });

  it("shows overdue and blocked reason, then lets an assignee mark blocked with a reason", async () => {
    operationsApi.fetchTopicTasks.mockResolvedValue([
      topicTask({
        is_overdue: true,
        blocked_reason: "等待外部接口确认"
      })
    ]);
    operationsApi.updateTopicTask.mockResolvedValue(
      topicTask({
        status: "blocked",
        blocked_reason: "等待法务确认"
      })
    );
    const wrapper = mountPage({ userId: "user-3", role: "viewer", workspaceRole: "viewer" });
    await flushPromises();

    expect(wrapper.text()).toContain("逾期");
    expect(wrapper.text()).toContain("阻塞原因：等待外部接口确认");

    await wrapper.find('.topic-task-row input[placeholder="等待接口或决策"]').setValue("等待法务确认");
    const blockedButton = wrapper.findAll(".topic-task-row .mini-action").find((button) => button.text().includes("阻塞"));
    expect(blockedButton).toBeTruthy();
    await blockedButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.updateTopicTask).toHaveBeenCalledWith("task-1", {
      status: "blocked",
      metadata_json: { blocked_reason: "等待法务确认" }
    });
    expect(wrapper.text()).toContain("阻塞原因：等待法务确认");
  });

  it("batch updates selected tasks through the backend batch API", async () => {
    operationsApi.fetchTopicTasks.mockResolvedValue([
      topicTask({ id: "task-1", title: "任务 A" }),
      topicTask({ id: "task-2", title: "任务 B" })
    ]);
    operationsApi.batchUpdateTopicTasks.mockResolvedValue({
      updated_count: 2,
      tasks: [
        topicTask({ id: "task-1", status: "blocked", blocked_reason: "等待外部接口确认" }),
        topicTask({ id: "task-2", status: "blocked", blocked_reason: "等待外部接口确认" })
      ]
    });
    const wrapper = mountPage();
    await flushPromises();

    const toolbar = wrapper.find(".task-batch-toolbar");
    expect(toolbar.exists()).toBe(true);
    await toolbar.find('input[type="checkbox"]').setValue(true);
    await toolbar.find("select").setValue("blocked");
    await toolbar.find('input[placeholder="批量 blocked 时必填"]').setValue("等待外部接口确认");
    await toolbar.find("button").trigger("click");
    await flushPromises();

    expect(operationsApi.batchUpdateTopicTasks).toHaveBeenCalledWith({
      workspace_code: "planning_intel",
      task_ids: ["task-1", "task-2"],
      status: "blocked",
      blocked_reason: "等待外部接口确认"
    });
    expect(wrapper.text()).toContain("已批量更新 2 个任务");
    expect(wrapper.text()).toContain("阻塞原因：等待外部接口确认");
  });
});
