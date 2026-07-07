import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ExportsPage from "./ExportsPage.vue";
import type {
  CompanySqlBatchExportRecord,
  CompanySqlImportReceiptRecord,
  CompanySqlPreflightRecord,
  CompanySqlTraceRecord,
  ExportJobRecord
} from "../api/exports";
import type { DailyReportRecord } from "../api/reports";
import { useWorkspaceStore } from "../stores/workspace";

const exportsApi = vi.hoisted(() => ({
  createCompanySqlBatchExport: vi.fn(),
  createCompanySqlExport: vi.fn(),
  createCompanySqlImportReceipt: vi.fn(),
  downloadExportJob: vi.fn(),
  fetchCompanySqlImportReceipts: vi.fn(),
  fetchCompanySqlTrace: vi.fn(),
  fetchExportJob: vi.fn(),
  fetchExportJobs: vi.fn(),
  preflightCompanySqlExport: vi.fn()
}));

const reportsApi = vi.hoisted(() => ({
  fetchDailyReports: vi.fn()
}));

const routeState = vi.hoisted(() => ({
  query: {} as Record<string, string>
}));

vi.mock("../api/exports", () => ({
  createCompanySqlBatchExport: exportsApi.createCompanySqlBatchExport,
  createCompanySqlExport: exportsApi.createCompanySqlExport,
  createCompanySqlImportReceipt: exportsApi.createCompanySqlImportReceipt,
  downloadExportJob: exportsApi.downloadExportJob,
  fetchCompanySqlImportReceipts: exportsApi.fetchCompanySqlImportReceipts,
  fetchCompanySqlTrace: exportsApi.fetchCompanySqlTrace,
  fetchExportJob: exportsApi.fetchExportJob,
  fetchExportJobs: exportsApi.fetchExportJobs,
  preflightCompanySqlExport: exportsApi.preflightCompanySqlExport
}));

vi.mock("../api/reports", () => ({
  fetchDailyReports: reportsApi.fetchDailyReports
}));

vi.mock("vue-router", () => ({
  useRoute: () => routeState
}));

function exportJob(overrides: Partial<ExportJobRecord> = {}): ExportJobRecord {
  return {
    id: "export-1",
    export_type: "company_sql",
    status: "completed",
    workspace_code: "planning_intel",
    domain_code: "ai",
    params_json: {},
    result_json: { item_count: 1, statement_count: 4, sql_size_bytes: 6 },
    latest_import_receipt: null,
    created_at: "2026-07-05T09:00:00Z",
    completed_at: "2026-07-05T09:01:00Z",
    ...overrides
  };
}

function importReceipt(overrides: Partial<CompanySqlImportReceiptRecord> = {}): CompanySqlImportReceiptRecord {
  return {
    id: "receipt-1",
    export_job_id: "export-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    target_system: "company_intranet_prod",
    import_status: "partial",
    imported_at: "2026-07-05T10:00:00Z",
    imported_statement_count: 3,
    failed_statement_count: 1,
    failure_items: [
      {
        export_job_item_id: "export-item-1",
        sql_sequence: 1,
        sql_table: "ai_journal",
        error_code: "column_too_long",
        error_message: "source_title 超过内网字段长度",
        sql_excerpt: "INSERT IGNORE INTO ai_journal..."
      }
    ],
    notes: "内网测试导入反馈",
    recorded_by_id: "user-1",
    recorded_by_name: "规划部管理员",
    created_at: "2026-07-05T10:01:00Z",
    updated_at: "2026-07-05T10:01:00Z",
    ...overrides
  };
}

