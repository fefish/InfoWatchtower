import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AppShell from "./AppShell.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useSessionStore } from "../stores/session";

const pushMock = vi.hoisted(() => vi.fn());

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: pushMock
  })
}));

const workspaceApi = vi.hoisted(() => ({
  fetchWorkspaces: vi.fn(),
  fetchWorkspaceSections: vi.fn(),
  createWorkspace: vi.fn(),
  updateWorkspaceLabelPolicy: vi.fn()
}));

const sourceApi = vi.hoisted(() => ({
  createSource: vi.fn(),
  fetchSources: vi.fn(),
  updateSourceWorkspaceConfig: vi.fn()
}));

const notificationsApi = vi.hoisted(() => ({
  fetchUnreadNotificationCount: vi.fn()
}));

const searchApi = vi.hoisted(() => ({
  searchWorkspace: vi.fn()
}));
const localStorageMock = vi.hoisted(() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    })
  };
});

vi.mock("../api/workspaces", () => ({
  createWorkspace: workspaceApi.createWorkspace,
  fetchWorkspaces: workspaceApi.fetchWorkspaces,
  fetchWorkspaceSections: workspaceApi.fetchWorkspaceSections,
  updateWorkspaceLabelPolicy: workspaceApi.updateWorkspaceLabelPolicy
}));

vi.mock("../api/sources", () => ({
  createSource: sourceApi.createSource,
  fetchSources: sourceApi.fetchSources,
  updateSourceWorkspaceConfig: sourceApi.updateSourceWorkspaceConfig
}));

vi.mock("../api/notifications", () => ({
  fetchUnreadNotificationCount: notificationsApi.fetchUnreadNotificationCount
}));

vi.mock("../api/search", () => ({
  searchWorkspace: searchApi.searchWorkspace
}));

const routerLinkStub = {
  props: ["to"],
  template: `<a :href="typeof to === 'string' ? to : to.path"><slot /></a>`
};

function planningWorkspace() {
  return {
    code: "planning_intel",
    name: "规划部情报工作台",
    description: "行业信号、日报周报、专题洞察和内部需求闭环。",
    workspace_type: "team",
    default_domain_code: "ai",
    enabled: true
  };
}

function mountShell(options: { workspaces?: ReturnType<typeof planningWorkspace>[] } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const session = useSessionStore();
  session.user = {
    id: "user-1",
    external_provider: "local",
    external_id: "admin",
    employee_no: null,
    username: "admin",
    display_name: "规划部管理员",
    department: null,
    email: "admin@example.com",
    roles: ["super_admin"],
    status: "active",
    is_active: true
  };
  session.checked = true;

  const runtime = useRuntimeStore();
  runtime.checked = true;
  runtime.deployMode = "standalone";
  runtime.capabilities = {
    ingestion: true,
    sync_publisher: false,
    sync_consumer: false,
    embedding: false,
    search: true
  };

  workspaceApi.fetchWorkspaces.mockResolvedValue(options.workspaces ?? [planningWorkspace()]);
  workspaceApi.fetchWorkspaceSections.mockResolvedValue([
    {
      section_key: "dashboard",
      name: "今日速览",
      section_type: "core",
      route_path: "/dashboard",
      sort_order: 1,
      enabled: true,
      group: "today"
    },
    {
      section_key: "ingestion_coverage",
      name: "抓取与覆盖",
      section_type: "core",
      route_path: "/ingestion-runs",
      sort_order: 2,
      enabled: true,
      group: "collect"
    }
  ]);
  notificationsApi.fetchUnreadNotificationCount.mockResolvedValue({ unread_count: 3 });
  return mount(AppShell, {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: routerLinkStub,
        RouterView: { template: "<main />" }
      }
    }
  });
}

