import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RequirementsPage from "./RequirementsPage.vue";
import type { RequirementRecord } from "../api/operations";
import type { WorkspaceMemberRecord } from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createRequirement: vi.fn(),
  fetchRequirements: vi.fn(),
  updateRequirement: vi.fn()
}));

const workspacesApi = vi.hoisted(() => ({
  fetchWorkspaceMembers: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/operations", () => ({
  createRequirement: operationsApi.createRequirement,
  fetchRequirements: operationsApi.fetchRequirements,
  updateRequirement: operationsApi.updateRequirement
}));

vi.mock("../api/workspaces", () => ({
  fetchWorkspaceMembers: workspacesApi.fetchWorkspaceMembers
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function requirement(overrides: Partial<RequirementRecord> = {}): RequirementRecord {
  return {
    id: "req-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    title: "跟踪外部信号",
    description: "沉淀到内部需求",
    priority: "medium",
    status: "open",
    due_at: null,
    owner_user_id: null,
    owner_name: null,
    source_count: 0,
    source_links: [],
    task_count: 0,
    metadata_json: {},
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function workspaceMember(overrides: Partial<WorkspaceMemberRecord> = {}): WorkspaceMemberRecord {
  return {
    user: {
      id: "user-owner",
      external_provider: "local",
      external_id: "requirement-owner",
      employee_no: null,
      username: "requirement-owner",
      display_name: "Requirement Owner",
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

function mountPage(options: { role?: "super_admin" | "viewer"; workspaceRole?: string } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const session = useSessionStore();
  session.user = {
    id: "admin-user",
    external_provider: "local",
    external_id: "admin",
    employee_no: null,
    username: "admin",
    display_name: "Admin",
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

  return mount(RequirementsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("RequirementsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    operationsApi.fetchRequirements.mockResolvedValue([requirement()]);
    operationsApi.createRequirement.mockResolvedValue(requirement({ id: "req-new" }));
    operationsApi.updateRequirement.mockResolvedValue(requirement({ owner_user_id: "user-owner", owner_name: "Requirement Owner" }));
    workspacesApi.fetchWorkspaceMembers.mockResolvedValue([workspaceMember()]);
  });

  it("highlights a requirement from a notification anchor", async () => {
    routeState.query = { requirement_id: "req-2" };
    operationsApi.fetchRequirements.mockResolvedValue([
      requirement(),
      requirement({ id: "req-2", title: "被通知的需求", description: "状态变化提醒" })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const anchored = wrapper.find(".requirement-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("被通知的需求");
  });

  it("creates a requirement with an owner from workspace members", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find("input").setValue("跟踪模型工程趋势");
    const selects = wrapper.findAll("form select");
    await selects[1].setValue("user-owner");
    await wrapper.find('input[placeholder="从日报采信条目复制 ID，可留空"]').setValue("daily-item-1");
    const textareas = wrapper.findAll("form textarea");
    await textareas[1].setValue("日报采信项触发");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(workspacesApi.fetchWorkspaceMembers).toHaveBeenCalledWith("planning_intel");
    expect(operationsApi.createRequirement).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        title: "跟踪模型工程趋势",
        owner_user_id: "user-owner",
        source_daily_report_item_id: "daily-item-1",
        source_note: "日报采信项触发"
      })
    );
  });

  it("renders source links for requirement traceability", async () => {
    operationsApi.fetchRequirements.mockResolvedValue([
      requirement({
        source_count: 1,
        source_links: [
          {
            id: "source-link-1",
            link_type: "evidence",
            note: "日报采信项触发",
            insight_id: null,
            daily_report_item_id: "daily-item-1",
            weekly_report_item_id: null,
            entity_milestone_id: null,
            historical_report_id: null,
            historical_feedback_item_id: null,
            news_item_id: "news-1",
            raw_item_id: "raw-1",
            source_object_type: "daily_report_item",
            source_title: "Agent 编排能力进入工程化阶段",
            source_url: "https://example.com/agent-signal",
            data_source_name: "AI 工程源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find(".requirement-source-list").exists()).toBe(true);
    expect(wrapper.text()).toContain("日报条目");
    expect(wrapper.text()).toContain("Agent 编排能力进入工程化阶段");
    expect(wrapper.text()).toContain("AI 工程源");
    expect(wrapper.text()).toContain("日报采信项触发");
  });

  it("renders entity milestone source links for requirement traceability", async () => {
    operationsApi.fetchRequirements.mockResolvedValue([
      requirement({
        source_count: 1,
        source_links: [
          {
            id: "source-link-entity-1",
            link_type: "evidence",
            note: "实体事件触发",
            insight_id: null,
            daily_report_item_id: null,
            weekly_report_item_id: null,
            entity_milestone_id: "milestone-1",
            historical_report_id: null,
            historical_feedback_item_id: null,
            news_item_id: null,
            raw_item_id: null,
            source_object_type: "entity_milestone",
            source_title: "OpenAI 企业 Agent 进入人工确认",
            source_url: "https://example.com/openai-agent",
            data_source_name: "Agent 源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("实体事件");
    expect(wrapper.text()).toContain("OpenAI 企业 Agent 进入人工确认");
    expect(wrapper.text()).toContain("实体事件触发");
  });

  it("renders historical report source links for requirement traceability", async () => {
    operationsApi.fetchRequirements.mockResolvedValue([
      requirement({
        source_count: 1,
        source_links: [
          {
            id: "source-link-history-1",
            link_type: "evidence",
            note: "历史报告触发",
            insight_id: null,
            daily_report_item_id: null,
            weekly_report_item_id: null,
            entity_milestone_id: null,
            historical_report_id: "historical-report-1",
            historical_feedback_item_id: null,
            news_item_id: null,
            raw_item_id: null,
            source_object_type: "historical_report",
            source_title: "技术洞察日报 2026-05-01",
            source_url: null,
            data_source_name: null,
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("历史报告");
    expect(wrapper.text()).toContain("技术洞察日报 2026-05-01");
    expect(wrapper.text()).toContain("历史报告触发");
    expect(wrapper.find('a[href="/historical-reports?id=historical-report-1"]').exists()).toBe(true);
  });

  it("renders historical feedback source links for requirement traceability", async () => {
    operationsApi.fetchRequirements.mockResolvedValue([
      requirement({
        source_count: 1,
        source_links: [
          {
            id: "source-link-feedback-1",
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
            source_url: "https://example.com/legacy-quality",
            data_source_name: "历史质量源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("历史反馈");
    expect(wrapper.text()).toContain("历史质量反馈：来源质量偏低");
    expect(wrapper.text()).toContain("历史质量反馈触发");
    expect(wrapper.find('a[href="/quality-archive?feedback_id=feedback-1"]').exists()).toBe(true);
  });

  it("submits requirement conclusion feedback to recommendation metadata", async () => {
    operationsApi.fetchRequirements.mockResolvedValue([
      requirement({
        source_count: 1,
        source_links: [
          {
            id: "source-link-1",
            link_type: "evidence",
            note: "日报采信项触发",
            insight_id: null,
            daily_report_item_id: null,
            weekly_report_item_id: null,
            entity_milestone_id: null,
            historical_report_id: null,
            historical_feedback_item_id: null,
            news_item_id: "news-1",
            raw_item_id: "raw-1",
            source_object_type: "news_item",
            source_title: "Agent 编排能力进入工程化阶段",
            source_url: "https://example.com/agent-signal",
            data_source_name: "AI 工程源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    ]);
    operationsApi.updateRequirement.mockResolvedValue(
      requirement({
        source_count: 1,
        source_links: [
          {
            id: "source-link-1",
            link_type: "evidence",
            note: "日报采信项触发",
            insight_id: null,
            daily_report_item_id: null,
            weekly_report_item_id: null,
            entity_milestone_id: null,
            historical_report_id: null,
            historical_feedback_item_id: null,
            news_item_id: "news-1",
            raw_item_id: "raw-1",
            source_object_type: "news_item",
            source_title: "Agent 编排能力进入工程化阶段",
            source_url: "https://example.com/agent-signal",
            data_source_name: "AI 工程源",
            created_at: "2026-07-05T09:00:00Z"
          }
        ],
        metadata_json: {
          recommendation_feedback: {
            outcome: "negative",
            reason: "不纳入后续跟踪"
          }
        }
      })
    );
    const wrapper = mountPage();
    await flushPromises();

    const selects = wrapper.findAll(".requirement-row .task-row-actions .compact-field select");
    await selects[1].setValue("negative");
    await wrapper.find(".requirement-row .task-row-actions .compact-field input").setValue("不纳入后续跟踪");
    const actions = wrapper.findAll(".requirement-row .mini-action");
    await actions[1].trigger("click");
    await flushPromises();

    expect(operationsApi.updateRequirement).toHaveBeenCalledWith("req-1", {
      metadata_json: {
        recommendation_feedback: {
          outcome: "negative",
          reason: "不纳入后续跟踪"
        }
      }
    });
    expect(wrapper.text()).toContain("推荐反哺 负向");
  });

  it("hides owner and status controls from workspace viewers", async () => {
    const wrapper = mountPage({ role: "viewer", workspaceRole: "viewer" });
    await flushPromises();

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.find(".compact-field select").exists()).toBe(false);
    expect(wrapper.find(".mini-action").exists()).toBe(false);
    expect(workspacesApi.fetchWorkspaceMembers).not.toHaveBeenCalled();
  });
});
