import { mount, flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import IngestionRunsPage from "./IngestionRunsPage.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const api = vi.hoisted(() => ({
  fetchSources: vi.fn(),
  createHistoricalBackfillRun: vi.fn(),
  createIngestionRun: vi.fn(),
  fetchFailedSourceRetrySummary: vi.fn(),
  fetchIngestionCoverage: vi.fn(),
  fetchIngestionCoverageTrends: vi.fn(),
  fetchIngestionRun: vi.fn(),
  fetchIngestionRuns: vi.fn(),
  fetchSchedulerConfig: vi.fn(),
  previewManualImport: vi.fn(),
  retryFailedIngestionRun: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  route: {
    query: {} as Record<string, string>
  }
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState.route
}));

vi.mock("../api/sources", () => ({
  fetchSources: api.fetchSources
}));

vi.mock("../api/ingestion", () => ({
  createHistoricalBackfillRun: api.createHistoricalBackfillRun,
  createIngestionRun: api.createIngestionRun,
  fetchFailedSourceRetrySummary: api.fetchFailedSourceRetrySummary,
  fetchIngestionCoverage: api.fetchIngestionCoverage,
  fetchIngestionCoverageTrends: api.fetchIngestionCoverageTrends,
  fetchIngestionRun: api.fetchIngestionRun,
  fetchIngestionRuns: api.fetchIngestionRuns,
  fetchSchedulerConfig: api.fetchSchedulerConfig,
  previewManualImport: api.previewManualImport,
  retryFailedIngestionRun: api.retryFailedIngestionRun
}));

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

function runRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    run_key: "planning_intel:ingestion:run-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    run_type: "workspace_fetch",
    status: "completed",
    started_at: "2026-07-05T01:00:00Z",
    completed_at: "2026-07-05T01:01:00Z",
    source_total: 1,
    source_succeeded: 1,
    source_failed: 0,
    items_fetched: 2,
    raw_created: 2,
    raw_updated: 0,
    params_json: { workspace_code: "planning_intel", source_types: ["rss"] },
    summary_json: { sources: [] },
    ...overrides
  };
}

function coverageRecord(overrides: Record<string, unknown> = {}) {
  return {
    workspace_code: "planning_intel",
    day_key: "2026-07-05",
    run_id: null,
    run_key: null,
    run_type: null,
    run_status: null,
    target_range: "2026-07-05",
    recommendation_run_id: null,
    recommendation_run_key: null,
    daily_report_id: null,
    daily_report_status: null,
    funnel: {
      enabled_sources: 0,
      run_sources: 0,
      source_succeeded: 0,
      source_failed: 0,
      items_fetched: 0,
      raw_created: 0,
      raw_updated: 0,
      raw_in_target: 0,
      news_items: 0,
      dedupe_winners: 0,
      recommendation_candidates: 0,
      recommendation_selected: 0,
      generated_ready: 0,
      daily_adopted: 0
    },
    sources: [],
    ...overrides
  };
}

function coverageTrendsRecord(overrides: Record<string, unknown> = {}) {
  return {
    workspace_code: "planning_intel",
    days: 14,
    generated_at: "2026-07-05T09:00:00Z",
    total_runs: 2,
    total_source_failed: 1,
    total_raw_created: 6,
    average_success_rate: 0.67,
    points: [
      {
        day_key: "2026-07-04",
        run_count: 1,
        latest_run_id: "run-old",
        latest_run_key: "planning_intel:ingestion:old",
        latest_run_status: "partial",
        source_total: 2,
        source_succeeded: 1,
        source_failed: 1,
        source_skipped_unimplemented: 0,
        items_fetched: 2,
        raw_created: 2,
        raw_updated: 0,
        success_rate: 0.5
      },
      {
        day_key: "2026-07-05",
        run_count: 1,
        latest_run_id: "run-new",
        latest_run_key: "planning_intel:ingestion:new",
        latest_run_status: "completed",
        source_total: 1,
        source_succeeded: 1,
        source_failed: 0,
        source_skipped_unimplemented: 0,
        items_fetched: 4,
        raw_created: 4,
        raw_updated: 0,
        success_rate: 1
      }
    ],
    top_failed_sources: [
      {
        data_source_id: "source-1",
        name: "不稳定 RSS",
        source_type: "rss",
        failure_count: 1,
        last_error: "TimeoutError: read timed out",
        last_run_id: "run-old",
        last_run_key: "planning_intel:ingestion:old",
        last_failed_at: "2026-07-04T08:00:00Z"
      }
    ],
    ...overrides
  };
}

