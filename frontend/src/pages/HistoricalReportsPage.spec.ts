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
    ...overrides
  };
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
    operationsApi.fetchReportArchiveSummary.mockResolvedValue(summary());
    operationsApi.fetchReportArchive.mockResolvedValue([archiveEntry(), legacyEntry()]);
    operationsApi.fetchLegacyImportSummary.mockResolvedValue({
      workspace_code: "planning_intel",
      generated_at: "2026-07-05T09:00:00Z",
      expected_counts: {},
      metrics: [],
      report_refs: { total: 0, resolved: 0, unresolved: 0 },
      milestone_article_refs: { total: 0, resolved: 0, unresolved: 0 },
      milestone_report_refs: { total: 0, resolved: 0, unresolved: 0 },
      feedback_article_refs: { total: 0, resolved: 0, unresolved: 0 },
      total_unresolved_refs: 0,
      gap_item_count: 0
    });
    operationsApi.fetchLegacyImportGaps.mockResolvedValue([]);
    operationsApi.createRequirement.mockResolvedValue({ title: "跟进历史报告：旧系统历史日报" });
    operationsApi.fetchHistoricalReportDetail.mockResolvedValue(legacyDetail());
  });

  it("renders the unified archive with stats, month navigation and per-report quality metrics", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchReportArchive).toHaveBeenCalledWith(
      expect.objectContaining({ workspaceCode: "planning_intel" })
    );
    const rows = wrapper.findAll(".archive-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("已发布日报");
    expect(rows[0].text()).toContain("4 条目");
    expect(rows[0].text()).toContain("采信 3 · 75%");
    expect(rows[0].text()).toContain("头条 1");
    expect(rows[0].text()).toContain("机器之心 ×2");
    expect(rows[1].text()).toContain("旧系统导入");

    const monthButtons = wrapper.findAll(".archive-month-nav button");
    expect(monthButtons.map((button) => button.text())).toEqual([
      "全部月份",
      "2026年07月 · 1",
      "2025年06月 · 1"
    ]);

    await monthButtons[1].trigger("click");
    await flushPromises();
    expect(operationsApi.fetchReportArchive).toHaveBeenLastCalledWith(
      expect.objectContaining({ workspaceCode: "planning_intel", month: "2026-07" })
    );
  });

  it("opens the report detail page for a published daily report", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const openButton = wrapper.find(".archive-open-detail");
    expect(openButton.exists()).toBe(true);
    expect(openButton.text()).toContain("打开日报详情");
    await openButton.trigger("click");
    expect(routerState.push).toHaveBeenCalledWith("/daily-reports/daily-1");
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
      summary({ total: 0, published_daily: 0, legacy_reports: 0, months: [], total_items: 0, total_adopted: 0 })
    );

    const wrapper = mountPage();
    await flushPromises();

    const emptyState = wrapper.find(".empty-state");
    expect(emptyState.exists()).toBe(true);
    expect(emptyState.text()).toContain("发布日报/周报后会自动归档");
    expect(wrapper.find(".legacy-import-panel").exists()).toBe(false);
  });
});
