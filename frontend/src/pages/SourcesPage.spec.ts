import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SourcesPage from "./SourcesPage.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const api = vi.hoisted(() => ({
  fetchSources: vi.fn(),
  previewSourceImport: vi.fn(),
  importLegacySources: vi.fn(),
  importTechInsightLoopSources: vi.fn(),
  fetchSource: vi.fn(),
  createSource: vi.fn(),
  updateSourceDefinition: vi.fn(),
  updateSourceWorkspaceConfig: vi.fn(),
  fetchWorkspaceLabelPolicy: vi.fn(),
  updateWorkspaceLabelPolicy: vi.fn()
}));

vi.mock("../api/sources", () => ({
  fetchSources: api.fetchSources,
  previewSourceImport: api.previewSourceImport,
  importLegacySources: api.importLegacySources,
  importTechInsightLoopSources: api.importTechInsightLoopSources,
  fetchSource: api.fetchSource,
  createSource: api.createSource,
  updateSourceDefinition: api.updateSourceDefinition,
  updateSourceWorkspaceConfig: api.updateSourceWorkspaceConfig
}));

vi.mock("../api/workspaces", () => ({
  fetchWorkspaceLabelPolicy: api.fetchWorkspaceLabelPolicy,
  updateWorkspaceLabelPolicy: api.updateWorkspaceLabelPolicy
}));

function labelPolicy() {
  return {
    workspace_code: "planning_intel",
    label_set_code: "ai_sql_categories",
    news_format_code: "company_sql_v1",
    export_category_mode: "news_primary",
    required_content_fields: [
      "background",
      "effects",
      "eventSummary",
      "technologyAndInnovation",
      "valueAndImpact"
    ],
    allowed_primary_categories: ["AI 应用", "模型"],
    secondary_labels_by_primary: {},
    default_category: "AI 应用",
    fallback_category: "AI 应用",
    tagging_stages: ["generation"]
  };
}

function sourceRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "source-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    source_type: "rss",
    name: "测试 RSS",
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
    workspace_source_weight: 1,
    workspace_daily_limit: null,
    workspace_clustering_config: {},
    ...overrides
  };
}