function trace(exportJobId = "export-1", exportJobItemId = "export-item-1"): CompanySqlTraceRecord {
  return {
    export_job_id: exportJobId,
    item_count: 1,
    statement_count: 1,
    trace_items: [
      {
        export_job_item_id: exportJobItemId,
        sql_sequence: 1,
        sql_table: "ai_journal",
        status: "ready",
        daily_report_item_id: "daily-item-1",
        generated_news_id: "generated-1",
        news_item_id: "news-1",
        raw_item_id: "raw-1",
        data_source_id: "source-1",
        data_source_name: "Example RSS",
        source_type: "rss",
        source_url: "https://example.com/news",
        source_title: "原始标题",
        generated_title: "导出追溯标题",
        export_title: "编辑后的导出标题",
        category: "模型",
        adoption_status: 2,
        sql_excerpt: "INSERT INTO ai_journal...",
        title_source: "daily_report_items.editor_title",
        summary_source: "generated_news.summary",
        key_points_source: "generated_news.key_points",
        content_field_sources: {
          background: "generated_news.content_json",
          effects: "generated_news.content_json",
          eventSummary: "generated_news.content_json",
          technologyAndInnovation: "generated_news.content_json",
          valueAndImpact: "daily_report_items.editor_content_json"
        },
        editor_override_fields: ["title", "content_json.valueAndImpact"],
        field_diffs: [
          {
            field: "title",
            label: "标题",
            export_source: "daily_report_items.editor_title",
            export_value_preview: "编辑后的导出标题",
            generated_value_preview: "导出追溯标题",
            editor_value_preview: "编辑后的导出标题",
            raw_value_preview: null,
            changed_by_editor: true,
            truncated: false
          },
          {
            field: "summary",
            label: "摘要",
            export_source: "generated_news.summary",
            export_value_preview: "生成摘要",
            generated_value_preview: "生成摘要",
            editor_value_preview: null,
            raw_value_preview: null,
            changed_by_editor: false,
            truncated: false
          },
          {
            field: "raw_content",
            label: "原文内容",
            export_source: "raw_items.raw_content",
            export_value_preview: "原文内容预览",
            generated_value_preview: null,
            editor_value_preview: null,
            raw_value_preview: "原文内容预览",
            changed_by_editor: false,
            truncated: true
          },
          {
            field: "content_json.valueAndImpact",
            label: "正文 valueAndImpact",
            export_source: "daily_report_items.editor_content_json",
            export_value_preview: "编辑价值判断",
            generated_value_preview: "生成价值判断",
            editor_value_preview: "编辑价值判断",
            raw_value_preview: null,
            changed_by_editor: true,
            truncated: false
          }
        ]
      }
    ]
  };
}

function preflight(overrides: Partial<CompanySqlPreflightRecord> = {}): CompanySqlPreflightRecord {
  return {
    daily_report_id: "daily-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    day_key: "2026-07-05",
    report_status: "published",
    status: "passed",
    eligible_count: 1,
    blocked_count: 0,
    skipped_count: 0,
    warning_count: 1,
    error_count: 0,
    errors: [],
    warnings: [],
    items: [
      {
        daily_report_item_id: "daily-item-1",
        generated_news_id: "generated-1",
        news_item_id: "news-1",
        adoption_status: 2,
        status: "eligible",
        title: "可导出新闻",
        source_url: "https://example.com/news",
        category: "模型",
        errors: [],
        warnings: [
          {
            level: "warning",
            code: "raw_content_html_cleaned",
            message: "ai_journal.content 含 HTML，导出会清洗为纯文本。",
            field: "raw_content",
            daily_report_item_id: "daily-item-1"
          }
        ]
      }
    ],
    ...overrides
  };
}

function batchResult(overrides: Partial<CompanySqlBatchExportRecord> = {}): CompanySqlBatchExportRecord {
  return {
    batch_export_job_id: "batch-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    status: "partial_success",
    total_reports: 2,
    succeeded_count: 1,
    failed_count: 1,
    skipped_count: 0,
    total_item_count: 1,
    total_statement_count: 4,
    total_sql_text_bytes: 4096,
    manifest_json: { schema_version: 1 },
    created_at: "2026-07-05T09:00:00Z",
    completed_at: "2026-07-05T09:01:00Z",
    items: [
      {
        daily_report_id: "daily-1",
        day_key: "2026-07-05",
        status: "succeeded",
        preflight_status: "passed",
        export_job_id: "export-batch-1",
        download_url: "/api/exports/export-batch-1/download",
        item_count: 1,
        statement_count: 4,
        sql_text_bytes: 4096,
        warning_count: 0,
        error_count: 0,
        errors: []
      },
      {
        daily_report_id: "daily-2",
        day_key: "2026-07-06",
        status: "failed",
        preflight_status: "failed",
        export_job_id: null,
        download_url: null,
        item_count: 0,
        statement_count: 0,
        sql_text_bytes: 0,
        warning_count: 0,
        error_count: 1,
        errors: ["公司 SQL 只能导出已发布日报。"]
      }
    ],
    ...overrides
  };
}

