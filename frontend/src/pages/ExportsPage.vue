<script setup lang="ts">
import { Copy, DownloadCloud, FileCode2, RefreshCw, ShieldCheck } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createCompanySqlBatchExport,
  createCompanySqlExport,
  createCompanySqlImportReceipt,
  downloadExportJob,
  fetchCompanySqlImportReceipts,
  fetchCompanySqlTrace,
  fetchExportJob,
  fetchExportJobs,
  preflightCompanySqlExport,
  type CompanySqlBatchExportRecord,
  type CompanySqlTraceRecord,
  type CompanySqlExportRecord,
  type CompanySqlImportReceiptRecord,
  type CompanySqlPreflightRecord,
  type ExportJobRecord
} from "../api/exports";
import { fetchDailyReports, type DailyReportRecord } from "../api/reports";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const workspace = useWorkspaceStore();
const reports = ref<DailyReportRecord[]>([]);
const jobs = ref<ExportJobRecord[]>([]);
const selectedReportId = ref("");
const selectedBatchReportIds = ref<string[]>([]);
const exportResult = ref<CompanySqlExportRecord | null>(null);
const batchResult = ref<CompanySqlBatchExportRecord | null>(null);
const preflightResult = ref<CompanySqlPreflightRecord | null>(null);
const traceResult = ref<CompanySqlTraceRecord | null>(null);
const receiptJob = ref<ExportJobRecord | null>(null);
const importReceipts = ref<CompanySqlImportReceiptRecord[]>([]);
const loadingTraceJobId = ref("");
const loadingReceiptJobId = ref("");
const downloadingJobId = ref("");
const copyingSql = ref(false);
const loading = ref(false);
const exporting = ref(false);
const batchExporting = ref(false);
const preflighting = ref(false);
const savingReceipt = ref(false);
const error = ref("");
const message = ref("");
const anchoredExportLoadedId = ref("");
const receiptForm = ref({
  target_system: "company_intranet",
  import_status: "imported" as "pending" | "imported" | "failed" | "partial",
  imported_statement_count: 0,
  failed_statement_count: 0,
  notes: "",
  failure_items: [
    {
      sql_sequence: null as number | null,
      sql_table: "",
      error_code: "",
      error_message: ""
    }
  ]
});

const selectedReport = computed(
  () => reports.value.find((report) => report.id === selectedReportId.value) ?? reports.value[0] ?? null
);

const exportableReports = computed(() => reports.value.filter((report) => report.status === "published"));
const adoptedCount = computed(
  () => selectedReport.value?.items.filter((item) => item.adoption_status === 2).length ?? 0
);
const pendingExportJobId = computed(() => routeQueryString(route.query.export_job_id));
const pendingExportJobItemId = computed(() => routeQueryString(route.query.export_job_item_id));
const currentPreflight = computed(() =>
  preflightResult.value?.daily_report_id === selectedReport.value?.id ? preflightResult.value : null
);

function routeQueryString(value: unknown) {
  return Array.isArray(value) ? String(value[0] ?? "") : String(value ?? "");
}

async function loadExportsPage() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const [nextReports, nextJobs] = await Promise.all([
      fetchDailyReports(workspace.currentCode),
      fetchExportJobs(workspace.currentCode)
    ]);
    reports.value = nextReports;
    jobs.value = nextJobs;
    if (!selectedReportId.value) {
      selectedReportId.value = exportableReports.value[0]?.id ?? nextReports[0]?.id ?? "";
    }
    selectedBatchReportIds.value = selectedBatchReportIds.value.filter((id) =>
      nextReports.some((report) => report.id === id && report.status === "published")
    );
    await loadAnchoredExportJob();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载 SQL 导出页失败";
  } finally {
    loading.value = false;
  }
}

