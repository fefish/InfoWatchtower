import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HistoricalReportsPage from "./HistoricalReportsPage.vue";
import type {
  HistoricalReportDetailRecord,
  ReportArchiveListItem,
  ReportArchiveSummaryRecord
} from "../api/operations";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createRequirement: vi.fn(),
  fetchHistoricalReportDetail: vi.fn(),
  fetchLegacyImportGaps: vi.fn(),
  fetchLegacyImportSummary: vi.fn(),
  fetchReportArchive: vi.fn(),
  fetchReportArchiveSummary: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

const routerState = vi.hoisted(() => ({
  push: vi.fn()
}));

vi.mock("../api/operations", () => ({
  createRequirement: operationsApi.createRequirement,
  fetchHistoricalReportDetail: operationsApi.fetchHistoricalReportDetail,
  fetchLegacyImportGaps: operationsApi.fetchLegacyImportGaps,
  fetchLegacyImportSummary: operationsApi.fetchLegacyImportSummary,
  fetchReportArchive: operationsApi.fetchReportArchive,
  fetchReportArchiveSummary: operationsApi.fetchReportArchiveSummary
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState,
  useRouter: () => routerState
}));

function archiveEntry(overrides: Partial<ReportArchiveListItem> = {}): ReportArchiveListItem {
  return {
    id: "daily-1",
    origin: "published",
    report_type: "daily",
    workspace_code: "planning_intel",
    title: "2026-07-05 AI 情报日报",
    date_key: "2026-07-05",
    month: "2026-07",
    status: "published",
    published_at: "2026-07-05T12:00:00Z",
    item_count: 4,
    adopted_count: 3,
    headline_count: 1,
    adoption_rate: 0.75,
    top_sources: [
      { name: "机器之心", count: 2 },
      { name: "量子位", count: 1 }
    ],
    detail_kind: "daily_report",
    detail_id: "daily-1",
    content_excerpt: "今日头条：Agent 平台化。",
    ...overrides
  };
}

function weeklyEntry(overrides: Partial<ReportArchiveListItem> = {}): ReportArchiveListItem {
  return archiveEntry({
    id: "weekly-1",
    report_type: "weekly",
    title: "2026-W27 AI 情报周报",
    date_key: "2026-W27",
    month: "2026-06",
    detail_kind: "weekly_report",
    detail_id: "weekly-1",
    ...overrides
  });
}

function legacyEntry(overrides: Partial<ReportArchiveListItem> = {}): ReportArchiveListItem {
  return archiveEntry({
    id: "legacy-1",
    origin: "legacy",
    title: "旧系统历史日报",
    date_key: "2025-06-10",
    month: "2025-06",
    status: "published_imported",
    published_at: "2025-06-10T00:00:00Z",
    item_count: 3,
    adopted_count: 3,
    headline_count: 0,
    adoption_rate: 1,
    top_sources: [],
    detail_kind: "historical_report",
    detail_id: "legacy-1",
    content_excerpt: "旧系统正文摘要",
    ...overrides
  });
}

function legacyDetail(overrides: Partial<HistoricalReportDetailRecord> = {}): HistoricalReportDetailRecord {
  return {
    id: "legacy-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    legacy_system: "tech_insight_loop",
    legacy_id: "legacy-report-1",
    report_type: "daily",
    title: "旧系统历史日报",
    status: "published_imported",
    period_start_at: "2025-06-10T00:00:00Z",
    period_end_at: null,
    resolved_ref_count: 2,
    unresolved_ref_count: 1,
    content_excerpt: "旧系统正文摘要",
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    content: "完整历史报告正文",
    source_refs_json: { resolved: [], unresolved: [] },
    metadata_json: {},
    ...overrides
  };
}

function summary(overrides: Partial<ReportArchiveSummaryRecord> = {}): ReportArchiveSummaryRecord {
  return {
    workspace_code: "planning_intel",
    total: 2,
    published_daily: 1,
    published_weekly: 0,
    legacy_reports: 1,
    total_items: 4,
    total_adopted: 3,
    average_adoption_rate: 0.75,
    months: [
      { month: "2026-07", count: 1 },
      { month: "2025-06", count: 1 }
    ],
    latest_published_at: "2026-07-05T12:00:00Z",
    top_sources: [
      { name: "机器之心", count: 2 },
      { name: "量子位", count: 1 }
    ],
    ...overrides
  };
}

