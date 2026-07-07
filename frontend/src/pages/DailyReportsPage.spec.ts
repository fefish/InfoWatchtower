import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DailyReportsPage from "./DailyReportsPage.vue";
import { useWorkspaceStore } from "../stores/workspace";

const reportsApi = vi.hoisted(() => ({
  createDailyReportItemComment: vi.fn(),
  createDailyReportItemEntityMilestone: vi.fn(),
  createDailyReportItemInsight: vi.fn(),
  createDailyPipelineRun: vi.fn(),
  fetchDailyReportItemComments: vi.fn(),
  fetchDailyReports: vi.fn(),
  publishDailyReport: vi.fn(),
  rateDailyReportItem: vi.fn(),
  regenerateDailyReportGeneratedNews: vi.fn(),
  reactToDailyReportItem: vi.fn(),
  updateDailyReportItem: vi.fn()
}));

const renditionsApi = vi.hoisted(() => ({
  createReportFormat: vi.fn(),
  dailyRenditionExportUrl: vi.fn(),
  deleteReportFormat: vi.fn(),
  fetchDailyRenditions: vi.fn(),
  fetchReportFormats: vi.fn(),
  regenerateDailyRendition: vi.fn(),
  updateReportFormat: vi.fn()
}));

const workspaceApi = vi.hoisted(() => ({
  fetchWorkspaceFeedbackPolicy: vi.fn()
}));