describe("AppShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "localStorage", {
      value: localStorageMock,
      configurable: true
    });
    localStorageMock.clear();
    searchApi.searchWorkspace.mockResolvedValue({
      query: "agent",
      workspace_code: "planning_intel",
      results: [],
      next_cursor: null
    });
  });

  it("renders real global search and uses the notifications entry", async () => {
    const wrapper = mountShell();
    await flushPromises();

    expect(wrapper.find('input[type="search"]').exists()).toBe(true);
    expect(wrapper.find(".global-search").exists()).toBe(true);
    const notificationEntry = wrapper.find('a[aria-label="消息通知"]');
    expect(notificationsApi.fetchUnreadNotificationCount).toHaveBeenCalledTimes(1);
    expect(notificationEntry.exists()).toBe(true);
    expect(notificationEntry.attributes("href")).toBe("/notifications");
    expect(notificationEntry.find(".notification-badge").text()).toBe("3");
  });

  it("searches workspace objects and opens the selected result", async () => {
    searchApi.searchWorkspace.mockResolvedValue({
      query: "agent",
      workspace_code: "planning_intel",
      results: [
        {
          object_type: "daily_report_item",
          object_id: "item-1",
          title: "Agent 工程能力日报条目",
          summary: "日报条目摘要",
          matched_fields: ["title"],
          highlight: "Agent 工程能力",
          route: "/daily-reports?item_id=item-1",
          score: 0.91,
          updated_at: "2026-07-05T09:00:00Z"
        }
      ],
      next_cursor: null
    });

    const wrapper = mountShell();
    await flushPromises();
    await wrapper.find('input[type="search"]').setValue("agent");
    await flushPromises();

    expect(searchApi.searchWorkspace).toHaveBeenCalledWith("planning_intel", "agent", undefined, 10);
    expect(wrapper.find(".global-search-result").text()).toContain("Agent 工程能力日报条目");

    await wrapper.find(".global-search-result").trigger("click");
    expect(pushMock).toHaveBeenCalledWith("/daily-reports?item_id=item-1");
    expect(
      JSON.parse(localStorageMock.getItem("infowatchtower:search:recent:user-1:planning_intel") || "[]")[0]
    ).toMatchObject({
      object_type: "daily_report_item",
      object_id: "item-1",
      route: "/daily-reports?item_id=item-1"
    });
  });

  it("groups search results by object type and supports keyboard selection", async () => {
    searchApi.searchWorkspace.mockResolvedValue({
      query: "agent",
      workspace_code: "planning_intel",
      results: [
        {
          object_type: "daily_report_item",
          object_id: "item-1",
          title: "Agent 日报条目",
          summary: "日报条目摘要",
          matched_fields: ["title"],
          highlight: "Agent 日报",
          route: "/daily-reports?item_id=item-1",
          score: 0.91,
          updated_at: "2026-07-05T09:00:00Z"
        },
        {
          object_type: "export_job_item",
          object_id: "export-item-1",
          title: "Agent 导出 trace",
          summary: "导出追溯摘要",
          matched_fields: ["title"],
          highlight: "Agent 导出",
          route: "/exports?export_job_id=export-1&export_job_item_id=export-item-1",
          score: 0.88,
          updated_at: "2026-07-05T09:00:00Z"
        }
      ],
      next_cursor: null
    });

    const wrapper = mountShell();
    await flushPromises();
    const input = wrapper.find('input[type="search"]');
    await input.setValue("agent");
    await flushPromises();

    expect(wrapper.findAll(".global-search-group-title").map((item) => item.text())).toEqual([
      "日报条目1",
      "导出 trace1"
    ]);
    expect(wrapper.find(".global-search-result.active").text()).toContain("Agent 日报条目");

    await input.trigger("keydown", { key: "ArrowDown" });
    expect(wrapper.find(".global-search-result.active").text()).toContain("Agent 导出 trace");

    await input.trigger("keydown", { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith("/exports?export_job_id=export-1&export_job_item_id=export-item-1");
  });

  it("shows recent search results scoped by user and workspace", async () => {
    localStorageMock.setItem(
      "infowatchtower:search:recent:user-1:planning_intel",
      JSON.stringify([
        {
          object_type: "weekly_report_item",
          object_id: "weekly-item-1",
          title: "最近打开的周报条目",
          summary: "近期摘要",
          matched_fields: [],
          highlight: "近期摘要",
          route: "/weekly-reports?report_id=weekly-1&item_id=weekly-item-1",
          score: 0,
          updated_at: "2026-07-05T09:00:00Z"
        }
      ])
    );

    const wrapper = mountShell();
    await flushPromises();
    const input = wrapper.find('input[type="search"]');
    await input.trigger("focus");
    await flushPromises();

    expect(searchApi.searchWorkspace).not.toHaveBeenCalled();
    expect(wrapper.find(".global-search-recent-title").text()).toBe("最近打开");
    expect(wrapper.find(".global-search-result").text()).toContain("最近打开的周报条目");

    await input.trigger("keydown", { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith("/weekly-reports?report_id=weekly-1&item_id=weekly-item-1");
  });

  it("uses the top-right user pill as a real account entry", async () => {
    const wrapper = mountShell();
    await flushPromises();

    const accountEntry = wrapper.find('a[aria-label="账号设置"]');
    expect(accountEntry.exists()).toBe(true);
    expect(accountEntry.attributes("href")).toBe("/account");
    expect(accountEntry.text()).toContain("规划部管理员");
  });

  it("hides ingestion navigation when the deployment cannot ingest", async () => {
    const wrapper = mountShell();
    const runtime = useRuntimeStore();
    runtime.capabilities.ingestion = false;
    await flushPromises();

    expect(wrapper.text()).not.toContain("抓取与覆盖");
  });

  it("keeps the create-workspace entry as first-screen guidance when the user has no workspace", async () => {
    const wrapper = mountShell({ workspaces: [] });
    await flushPromises();

    // 空 workspace 列表不应白屏崩溃：管理员首屏可见「新建工作台」引导入口，标题回退为通用文案。
    expect(wrapper.find(".workspace-create-button").exists()).toBe(true);
    expect(wrapper.find(".topbar-title h1").text()).toBe("工作台");
    expect(wrapper.findAll(".workspace-switcher option")).toHaveLength(0);
  });
});

describe("AppShell 建台向导", () => {
  const aiSqlCategories = [
    "AI Infra",
    "AI 应用",
    "测评技术",
    "大厂动态",
    "模型",
    "算法",
    "推理加速",
    "训练技术",
    "智能体",
    "基础竞争力"
  ];
  const requiredContentFields = [
    "background",
    "effects",
    "eventSummary",
    "technologyAndInnovation",
    "valueAndImpact"
  ];

  function sharedSource(overrides: Record<string, unknown> = {}) {
    return {
      id: "source-1",
      workspace_code: "planning_intel",
      domain_code: "ai",
      source_type: "rss",
      name: "共享 RSS 源",
      url: "https://example.com/feed.xml",
      enabled: true,
      default_focus_id: 1,
      backfill_days: 7,
      source_score: 1,
      last_fetch_at: null,
      last_success_at: null,
      last_error: "",
      primary_category: "",
      info_category: "",
      source_tags: [],
      source_secondary_tags: [],
      source_tier: "",
      source_channel_type: "",
      expert_routes: [],
      inclusion_recommendation: "",
      metadata_only: false,
      needs_entry: false,
      fetch_entry_status: "ready",
      source_quality_notes: "",
      workspace_link_enabled: true,
      workspace_source_weight: 2,
      workspace_daily_limit: 5,
      workspace_clustering_config: {},
      ...overrides
    };
  }

  function wizardButton(wrapper: ReturnType<typeof mountShell>, text: string) {
    const button = wrapper
      .findAll(".workspace-wizard button, .workspace-wizard-done button")
      .find((item) => item.text().includes(text));
    if (!button) {
      throw new Error(`Wizard button not found: ${text}`);
    }
    return button;
  }

  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "localStorage", {
      value: localStorageMock,
      configurable: true
    });
    localStorageMock.clear();
    searchApi.searchWorkspace.mockResolvedValue({
      query: "",
      workspace_code: "planning_intel",
      results: [],
      next_cursor: null
    });
    sourceApi.fetchSources.mockResolvedValue([sharedSource()]);
    sourceApi.updateSourceWorkspaceConfig.mockResolvedValue(sharedSource());
    sourceApi.createSource.mockResolvedValue({ id: "source-new" });
    workspaceApi.createWorkspace.mockResolvedValue({
      code: "hardware_intel",
      name: "硬件情报工作台",
      description: "",
      workspace_type: "team",
      default_domain_code: "hardware",
      enabled: true
    });
    workspaceApi.updateWorkspaceLabelPolicy.mockResolvedValue({});
  });

  async function openWizard(wrapper: ReturnType<typeof mountShell>) {
    await wrapper.find(".workspace-create-button").trigger("click");
    await flushPromises();
  }

  async function fillBasicsAndGoToStep2(wrapper: ReturnType<typeof mountShell>) {
    await wrapper.find('input[placeholder="例如 hardware_intel"]').setValue("hardware_intel");
    await wrapper.find('input[placeholder="例如 硬件情报工作台"]').setValue("硬件情报工作台");
    await wrapper.find('input[placeholder="ai / hardware / policy"]').setValue("hardware");
    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();
  }

  it("walks through the three wizard steps and rejects invalid workspace codes", async () => {
    const wrapper = mountShell();
    await flushPromises();
    await openWizard(wrapper);

    expect(wrapper.find(".workspace-wizard").exists()).toBe(true);
    expect(wrapper.find(".wizard-steps span.active").text()).toContain("基本信息");

    // 非法标识（数字开头）在第 1 步被拦截，不进入第 2 步。
    await wrapper.find('input[placeholder="例如 hardware_intel"]').setValue("1bad-code");
    await wrapper.find('input[placeholder="例如 硬件情报工作台"]').setValue("硬件情报工作台");
    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();
    expect(wrapper.find(".workspace-wizard .form-error").text()).toContain("标识需以小写字母开头");
    expect(wrapper.find(".wizard-steps span.active").text()).toContain("基本信息");

    await wrapper.find('input[placeholder="例如 hardware_intel"]').setValue("hardware_intel");
    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();
    expect(wrapper.find(".wizard-steps span.active").text()).toContain("选择信息源");
    expect(sourceApi.fetchSources).toHaveBeenCalled();
    expect(wrapper.find(".wizard-source-row").text()).toContain("共享 RSS 源");

    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();
    expect(wrapper.find(".wizard-steps span.active").text()).toContain("标签策略");
    expect(wrapper.find('input[type="radio"][value="ai_sql"]').exists()).toBe(true);
  });

  it("links checked shared sources via workspace-link and submits the ai_sql preset policy", async () => {
    const wrapper = mountShell();
    await flushPromises();
    await openWizard(wrapper);
    await fillBasicsAndGoToStep2(wrapper);

    await wrapper.find('.wizard-source-row input[type="checkbox"]').setValue(true);
    expect(wrapper.find(".wizard-section-title span").text()).toContain("1 已选");
    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();

    await wrapper.find('input[type="radio"][value="ai_sql"]').setValue(true);
    await wizardButton(wrapper, "创建工作台").trigger("click");
    await flushPromises();

    expect(workspaceApi.createWorkspace).toHaveBeenCalledWith({
      code: "hardware_intel",
      name: "硬件情报工作台",
      description: "",
      default_domain_code: "hardware"
    });
    // 勾选的共享源逐个走 workspace-link 挂到新工作台，沿用共享池里的权重和日配额。
    expect(sourceApi.updateSourceWorkspaceConfig).toHaveBeenCalledWith("source-1", {
      workspace_code: "hardware_intel",
      enabled: true,
      source_weight: 2,
      daily_limit: 5
    });
    expect(sourceApi.createSource).not.toHaveBeenCalled();
    expect(workspaceApi.updateWorkspaceLabelPolicy).toHaveBeenCalledWith("hardware_intel", {
      label_set_code: "ai_sql_categories",
      news_format_code: "company_sql_v1",
      export_category_mode: "news_primary",
      required_content_fields: requiredContentFields,
      allowed_primary_categories: aiSqlCategories,
      secondary_labels_by_primary: {},
      default_category: "AI 应用",
      fallback_category: "AI 应用"
    });

    // 完成页给出下一步入口：完成关闭 + 前往数据源管理。
    const done = wrapper.find(".workspace-wizard-done");
    expect(done.exists()).toBe(true);
    expect(done.text()).toContain("hardware_intel");
    expect(done.text()).toContain("数据源");
    await wizardButton(wrapper, "数据源").trigger("click");
    expect(pushMock).toHaveBeenCalledWith("/sources");
  });

  it("creates the custom source and derives the blank preset policy from custom categories", async () => {
    const wrapper = mountShell();
    await flushPromises();
    await openWizard(wrapper);
    await fillBasicsAndGoToStep2(wrapper);

    await wrapper.find('input[placeholder="例如 硬件新闻 RSS"]').setValue("硬件新闻 RSS");
    await wrapper.find('input[placeholder="https://example.com/feed.xml"]').setValue("https://hw.example.com/feed.xml");
    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();

    await wrapper.find('input[type="radio"][value="blank"]').setValue(true);
    await wrapper.find(".wizard-textarea-label textarea").setValue("算力芯片\n\n端侧设备\n");
    await wizardButton(wrapper, "创建工作台").trigger("click");
    await flushPromises();

    expect(sourceApi.createSource).toHaveBeenCalledWith({
      workspace_code: "hardware_intel",
      name: "硬件新闻 RSS",
      source_type: "rss",
      url: "https://hw.example.com/feed.xml",
      domain_code: "hardware"
    });
    // 空白预设：空行被清理，首个标签兜底为 default/fallback。
    expect(workspaceApi.updateWorkspaceLabelPolicy).toHaveBeenCalledWith(
      "hardware_intel",
      expect.objectContaining({
        label_set_code: "hardware_intel_custom_categories",
        news_format_code: "custom_intel_v1",
        allowed_primary_categories: ["算力芯片", "端侧设备"],
        default_category: "算力芯片",
        fallback_category: "算力芯片"
      })
    );
    expect(wrapper.find(".workspace-wizard-done").exists()).toBe(true);
  });

  it("submits the ai_tools preset with secondary labels for every primary category", async () => {
    const wrapper = mountShell();
    await flushPromises();
    await openWizard(wrapper);
    await fillBasicsAndGoToStep2(wrapper);
    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();

    await wrapper.find('input[type="radio"][value="ai_tools"]').setValue(true);
    await wizardButton(wrapper, "创建工作台").trigger("click");
    await flushPromises();

    expect(workspaceApi.updateWorkspaceLabelPolicy).toHaveBeenCalledWith(
      "hardware_intel",
      expect.objectContaining({
        label_set_code: "ai_tools_categories",
        news_format_code: "tool_intel_v1",
        allowed_primary_categories: ["工具新功能", "工具新案例", "工具新技术"],
        secondary_labels_by_primary: {
          工具新功能: ["cursor", "claude code", "opencode", "codex"],
          工具新案例: ["cursor", "claude code", "opencode", "codex"],
          工具新技术: ["cursor", "claude code", "opencode", "codex"]
        },
        default_category: "工具新功能"
      })
    );
  });

  it("keeps the wizard open and shows the error when the policy step fails mid-flow", async () => {
    workspaceApi.updateWorkspaceLabelPolicy.mockRejectedValue(new Error("permission denied: workspace admin required"));
    const wrapper = mountShell();
    await flushPromises();
    await openWizard(wrapper);
    await fillBasicsAndGoToStep2(wrapper);
    await wizardButton(wrapper, "下一步").trigger("click");
    await flushPromises();

    await wizardButton(wrapper, "创建工作台").trigger("click");
    await flushPromises();

    // 工作台已创建但策略挂载失败：向导停在第 3 步展示错误，不进入完成页。
    expect(workspaceApi.createWorkspace).toHaveBeenCalled();
    expect(wrapper.find(".workspace-wizard .form-error").text()).toContain("permission denied: workspace admin required");
    expect(wrapper.find(".workspace-wizard-done").exists()).toBe(false);
    expect(wrapper.find(".wizard-steps span.active").text()).toContain("标签策略");
  });
});