function legacySummaryRecord(overrides: Partial<ReportArchiveSummaryRecord> = {}): ReportArchiveSummaryRecord {
  return summary({
    total: 1,
    published_daily: 0,
    published_weekly: 0,
    legacy_reports: 1,
    total_items: 0,
    total_adopted: 0,
    average_adoption_rate: 0,
    months: [{ month: "2025-06", count: 1 }],
    latest_published_at: null,
    top_sources: [],
    ...overrides
  });
}

function mountPage(options: { asAdmin?: boolean } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  if (options.asAdmin) {
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
      roles: ["super_admin"]
    };
  }
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
      current_user_workspace_role: options.asAdmin ? "owner" : "viewer"
    }
  ];
  return mount(HistoricalReportsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

describe("HistoricalReportsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    operationsApi.fetchReportArchiveSummary.mockImplementation(
      async (_workspaceCode: string, filters?: { origin?: string }) =>
        filters?.origin === "legacy" ? legacySummaryRecord() : summary()
    );
    operationsApi.fetchReportArchive.mockResolvedValue([archiveEntry(), legacyEntry()]);
    operationsApi.fetchLegacyImportSummary.mockResolvedValue({
      workspace_code: "planning_intel",
      generated_at: "2026-07-05T09:00:00Z",
      expected_counts: {},
      metrics: [],
      report_refs: { total: 3, resolved: 2, unresolved: 1 },
      milestone_article_refs: { total: 0, resolved: 0, unresolved: 0 },
      milestone_report_refs: { total: 0, resolved: 0, unresolved: 0 },
      feedback_article_refs: { total: 0, resolved: 0, unresolved: 0 },
      total_unresolved_refs: 1,
      gap_item_count: 1
    });
    operationsApi.fetchLegacyImportGaps.mockResolvedValue([]);
    operationsApi.createRequirement.mockResolvedValue({ title: "跟进历史报告：旧系统历史日报" });
    operationsApi.fetchHistoricalReportDetail.mockResolvedValue(legacyDetail());
  });

  it("renders the cross-source positioning header and comparison summary card", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const hero = wrapper.find(".module-hero");
    expect(hero.text()).toContain("跨来源报告资产库：旧系统导入资产的归档、验收与跨来源统计对比");
    expect(hero.text()).toContain("日常按天/周回溯请直接用日报/周报页的时间轴");

    const compare = wrapper.find(".archive-compare");
    expect(compare.exists()).toBe(true);
    const columns = compare.findAll(".archive-compare-col");
    expect(columns).toHaveLength(2);
    expect(columns[0].text()).toContain("本系统已发布");
    expect(columns[0].text()).toContain("日报 1 · 周报 0");
    expect(columns[0].text()).toContain("平均采信率 75%");
    expect(columns[0].text()).toContain("采信 3 / 4 条目");
    expect(columns[0].text()).toContain("机器之心 ×2");
    expect(columns[1].text()).toContain("旧系统导入");
    expect(columns[1].text()).toContain("报告引用解析 2 / 3");
  });

  it("deep-links published entries to the report pages instead of rendering their body in page", async () => {
    operationsApi.fetchReportArchive.mockResolvedValue([archiveEntry(), weeklyEntry(), legacyEntry()]);
    const wrapper = mountPage();
    await flushPromises();

    const rows = wrapper.findAll(".archive-row");
    expect(rows).toHaveLength(3);
    expect(rows[0].text()).toContain("在日报页阅读");

    await rows[0].trigger("click");
    expect(routerState.push).toHaveBeenCalledWith({
      path: "/daily-reports",
      query: { report_id: "daily-1" }
    });

    await rows[1].trigger("click");
    expect(routerState.push).toHaveBeenCalledWith({
      path: "/weekly-reports",
      query: { report_id: "weekly-1" }
    });

    // 已发布条目不做页内正文渲染：正文详情请求只发生在 legacy 条目上
    expect(operationsApi.fetchHistoricalReportDetail).toHaveBeenCalledTimes(1);
    expect(operationsApi.fetchHistoricalReportDetail).toHaveBeenCalledWith("legacy-1");
    expect(wrapper.find(".archive-legacy-content").text()).toContain("完整历史报告正文");
  });

  it("renders legacy report bodies in page when a legacy entry is clicked", async () => {
    operationsApi.fetchReportArchive.mockResolvedValue([
      archiveEntry(),
      legacyEntry(),
      legacyEntry({ id: "legacy-2", detail_id: "legacy-2", title: "旧系统历史周报" })
    ]);
    const wrapper = mountPage();
    await flushPromises();

    operationsApi.fetchHistoricalReportDetail.mockResolvedValue(
      legacyDetail({ id: "legacy-2", title: "旧系统历史周报", content: "第二篇历史正文" })
    );
    const rows = wrapper.findAll(".archive-row");
    await rows[2].trigger("click");
    await flushPromises();

    expect(routerState.push).not.toHaveBeenCalled();
    expect(operationsApi.fetchHistoricalReportDetail).toHaveBeenLastCalledWith("legacy-2");
    expect(wrapper.find(".archive-legacy-content").text()).toContain("第二篇历史正文");
  });

  it("shows the month navigation only inside the legacy view", async () => {
    const wrapper = mountPage();
    await flushPromises();

    // 默认视图（跨来源合并列表）不提供按月浏览：该职责已移交报告页时间轴
    expect(wrapper.find(".archive-month-nav").exists()).toBe(false);

    await wrapper.find(".archive-origin-filter").setValue("legacy");
    await wrapper.find(".archive-filters .icon-button").trigger("click");
    await flushPromises();

    expect(operationsApi.fetchReportArchiveSummary).toHaveBeenCalledWith("planning_intel", {
      origin: "legacy"
    });
    const monthNav = wrapper.find(".archive-month-nav");
    expect(monthNav.exists()).toBe(true);
    const buttons = monthNav.findAll("button");
    expect(buttons.map((button) => button.text())).toEqual(["全部月份", "2025年06月 · 1"]);

    await buttons[1].trigger("click");
    await flushPromises();
    expect(operationsApi.fetchReportArchive).toHaveBeenLastCalledWith(
      expect.objectContaining({ workspaceCode: "planning_intel", month: "2025-06", origin: "legacy" })
    );

    // 切回全部来源后月份导航收起
    await wrapper.find(".archive-origin-filter").setValue("");
    await wrapper.find(".archive-filters .icon-button").trigger("click");
    await flushPromises();
    expect(wrapper.find(".archive-month-nav").exists()).toBe(false);
    expect(operationsApi.fetchReportArchive).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ month: expect.anything() })
    );
  });

  it("hides the average adoption metric when there are no published samples", async () => {
    operationsApi.fetchReportArchiveSummary.mockResolvedValue(
      summary({
        total: 1,
        published_daily: 0,
        published_weekly: 0,
        legacy_reports: 1,
        total_items: 0,
        total_adopted: 0,
        average_adoption_rate: 0,
        latest_published_at: null,
        top_sources: []
      })
    );
    operationsApi.fetchReportArchive.mockResolvedValue([legacyEntry()]);
    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find(".archive-compare-adoption").exists()).toBe(false);
    expect(wrapper.find(".archive-compare-adoption-empty").text()).toContain("暂无已发布采信样本");
    expect(wrapper.text()).not.toContain("0%");
    expect(wrapper.text()).not.toContain("0.0");
  });

  it("anchors a legacy report from a search route and creates a requirement with source trace", async () => {
    routeState.query = { id: "legacy-1" };
    const wrapper = mountPage({ asAdmin: true });
    await flushPromises();

    expect(operationsApi.fetchHistoricalReportDetail).toHaveBeenCalledWith("legacy-1");
    const anchored = wrapper.find(".archive-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(wrapper.find(".archive-legacy-content").text()).toContain("完整历史报告正文");

    await wrapper.find(".archive-requirement-form input").setValue("跟进旧日报里的 Agent 线索");
    await wrapper.find(".archive-requirement-form textarea").setValue("历史报告复盘触发");
    await wrapper.find(".archive-requirement-form button").trigger("click");
    await flushPromises();

    expect(operationsApi.createRequirement).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        title: "跟进旧日报里的 Agent 线索",
        source_historical_report_id: "legacy-1",
        source_note: "历史报告复盘触发"
      })
    );
    expect(wrapper.text()).toContain("已创建需求");
  });

  it("explains that published reports auto-archive when the archive is empty", async () => {
    operationsApi.fetchReportArchive.mockResolvedValue([]);
    operationsApi.fetchReportArchiveSummary.mockResolvedValue(
      summary({
        total: 0,
        published_daily: 0,
        legacy_reports: 0,
        months: [],
        total_items: 0,
        total_adopted: 0,
        top_sources: []
      })
    );

    const wrapper = mountPage();
    await flushPromises();

    const emptyState = wrapper.find(".empty-state");
    expect(emptyState.exists()).toBe(true);
    expect(emptyState.text()).toContain("发布日报/周报后会自动进入跨来源统计与合并检索");
    expect(wrapper.find(".legacy-import-panel").exists()).toBe(false);
  });
});