function mountPage(
  options: {
    canIngest?: boolean;
    noWorkspace?: boolean;
    sources?: ReturnType<typeof sourceRecord>[];
    sourcesError?: Error;
    legacyImportResult?: { created: number; updated: number; total: number };
    techImportResult?: {
      created: number;
      updated: number;
      total: number;
      fetchable: number;
      metadata_only: number;
    };
  } = {}
) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const workspace = useWorkspaceStore();
  workspace.currentCode = options.noWorkspace ? "" : "planning_intel";
  workspace.options = options.noWorkspace
    ? []
    : [
        {
          code: "planning_intel",
          name: "规划部情报工作台",
          description: "",
          workspace_type: "team",
          default_domain_code: "ai",
          enabled: true
        }
      ];

  const runtime = useRuntimeStore();
  runtime.checked = true;
  runtime.capabilities = {
    ingestion: options.canIngest ?? true,
    sync_publisher: false,
    sync_consumer: false,
    embedding: false,
    search: true
  };

  api.fetchWorkspaceLabelPolicy.mockResolvedValue(labelPolicy());
  if (options.sourcesError) {
    api.fetchSources.mockRejectedValue(options.sourcesError);
  } else {
    api.fetchSources.mockResolvedValue(options.sources ?? []);
  }
  api.previewSourceImport.mockResolvedValue({
    catalog: "legacy",
    total: 361,
    would_create: 294,
    would_update: 67,
    samples: [{ name: "OpenAI Blog", source_type: "rss", url: "https://openai.com/blog/rss.xml" }]
  });
  api.importLegacySources.mockResolvedValue(options.legacyImportResult ?? { created: 294, updated: 67, total: 361 });
  api.importTechInsightLoopSources.mockResolvedValue(
    options.techImportResult ?? { created: 0, updated: 0, total: 0, fetchable: 0, metadata_only: 0 }
  );

  return mount(SourcesPage, {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: {
          props: ["to"],
          template: '<a :href="typeof to === \'string\' ? to : \'#\'"><slot /></a>'
        }
      }
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

describe("SourcesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens an import preview before mutating source seeds", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "导入数据").trigger("click");
    await flushPromises();

    expect(api.previewSourceImport).toHaveBeenCalledWith("legacy");
    expect(api.importLegacySources).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("导入预览");
    expect(wrapper.text()).toContain("361 识别记录");
    expect(wrapper.text()).toContain("294 将新增");

    await buttonByText(wrapper, "确认导入").trigger("click");
    await flushPromises();

    expect(api.importLegacySources).toHaveBeenCalledTimes(1);
    expect(api.fetchSources).toHaveBeenCalledWith("planning_intel");
    expect(wrapper.text()).toContain("导入完成：新增 294，更新 67，总计 361");
  });

  it("shows a warning instead of success when legacy import finds no records", async () => {
    const wrapper = mountPage({ legacyImportResult: { created: 0, updated: 0, total: 0 } });
    await flushPromises();

    await buttonByText(wrapper, "导入数据").trigger("click");
    await flushPromises();
    await buttonByText(wrapper, "确认导入").trigger("click");
    await flushPromises();

    expect(api.importLegacySources).toHaveBeenCalledTimes(1);
    expect(wrapper.find(".form-warning").text()).toContain("未发现可导入的旧种子源");
    expect(wrapper.find(".form-success").exists()).toBe(false);
  });

  it("shows an info state when legacy import only updates existing records", async () => {
    const wrapper = mountPage({ legacyImportResult: { created: 0, updated: 7, total: 361 } });
    await flushPromises();

    await buttonByText(wrapper, "导入数据").trigger("click");
    await flushPromises();
    await buttonByText(wrapper, "确认导入").trigger("click");
    await flushPromises();

    expect(api.importLegacySources).toHaveBeenCalledTimes(1);
    expect(wrapper.find(".form-info").text()).toContain("源已全部存在，本次更新 7 条元数据");
    expect(wrapper.find(".form-success").exists()).toBe(false);
  });

  it("shows a warning instead of success when Tech source import finds no records", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "导入 Tech 源").trigger("click");
    await flushPromises();
    await buttonByText(wrapper, "确认导入").trigger("click");
    await flushPromises();

    expect(api.importTechInsightLoopSources).toHaveBeenCalledTimes(1);
    expect(wrapper.find(".form-warning").text()).toContain("未识别到 Tech 源数据");
    expect(wrapper.find(".form-success").exists()).toBe(false);
  });

  it("hides ingestion controls in read-only deployment modes", async () => {
    const wrapper = mountPage({ canIngest: false, sources: [sourceRecord()] });
    await flushPromises();

    const buttonTexts = wrapper.findAll("button").map((button) => button.text());
    expect(buttonTexts.some((text) => text.includes("新增源"))).toBe(false);
    expect(buttonTexts.some((text) => text.includes("导入数据"))).toBe(false);
    expect(buttonTexts.some((text) => text.includes("导入 Tech 源"))).toBe(false);
    expect(buttonTexts.some((text) => text.includes("抓取"))).toBe(false);
  });

  it("marks manual and unconfigured internal sources as push-based with the semantic tooltip", async () => {
    const wrapper = mountPage({
      sources: [
        sourceRecord({ id: "source-manual", source_type: "manual", url: null, name: "手工导入源" }),
        sourceRecord({ id: "source-internal", source_type: "internal", url: null, name: "内部系统源" }),
        sourceRecord({
          id: "source-internal-pull",
          source_type: "internal",
          url: "https://intranet.example.com/api/items",
          name: "内部拉取源"
        }),
        sourceRecord()
      ]
    });
    await flushPromises();

    // manual 恒为推入式；internal 未配入口视为推入式；配了入口的 internal 与 rss 不打标。
    const chips = wrapper.findAll(".push-based-chip");
    expect(chips).toHaveLength(2);
    expect(chips[0].text()).toContain("推入式");
    expect(chips[0].attributes("title")).toContain("定时抓取 0 条是正常行为");
    expect(wrapper.text()).toContain("手工导入");
    expect(wrapper.text()).toContain("内部系统");
  });

  it("marks unconfigured wechat sources as 待配置 instead of a broken source", async () => {
    const wrapper = mountPage({
      sources: [
        sourceRecord({
          id: "source-wx",
          source_type: "wechat",
          url: null,
          enabled: false,
          needs_entry: true,
          metadata_only: true,
          fetch_entry_status: "needs_entry",
          workspace_link_enabled: false,
          name: "机器之心公众号"
        })
      ]
    });
    await flushPromises();

    const chip = wrapper.find(".wechat-pending-chip");
    expect(chip.exists()).toBe(true);
    expect(chip.text()).toContain("待配置");
    expect(chip.attributes("title")).toContain("RSSHub");
    expect(wrapper.text()).toContain("微信公众号");
    expect(wrapper.find(".push-based-chip").exists()).toBe(false);
  });

  it("groups the import preview by source_type with push-based and wechat semantics", async () => {
    const wrapper = mountPage();
    await flushPromises();
    api.previewSourceImport.mockResolvedValue({
      catalog: "tech",
      total: 5,
      would_create: 5,
      would_update: 0,
      samples: [
        { name: "OpenAI Blog", source_type: "rss", url: "https://openai.com/blog/rss.xml" },
        { name: "内部快讯 API", source_type: "internal", url: null },
        { name: "机器之心公众号", source_type: "wechat", url: null },
        { name: "新智元公众号", source_type: "wechat", url: null }
      ]
    });

    await buttonByText(wrapper, "导入 Tech 源").trigger("click");
    await flushPromises();

    const panel = wrapper.find('[aria-label="数据源导入预览"]');
    const groups = panel.findAll(".preview-group");
    expect(groups).toHaveLength(3);
    // 分组按 source_type 排序：internal / rss / wechat，各组给出样本小计。
    expect(groups[0].text()).toContain("内部系统");
    expect(groups[0].text()).toContain("样本 1 条");
    expect(groups[0].find(".preview-group-note").text()).toContain("推入式源");
    expect(groups[1].text()).toContain("RSS");
    expect(groups[1].find(".preview-group-note").exists()).toBe(false);
    expect(groups[2].text()).toContain("微信公众号");
    expect(groups[2].text()).toContain("样本 2 条");
    expect(groups[2].find(".preview-group-note").text()).toContain("待配置");
  });

  it("links every source row to the source detail page", async () => {
    const wrapper = mountPage({ sources: [sourceRecord()] });
    await flushPromises();

    const detailLink = wrapper.find('a[href="/sources/source-1"]');
    expect(detailLink.exists()).toBe(true);
    expect(detailLink.text()).toContain("详情");
  });

  it("creates a paper API source from the source panel", async () => {
    api.createSource.mockResolvedValue({
      created: true,
      source: sourceRecord({
        id: "source-paper-api",
        source_type: "paper_api",
        name: "Semantic Scholar AI API",
        url: "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=artificial%20intelligence",
        backfill_days: 30
      })
    });
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "新增源").trigger("click");
    await flushPromises();
    const panel = wrapper.find('[aria-label="新增信息源"]');
    expect(panel.text()).toContain("论文 API");

    await panel.find('input[placeholder="例如 机器之心 RSS"]').setValue("Semantic Scholar AI API");
    await panel.find("select").setValue("paper_api");
    expect(
      panel
        .find(
          'input[placeholder="https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=artificial%20intelligence"]'
        )
        .exists()
    ).toBe(true);
    await panel
      .find(
        'input[placeholder="https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=artificial%20intelligence"]'
      )
      .setValue("https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=artificial%20intelligence");
    await panel.find('input[type="number"]').setValue("30");

    await buttonByText(wrapper, "创建并启用").trigger("click");
    await flushPromises();

    expect(api.createSource).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        name: "Semantic Scholar AI API",
        source_type: "paper_api",
        url: "https://api.semanticscholar.org/graph/v1/paper/search/bulk?query=artificial%20intelligence",
        backfill_days: 30
      })
    );
    expect(wrapper.text()).toContain("已创建信息源：Semantic Scholar AI API");
  });

  it("shows an error instead of a success message when label policy save fails", async () => {
    api.updateWorkspaceLabelPolicy.mockRejectedValue(new Error("permission denied"));
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "保存策略").trigger("click");
    await flushPromises();

    expect(api.updateWorkspaceLabelPolicy).toHaveBeenCalledWith(
      "planning_intel",
      expect.objectContaining({
        label_set_code: "ai_sql_categories",
        news_format_code: "company_sql_v1",
        allowed_primary_categories: ["AI 应用", "模型"]
      })
    );
    expect(wrapper.find(".form-error").text()).toContain("permission denied");
    expect(wrapper.find(".form-success").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("已保存：规划部情报工作台 的统一标签策略");
  });

  it("shows the membership permission error when the source list request is rejected", async () => {
    const wrapper = mountPage({ sourcesError: new Error("permission denied: workspace membership required") });
    await flushPromises();

    // 无 membership 的 403 拒绝：源列表加载失败要给出错误提示，而不是留一片空白。
    expect(wrapper.find(".form-error").text()).toContain("permission denied: workspace membership required");
    expect(wrapper.findAll(".source-row")).toHaveLength(0);
  });

  it("renders an idle empty state without requesting sources when the user has no workspace", async () => {
    const wrapper = mountPage({ noWorkspace: true });
    await flushPromises();

    // 空 workspace 列表（无任何成员身份）：不发起数据请求，首屏保留空态引导而不是白屏。
    expect(api.fetchSources).not.toHaveBeenCalled();
    expect(api.fetchWorkspaceLabelPolicy).not.toHaveBeenCalled();
    expect(wrapper.find(".empty-state").text()).toContain("暂无数据源");
  });
});
