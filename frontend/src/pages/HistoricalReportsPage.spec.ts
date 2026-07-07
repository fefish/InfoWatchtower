import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HistoricalReportsPage from "./HistoricalReportsPage.vue";
import type {
  HistoricalReportDetailRecord,
  HistoricalReportListItem,
  HistoricalReportSummaryRecord,
  LegacyImportSummaryRecord
} from "../api/operations";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createRequirement: vi.fn(),
  fetchHistoricalReportDetail: vi.fn(),
  fetchHistoricalReports: vi.fn(),
  fetchHistoricalReportSummary: vi.fn(),
  fetchLegacyImportGaps: vi.fn(),
  fetchLegacyImportSummary: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/operations", () => ({
  createRequirement: operationsApi.createRequirement,
  fetchHistoricalReportDetail: operationsApi.fetchHistoricalReportDetail,
  fetchHistoricalReports: operationsApi.fetchHistoricalReports,
  fetchHistoricalReportSummary: operationsApi.fetchHistoricalReportSummary,
  fetchLegacyImportGaps: operationsApi.fetchLegacyImportGaps,
  fetchLegacyImportSummary: operationsApi.fetchLegacyImportSummary
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function report(overrides: Partial<HistoricalReportListItem> = {}): HistoricalReportListItem {
  return {
    id: "report-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    legacy_system: "tech_insight_loop",
    legacy_id: "legacy-report-1",
    report_type: "daily",
    title: "历史日报",
    status: "imported",
    period_start_at: "2026-07-01T00:00:00Z",
    period_end_at: null,
    resolved_ref_count: 1,
    unresolved_ref_count: 0,
    content_excerpt: "历史正文摘要",
    created_at: "2026-07-05T09:00:00Z",
    updated_at: "2026-07-05T09:00:00Z",
    ...overrides
  };
}

function reportDetail(overrides: Partial<HistoricalReportDetailRecord> = {}): HistoricalReportDetailRecord {
  return {
    ...report(overrides),
    content: "完整历史报告正文",
    source_refs_json: { resolved: [], unresolved: [] },
    metadata_json: {},
    ...overrides
  };
}

function summary(): HistoricalReportSummaryRecord {
  return {
    workspace_code: "planning_intel",
    total: 2,
    by_report_type: { daily: 1, weekly: 1 },
    by_status: { imported: 2 },
    unresolved_report_count: 0,
    unresolved_ref_count: 0,
    earliest_period_start_at: "2026-07-01T00:00:00Z",
    latest_period_start_at: "2026-07-02T00:00:00Z"
  };
}

function legacySummary(): LegacyImportSummaryRecord {
  return {
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
    operationsApi.fetchHistoricalReportSummary.mockResolvedValue(summary());
    operationsApi.fetchHistoricalReports.mockResolvedValue([report()]);
    operationsApi.fetchLegacyImportSummary.mockResolvedValue(legacySummary());
    operationsApi.fetchLegacyImportGaps.mockResolvedValue([]);
    operationsApi.createRequirement.mockResolvedValue({ title: "跟进历史报告：历史日报" });
    operationsApi.fetchHistoricalReportDetail.mockImplementation((id: string) =>
      Promise.resolve(reportDetail({ id, title: id === "report-2" ? "搜索命中的历史报告" : "历史日报" }))
    );
  });

  it("selects and highlights a historical report from a search route", async () => {
    routeState.query = { id: "report-2" };
    operationsApi.fetchHistoricalReports.mockResolvedValue([
      report(),
      report({ id: "report-2", title: "搜索命中的历史报告", legacy_id: "legacy-report-2" })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchHistoricalReportDetail).toHaveBeenCalledWith("report-2");
    const anchored = wrapper.find(".historical-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("搜索命中的历史报告");
    expect(wrapper.find(".historical-detail").text()).toContain("搜索命中的历史报告");
  });

  it("creates a requirement from a historical report with source trace", async () => {
    const wrapper = mountPage({ asAdmin: true });
    await flushPromises();

    await wrapper.find(".historical-requirement-form input").setValue("跟进旧日报里的 Agent 线索");
    await wrapper.find(".historical-requirement-form textarea").setValue("历史报告复盘触发");
    await wrapper.find(".historical-requirement-form button").trigger("click");
    await flushPromises();

    expect(operationsApi.createRequirement).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        title: "跟进旧日报里的 Agent 线索",
        source_historical_report_id: "report-1",
        source_note: "历史报告复盘触发"
      })
    );
    expect(wrapper.text()).toContain("已创建需求");
  });
});