function dailyReport(overrides: Partial<DailyReportRecord> = {}): DailyReportRecord {
  return {
    id: "daily-1",
    workspace_code: "planning_intel",
    domain_code: "ai",
    day_key: "2026-07-05",
    title: "日报",
    summary: "",
    status: "published",
    published_at: "2026-07-05T09:00:00Z",
    items: [],
    ...overrides
  };
}

function mountPage() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const workspace = useWorkspaceStore();
  workspace.currentCode = "planning_intel";
  return mount(ExportsPage, {
    global: {
      plugins: [pinia]
    }
  });
}

function buttonByText(wrapper: ReturnType<typeof mount>, label: string) {
  const button = wrapper.findAll("button").find((candidate) => candidate.text().includes(label));
  if (!button) {
    throw new Error(`Button not found: ${label}`);
  }
  return button;
}

describe("ExportsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:company-sql")
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn()
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) }
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    routeState.query = {};
    reportsApi.fetchDailyReports.mockResolvedValue([dailyReport()]);
    exportsApi.fetchExportJobs.mockResolvedValue([exportJob()]);
    exportsApi.fetchExportJob.mockImplementation((id: string) => Promise.resolve(exportJob({ id })));
    exportsApi.fetchCompanySqlTrace.mockImplementation((id: string) => Promise.resolve(trace(id)));
    exportsApi.fetchCompanySqlImportReceipts.mockResolvedValue([importReceipt()]);
    exportsApi.preflightCompanySqlExport.mockResolvedValue(preflight());
    exportsApi.downloadExportJob.mockResolvedValue(new Blob(["-- sql"], { type: "text/sql" }));
    exportsApi.createCompanySqlBatchExport.mockResolvedValue(batchResult());
    exportsApi.createCompanySqlImportReceipt.mockResolvedValue(importReceipt({ id: "receipt-new", import_status: "imported", failed_statement_count: 0, failure_items: [] }));
    exportsApi.createCompanySqlExport.mockResolvedValue({
      export_job_id: "export-new",
      daily_report_id: "daily-1",
      workspace_code: "planning_intel",
      domain_code: "ai",
      status: "completed",
      item_count: 1,
      statement_count: 1,
      sql_text: "-- sql",
      sql_text_bytes: 6,
      sql_text_preview_bytes: 6,
      sql_text_truncated: false,
      download_url: "/api/exports/export-new/download",
      download_filename: "planning_intel_2026-07-05_company_sql.sql",
      created_at: "2026-07-05T09:00:00Z",
      completed_at: "2026-07-05T09:01:00Z",
      result_json: {}
    });
  });

  it("loads trace and highlights an export job from a search route", async () => {
    routeState.query = { export_job_id: "export-2" };
    exportsApi.fetchExportJobs.mockResolvedValue([
      exportJob(),
      exportJob({ id: "export-2", result_json: { item_count: 2, statement_count: 8 } })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(exportsApi.fetchCompanySqlTrace).toHaveBeenCalledWith("export-2");
    const anchored = wrapper.find(".export-job-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("export-2");
    expect(wrapper.text()).toContain("编辑后的导出标题");
    expect(wrapper.text()).toContain("INSERT INTO ai_journal");
    expect(wrapper.text()).toContain("标题：编辑覆盖");
    expect(wrapper.text()).toContain("摘要：生成稿");
    expect(wrapper.text()).toContain("价值：编辑覆盖");
    expect(wrapper.text()).toContain("导出：编辑后的导出标题");
    expect(wrapper.text()).toContain("编辑：编辑后的导出标题");
    expect(wrapper.text()).toContain("生成：导出追溯标题");
    expect(wrapper.text()).toContain("来源：原文内容预览");
    expect(wrapper.text()).toContain("已截断");
  });

  it("highlights an export trace item from a search route", async () => {
    routeState.query = { export_job_id: "export-2", export_job_item_id: "export-item-2" };
    exportsApi.fetchExportJobs.mockResolvedValue([exportJob({ id: "export-2" })]);
    exportsApi.fetchCompanySqlTrace.mockResolvedValue(trace("export-2", "export-item-2"));

    const wrapper = mountPage();
    await flushPromises();

    expect(exportsApi.fetchCompanySqlTrace).toHaveBeenCalledWith("export-2");
    const anchored = wrapper.find(".export-trace-row.anchored");
    expect(anchored.exists()).toBe(true);
    expect(anchored.attributes("aria-current")).toBe("true");
    expect(anchored.text()).toContain("ai_journal");
    expect(anchored.text()).toContain("编辑后的导出标题");
  });

  it("shows preflight summary before company SQL export", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "运行预检").trigger("click");
    await flushPromises();

    expect(exportsApi.preflightCompanySqlExport).toHaveBeenCalledWith("daily-1");
    expect(wrapper.text()).toContain("导出前预检 · 通过");
    expect(wrapper.text()).toContain("0 错误");
    expect(wrapper.text()).toContain("ai_journal.content 含 HTML");
    expect(wrapper.text()).toContain("可导出新闻");
  });

  it("stops SQL generation when preflight fails", async () => {
    exportsApi.preflightCompanySqlExport.mockResolvedValue(
      preflight({
        status: "failed",
        eligible_count: 0,
        blocked_count: 1,
        warning_count: 0,
        error_count: 1,
        items: [
          {
            daily_report_item_id: "daily-item-1",
            generated_news_id: "generated-1",
            news_item_id: "news-1",
            adoption_status: 2,
            status: "blocked",
            title: "失败新闻",
            source_url: null,
            category: "模型",
            errors: [
              {
                level: "error",
                code: "source_url_missing",
                message: "source_url 不能为空。",
                field: "source_url",
                daily_report_item_id: "daily-item-1"
              }
            ],
            warnings: []
          }
        ]
      })
    );
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "生成 SQL").trigger("click");
    await flushPromises();

    expect(exportsApi.preflightCompanySqlExport).toHaveBeenCalledWith("daily-1");
    expect(exportsApi.createCompanySqlExport).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("预检未通过");
    expect(wrapper.text()).toContain("source_url 不能为空");
  });

  it("downloads historical export jobs through the server endpoint", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "下载 SQL").trigger("click");
    await flushPromises();

    expect(exportsApi.downloadExportJob).toHaveBeenCalledWith("export-1");
    expect(wrapper.text()).toContain("SQL 6 B");
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:company-sql");
    expect(wrapper.text()).toContain("SQL 下载已开始");
  });

  it("loads and records company SQL intranet import receipts", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "导入回执").trigger("click");
    await flushPromises();

    expect(exportsApi.fetchCompanySqlImportReceipts).toHaveBeenCalledWith("export-1");
    expect(wrapper.text()).toContain("内网导入回执");
    expect(wrapper.text()).toContain("/api/exports/export-1/import-receipts/callback");
    expect(wrapper.text()).toContain("页面不展示 token");
    expect(wrapper.text()).toContain("部分失败");
    expect(wrapper.text()).toContain("source_title 超过内网字段长度");

    await wrapper.find("form.receipt-form").trigger("submit");
    await flushPromises();

    expect(exportsApi.createCompanySqlImportReceipt).toHaveBeenCalledWith("export-1", {
      target_system: "company_intranet",
      import_status: "imported",
      imported_statement_count: 4,
      failed_statement_count: 0,
      failure_items: [],
      notes: ""
    });
    expect(wrapper.text()).toContain("导入回执已登记：已导入");
    expect(wrapper.text()).toContain("导入：已导入");
  });

  it("does not offer SQL download actions for batch manifest history rows", async () => {
    exportsApi.fetchExportJobs.mockResolvedValue([
      exportJob({
        id: "batch-1",
        export_type: "company_sql_batch",
        result_json: {
          manifest: { succeeded_count: 1, failed_count: 0 }
        }
      })
    ]);

    const wrapper = mountPage();
    await flushPromises();

    expect(wrapper.text()).toContain("Manifest 记录");
    expect(wrapper.find(".export-job-row").text()).not.toContain("下载 SQL");
    expect(wrapper.find(".export-job-row").text()).not.toContain("查看追溯");
  });

  it("copies the generated SQL preview instead of requiring manual selection", async () => {
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "生成 SQL").trigger("click");
    await flushPromises();
    await buttonByText(wrapper, "复制 SQL").trigger("click");
    await flushPromises();

    expect(exportsApi.createCompanySqlExport).toHaveBeenCalledWith("daily-1");
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("-- sql");
    expect(wrapper.text()).toContain("SQL 已复制");
  });

  it("creates a batch export manifest and keeps per-day server downloads", async () => {
    reportsApi.fetchDailyReports.mockResolvedValue([
      dailyReport(),
      dailyReport({
        id: "daily-2",
        day_key: "2026-07-06",
        title: "第二天日报",
        published_at: "2026-07-06T09:00:00Z"
      })
    ]);
    const wrapper = mountPage();
    await flushPromises();

    const checkboxes = wrapper.findAll('input[type="checkbox"]');
    await checkboxes[0].setValue(true);
    await checkboxes[1].setValue(true);
    await buttonByText(wrapper, "生成批量 Manifest").trigger("click");
    await flushPromises();

    expect(exportsApi.createCompanySqlBatchExport).toHaveBeenCalledWith(["daily-1", "daily-2"]);
    expect(wrapper.text()).toContain("批量导出完成：1 成功，1 失败");
    expect(wrapper.text()).toContain("Manifest partial_success");
    expect(wrapper.text()).toContain("2026-07-05");
    expect(wrapper.text()).toContain("公司 SQL 只能导出已发布日报");

    const batchDownloadButton = wrapper.find(".batch-result-row button");
    expect(batchDownloadButton.exists()).toBe(true);
    await batchDownloadButton.trigger("click");
    await flushPromises();
    expect(exportsApi.downloadExportJob).toHaveBeenCalledWith("export-batch-1");
  });

  it("marks large SQL previews as truncated and keeps full file on server download", async () => {
    exportsApi.createCompanySqlExport.mockResolvedValue({
      export_job_id: "export-large",
      daily_report_id: "daily-1",
      workspace_code: "planning_intel",
      domain_code: "ai",
      status: "completed",
      item_count: 120,
      statement_count: 480,
      sql_text: "-- truncated preview",
      sql_text_bytes: 512 * 1024,
      sql_text_preview_bytes: 200 * 1024,
      sql_text_truncated: true,
      download_url: "/api/exports/export-large/download",
      download_filename: "planning_intel_2026-07-05_company_sql.sql",
      created_at: "2026-07-05T09:00:00Z",
      completed_at: "2026-07-05T09:01:00Z",
      result_json: { sql_size_bytes: 512 * 1024, download_strategy: "server_streaming" }
    });
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "生成 SQL").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("完整文件 512.0 KB");
    expect(wrapper.text()).toContain("SQL 文件较大，页面只显示截断预览");
    expect(wrapper.findAll("button").some((button) => button.text().includes("预览已截断"))).toBe(true);
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it("shows a server download error instead of faking success", async () => {
    exportsApi.downloadExportJob.mockRejectedValue(new Error("insufficient workspace role"));
    const wrapper = mountPage();
    await flushPromises();

    await buttonByText(wrapper, "下载 SQL").trigger("click");
    await flushPromises();

    expect(exportsApi.downloadExportJob).toHaveBeenCalledWith("export-1");
    expect(wrapper.text()).toContain("insufficient workspace role");
    expect(wrapper.text()).not.toContain("SQL 下载已开始");
  });
});