function failedRetrySummary(overrides: Record<string, unknown> = {}) {
  return {
    workspace_code: "planning_intel",
    generated_at: "2026-07-05T09:00:00Z",
    policy: {
      enabled: true,
      base_delay_seconds: 900,
      max_delay_seconds: 3600,
      max_attempts: 3,
      limit: 10
    },
    due_count: 1,
    blocked_count: 0,
    next_retry_at: null,
    runs: [
      {
        run_id: "run-old",
        run_key: "planning_intel:ingestion:old",
        run_type: "workspace_fetch",
        status: "partial",
        failed_source_count: 1,
        attempt_count: 0,
        last_attempt_at: "2026-07-05T07:00:00Z",
        next_retry_at: "2026-07-05T07:15:00Z",
        blocked: false,
        due: true,
        latest_retry_run_id: null,
        latest_retry_run_key: null,
        latest_retry_status: null
      }
    ],
    ...overrides
  };
}

function manualPreview(overrides: Record<string, unknown> = {}) {
  return {
    workspace_code: "planning_intel",
    input_format: "csv",
    filename: "",
    total_rows: 1,
    accepted_count: 1,
    rejected_count: 0,
    accepted_items: [
      {
        data_source_id: "source-1",
        source_title: "手工新闻",
        source_url: "https://example.com/manual",
        raw_content: "正文",
        published_at: "2026-07-05T09:00:00Z"
      }
    ],
    errors: [],
    error_report_csv: "row_number,status,error_code,error_message\n2,accepted,,\n",
    ...overrides
  };
}