async function loadAnchoredExportJob() {
  const exportJobId = pendingExportJobId.value;
  if (!exportJobId || anchoredExportLoadedId.value === exportJobId) {
    return;
  }
  let job = jobs.value.find((item) => item.id === exportJobId);
  try {
    if (!job) {
      const fetchedJob = await fetchExportJob(exportJobId);
      jobs.value = [fetchedJob, ...jobs.value.filter((item) => item.id !== fetchedJob.id)];
      job = fetchedJob;
    }
    await loadTrace(job);
    anchoredExportLoadedId.value = exportJobId;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载导出追溯失败";
  }
}

async function runExport() {
  if (!selectedReport.value) {
    return;
  }
  exporting.value = true;
  error.value = "";
  message.value = "";
  try {
    const preflight = await runPreflight({ quiet: true });
    if (!preflight || preflight.status !== "passed") {
      message.value = "";
      error.value = "预检未通过，已停止生成 SQL。";
      return;
    }
    exportResult.value = await createCompanySqlExport(selectedReport.value.id);
    traceResult.value = await fetchCompanySqlTrace(exportResult.value.export_job_id);
    message.value = `SQL 已生成：${exportResult.value.item_count} 条新闻，${exportResult.value.statement_count} 条语句`;
    await loadExportsPage();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "生成 SQL 失败";
  } finally {
    exporting.value = false;
  }
}

async function runBatchExport() {
  if (selectedBatchReportIds.value.length === 0) {
    return;
  }
  batchExporting.value = true;
  error.value = "";
  message.value = "";
  try {
    batchResult.value = await createCompanySqlBatchExport(selectedBatchReportIds.value);
    message.value = `批量导出完成：${batchResult.value.succeeded_count} 成功，${batchResult.value.failed_count} 失败`;
    await loadExportsPage();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "批量生成 SQL 失败";
  } finally {
    batchExporting.value = false;
  }
}

async function runPreflight(options: { quiet?: boolean } = {}) {
  if (!selectedReport.value) {
    return null;
  }
  preflighting.value = true;
  error.value = "";
  if (!options.quiet) {
    message.value = "";
  }
  try {
    const result = await preflightCompanySqlExport(selectedReport.value.id);
    preflightResult.value = result;
    if (!options.quiet) {
      message.value =
        result.status === "passed"
          ? `预检通过：${result.eligible_count} 条可导出，${result.warning_count} 条提醒`
          : `预检未通过：${result.error_count} 个错误，${result.blocked_count} 条阻断`;
    }
    return result;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导出预检失败";
    return null;
  } finally {
    preflighting.value = false;
  }
}

async function loadTrace(job: ExportJobRecord) {
  loadingTraceJobId.value = job.id;
  error.value = "";
  try {
    traceResult.value = await fetchCompanySqlTrace(job.id);
    message.value = `已加载导出追溯：${traceResult.value.statement_count} 条 SQL 语句`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载导出追溯失败";
  } finally {
    loadingTraceJobId.value = "";
  }
}

async function loadImportReceipts(job: ExportJobRecord) {
  loadingReceiptJobId.value = job.id;
  error.value = "";
  try {
    receiptJob.value = job;
    resetReceiptForm(job);
    importReceipts.value = await fetchCompanySqlImportReceipts(job.id);
    message.value = `已加载导入回执：${importReceipts.value.length} 条`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载导入回执失败";
  } finally {
    loadingReceiptJobId.value = "";
  }
}

