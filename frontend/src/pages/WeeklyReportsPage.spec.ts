import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WeeklyReportsPage from "./WeeklyReportsPage.vue";
import type { WeeklyReportRecord } from "../api/reports";
import { useWorkspaceStore } from "../stores/workspace";

const reportsApi = vi.hoisted(() => ({
  createWeeklyReport: vi.fn(),
  createWeeklyReportItemEntityMilestone: vi.fn(),
  createWeeklyReportItemInsight: vi.fn(),
  fetchWeeklyReport: vi.fn(),
  fetchWeeklyReports: vi.fn(),
  publishWeeklyReport: vi.fn(),
  updateWeeklyReportItem: vi.fn()
}));

const renditionsApi = vi.hoisted(() => ({
  fetchReportFormats: vi.fn(),
  weeklyRenditionExportUrl: vi.fn()
}));

const watchersApi = vi.hoisted(() => ({
  fetchObjectWatcher: vi.fn(),
  updateObjectWatcher: vi.fn()
}));

const operationsApi = vi.hoisted(() => ({
  fetchReportArchive: vi.fn(),
  fetchReportArchiveSummary: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/reports", () => reportsApi);

vi.mock("../api/operations", () => operationsApi);

vi.mock("../api/renditions", () => renditionsApi);

vi.mock("../api/watchers", () => watchersApi);

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function weeklyReport(overrides: Partial<WeeklyReportRecord> = {}): WeeklyReportRecord {
  return {
    id: "weekly-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    week_key: "2026-W27",
    title: "规划部周报",
    summary: "周报摘要",
    status: "draft",
    published_at: null,
    items: [
      {
        id: "weekly-item-1",
        daily_report_item_id: "daily-item-1",
        daily_day_key: "2026-07-05",
        generated_news: {
          id: "generated-1",
          category: "模型",
          title: "周报条目",
          summary: "条目摘要",
          key_points: "要点",
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
        sort_order: 1,
        weekly_score: 0,
        final_score: 0,
        heat_score: 0,
        feedback_score: 0,
        editor_title: null,
        editor_summary: null,
        editor_content_json: null
      }
    ],
    ...overrides
  };
}

function reportFormat(formatCode: string, name: string) {
  return {
    id: `format-${formatCode}`,
    workspace_code: "planning_intel",
    format_code: formatCode,
    name,
    description: "",
    builtin: true,
    locked: false,
    group_by: "board",
    headline_enabled: false,
    headline_auto_top_n: 0,
    item_fields: ["tag_line", "bullet_points", "takeaway", "source_link"],
    export_targets: ["md", "html"],
    enabled: true,
    sort_order: 20
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

  return mount(WeeklyReportsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("WeeklyReportsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    reportsApi.fetchWeeklyReports.mockResolvedValue([weeklyReport()]);
    reportsApi.fetchWeeklyReport.mockResolvedValue(weeklyReport());
    operationsApi.fetchReportArchive.mockResolvedValue([]);
    operationsApi.fetchReportArchiveSummary.mockResolvedValue({
      workspace_code: "planning_intel",
      total: 0,
      published_daily: 0,
      published_weekly: 0,
      legacy_reports: 0,
      total_items: 0,
      total_adopted: 0,
      average_adoption_rate: 0,
      months: [],
      latest_published_at: null
    });
    reportsApi.createWeeklyReportItemInsight.mockResolvedValue({
      insight: {
        id: "insight-1",
        workspace_code: "planning_intel",
        domain_code: "ai",
        news_item_id: "news-1",
        raw_item_id: "raw-1",
        title: "周报条目",
        summary: "条目摘要",
        insight_type: "trend",
        status: "linked_to_requirement",
        source_report_type: "weekly",
        source_report_id: "weekly-1",
        source_report_item_id: "weekly-item-1",
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
        title: "研判：周报条目",
        description: "条目摘要",
        implication_type: "opportunity",
        metadata_json: {},
        created_at: "2026-07-05T09:00:00Z",
        updated_at: "2026-07-05T09:00:00Z"
      },
      requirement: {
        id: "req-1",
        workspace_code: "planning_intel",
        domain_code: "ai",
        title: "跟进：周报条目",
        description: "条目摘要",
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
    reportsApi.createWeeklyReportItemEntityMilestone.mockResolvedValue({
      id: "milestone-1",
      workspace_code: "planning_intel",
      domain_code: "ai",
      legacy_system: "current",
      legacy_id: "weekly:weekly-item-1:entity-1",
      tracked_entity_id: "entity-1",
      entity_name: "OpenAI",
      entity_type: "company",
      legacy_article_id: null,
      legacy_report_id: null,
      raw_item_id: "raw-1",
      historical_report_id: null,
      event_time: "2026-07-05T09:00:00Z",
      event_type: "report_signal",
      title: "周报条目",
      timeline_brief: "条目摘要",
      source_url: "https://example.com/news",
      source_name: "测试源",
      board: "模型",
      selected_for_timeline: true,
      curation_status: "draft",
      importance_score: 70,
      importance_level: "medium",
      article_ref_resolved: null,
      report_ref_resolved: null,
      event_content: "条目摘要",
      impact: "条目摘要",
      event_brief: "条目摘要",
      impact_brief: "条目摘要",
      confidence_score: 0.8,
      event_dedupe_key: "entity-1:weekly:weekly-item-1",
      legacy_refs: {},
      metadata_json: {},
      created_at: "2026-07-05T09:00:00Z",
      updated_at: "2026-07-05T09:00:00Z"
    });
    renditionsApi.fetchReportFormats.mockResolvedValue([]);
    renditionsApi.weeklyRenditionExportUrl.mockReturnValue("#");
    watchersApi.fetchObjectWatcher.mockResolvedValue({
      object_type: "weekly_report_item",
      object_id: "weekly-item-1",
      workspace_code: "planning_intel",
      watching: false,
      watcher_count: 0
    });
    watchersApi.updateObjectWatcher.mockResolvedValue({
      object_type: "weekly_report_item",
      object_id: "weekly-item-1",
      workspace_code: "planning_intel",
      watching: true,
      watcher_count: 1
    });
  });

  it("selects a weekly report from a notification report anchor", async () => {
    routeState.query = { report_id: "weekly-2" };
    reportsApi.fetchWeeklyReports.mockResolvedValue([
      weeklyReport(),
      weeklyReport({
        id: "weekly-2",
        week_key: "2026-W28",
        title: "第二份规划部周报"
      })
    ]);

    // 草稿节点在时间轴上仅 member+ 渲染，锚点定位用 member 视角验证。
    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    expect(wrapper.find(".weekly-detail h3").text()).toBe("第二份规划部周报");
    expect(wrapper.find(".report-tab.active strong").text()).toBe("2026-W28");
  });

  it("shows the backend weekly summary as a dedicated summary segment", async () => {
    reportsApi.fetchWeeklyReports.mockResolvedValue([
      weeklyReport({
        summary: "本周采信 3 条，覆盖 2 个板块。关键亮点：模型突破；工程落地。"
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    const summary = wrapper.find(".weekly-generated-summary");
    expect(summary.exists()).toBe(true);
    expect(summary.text()).toContain("本周采信 3 条");
    expect(summary.text()).toContain("关键亮点");
  });

  it("selects and highlights a weekly item from a search anchor", async () => {
    routeState.query = { item_id: "weekly-item-2" };
    reportsApi.fetchWeeklyReports.mockResolvedValue([
      weeklyReport(),
      weeklyReport({
        id: "weekly-2",
        week_key: "2026-W28",
        title: "第二份规划部周报",
        items: [
          {
            id: "weekly-item-2",
            daily_report_item_id: "daily-item-2",
            daily_day_key: "2026-07-06",
            generated_news: {
              id: "generated-2",
              category: "AI Infra",
              title: "被搜索定位的周报条目",
              summary: "周报条目摘要",
              key_points: "锚点",
              content_json: {
                background: "背景",
                effects: "效果",
                eventSummary: "事件",
                technologyAndInnovation: "技术",
                valueAndImpact: "价值"
              },
              source_url: "https://example.com/infra",
              generation_status: "ready",
              news_item_id: "news-2",
              recommendation_item_id: "rec-2"
            },
            adoption_status: 2,
            sort_order: 1,
            weekly_score: 0,
            final_score: 0,
            heat_score: 0,
            feedback_score: 0,
            editor_title: null,
            editor_summary: null,
            editor_content_json: null
          }
        ]
      })
    ]);

    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    expect(wrapper.find(".weekly-detail h3").text()).toBe("第二份规划部周报");
    expect(wrapper.find(".report-tab.active strong").text()).toBe("2026-W28");
    const anchored = wrapper.find(".weekly-item-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("被搜索定位的周报条目");
  });

  it("creates a strategy loop requirement from a weekly report item for admins", async () => {
    const wrapper = mountPage({ workspaceRole: "admin" });
    await flushPromises();

    const strategyButton = wrapper.findAll(".weekly-brief-actions .mini-action").find(
      (button) => button.text().includes("沉淀需求")
    );
    expect(strategyButton?.exists()).toBe(true);
    await strategyButton?.trigger("click");
    await flushPromises();

    expect(reportsApi.createWeeklyReportItemInsight).toHaveBeenCalledWith(
      "weekly-item-1",
      expect.objectContaining({
        insight_title: "周报条目",
        requirement_title: "跟进：周报条目",
        requirement_status: "draft"
      })
    );
    expect(wrapper.text()).toContain("已沉淀内部需求：跟进：周报条目");
  });

  it("registers an entity milestone from a weekly report item", async () => {
    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    const milestoneButton = wrapper.findAll(".weekly-brief-actions .mini-action").find(
      (button) => button.text().includes("登记事件")
    );
    expect(milestoneButton?.exists()).toBe(true);
    await milestoneButton?.trigger("click");
    await flushPromises();

    const input = wrapper.find(".inline-milestone-form input");
    expect(input.exists()).toBe(true);
    // 登记事件提交按钮必须走 icon-button 基线样式，避免未定义的裸类导致无样式按钮
    expect(wrapper.find(".inline-milestone-form button[type='submit']").classes()).toContain("icon-button");
    await input.setValue("OpenAI");
    await wrapper.find(".inline-milestone-form").trigger("submit");
    await flushPromises();

    expect(reportsApi.createWeeklyReportItemEntityMilestone).toHaveBeenCalledWith(
      "weekly-item-1",
      expect.objectContaining({
        entity_name: "OpenAI",
        event_title: "周报条目",
        event_brief: "条目摘要",
        board: "模型"
      })
    );
    expect(wrapper.text()).toContain("已登记实体事件：OpenAI · 周报条目");
  });

  it("hides weekly editorial controls for workspace viewers while keeping reading intact", async () => {
    const wrapper = mountPage({ workspaceRole: "viewer" });
    await flushPromises();

    // viewer 无「生成周报草稿」按钮与草稿参数卡片。
    const heroButtons = wrapper.findAll(".module-hero .icon-button").map((button) => button.text());
    expect(heroButtons.some((text) => text.includes("生成周报草稿"))).toBe(false);
    expect(heroButtons.some((text) => text.includes("刷新"))).toBe(true);
    expect(wrapper.find(".run-command").exists()).toBe(false);
    // draft 状态下 member 可见的「发布周报」对 viewer 隐藏。
    expect(wrapper.findAll(".weekly-detail .icon-button")).toHaveLength(0);

    // 条目行：采信/候选/剔除/排序/编辑整组隐藏，关注（阅读反馈）与正文保留。
    const actionTexts = wrapper.findAll(".weekly-brief-actions .mini-action").map((button) => button.text());
    expect(actionTexts.some((text) => text.includes("采信"))).toBe(false);
    expect(actionTexts.some((text) => text.includes("候选"))).toBe(false);
    expect(actionTexts.some((text) => text.includes("剔除"))).toBe(false);
    expect(actionTexts.some((text) => text.includes("编辑"))).toBe(false);
    expect(actionTexts.some((text) => text.includes("关注"))).toBe(true);
    expect(wrapper.find(".weekly-brief-main h3").text()).toBe("周报条目");
  });

  it("keeps weekly editorial controls for workspace members", async () => {
    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    const heroButtons = wrapper.findAll(".module-hero .icon-button").map((button) => button.text());
    expect(heroButtons.some((text) => text.includes("生成周报草稿"))).toBe(true);
    expect(wrapper.find(".run-command").exists()).toBe(true);
    const actionTexts = wrapper.findAll(".weekly-brief-actions .mini-action").map((button) => button.text());
    expect(actionTexts.some((text) => text.includes("采信"))).toBe(true);
    expect(actionTexts.some((text) => text.includes("编辑"))).toBe(true);
  });

  it("loads and toggles weekly report item watcher state", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(watchersApi.fetchObjectWatcher).toHaveBeenCalledWith("weekly_report_item", "weekly-item-1");
    const watchButton = wrapper.findAll(".weekly-brief-actions .mini-action").find(
      (button) => button.text().includes("关注")
    );
    expect(watchButton?.attributes("aria-pressed")).toBe("false");

    await watchButton?.trigger("click");
    await flushPromises();

    expect(watchersApi.updateObjectWatcher).toHaveBeenCalledWith("weekly_report_item", "weekly-item-1", true);
    expect(wrapper.text()).toContain("已关注");
    expect(wrapper.text()).toContain("已关注该周报条目");
  });

  it("selects a weekly report and highlights the rendition export from a search anchor", async () => {
    routeState.query = {
      report_id: "weekly-2",
      rendition_id: "weekly-rendition-1",
      format_code: "tech_insight_v1"
    };
    reportsApi.fetchWeeklyReports.mockResolvedValue([
      weeklyReport(),
      weeklyReport({
        id: "weekly-2",
        week_key: "2026-W28",
        title: "第二份规划部周报"
      })
    ]);
    renditionsApi.fetchReportFormats.mockResolvedValue([reportFormat("tech_insight_v1", "技术洞察版")]);
    renditionsApi.weeklyRenditionExportUrl.mockImplementation(
      (reportId: string, formatCode: string, target: string) =>
        `/api/weekly-reports/${reportId}/renditions/${formatCode}/export?target=${target}`
    );

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find(".weekly-detail h3").text()).toBe("第二份规划部周报");
    const anchoredLinks = wrapper.findAll(".table-action.anchored");
    expect(anchoredLinks).toHaveLength(2);
    expect(anchoredLinks[0].attributes("aria-current")).toBe("true");
    expect(anchoredLinks[0].text()).toContain("技术洞察版");
    expect(anchoredLinks[0].attributes("href")).toContain("/weekly-reports/weekly-2/renditions/tech_insight_v1");
  });

  it("opens an archived weekly report from the timeline via the weekly report API", async () => {
    operationsApi.fetchReportArchive.mockResolvedValue([
      {
        id: "archive-w20",
        origin: "published",
        report_type: "weekly",
        workspace_code: "planning_intel",
        title: "2026-W20 周报",
        date_key: "2026-W20",
        month: "2026-05",
        status: "published",
        published_at: "2026-05-17T12:00:00Z",
        item_count: 12,
        adopted_count: 9,
        headline_count: 0,
        adoption_rate: 0.75,
        top_sources: [],
        detail_kind: "weekly_report",
        detail_id: "weekly-old",
        content_excerpt: ""
      }
    ]);
    reportsApi.fetchWeeklyReport.mockResolvedValue(
      weeklyReport({ id: "weekly-old", week_key: "2026-W20", title: "五月第三周周报", status: "published" })
    );

    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    // 左栏是按月分组时间轴（weekly 变体，节点主标为 ISO 周），替代 run-list 平铺。
    const timeline = wrapper.find('aside[aria-label="报告时间轴"]');
    expect(timeline.exists()).toBe(true);
    expect(operationsApi.fetchReportArchive).toHaveBeenCalledWith(
      expect.objectContaining({
        workspaceCode: "planning_intel",
        reportType: "weekly",
        origin: "published",
        offset: 0
      })
    );

    const archiveNode = timeline
      .findAll(".timeline-node")
      .find((node) => node.text().includes("2026-W20"));
    expect(archiveNode).toBeTruthy();
    await archiveNode!.trigger("click");
    await flushPromises();

    expect(reportsApi.fetchWeeklyReport).toHaveBeenCalledWith("weekly-old");
    expect(wrapper.find(".weekly-detail h3").text()).toBe("五月第三周周报");
  });

  it("filters weekly items by board tag chips and keyword as display-only filtering", async () => {
    const report = weeklyReport();
    report.items.push({
      ...weeklyReport().items[0],
      id: "weekly-item-2",
      generated_news: {
        ...weeklyReport().items[0].generated_news!,
        id: "generated-2",
        category: "AI Infra",
        title: "推理集群周报条目",
        summary: "集群摘要"
      }
    });
    reportsApi.fetchWeeklyReports.mockResolvedValue([report]);

    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    expect(wrapper.findAll(".weekly-item-row")).toHaveLength(2);
    expect(wrapper.find(".filter-count").text()).toBe("2/2 条");

    // 一级标签胶囊：过滤只影响显示。
    const chip = wrapper.findAll(".filter-chip").find((button) => button.text() === "模型");
    expect(chip).toBeTruthy();
    await chip!.trigger("click");
    expect(wrapper.findAll(".weekly-item-row")).toHaveLength(1);
    expect(wrapper.find(".filter-count").text()).toBe("1/2 条");

    // 关键词 0 命中：显示清除入口。
    await wrapper.find(".filter-keyword").setValue("不存在的关键词");
    expect(wrapper.findAll(".weekly-item-row")).toHaveLength(0);
    const filterEmpty = wrapper.find(".filter-empty");
    expect(filterEmpty.exists()).toBe(true);
    expect(filterEmpty.text()).toContain("没有条目命中当前筛选");

    await filterEmpty.find("button").trigger("click");
    expect(wrapper.findAll(".weekly-item-row")).toHaveLength(2);

    // 纯前端过滤：不发写请求。
    expect(reportsApi.updateWeeklyReportItem).not.toHaveBeenCalled();
    expect(reportsApi.fetchWeeklyReports).toHaveBeenCalledTimes(1);
  });

  it("uses reader-facing copy without implementation terms on notes and empty states", async () => {
    reportsApi.fetchWeeklyReports.mockResolvedValue([weeklyReport({ items: [] })]);

    const wrapper = mountPage({ workspaceRole: "member" });
    await flushPromises();

    // 文案违例 #3/#4/#5（frontend-product-design §14.2）已替换为业务话术。
    const pageText = wrapper.text();
    expect(pageText).toContain("只读取已发布日报中已采信的条目；单次草稿最多 200 条，周报长文自动生成暂不支持");
    expect(pageText).toContain("请确认该周内有已发布日报，且日报里有已采信条目");
    expect(pageText).not.toContain("采信状态为 2");
    expect(pageText).not.toContain("adoption_status");
    expect(pageText).not.toContain("本阶段");
    expect(pageText).not.toContain("SQL 预览回填");
  });
});
