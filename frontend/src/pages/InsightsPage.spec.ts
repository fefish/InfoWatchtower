import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import InsightsPage from "./InsightsPage.vue";
import type { InsightRecord, StrategicImplicationRecord } from "../api/operations";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createInsight: vi.fn(),
  createStrategicImplication: vi.fn(),
  fetchInsights: vi.fn(),
  fetchStrategicImplications: vi.fn(),
  updateInsight: vi.fn(),
  updateStrategicImplication: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/operations", () => ({
  createInsight: operationsApi.createInsight,
  createStrategicImplication: operationsApi.createStrategicImplication,
  fetchInsights: operationsApi.fetchInsights,
  fetchStrategicImplications: operationsApi.fetchStrategicImplications,
  updateInsight: operationsApi.updateInsight,
  updateStrategicImplication: operationsApi.updateStrategicImplication
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function insight(overrides: Partial<InsightRecord> = {}): InsightRecord {
  return {
    id: "insight-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    news_item_id: "news-1",
    raw_item_id: "raw-1",
    title: "Agent 记忆层进入产品化",
    summary: "需要判断内部工具链是否要引入记忆层。",
    insight_type: "trend",
    status: "draft",
    source_report_type: "daily",
    source_report_id: "daily-1",
    source_report_item_id: "daily-item-1",
    source_title: "Agent runtime gains memory layer",
    source_url: "https://example.com/agent-memory",
    data_source_name: "Strategy Source",
    implication_count: 1,
    confidence_score: 0.82,
    metadata_json: {},
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function implication(overrides: Partial<StrategicImplicationRecord> = {}): StrategicImplicationRecord {
  return {
    id: "implication-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    insight_id: "insight-1",
    insight_title: "Agent 记忆层进入产品化",
    title: "内部工具链需要记忆能力评估",
    description: "影响 Agent 编排、权限和长期上下文设计。",
    implication_type: "opportunity",
    metadata_json: {},
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function mountPage(options: { role?: "super_admin" | "viewer"; workspaceRole?: string } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const session = useSessionStore();
  session.user = {
    id: "user-1",
    external_provider: "local",
    external_id: "user-1",
    employee_no: null,
    username: "user-1",
    display_name: "User One",
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

  return mount(InsightsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("InsightsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    operationsApi.fetchInsights.mockResolvedValue([insight()]);
    operationsApi.fetchStrategicImplications.mockResolvedValue([implication()]);
    operationsApi.createInsight.mockResolvedValue(insight({ id: "insight-new", implication_count: 0 }));
    operationsApi.createStrategicImplication.mockResolvedValue(implication({ id: "implication-new" }));
    operationsApi.updateInsight.mockResolvedValue(insight({ status: "confirmed" }));
    operationsApi.updateStrategicImplication.mockResolvedValue(implication({ implication_type: "risk" }));
  });

  it("renders insights with source trace and implications", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchInsights).toHaveBeenCalledWith("planning_intel", { status: undefined, q: undefined });
    expect(wrapper.text()).toContain("Agent 记忆层进入产品化");
    expect(wrapper.text()).toContain("Agent runtime gains memory layer");
    expect(wrapper.text()).toContain("Strategy Source");
    expect(wrapper.text()).toContain("内部工具链需要记忆能力评估");
  });

  it("creates an insight from a news item id", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const inputs = wrapper.findAll("form").at(0)!.findAll("input");
    await inputs[0].setValue("news-2");
    await inputs[1].setValue("推理基础设施成为新瓶颈");
    await wrapper.findAll("form").at(0)!.find("textarea").setValue("需要评估成本和架构影响");
    await wrapper.findAll("form").at(0)!.trigger("submit");
    await flushPromises();

    expect(operationsApi.createInsight).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        news_item_id: "news-2",
        title: "推理基础设施成为新瓶颈",
        summary: "需要评估成本和架构影响"
      })
    );
  });

  it("creates and edits strategic implications", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const implicationForm = wrapper.findAll("form").at(1)!;
    await implicationForm.find("input").setValue("内部基础设施需要容量复盘");
    await implicationForm.find("textarea").setValue("影响 GPU 采购和模型服务部署");
    await implicationForm.trigger("submit");
    await flushPromises();

    expect(operationsApi.createStrategicImplication).toHaveBeenCalledWith(
      expect.objectContaining({
        insight_id: "insight-1",
        title: "内部基础设施需要容量复盘",
        description: "影响 GPU 采购和模型服务部署"
      })
    );

    await wrapper.find(".implication-row .mini-action").trigger("click");
    await flushPromises();
    const implicationInputs = wrapper.find(".implication-row").findAll("input");
    await implicationInputs[0].setValue("内部基础设施需要风险复盘");
    await wrapper.find(".implication-row .mini-action.active").trigger("click");
    await flushPromises();

    expect(operationsApi.updateStrategicImplication).toHaveBeenCalledWith(
      "implication-new",
      expect.objectContaining({
        title: "内部基础设施需要风险复盘"
      })
    );
  });

  it("updates insight status and hides write controls from viewers", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const insightButtons = wrapper.find(".insight-row").findAll(".mini-action");
    await insightButtons[1].trigger("click");
    await flushPromises();
    expect(operationsApi.updateInsight).toHaveBeenCalledWith("insight-1", { status: "confirmed" });

    const viewerWrapper = mountPage({ role: "viewer", workspaceRole: "viewer" });
    await flushPromises();
    expect(viewerWrapper.find("form").exists()).toBe(false);
    expect(viewerWrapper.find(".insight-row .mini-action").exists()).toBe(false);
  });
});