function mountPage(
  options: {
    canIngest?: boolean;
    sources?: ReturnType<typeof sourceRecord>[];
    runs?: ReturnType<typeof runRecord>[];
    coverage?: ReturnType<typeof coverageRecord>;
  } = {}
) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  workspace.options = [
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

  api.fetchSources.mockResolvedValue(options.sources ?? [sourceRecord()]);
  api.fetchIngestionRuns.mockResolvedValue(options.runs ?? []);
  api.fetchIngestionCoverage.mockResolvedValue(options.coverage ?? coverageRecord());
  api.fetchIngestionCoverageTrends.mockResolvedValue(coverageTrendsRecord());
  api.fetchFailedSourceRetrySummary.mockResolvedValue(failedRetrySummary());
  api.previewManualImport.mockResolvedValue(manualPreview());
  api.fetchSchedulerConfig.mockResolvedValue({
    enabled: false,
    daily_time: "09:00",
    timezone: "Asia/Shanghai",
    interval_seconds: 900,
    workspace_code: "planning_intel",
    source_types: "rss,paper_rss",
    limit: null,
    max_items_per_source: null,
    job_mode: "ingestion_only",
    day_offset_days: -1,
    failed_source_auto_retry_enabled: true,
    failed_source_retry_base_seconds: 900,
    failed_source_retry_max_attempts: 3,
    failed_source_retry_limit: 10,
    config_hint: "测试配置"
  });

  return mount(IngestionRunsPage, {
    global: {
      plugins: [pinia]
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

describe("IngestionRunsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeState.route.query = {};
  });

  it("rejects zero source limits before creating an ingestion run", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await wrapper.find('input[placeholder="空 = 全部启用源"]').setValue("0");
    await buttonByText(wrapper, "运行抓取").trigger("click");
    await flushPromises();

    expect(api.createIngestionRun).not.toHaveBeenCalled();
    expect(api.fetchSources).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("本次运行源数上限必须为空或大于 0");
  });

  it("does not create a run when selected source types have no enabled sources", async () => {
    const wrapper = mountPage({ sources: [] });
    await flushPromises();

    await buttonByText(wrapper, "运行抓取").trigger("click");
    await flushPromises();

    expect(api.fetchSources).toHaveBeenCalledWith("planning_intel");
    expect(api.createIngestionRun).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("当前工作台在所选源类型下没有启用源");
  });

  it("renders the backend no_sources run as a warning with the hint and status label", async () => {
    // 前置守卫通过（有启用源）但后端仍返回 no_sources（如启用状态竞态或 scheduler 侧变更）。
    const noSourcesRun = runRecord({
      id: "run-empty",
      run_key: "planning_intel:ingestion:empty",
      status: "no_sources",
      source_total: 0,
      source_succeeded: 0,
      source_failed: 0,
      items_fetched: 0,
      raw_created: 0,
      summary_json: { hint: "工作台在 rss 类型下没有启用源。", sources: [] }
    });
    api.createIngestionRun.mockResolvedValue(noSourcesRun);
    const wrapper = mountPage();
    await flushPromises();
    api.fetchIngestionRuns.mockResolvedValue([noSourcesRun]);

    await buttonByText(wrapper, "运行抓取").trigger("click");
    await flushPromises();

    expect(api.createIngestionRun).toHaveBeenCalledTimes(1);
    expect(wrapper.find(".form-warning").text()).toContain("抓取运行未执行：工作台在 rss 类型下没有启用源。");
    expect(wrapper.find(".run-tab").text()).toContain("无可用源");
  });

  it("renders the backfill no_sources result as a warning instead of a success message", async () => {
    const noSourcesRun = runRecord({
      id: "run-backfill-empty",
      run_key: "planning_intel:backfill:empty",
      run_type: "historical_backfill",
      status: "no_sources",
      source_total: 0,
      source_succeeded: 0,
      source_failed: 0,
      items_fetched: 0,
      raw_created: 0,
      summary_json: { hint: "目标窗口内没有匹配的启用源。", sources: [] }
    });
    api.createHistoricalBackfillRun.mockResolvedValue(noSourcesRun);
    const wrapper = mountPage();
    await flushPromises();
    api.fetchIngestionRuns.mockResolvedValue([noSourcesRun]);

    await buttonByText(wrapper, "历史补采").trigger("click");
    await buttonByText(wrapper, "运行补采").trigger("click");
    await flushPromises();

    expect(api.createHistoricalBackfillRun).toHaveBeenCalledTimes(1);
    expect(wrapper.find(".form-warning").text()).toContain("补采运行未执行：目标窗口内没有匹配的启用源。");
    expect(wrapper.text()).not.toContain("补采运行已完成");
  });

  it("warns about skipped unimplemented source types right after submitting a run", async () => {
    const skippedRun = runRecord({
      id: "run-skipped",
      run_key: "planning_intel:ingestion:skipped",
      status: "skipped_unimplemented",
      source_total: 1,
      source_succeeded: 0,
      source_failed: 0,
      items_fetched: 0,
      raw_created: 0,
      summary_json: {
        source_skipped_unimplemented: 1,
        sources: [
          {
            data_source_id: "source-wiseflow",
            source_type: "wiseflow",
            status: "skipped_unimplemented",
            error: "AdapterNotImplementedError"
          }
        ]
      }
    });
    api.createIngestionRun.mockResolvedValue(skippedRun);
    const wrapper = mountPage();
    await flushPromises();
    api.fetchIngestionRuns.mockResolvedValue([skippedRun]);

    await buttonByText(wrapper, "运行抓取").trigger("click");
    await flushPromises();

    expect(wrapper.find(".form-warning").text()).toContain("包含 1 个尚未实现的源类型");
  });

  it("hides run actions in read-only deployment modes", async () => {
    const wrapper = mountPage({ canIngest: false, sources: [sourceRecord()] });
    await flushPromises();

    const buttonTexts = wrapper.findAll("button").map((button) => button.text());
    expect(buttonTexts.some((text) => text.includes("运行抓取"))).toBe(false);
    expect(buttonTexts.some((text) => text.includes("运行补采"))).toBe(false);
  });

  it("retries failed sources from the selected run", async () => {
    const failedRun = runRecord({
      id: "run-failed",
      run_key: "planning_intel:ingestion:failed",
      status: "partial",
      source_total: 2,
      source_succeeded: 1,
      source_failed: 1,
      items_fetched: 3,
      raw_created: 2,
      summary_json: {
        sources: [
          { data_source_id: "source-ok", source_type: "rss", status: "completed" },
          { data_source_id: "source-failed", source_type: "rss", status: "failed", error: "TimeoutError" }
        ]
      }
    });
    const retryRun = runRecord({
      id: "run-retry",
      run_key: "planning_intel:ingestion:retry",
      status: "failed",
      source_total: 1,
      source_succeeded: 0,
      source_failed: 1,
      items_fetched: 0,
      raw_created: 0,
      raw_updated: 0,
      params_json: { retry_of_run_id: "run-failed", source_ids: ["source-failed"] },
      summary_json: {
        sources: [{ data_source_id: "source-failed", source_type: "rss", status: "failed", error: "TimeoutError" }]
      }
    });
    api.fetchIngestionRuns
      .mockResolvedValueOnce([failedRun])
      .mockResolvedValueOnce([retryRun, failedRun]);
    api.retryFailedIngestionRun.mockResolvedValue(retryRun);
    const wrapper = mountPage({
      runs: [failedRun],
      coverage: coverageRecord({
        run_id: "run-failed",
        run_key: "planning_intel:ingestion:failed",
        run_status: "partial",
        funnel: {
          ...coverageRecord().funnel,
          enabled_sources: 2,
          run_sources: 2,
          source_succeeded: 1,
          source_failed: 1
        },
        sources: [
          {
            data_source_id: "source-failed",
            name: "失败源",
            source_type: "rss",
            run_status: "failed",
            error: "TimeoutError",
            run_fetched: 0,
            run_created: 0,
            run_updated: 0,
            in_target_range: 0,
            out_of_target_range: 0,
            missing_published_at: 0,
            raw_in_target: 0,
            news_items: 0,
            dedupe_winners: 0,
            recommendation_candidates: 0,
            recommendation_selected: 0,
            generated_ready: 0,
            daily_adopted: 0
          }
        ]
      })
    });
    await flushPromises();

    await buttonByText(wrapper, "重试失败源 1").trigger("click");
    await flushPromises();

    expect(api.retryFailedIngestionRun).toHaveBeenCalledWith("run-failed");
    expect(wrapper.text()).toContain("失败源重试已完成但未返回条目");
  });

  it("does not show retry action when the selected run has no failed sources", async () => {
    const wrapper = mountPage({ runs: [runRecord()] });
    await flushPromises();

    const buttonTexts = wrapper.findAll("button").map((button) => button.text());
    expect(buttonTexts.some((text) => text.includes("重试失败源"))).toBe(false);
  });

  it("renders unimplemented adapter sources as explicit skipped state", async () => {
    const skippedRun = runRecord({
      status: "skipped_unimplemented",
      source_total: 1,
      source_succeeded: 0,
      source_failed: 0,
      items_fetched: 0,
      raw_created: 0,
      summary_json: {
        source_skipped_unimplemented: 1,
        sources: [
          {
            data_source_id: "source-wiseflow",
            name: "Wiseflow Legacy",
            source_type: "wiseflow",
            status: "skipped_unimplemented",
            error: "AdapterNotImplementedError: source_type=wiseflow adapter is not implemented"
          }
        ]
      }
    });
    const wrapper = mountPage({
      runs: [skippedRun],
      coverage: coverageRecord({
        run_id: "run-1",
        run_key: "planning_intel:ingestion:run-1",
        run_status: "skipped_unimplemented",
        funnel: {
          ...coverageRecord().funnel,
          enabled_sources: 1,
          run_sources: 1
        },
        sources: [
          {
            data_source_id: "source-wiseflow",
            name: "Wiseflow Legacy",
            source_type: "wiseflow",
            run_status: "skipped_unimplemented",
            error: "AdapterNotImplementedError: source_type=wiseflow adapter is not implemented",
            run_fetched: 0,
            run_created: 0,
            run_updated: 0,
            in_target_range: 0,
            out_of_target_range: 0,
            missing_published_at: 0,
            raw_in_target: 0,
            news_items: 0,
            dedupe_winners: 0,
            recommendation_candidates: 0,
            recommendation_selected: 0,
            generated_ready: 0,
            daily_adopted: 0
          }
        ]
      })
    });
    await flushPromises();

    expect(wrapper.text()).toContain("源类型未实现");
    expect(wrapper.text()).toContain("Wiseflow Legacy");
    expect(wrapper.text()).toContain("尚未实现");
    expect(wrapper.find(".status-on.skipped").exists()).toBe(true);
  });

  it("renders coverage trends and top failed sources", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(api.fetchIngestionCoverageTrends).toHaveBeenCalledWith("planning_intel", 14);
    expect(wrapper.text()).toContain("近 14 日覆盖趋势");
    expect(wrapper.text()).toContain("近 14 天 2 次运行");
    expect(wrapper.text()).toContain("不稳定 RSS");
    expect(wrapper.text()).toContain("1 次失败");
    expect(wrapper.find(".coverage-trend-bars").exists()).toBe(true);
  });

  it("renders failed source auto retry policy and due runs", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(api.fetchFailedSourceRetrySummary).toHaveBeenCalledWith("planning_intel");
    expect(wrapper.text()).toContain("失败源自动重试：已开启");
    expect(wrapper.text()).toContain("到期 1");
    expect(wrapper.text()).toContain("planning_intel:ingestion:old");
  });

  it("selects an ingestion run from the run_id route anchor", async () => {
    routeState.route.query = { run_id: "run-anchor" };
    const anchoredRun = runRecord({
      id: "run-anchor",
      run_key: "planning_intel:ingestion:anchored",
      status: "partial",
      source_failed: 1,
      summary_json: {
        sources: [
          { data_source_id: "source-anchor", source_type: "rss", status: "failed", error: "TimeoutError" }
        ]
      }
    });
    api.fetchIngestionRun.mockResolvedValue(anchoredRun);

    const wrapper = mountPage({ runs: [] });
    await flushPromises();

    expect(api.fetchIngestionRun).toHaveBeenCalledWith("run-anchor");
    expect(wrapper.text()).toContain("planning_intel:ingestion:anchored");
    expect(api.fetchIngestionCoverage).toHaveBeenLastCalledWith(
      "planning_intel",
      expect.any(String),
      "run-anchor"
    );
  });

  it("submits manual import CSV rows as historical backfill manual items", async () => {
    const manualRun = runRecord({
      id: "run-manual",
      run_key: "planning_intel:backfill:manual",
      run_type: "historical_backfill",
      items_fetched: 1,
      raw_created: 1,
      params_json: {
        workspace_code: "planning_intel",
        source_types: ["rss"],
        backfill_mode: "manual_import",
        manual_items: 1
      },
      summary_json: {
        items_in_target_range: 1,
        items_out_of_target_range: 0,
        items_missing_published_at: 0,
        sources: []
      }
    });
    api.createHistoricalBackfillRun.mockResolvedValue(manualRun);
    api.fetchIngestionRuns
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([manualRun]);

    const wrapper = mountPage({ sources: [sourceRecord()] });
    await flushPromises();

    await buttonByText(wrapper, "历史补采").trigger("click");
    await wrapper.find("select").setValue("manual_import");
    await flushPromises();
    await wrapper
      .find("textarea")
      .setValue("source_title,source_url,raw_content,published_at\n手工新闻,https://example.com/manual,正文,2026-07-05T09:00:00Z");
    await buttonByText(wrapper, "预览导入").trigger("click");
    await flushPromises();
    await buttonByText(wrapper, "运行补采").trigger("click");
    await flushPromises();

    expect(api.previewManualImport).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        input_format: "auto",
        input_text: expect.stringContaining("手工新闻")
      })
    );
    expect(api.createHistoricalBackfillRun).toHaveBeenCalledWith(
      expect.objectContaining({
        workspace_code: "planning_intel",
        backfill_mode: "manual_import",
        manual_items: [
          {
            data_source_id: "source-1",
            source_title: "手工新闻",
            source_url: "https://example.com/manual",
            raw_content: "正文",
            published_at: "2026-07-05T09:00:00Z"
          }
        ]
      })
    );
    expect(wrapper.text()).toContain("手工导入已完成");
  });

  it("blocks manual import submit before preview", async () => {
    const wrapper = mountPage({ sources: [sourceRecord()] });
    await flushPromises();

    await buttonByText(wrapper, "历史补采").trigger("click");
    await wrapper.find("select").setValue("manual_import");
    await flushPromises();
    await buttonByText(wrapper, "运行补采").trigger("click");
    await flushPromises();

    expect(api.previewManualImport).not.toHaveBeenCalled();
    expect(api.createHistoricalBackfillRun).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("请先预览手工导入");
  });

  it("blocks manual import when preview has zero accepted rows and shows report", async () => {
    api.previewManualImport.mockResolvedValueOnce(
      manualPreview({
        total_rows: 1,
        accepted_count: 0,
        rejected_count: 1,
        accepted_items: [],
        errors: [{ row_number: 2, code: "empty_payload", message: "至少需要标题、URL 或正文之一", raw_text: ",,," }],
        error_report_csv: "row_number,status,error_code,error_message\n2,rejected,empty_payload,至少需要标题\n"
      })
    );
    const wrapper = mountPage({ sources: [sourceRecord()] });
    await flushPromises();

    await buttonByText(wrapper, "历史补采").trigger("click");
    await wrapper.find("select").setValue("manual_import");
    await flushPromises();
    await wrapper.find("textarea").setValue("source_title,source_url,raw_content\n,,");
    await buttonByText(wrapper, "预览导入").trigger("click");
    await flushPromises();
    await buttonByText(wrapper, "运行补采").trigger("click");
    await flushPromises();

    expect(api.createHistoricalBackfillRun).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("预览结果：可导入 0 条");
    expect(wrapper.text()).toContain("请先预览手工导入");
  });
});