async function saveImportReceipt() {
  if (!receiptJob.value) {
    return;
  }
  savingReceipt.value = true;
  error.value = "";
  message.value = "";
  try {
    const failureItems = receiptForm.value.failure_items
      .filter((item) => item.error_message.trim())
      .map((item) => ({
        sql_sequence: item.sql_sequence,
        sql_table: item.sql_table.trim() || null,
        error_code: item.error_code.trim(),
        error_message: item.error_message.trim()
      }));
    const saved = await createCompanySqlImportReceipt(receiptJob.value.id, {
      target_system: receiptForm.value.target_system.trim() || "company_intranet",
      import_status: receiptForm.value.import_status,
      imported_statement_count: receiptForm.value.imported_statement_count,
      failed_statement_count:
        receiptForm.value.import_status === "imported"
          ? 0
          : Math.max(receiptForm.value.failed_statement_count, failureItems.length),
      failure_items: receiptForm.value.import_status === "imported" ? [] : failureItems,
      notes: receiptForm.value.notes.trim()
    });
    importReceipts.value = [saved, ...importReceipts.value.filter((item) => item.id !== saved.id)];
    jobs.value = jobs.value.map((job) =>
      job.id === saved.export_job_id ? { ...job, latest_import_receipt: saved } : job
    );
    receiptJob.value = jobs.value.find((job) => job.id === saved.export_job_id) ?? receiptJob.value;
    resetReceiptForm(receiptJob.value);
    message.value = `导入回执已登记：${importStatusLabel(saved.import_status)}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登记导入回执失败";
  } finally {
    savingReceipt.value = false;
  }
}

async function downloadSql(exportJobId: string, dayKey?: string) {
  if (!exportJobId) {
    return;
  }
  downloadingJobId.value = exportJobId;
  error.value = "";
  message.value = "";
  try {
    const blob = await downloadExportJob(exportJobId);
    const job =
      jobs.value.find((item) => item.id === exportJobId) ??
      (exportResult.value?.export_job_id === exportJobId
        ? {
            workspace_code: exportResult.value.workspace_code,
            result_json: { day_key: dayKey ?? selectedReport.value?.day_key ?? "daily" }
          }
        : null);
    const workspaceCode = job?.workspace_code ?? exportResult.value?.workspace_code ?? workspace.currentCode ?? "workspace";
    triggerDownload(blob, `${workspaceCode}_${exportJobDayKey(job, dayKey)}_company_sql.sql`);
    message.value = "SQL 下载已开始";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "下载 SQL 失败";
  } finally {
    downloadingJobId.value = "";
  }
}

async function copySqlPreview() {
  if (!exportResult.value) {
    return;
  }
  if (exportResult.value.sql_text_truncated) {
    error.value = "SQL 预览已截断，请使用服务端下载获取完整文件。";
    return;
  }
  copyingSql.value = true;
  error.value = "";
  message.value = "";
  try {
    await navigator.clipboard.writeText(exportResult.value.sql_text);
    message.value = "SQL 已复制";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "复制 SQL 失败";
  } finally {
    copyingSql.value = false;
  }
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function exportJobDayKey(job: { result_json?: Record<string, unknown> } | null, fallback?: string) {
  const dayKey = job?.result_json?.day_key;
  if (typeof dayKey === "string" && dayKey) {
    return dayKey;
  }
  return fallback || "daily";
}

function exportJobSqlSizeLabel(job: ExportJobRecord) {
  const bytes = numberFromResult(job.result_json.sql_size_bytes);
  return bytes === null ? "SQL 大小未记录" : `SQL ${formatBytes(bytes)}`;
}

function numberFromResult(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatBytes(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "未知大小";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "未完成";
  }
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function statusLabel(status: string) {
  return status === "published" ? "已发布" : "草稿";
}

function preflightStatusLabel(status: string) {
  if (status === "passed") {
    return "通过";
  }
  if (status === "failed") {
    return "未通过";
  }
  return status;
}

function batchItemStatusLabel(status: string) {
  if (status === "succeeded") {
    return "成功";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "skipped") {
    return "跳过";
  }
  return status;
}

function importStatusLabel(status: string) {
  if (status === "imported") {
    return "已导入";
  }
  if (status === "partial") {
    return "部分失败";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "pending") {
    return "待回执";
  }
  return status;
}

function resetReceiptForm(job: ExportJobRecord | null) {
  const statementCount = job ? numberFromResult(job.result_json.statement_count) ?? 0 : 0;
  receiptForm.value = {
    target_system: "company_intranet",
    import_status: "imported",
    imported_statement_count: statementCount,
    failed_statement_count: 0,
    notes: "",
    failure_items: [
      {
        sql_sequence: null,
        sql_table: "",
        error_code: "",
        error_message: ""
      }
    ]
  };
}

function addReceiptFailureItem() {
  receiptForm.value.failure_items.push({
    sql_sequence: null,
    sql_table: "",
    error_code: "",
    error_message: ""
  });
}

function removeReceiptFailureItem(index: number) {
  if (receiptForm.value.failure_items.length <= 1) {
    receiptForm.value.failure_items = [
      {
        sql_sequence: null,
        sql_table: "",
        error_code: "",
        error_message: ""
      }
    ];
    return;
  }
  receiptForm.value.failure_items.splice(index, 1);
}

function isCompanySqlJob(job: ExportJobRecord) {
  return job.export_type === "company_sql";
}

function isAnchoredExportJob(job: ExportJobRecord) {
  return pendingExportJobId.value === job.id;
}

function isAnchoredTraceItem(item: CompanySqlTraceRecord["trace_items"][number]) {
  return pendingExportJobItemId.value === item.export_job_item_id;
}

function fieldSourceLabel(source: string) {
  if (source.startsWith("daily_report_items.")) {
    return "编辑覆盖";
  }
  if (source.startsWith("generated_news.")) {
    return "生成稿";
  }
  if (source === "missing") {
    return "缺失";
  }
  return source;
}

function contentFieldLabel(field: string) {
  const labels: Record<string, string> = {
    background: "背景",
    effects: "影响",
    eventSummary: "事件",
    technologyAndInnovation: "技术",
    valueAndImpact: "价值"
  };
  return labels[field] ?? field;
}

function traceContentFieldEntries(item: CompanySqlTraceRecord["trace_items"][number]) {
  return Object.entries(item.content_field_sources);
}

function optionalPreviewLabel(value: string | null) {
  return value && value.trim() ? value : "无";
}

watch(
  () => workspace.currentCode,
  () => {
    selectedReportId.value = "";
    selectedBatchReportIds.value = [];
    exportResult.value = null;
    batchResult.value = null;
    traceResult.value = null;
    receiptJob.value = null;
    importReceipts.value = [];
    anchoredExportLoadedId.value = "";
    void loadExportsPage();
  }
);

watch(selectedReportId, () => {
  preflightResult.value = null;
  exportResult.value = null;
  traceResult.value = null;
});

watch(pendingExportJobId, () => {
  anchoredExportLoadedId.value = "";
  void loadAnchoredExportJob();
});

onMounted(loadExportsPage);
</script>

<template>
  <section class="layout-list">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Company SQL Export</p>
        <h2>SQL 导出</h2>
        <p>只导出已发布日报中 adoption_status = 2 的采信条目，并保持旧内网 SQL 字段兼容。</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadExportsPage">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button
          type="button"
          class="icon-button"
          :disabled="exporting || !selectedReport || selectedReport.status !== 'published'"
          @click="runExport"
        >
          <FileCode2 :size="17" />
          <span>{{ exporting ? "预检/生成中" : "生成 SQL" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="module-grid two">
      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Report Scope</p>
            <h3>选择日报</h3>
          </div>
          <span class="metric-pill">{{ exportableReports.length }} 已发布</span>
        </div>

        <label class="config-field">
          日报
          <select v-model="selectedReportId">
            <option v-for="report in reports" :key="report.id" :value="report.id">
              {{ report.day_key }} · {{ statusLabel(report.status) }} · {{ report.items.length }} 条
            </option>
          </select>
        </label>

        <div v-if="selectedReport" class="scope-panel">
          <div>
            <span>日报标题</span>
            <strong>{{ selectedReport.title }}</strong>
          </div>
          <div>
            <span>采信条目</span>
            <strong>{{ adoptedCount }} / {{ selectedReport.items.length }}</strong>
          </div>
          <div>
            <span>导出规则</span>
            <strong>每条新闻 4 类 SQL，Focus_ID 默认 1</strong>
          </div>
        </div>

        <div class="preflight-actions">
          <button
            type="button"
            class="icon-button secondary"
            :disabled="preflighting || !selectedReport"
            @click="runPreflight()"
          >
            <ShieldCheck :size="17" />
            <span>{{ preflighting ? "预检中" : "运行预检" }}</span>
          </button>
        </div>

        <div v-if="currentPreflight" class="preflight-panel">
          <div class="card-title-row compact">
            <div>
              <p class="eyebrow">Preflight</p>
              <h4>导出前预检 · {{ preflightStatusLabel(currentPreflight.status) }}</h4>
            </div>
            <span class="metric-pill" :class="{ danger: currentPreflight.status !== 'passed' }">
              {{ currentPreflight.error_count }} 错误 · {{ currentPreflight.warning_count }} 提醒
            </span>
          </div>
          <div class="scope-panel">
            <div>
              <span>可导出</span>
              <strong>{{ currentPreflight.eligible_count }}</strong>
            </div>
            <div>
              <span>阻断</span>
              <strong>{{ currentPreflight.blocked_count }}</strong>
            </div>
            <div>
              <span>跳过</span>
              <strong>{{ currentPreflight.skipped_count }}</strong>
            </div>
          </div>
          <div v-if="currentPreflight.errors.length" class="issue-list">
            <strong>报告级错误</strong>
            <p v-for="issue in currentPreflight.errors" :key="issue.code" class="issue-row error">
              {{ issue.message }}
            </p>
          </div>
          <div v-if="currentPreflight.items.length" class="preflight-items">
            <article
              v-for="item in currentPreflight.items"
              :key="item.daily_report_item_id"
              class="preflight-item"
              :class="item.status"
            >
              <div>
                <strong>{{ item.title || "未命名条目" }}</strong>
                <span>{{ item.status }} · adoption {{ item.adoption_status }} · {{ item.category || "未分类" }}</span>
              </div>
              <div v-if="item.errors.length || item.warnings.length" class="issue-list">
                <p v-for="issue in item.errors" :key="`error-${issue.code}-${issue.field}`" class="issue-row error">
                  {{ issue.field }} · {{ issue.message }}
                </p>
                <p v-for="issue in item.warnings" :key="`warning-${issue.code}-${issue.field}`" class="issue-row warning">
                  {{ issue.field }} · {{ issue.message }}
                </p>
              </div>
            </article>
          </div>
        </div>

        <div class="batch-export-panel">
          <div class="card-title-row compact">
            <div>
              <p class="eyebrow">Batch Governance</p>
              <h4>批量导出治理</h4>
            </div>
            <span class="metric-pill">{{ selectedBatchReportIds.length }} 已选</span>
          </div>
          <div class="batch-report-list">
            <label v-for="report in exportableReports" :key="report.id" class="batch-report-option">
              <input v-model="selectedBatchReportIds" type="checkbox" :value="report.id" />
              <span>{{ report.day_key }} · {{ report.items.length }} 条 · {{ report.title }}</span>
            </label>
            <p v-if="exportableReports.length === 0" class="empty-state compact">暂无可批量导出的已发布日报。</p>
          </div>
          <div class="preflight-actions">
            <button
              type="button"
              class="icon-button secondary"
              :disabled="batchExporting || selectedBatchReportIds.length === 0"
              @click="runBatchExport"
            >
              <FileCode2 :size="17" />
              <span>{{ batchExporting ? "批量生成中" : "生成批量 Manifest" }}</span>
            </button>
          </div>
          <div v-if="batchResult" class="batch-result-list">
            <p class="batch-result-summary">
              Manifest {{ batchResult.status }} · {{ batchResult.succeeded_count }} 成功 ·
              {{ batchResult.failed_count }} 失败 · SQL {{ formatBytes(batchResult.total_sql_text_bytes) }}
            </p>
            <article v-for="item in batchResult.items" :key="item.daily_report_id" class="batch-result-row">
              <div>
                <strong>{{ item.day_key || item.daily_report_id }}</strong>
                <span>
                  {{ batchItemStatusLabel(item.status) }} · {{ item.statement_count }} SQL ·
                  {{ formatBytes(item.sql_text_bytes) }}
                </span>
                <small v-if="item.errors.length">{{ item.errors.join("；") }}</small>
              </div>
              <button
                v-if="item.export_job_id"
                type="button"
                class="text-link"
                :disabled="downloadingJobId === item.export_job_id"
                @click="downloadSql(item.export_job_id, item.day_key || undefined)"
              >
                {{ downloadingJobId === item.export_job_id ? "下载中" : "下载" }}
              </button>
            </article>
          </div>
        </div>

        <div class="contract-note">
          <ShieldCheck :size="18" />
          <p>
            SQL 兼容层只读取日报编辑后的最终内容；原始 raw、generated_news 和 daily_report_item
            仍保留追溯链路。
          </p>
        </div>
      </article>

      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Export History</p>
            <h3>导出历史</h3>
          </div>
          <span class="metric-pill">{{ jobs.length }} jobs</span>
        </div>
        <div class="history-list">
          <article
            v-for="job in jobs"
            :key="job.id"
            class="history-row export-job-row"
            :class="{ anchored: isAnchoredExportJob(job) }"
            :aria-current="isAnchoredExportJob(job) ? 'true' : undefined"
          >
            <strong>{{ job.export_type }}</strong>
            <span>{{ job.status }} · {{ formatDateTime(job.completed_at || job.created_at) }}</span>
            <span>{{ exportJobSqlSizeLabel(job) }}</span>
            <span v-if="job.latest_import_receipt">
              导入：{{ importStatusLabel(job.latest_import_receipt.import_status) }} ·
              {{ job.latest_import_receipt.target_system }}
            </span>
            <small>{{ job.id }}</small>
            <div class="history-actions">
              <button
                v-if="isCompanySqlJob(job)"
                type="button"
                class="text-link"
                :disabled="loadingTraceJobId === job.id"
                @click="loadTrace(job)"
              >
                {{ loadingTraceJobId === job.id ? "加载中" : "查看追溯" }}
              </button>
              <button
                v-if="isCompanySqlJob(job)"
                type="button"
                class="text-link"
                :disabled="downloadingJobId === job.id"
                @click="downloadSql(job.id)"
              >
                {{ downloadingJobId === job.id ? "下载中" : "下载 SQL" }}
              </button>
              <button
                v-if="isCompanySqlJob(job)"
                type="button"
                class="text-link"
                :disabled="loadingReceiptJobId === job.id"
                @click="loadImportReceipts(job)"
              >
                {{ loadingReceiptJobId === job.id ? "加载中" : "导入回执" }}
              </button>
              <span v-if="!isCompanySqlJob(job)" class="history-note">Manifest 记录</span>
            </div>
          </article>
          <p v-if="!loading && jobs.length === 0" class="empty-state">暂无导出历史，先选择已发布日报生成公司 SQL 预览。</p>
        </div>
      </article>
    </section>

    <section v-if="receiptJob" class="module-card import-receipt-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Import Receipt</p>
          <h3>内网导入回执</h3>
          <p>{{ receiptJob.id }} · {{ exportJobSqlSizeLabel(receiptJob) }}</p>
        </div>
        <span class="metric-pill">{{ importReceipts.length }} 条回执</span>
      </div>

      <div class="scope-panel">
        <div>
          <span>最新状态</span>
          <strong>
            {{
              receiptJob.latest_import_receipt
                ? importStatusLabel(receiptJob.latest_import_receipt.import_status)
                : "待回执"
            }}
          </strong>
        </div>
        <div>
          <span>目标系统</span>
          <strong>{{ receiptJob.latest_import_receipt?.target_system || "未记录" }}</strong>
        </div>
        <div>
          <span>失败语句</span>
          <strong>{{ receiptJob.latest_import_receipt?.failed_statement_count ?? 0 }}</strong>
        </div>
      </div>

      <div class="contract-note">
        <ShieldCheck :size="18" />
        <p>
          自动回调：POST /api/exports/{{ receiptJob.id }}/import-receipts/callback。该接口只接受 Bearer
          service token，页面不展示 token。
        </p>
      </div>

      <form class="receipt-form" @submit.prevent="saveImportReceipt">
        <div class="form-grid">
          <label class="config-field">
            目标系统
            <input v-model="receiptForm.target_system" type="text" />
          </label>
          <label class="config-field">
            导入状态
            <select v-model="receiptForm.import_status">
              <option value="imported">已导入</option>
              <option value="partial">部分失败</option>
              <option value="failed">失败</option>
              <option value="pending">待回执</option>
            </select>
          </label>
          <label class="config-field">
            已导入语句
            <input v-model.number="receiptForm.imported_statement_count" min="0" type="number" />
          </label>
          <label class="config-field">
            失败语句
            <input v-model.number="receiptForm.failed_statement_count" min="0" type="number" />
          </label>
        </div>

        <div v-if="receiptForm.import_status !== 'imported'" class="receipt-failure-editor">
          <div class="card-title-row compact">
            <div>
              <p class="eyebrow">Failures</p>
              <h4>失败语句</h4>
            </div>
            <button type="button" class="text-link" @click="addReceiptFailureItem">添加失败项</button>
          </div>
          <article v-for="(failure, index) in receiptForm.failure_items" :key="index" class="receipt-failure-row">
            <label class="config-field">
              SQL 序号
              <input v-model.number="failure.sql_sequence" min="1" type="number" />
            </label>
            <label class="config-field">
              SQL 表
              <input v-model="failure.sql_table" type="text" placeholder="ai_journal" />
            </label>
            <label class="config-field">
              错误码
              <input v-model="failure.error_code" type="text" />
            </label>
            <label class="config-field wide">
              错误原因
              <input v-model="failure.error_message" type="text" />
            </label>
            <button type="button" class="text-link" @click="removeReceiptFailureItem(index)">移除</button>
          </article>
        </div>

        <label class="config-field">
          备注
          <textarea v-model="receiptForm.notes" rows="3"></textarea>
        </label>
        <div class="preflight-actions">
          <button type="submit" class="icon-button secondary" :disabled="savingReceipt">
            <ShieldCheck :size="17" />
            <span>{{ savingReceipt ? "登记中" : "登记回执" }}</span>
          </button>
        </div>
      </form>

      <div class="receipt-list">
        <article v-for="receipt in importReceipts" :key="receipt.id" class="receipt-row">
          <div>
            <strong>{{ importStatusLabel(receipt.import_status) }} · {{ receipt.target_system }}</strong>
            <span>
              {{ formatDateTime(receipt.imported_at || receipt.created_at) }} ·
              {{ receipt.imported_statement_count }} 成功 · {{ receipt.failed_statement_count }} 失败
            </span>
            <small v-if="receipt.notes">{{ receipt.notes }}</small>
          </div>
          <div v-if="receipt.failure_items.length" class="issue-list">
            <p v-for="failure in receipt.failure_items" :key="`${receipt.id}-${failure.sql_sequence}-${failure.sql_table}`" class="issue-row error">
              #{{ failure.sql_sequence || "-" }} {{ failure.sql_table || "-" }} · {{ failure.error_message }}
            </p>
          </div>
        </article>
        <p v-if="importReceipts.length === 0" class="empty-state compact">暂无导入回执。</p>
      </div>
    </section>

    <section v-if="exportResult" class="module-card sql-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Preview</p>
          <h3>SQL 预览</h3>
          <p>
            完整文件 {{ formatBytes(exportResult.sql_text_bytes) }} · 当前预览
            {{ formatBytes(exportResult.sql_text_preview_bytes) }}
          </p>
        </div>
        <div class="history-actions">
          <button
            type="button"
            class="icon-button secondary"
            :disabled="copyingSql || exportResult.sql_text_truncated"
            @click="copySqlPreview"
          >
            <Copy :size="17" />
            <span>{{ copyingSql ? "复制中" : exportResult.sql_text_truncated ? "预览已截断" : "复制 SQL" }}</span>
          </button>
          <button
            type="button"
            class="icon-button secondary"
            :disabled="downloadingJobId === exportResult.export_job_id"
            @click="downloadSql(exportResult.export_job_id, selectedReport?.day_key)"
          >
            <DownloadCloud :size="17" />
            <span>{{ downloadingJobId === exportResult.export_job_id ? "下载中" : "下载 SQL" }}</span>
          </button>
        </div>
      </div>
      <p v-if="exportResult.sql_text_truncated" class="form-warning">
        SQL 文件较大，页面只显示截断预览；完整文件请使用服务端下载。
      </p>
      <textarea class="sql-preview" readonly :value="exportResult.sql_text"></textarea>
    </section>

    <section v-if="traceResult" class="module-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Lineage</p>
          <h3>SQL 条目追溯</h3>
        </div>
        <span class="metric-pill">{{ traceResult.statement_count }} statements</span>
      </div>
      <div class="trace-list">
        <article
          v-for="item in traceResult.trace_items"
          :key="item.export_job_item_id"
          class="trace-row export-trace-row"
          :class="{ anchored: isAnchoredTraceItem(item) }"
          :aria-current="isAnchoredTraceItem(item) ? 'true' : undefined"
        >
          <div>
            <strong>#{{ item.sql_sequence }} {{ item.sql_table }}</strong>
            <span>{{ item.export_title || item.generated_title }}</span>
            <small>{{ item.category }} · adoption {{ item.adoption_status }} · {{ item.data_source_name || "未知来源" }}</small>
          </div>
          <div class="trace-id-grid">
            <span>daily {{ item.daily_report_item_id.slice(0, 8) }}</span>
            <span>generated {{ item.generated_news_id.slice(0, 8) }}</span>
            <span>news {{ item.news_item_id.slice(0, 8) }}</span>
            <span>raw {{ item.raw_item_id ? item.raw_item_id.slice(0, 8) : "-" }}</span>
          </div>
          <details class="trace-details">
            <summary>SQL / 字段来源</summary>
            <pre class="trace-sql-excerpt">{{ item.sql_excerpt }}</pre>
            <div class="trace-source-grid">
              <span>标题：{{ fieldSourceLabel(item.title_source) }}</span>
              <span>摘要：{{ fieldSourceLabel(item.summary_source) }}</span>
              <span>关键点：{{ fieldSourceLabel(item.key_points_source) }}</span>
              <span>编辑覆盖：{{ item.editor_override_fields.length ? item.editor_override_fields.join(", ") : "无" }}</span>
            </div>
            <div class="trace-content-sources">
              <span v-for="entry in traceContentFieldEntries(item)" :key="entry[0]">
                {{ contentFieldLabel(entry[0]) }}：{{ fieldSourceLabel(entry[1]) }}
              </span>
            </div>
            <div class="trace-diff-list">
              <article v-for="diff in item.field_diffs" :key="diff.field" class="trace-diff-row">
                <div>
                  <strong>{{ diff.label }}</strong>
                  <span>{{ fieldSourceLabel(diff.export_source) }}{{ diff.truncated ? " · 已截断" : "" }}</span>
                </div>
                <p>导出：{{ optionalPreviewLabel(diff.export_value_preview) }}</p>
                <p>编辑：{{ optionalPreviewLabel(diff.editor_value_preview) }}</p>
                <p>生成：{{ optionalPreviewLabel(diff.generated_value_preview) }}</p>
                <p>来源：{{ optionalPreviewLabel(diff.raw_value_preview) }}</p>
              </article>
            </div>
          </details>
        </article>
      </div>
    </section>
  </section>
</template>
