import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import QualityArchivePage from "./QualityArchivePage.vue";
import type {
  HistoricalFeedbackItemRecord,
  HistoricalJobRunRecord,
  LegacyImportGapItemRecord,
  QualityArchiveSummaryRecord
} from "../api/operations";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const operationsApi = vi.hoisted(() => ({
  createRequirement: vi.fn(),
  fetchHistoricalFeedbackItems: vi.fn(),
  fetchHistoricalJobRuns: vi.fn(),
  fetchLegacyImportGaps: vi.fn(),
  fetchQualityArchiveSummary: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/operations", () => ({
  createRequirement: operationsApi.createRequirement,
  fetchHistoricalFeedbackItems: operationsApi.fetchHistoricalFeedbackItems,
  fetchHistoricalJobRuns: operationsApi.fetchHistoricalJobRuns,
  fetchLegacyImportGaps: operationsApi.fetchLegacyImportGaps,
  fetchQualityArchiveSummary: operationsApi.fetchQualityArchiveSummary
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function summary(overrides: Partial<QualityArchiveSummaryRecord> = {}): QualityArchiveSummaryRecord {
  return {
    workspace_code: "legacy_tech_insight_loop",
    total_feedback: 3,
    total_quality_feedback: 2,
    total_job_runs: 4,
    unresolved_feedback_count: 1,
    unresolved_feedback_ref_count: 1,
    total_job_failures: 2,
    by_feedback_type: { useful: 2, noisy: 1 },
    by_quality_reason: { "source-quality": 2 },
    by_job_type: { crawler: 3, summarizer: 1 },
    by_job_status: { completed: 3, failed: 1 },
    latest_feedback_at: "2026-07-05T09:00:00Z",
    latest_job_started_at: "2026-07-05T08:00:00Z",
    ...overrides
  };
}

function feedback(overrides: Partial<HistoricalFeedbackItemRecord> = {}): HistoricalFeedbackItemRecord {
  return {
    id: "feedback-1",
    workspace_code: "legacy_tech_insight_loop",
    domain_code: "ai",
    legacy_system: "tech_insight_loop",
    legacy_table: "article_quality_feedback",
    legacy_id: "legacy-feedback-1",
    legacy_article_id: "article-1",
    raw_item_id: null,
    feedback_kind: "quality_feedback",
    user_name: "规划用户",
    feedback_type: "source-quality",
    reason: "来源质量偏低",
    comment: "需要补历史素材映射",
    feedback_at: "2026-07-05T09:00:00Z",
    article_ref_resolved: false,
    created_at: "2026-07-05T09:01:00Z",
    updated_at: "2026-07-05T09:01:00Z",
    ...overrides
  };
}

function jobRun(overrides: Partial<HistoricalJobRunRecord> = {}): HistoricalJobRunRecord {
  return {
    id: "job-1",
    workspace_code: "legacy_tech_insight_loop",
    domain_code: "ai",
    legacy_system: "tech_insight_loop",
    legacy_table: "jobs",
    legacy_id: "legacy-job-1",
    job_type: "crawler",
    status: "failed",
    message: "Timeout while fetching source",
    started_at: "2026-07-05T08:00:00Z",
    ended_at: "2026-07-05T08:03:00Z",
    total_sources: 10,
    processed_sources: 8,
    inserted_count: 12,
    failed_count: 2,
    details_json: {},
    created_at: "2026-07-05T08:04:00Z",
    updated_at: "2026-07-05T08:04:00Z",
    ...overrides
  };
}

function gap(overrides: Partial<LegacyImportGapItemRecord> = {}): LegacyImportGapItemRecord {
  return {
    id: "gap-1",
    kind: "historical_feedback",
    legacy_id: "legacy-feedback-1",
    title: "未解析的质量反馈引用",
    ref_type: "article",
    unresolved_count: 1,
    unresolved_refs: [{ article_id: "missing-article" }],
    detail_path: "/quality-archive",
    context: {},
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
  workspace.currentCode = "legacy_tech_insight_loop";
  workspace.options = [
    {
      code: "legacy_tech_insight_loop",
      name: "历史归档工作台",
      description: "",
      workspace_type: "archive_workspace",
      default_domain_code: "ai",
      enabled: true,
      current_user_workspace_role: options.asAdmin ? "owner" : "viewer"
    }
  ];
  return mount(QualityArchivePage, {
    global: {
      plugins: [pinia]
    }
  });
}

function filterButton(wrapper: ReturnType<typeof mount>, index: number) {
  const buttons = wrapper.findAll("button").filter((button) => button.text().includes("筛选"));
  const button = buttons[index];
  if (!button) {
    throw new Error(`Filter button not found at index ${index}`);
  }
  return button;
}

describe("QualityArchivePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.query = {};
    operationsApi.fetchQualityArchiveSummary.mockResolvedValue(summary());
    operationsApi.fetchHistoricalFeedbackItems.mockResolvedValue([feedback()]);
    operationsApi.fetchHistoricalJobRuns.mockResolvedValue([jobRun()]);
    operationsApi.fetchLegacyImportGaps.mockResolvedValue([gap()]);
    operationsApi.createRequirement.mockResolvedValue({ title: "复盘质量反馈：来源质量偏低" });
  });

  it("loads quality archive summary, feedback, jobs and unresolved gaps", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(operationsApi.fetchQualityArchiveSummary).toHaveBeenCalledWith("legacy_tech_insight_loop");
    expect(operationsApi.fetchHistoricalFeedbackItems).toHaveBeenCalledWith({
      workspaceCode: "legacy_tech_insight_loop",
      feedbackKind: undefined,
      query: undefined,
      hasUnresolvedRefs: null
    });
    expect(operationsApi.fetchHistoricalJobRuns).toHaveBeenCalledWith({
      workspaceCode: "legacy_tech_insight_loop",
      status: undefined,
      query: undefined
    });
    expect(operationsApi.fetchLegacyImportGaps).toHaveBeenCalledWith({
      workspaceCode: "legacy_tech_insight_loop",
      kind: "historical_feedback",
      limit: 8
    });
    expect(wrapper.text()).toContain("普通反馈");
    expect(wrapper.text()).toContain("质量反馈");
    expect(wrapper.text()).toContain("来源质量偏低");
    expect(wrapper.text()).toContain("未解析");
    expect(wrapper.text()).toContain("Timeout while fetching source");
    expect(wrapper.text()).toContain("未解析的质量反馈引用");
    expect(wrapper.text()).toContain("不写入当前评论、任务、推荐或公司 SQL");
  });

  it("creates a requirement from historical feedback with source trace for admins", async () => {
    routeState.query = { feedback_id: "feedback-1" };
    const wrapper = mountPage({ asAdmin: true });
    await flushPromises();

    const anchored = wrapper.find(".quality-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");

    const transferButton = wrapper.findAll(".quality-row .mini-action").find((button) => button.text().includes("转需求"));
    expect(transferButton).toBeTruthy();
    await transferButton!.trigger("click");
    await flushPromises();

    expect(operationsApi.createRequirement).toHaveBeenCalledWith({
      workspace_code: "legacy_tech_insight_loop",
      title: "复盘质量反馈：来源质量偏低",
      description:
        "由历史质量归档触发。\n\n用户：规划用户\n类型：source-quality\n原因：来源质量偏低\n评论：需要补历史素材映射",
      priority: "medium",
      status: "open",
      source_historical_feedback_item_id: "feedback-1",
      source_note: "质量反馈 legacy-feedback-1 触发"
    });
    expect(wrapper.text()).toContain("已创建需求：复盘质量反馈：来源质量偏低");
  });

  it("applies feedback and job filters through archive APIs", async () => {
    const wrapper = mountPage();
    await flushPromises();

    const selects = wrapper.findAll("select");
    await selects[0].setValue("quality_feedback");
    await wrapper.find('input[placeholder="原因、评论或用户"]').setValue("低质");
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await filterButton(wrapper, 0).trigger("click");
    await flushPromises();

    expect(operationsApi.fetchHistoricalFeedbackItems).toHaveBeenLastCalledWith({
      workspaceCode: "legacy_tech_insight_loop",
      feedbackKind: "quality_feedback",
      query: "低质",
      hasUnresolvedRefs: true
    });

    await selects[1].setValue("failed");
    await wrapper.find('input[placeholder="类型、状态或消息"]').setValue("timeout");
    await filterButton(wrapper, 1).trigger("click");
    await flushPromises();

    expect(operationsApi.fetchHistoricalJobRuns).toHaveBeenLastCalledWith({
      workspaceCode: "legacy_tech_insight_loop",
      status: "failed",
      query: "timeout"
    });
  });

  it("shows archive empty states without creating current feedback affordances", async () => {
    operationsApi.fetchQualityArchiveSummary.mockResolvedValue(
      summary({
        total_feedback: 0,
        total_quality_feedback: 0,
        total_job_runs: 0,
        unresolved_feedback_count: 0,
        unresolved_feedback_ref_count: 0,
        total_job_failures: 0,
        by_feedback_type: {},
        by_quality_reason: {},
        by_job_type: {},
        by_job_status: {}
      })
    );
    operationsApi.fetchHistoricalFeedbackItems.mockResolvedValue([]);
    operationsApi.fetchHistoricalJobRuns.mockResolvedValue([]);
    operationsApi.fetchLegacyImportGaps.mockResolvedValue([]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("暂无旧反馈归档");
    expect(wrapper.text()).toContain("暂无旧任务记录");
    expect(wrapper.text()).toContain("暂无反馈引用缺口");
    expect(wrapper.findAll("button").some((button) => button.text().includes("评论"))).toBe(false);
    expect(wrapper.findAll("button").some((button) => button.text().includes("评分"))).toBe(false);
  });

  it("shows a recoverable error when archive APIs fail", async () => {
    operationsApi.fetchQualityArchiveSummary.mockRejectedValue(new Error("quality archive unavailable"));

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("quality archive unavailable");
  });
});