const watchersApi = vi.hoisted(() => ({
  fetchObjectWatcher: vi.fn(),
  updateObjectWatcher: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/reports", () => reportsApi);

vi.mock("../api/renditions", () => renditionsApi);

vi.mock("../api/workspaces", () => ({
  fetchWorkspaceFeedbackPolicy: workspaceApi.fetchWorkspaceFeedbackPolicy
}));

vi.mock("../api/watchers", () => watchersApi);

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function reportRecord() {
  return {
    id: "report-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    day_key: "2026-07-05",
    title: "规划部日报",
    summary: "今日摘要",
    status: "draft",
    published_at: null,
    items: [
      {
        id: "item-1",
        generated_news: {
          id: "generated-1",
          category: "模型",
          title: "测试新闻标题",
          summary: "测试摘要",
          key_points: "测试要点",
          content_json: {
            background: "背景",
            effects: "效果",
            eventSummary: "事件",
            technologyAndInnovation: "技术",
            valueAndImpact: "价值"
          },
          source_url: "https://example.com/news",
          generation_status: "ready",
          news_item_id: "news-1",
          recommendation_item_id: "rec-1"
        },
        adoption_status: 2,
        is_headline: false,
        sort_order: 1,
        editor_title: null,
        editor_summary: null,
        editor_key_points: null,
        editor_content_json: null,
        editor_notes: "",
        reaction_count: 0,
        rating_count: 0,
        rating_avg: 0,
        comment_count: 0
      }
    ]
  };
}

function reportFormat(formatCode: string, name: string) {
  return {
    id: `format-${formatCode}`,
    workspace_code: "planning_intel",
    format_code: formatCode,
    name,
    description: "",
    builtin: formatCode !== "custom_brief_v1",
    locked: formatCode === "company_sql_v1",
    group_by: formatCode === "company_sql_v1" ? "category" : "board",
    headline_enabled: formatCode !== "company_sql_v1",
    headline_auto_top_n: 6,
    item_fields: ["tag_line", "bullet_points", "takeaway", "source_link"],
    export_targets: ["md", "html"],
    enabled: true,
    sort_order: formatCode === "company_sql_v1" ? 10 : 20
  };
}

function renditionRecord() {
  return {
    id: "rendition-1",
    report_type: "daily",
    report_id: "report-1",
    format_code: "tech_insight_v1",
    status: "draft",
    title: "2026-07-05 技术洞察版",
    summary_json: {
      period_key: "2026-07-05",
      item_total: 1,
      group_distribution: { 模型: 1 },
      headline_titles: ["测试新闻标题"],
      source_total: 1
    },
    body_json: {
      format_code: "tech_insight_v1",
      group_by: "board",
      item_fields: ["tag_line", "bullet_points", "takeaway", "source_link"],
      headlines: ["item-1"],
      groups: [{ key: "模型", title: "模型", item_ids: ["item-1"] }],
      items: {
        "item-1": {
          item_id: "item-1",
          generated_news_id: "generated-1",
          title: "测试新闻标题",
          summary: "测试摘要",
          category: "模型",
          board: "模型",
          tag_line: ["模型"],
          bullet_points: ["测试要点"],
          takeaway: "测试总结",
          insight_source: "rule_projection_v1",
          five_fields: {},
          source_url: "https://example.com/news",
          source_name: "Example",
          score: 90,
          is_headline: true,
          generation_status: "ready"
        }
      }
    },
    generated_by: "rule_projection_v1",
    generated_at: "2026-07-05T09:00:00Z"
  };
}

function mountPage(options: { workspaceRole?: string } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

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
      current_user_workspace_role: options.workspaceRole ?? "viewer"
    }
  ];

  return mount(DailyReportsPage, {
    attachTo: document.body,
    global: {
      plugins: [pinia]
    }
  });
}

describe("DailyReportsPage feedback policy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
    routeState.query = {};
    reportsApi.fetchDailyReports.mockResolvedValue([reportRecord()]);
    reportsApi.fetchDailyReportItemComments.mockResolvedValue([]);
    reportsApi.createDailyReportItemInsight.mockResolvedValue({
      insight: {
        id: "insight-1",
        workspace_code: "planning_intel",
        domain_code: "ai",
        news_item_id: "news-1",
        raw_item_id: "raw-1",
        title: "测试新闻标题",
        summary: "测试摘要",
        insight_type: "trend",
        status: "linked_to_requirement",
        source_report_type: "daily",
        source_report_id: "report-1",
        source_report_item_id: "item-1",
        confidence_score: 0.8,
        metadata_json: {},
        created_at: "2026-07-05T09:00:00Z",
        updated_at: "2026-07-05T09:00:00Z"
      },
      implication: {
        id: "implication-1",
        workspace_code: "planning_intel",
        domain_code: "ai",
        insight_id: "insight-1",
        title: "研判：测试新闻标题",
        description: "测试摘要",
        implication_type: "opportunity",
        metadata_json: {},
        created_at: "2026-07-05T09:00:00Z",
        updated_at: "2026-07-05T09:00:00Z"
      },
      requirement: {
        id: "req-1",
        workspace_code: "planning_intel",
        domain_code: "ai",
        title: "跟进：测试新闻标题",
        description: "测试摘要",
        priority: "medium",
        status: "draft",
        due_at: null,
        owner_user_id: null,
        owner_name: null,
        source_count: 1,
        source_links: [],
        task_count: 0,
        metadata_json: {},
        created_at: "2026-07-05T09:00:00Z",
        updated_at: "2026-07-05T09:00:00Z"
      },
      task: null
    });
    reportsApi.createDailyReportItemEntityMilestone.mockResolvedValue({
      id: "milestone-1",
      workspace_code: "planning_intel",
      domain_code: "ai",
      legacy_system: "current",
      legacy_id: "daily:item-1:entity-1",
      tracked_entity_id: "entity-1",
      entity_name: "OpenAI",
      entity_type: "company",
      legacy_article_id: null,
      legacy_report_id: null,
      raw_item_id: "raw-1",
      historical_report_id: null,
      event_time: "2026-07-05T09:00:00Z",
      event_type: "report_signal",
      title: "测试新闻标题",
      timeline_brief: "测试摘要",
      source_url: "https://example.com/news",
      source_name: "测试源",
      board: "模型",
      selected_for_timeline: true,
      curation_status: "draft",
      importance_score: 70,
      importance_level: "medium",
      article_ref_resolved: null,
      report_ref_resolved: null,
      event_content: "测试摘要",
      impact: "测试摘要",
      event_brief: "测试摘要",
      impact_brief: "测试摘要",
      confidence_score: 0.8,
      event_dedupe_key: "entity-1:daily:item-1",
      legacy_refs: {},
      metadata_json: {},
      created_at: "2026-07-05T09:00:00Z",
      updated_at: "2026-07-05T09:00:00Z"
    });
    renditionsApi.fetchReportFormats.mockResolvedValue([]);
    renditionsApi.fetchDailyRenditions.mockResolvedValue([]);
    renditionsApi.dailyRenditionExportUrl.mockReturnValue("#");
    watchersApi.fetchObjectWatcher.mockResolvedValue({
      object_type: "daily_report_item",
      object_id: "item-1",
      workspace_code: "planning_intel",
      watching: false,
      watcher_count: 0
    });
    watchersApi.updateObjectWatcher.mockResolvedValue({
      object_type: "daily_report_item",
      object_id: "item-1",
      workspace_code: "planning_intel",
      watching: true,
      watcher_count: 1
    });
    workspaceApi.fetchWorkspaceFeedbackPolicy.mockResolvedValue({
      workspace_code: "planning_intel",
      viewer_can_react: false,
      viewer_can_rate: false,
      viewer_can_comment: false,
      viewer_can_edit: false,
      notify_on_comment: true,
      notify_on_publish: false
    });
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("disables viewer feedback controls when workspace feedback policy closes them", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find(".daily-item.story").trigger("click");
    await flushPromises();

    const feedbackButtons = Array.from(document.body.querySelectorAll(".feedback-row .mini-action")) as HTMLButtonElement[];
    const watchButton = feedbackButtons.find((button) => button.textContent?.includes("关注"));
    const likeButton = feedbackButtons.find((button) => button.textContent?.trim() === "0");
    const starButtons = Array.from(document.body.querySelectorAll(".feedback-row .star-button")) as HTMLButtonElement[];
    const commentInput = document.body.querySelector(".comment-box textarea") as HTMLTextAreaElement;
    const sendButton = document.body.querySelector(".comment-box button") as HTMLButtonElement;

    expect(workspaceApi.fetchWorkspaceFeedbackPolicy).toHaveBeenCalledWith("planning_intel");
    expect(watchButton?.disabled).toBe(false);
    expect(likeButton?.disabled).toBe(true);
    expect(starButtons).toHaveLength(5);
    expect(starButtons.every((button) => button.disabled)).toBe(true);
    expect(commentInput.disabled).toBe(true);
    expect(sendButton.disabled).toBe(true);
    expect(document.body.textContent).toContain("当前工作台已关闭浏览者的部分反馈入口");
  });

  it("hides strategy loop and entity milestone actions for workspace viewers", async () => {
    const wrapper = mountPage({ workspaceRole: "viewer" });
    await flushPromises();

    await wrapper.find(".daily-item.story").trigger("click");
    await flushPromises();

    // viewer 角色（roleRank 0）不满足沉淀需求（>= admin）与登记事件（>= member）门槛，按钮应直接隐藏。
    const actionTexts = Array.from(document.body.querySelectorAll(".editor-actions .mini-action")).map(
      (button) => button.textContent ?? ""
    );
    expect(actionTexts.some((text) => text.includes("沉淀需求"))).toBe(false);
    expect(actionTexts.some((text) => text.includes("登记事件"))).toBe(false);
  });

  it("shows the membership permission error instead of report content when loading is rejected", async () => {
    reportsApi.fetchDailyReports.mockRejectedValue(new Error("permission denied: workspace membership required"));

    const wrapper = mountPage();
    await flushPromises();

    // 无 membership 的 403 拒绝：页面渲染错误提示而不是空白或误报成功。
    expect(wrapper.find(".form-error").text()).toContain("permission denied: workspace membership required");
    expect(wrapper.find(".form-success").exists()).toBe(false);
    expect(wrapper.find(".daily-item.story").exists()).toBe(false);
  });

  it("loads and toggles daily report item watcher state from the detail drawer", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find(".daily-item.story").trigger("click");
    await flushPromises();

    expect(watchersApi.fetchObjectWatcher).toHaveBeenCalledWith("daily_report_item", "item-1");
    const watchButton = Array.from(document.body.querySelectorAll(".feedback-row .mini-action")).find(
      (button) => button.textContent?.includes("关注")
    ) as HTMLButtonElement | undefined;
    expect(watchButton?.getAttribute("aria-pressed")).toBe("false");

    watchButton?.click();
    await flushPromises();

    expect(watchersApi.updateObjectWatcher).toHaveBeenCalledWith("daily_report_item", "item-1", true);
    expect(document.body.textContent).toContain("已关注");
    expect(document.body.textContent).toContain("已关注该日报条目");
  });

  it("opens the report item detail from a notification item anchor", async () => {
    routeState.query = { item_id: "item-1", comment_id: "comment-1" };
    reportsApi.fetchDailyReportItemComments.mockResolvedValue([
      {
        id: "comment-1",
        user_display_name: "评论者",
        body: "这条评论需要定位",
        parent_id: null,
        root_id: null,
        created_at: "2026-07-05T09:00:00Z"
      },
      {
        id: "comment-2",
        user_display_name: "评论者",
        body: "普通评论",
        parent_id: null,
        root_id: null,
        created_at: "2026-07-05T09:05:00Z"
      }
    ]);
    const wrapper = mountPage();
    await flushPromises();

    expect(reportsApi.fetchDailyReports).toHaveBeenCalledWith("planning_intel");
    expect(reportsApi.fetchDailyReportItemComments).toHaveBeenCalledWith("item-1");
    expect(wrapper.find(".daily-item.story.active").exists()).toBe(true);
    expect(document.body.querySelector(".report-modal-backdrop")?.textContent).toContain("测试新闻标题");
    const anchoredComment = document.body.querySelector(".comment-row.anchored") as HTMLElement;
    expect(anchoredComment?.textContent).toContain("这条评论需要定位");
    expect(anchoredComment?.getAttribute("aria-current")).toBe("true");
  });

  it("creates a strategy loop requirement from a daily report item for admins", async () => {
    const wrapper = mountPage({ workspaceRole: "admin" });
    await flushPromises();

    await wrapper.find(".daily-item.story").trigger("click");
    await flushPromises();
    const strategyButton = Array.from(document.body.querySelectorAll(".editor-actions .mini-action")).find(
      (button) => button.textContent?.includes("沉淀需求")
    ) as HTMLButtonElement | undefined;
    expect(strategyButton).toBeTruthy();
    strategyButton?.click();
    await flushPromises();

    expect(reportsApi.createDailyReportItemInsight).toHaveBeenCalledWith(
      "item-1",
      expect.objectContaining({
        insight_title: "测试新闻标题",
        requirement_title: "跟进：测试新闻标题",
        requirement_status: "draft"
      })
    );
    expect(wrapper.text()).toContain("已沉淀内部需求：跟进：测试新闻标题");
  });

  it("registers an entity milestone from a daily report item", async () => {
    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    await wrapper.find(".daily-item.story").trigger("click");
    await flushPromises();
    const milestoneButton = Array.from(document.body.querySelectorAll(".editor-actions .mini-action")).find(
      (button) => button.textContent?.includes("登记事件")
    ) as HTMLButtonElement | undefined;
    expect(milestoneButton).toBeTruthy();
    milestoneButton?.click();
    await flushPromises();

    const input = document.body.querySelector(".inline-milestone-form input") as HTMLInputElement | null;
    expect(input).toBeTruthy();
    input!.value = "OpenAI";
    input!.dispatchEvent(new Event("input", { bubbles: true }));
    document.body
      .querySelector(".inline-milestone-form")
      ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flushPromises();

    expect(reportsApi.createDailyReportItemEntityMilestone).toHaveBeenCalledWith(
      "item-1",
      expect.objectContaining({
        entity_name: "OpenAI",
        event_title: "测试新闻标题",
        event_brief: "测试摘要",
        board: "模型"
      })
    );
    expect(wrapper.text()).toContain("已登记实体事件：OpenAI · 测试新闻标题");
  });

  it("selects a daily report from a notification report anchor", async () => {
    const firstReport = reportRecord();
    const secondReport = {
      ...reportRecord(),
      id: "report-2",
      day_key: "2026-07-04",
      title: "第二份规划部日报",
      items: [
        {
          ...reportRecord().items[0],
          id: "item-2",
          generated_news: {
            ...reportRecord().items[0].generated_news,
            id: "generated-2",
            title: "第二条新闻"
          }
        }
      ]
    };
    routeState.query = { report_id: "report-2" };
    reportsApi.fetchDailyReports.mockResolvedValue([firstReport, secondReport]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find(".daily-report-card h3").text()).toBe("第二份规划部日报");
    expect(wrapper.find(".report-modal-backdrop").exists()).toBe(false);
  });

  it("selects and highlights a report rendition from a search anchor", async () => {
    routeState.query = {
      report_id: "report-1",
      rendition_id: "rendition-1",
      format_code: "tech_insight_v1"
    };
    renditionsApi.fetchReportFormats.mockResolvedValue([
      reportFormat("company_sql_v1", "公司 SQL 版"),
      reportFormat("tech_insight_v1", "技术洞察版")
    ]);
    renditionsApi.regenerateDailyRendition.mockResolvedValue(renditionRecord());

    // member+ 走 regenerate 重投影；viewer 只读路径见下方 viewer 阅读视角用例。
    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();
    await flushPromises();

    expect(renditionsApi.regenerateDailyRendition).toHaveBeenCalledWith("report-1", "tech_insight_v1");
    const anchoredTab = wrapper.find(".coverage-filter button.anchored");
    expect(anchoredTab.exists()).toBe(true);
    expect(anchoredTab.attributes("aria-current")).toBe("true");
    expect(anchoredTab.text()).toContain("技术洞察版");
    const anchoredRendition = wrapper.find(".rendition-view.anchored");
    expect(anchoredRendition.exists()).toBe(true);
    expect(anchoredRendition.attributes("aria-current")).toBe("true");
    expect(anchoredRendition.text()).toContain("测试新闻标题");
  });

  it("hides editorial controls for workspace viewers while keeping reading intact", async () => {
    const wrapper = mountPage({ workspaceRole: "viewer" });
    await flushPromises();

    // 顶部工具栏：viewer 无「生成日报草稿」与日期控件，仅保留刷新。
    const toolbarTexts = wrapper.findAll(".report-command .toolbar-actions button").map((button) => button.text());
    expect(toolbarTexts.some((text) => text.includes("生成日报草稿"))).toBe(false);
    expect(toolbarTexts.some((text) => text.includes("刷新"))).toBe(true);
    expect(wrapper.find(".date-control").exists()).toBe(false);

    // 报告头部：draft 状态下 member 可见的「发布/重跑生成稿」对 viewer 隐藏。
    const headerTexts = wrapper.findAll(".daily-report-header .toolbar-actions button").map((button) => button.text());
    expect(headerTexts.some((text) => text.includes("发布"))).toBe(false);
    expect(headerTexts.some((text) => text.includes("重跑"))).toBe(false);
    // 格式管理入口隐藏，导出链接保留。
    expect(wrapper.find(".rendition-actions").text()).not.toContain("格式");

    // 详情弹层：采信/备选/剔除与编辑按钮整组隐藏，阅读正文保留。
    await wrapper.find(".daily-item.story").trigger("click");
    await flushPromises();
    const modalActionTexts = Array.from(
      document.body.querySelectorAll(".modal-editor-panel .editor-actions .mini-action")
    ).map((button) => button.textContent ?? "");
    expect(modalActionTexts.some((text) => text.includes("采信"))).toBe(false);
    expect(modalActionTexts.some((text) => text.includes("剔除"))).toBe(false);
    const editButtons = Array.from(
      document.body.querySelectorAll(".section-title-row .mini-action")
    ).map((button) => button.textContent ?? "");
    expect(editButtons.some((text) => text.includes("编辑"))).toBe(false);
    expect(document.body.querySelector(".modal-story-detail")?.textContent).toContain("测试摘要");
  });

  it("loads published renditions read-only for viewers without member regenerate", async () => {
    renditionsApi.fetchReportFormats.mockResolvedValue([
      reportFormat("company_sql_v1", "内网版"),
      reportFormat("tech_insight_v1", "技术洞察版")
    ]);
    renditionsApi.fetchDailyRenditions.mockResolvedValue([renditionRecord()]);

    const wrapper = mountPage({ workspaceRole: "viewer" });
    await flushPromises();
    await flushPromises();

    // 默认切到技术洞察版：viewer 走 GET renditions 读取发布时投影的快照，
    // 不触发 member 权限的 regenerate。
    expect(renditionsApi.fetchDailyRenditions).toHaveBeenCalledWith("report-1");
    expect(renditionsApi.regenerateDailyRendition).not.toHaveBeenCalled();
    const renditionView = wrapper.find(".rendition-view");
    expect(renditionView.text()).toContain("测试新闻标题");
    // 头条编辑按钮对 viewer 隐藏。
    expect(renditionView.find(".headline-toggle").exists()).toBe(false);
  });

  it("gives invited viewers the latest published daily report on landing", async () => {
    // 游客旅程终点：受邀 viewer 登录 →（路由守卫落地 /daily-reports，见 router spec）
    // → 直接读到最新已发布日报与其成稿。
    reportsApi.fetchDailyReports.mockResolvedValue([
      { ...reportRecord(), status: "published", published_at: "2026-07-05T12:00:00Z" }
    ]);
    renditionsApi.fetchReportFormats.mockResolvedValue([
      reportFormat("company_sql_v1", "内网版"),
      reportFormat("tech_insight_v1", "技术洞察版")
    ]);
    renditionsApi.fetchDailyRenditions.mockResolvedValue([renditionRecord()]);

    const wrapper = mountPage({ workspaceRole: "viewer" });
    await flushPromises();
    await flushPromises();

    expect(wrapper.find(".report-tab").text()).toContain("已发布");
    expect(wrapper.find(".daily-report-card h3").text()).toBe("规划部日报");
    expect(wrapper.find(".rendition-view").text()).toContain("测试新闻标题");
    const headerButtons = wrapper.findAll(".daily-report-header .toolbar-actions button");
    expect(headerButtons).toHaveLength(0);
  });
});
