<script setup lang="ts">
import { DownloadCloud, FileCode2, RefreshCw, ShieldCheck } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import {
  createCompanySqlExport,
  fetchCompanySqlTrace,
  fetchExportJobs,
  type CompanySqlTraceRecord,
  type CompanySqlExportRecord,
  type ExportJobRecord
} from "../api/exports";
import { fetchDailyReports, type DailyReportRecord } from "../api/reports";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const reports = ref<DailyReportRecord[]>([]);
const jobs = ref<ExportJobRecord[]>([]);
const selectedReportId = ref("");
const exportResult = ref<CompanySqlExportRecord | null>(null);
const traceResult = ref<CompanySqlTraceRecord | null>(null);
const loadingTraceJobId = ref("");
const loading = ref(false);
const exporting = ref(false);
const error = ref("");
const message = ref("");

const selectedReport = computed(
  () => reports.value.find((report) => report.id === selectedReportId.value) ?? reports.value[0] ?? null
);

const exportableReports = computed(() => reports.value.filter((report) => report.status === "published"));
const adoptedCount = computed(
  () => selectedReport.value?.items.filter((item) => item.adoption_status === 2).length ?? 0
);

async function loadExportsPage() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const [nextReports, nextJobs] = await Promise.all([
      fetchDailyReports(workspace.currentCode),
      fetchExportJobs()
    ]);
    reports.value = nextReports;
    jobs.value = nextJobs.filter((job) => job.workspace_code === workspace.currentCode);
    if (!selectedReportId.value) {
      selectedReportId.value = exportableReports.value[0]?.id ?? nextReports[0]?.id ?? "";
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载 SQL 导出页失败";
  } finally {
    loading.value = false;
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

function downloadSql() {
  if (!exportResult.value) {
    return;
  }
  const blob = new Blob([exportResult.value.sql_text], { type: "text/sql;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${exportResult.value.workspace_code}_${selectedReport.value?.day_key ?? "daily"}_company_sql.sql`;
  link.click();
  URL.revokeObjectURL(url);
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

watch(
  () => workspace.currentCode,
  () => {
    selectedReportId.value = "";
    exportResult.value = null;
    traceResult.value = null;
    void loadExportsPage();
  }
);

onMounted(loadExportsPage);
</script>

<template>
  <section class="module-page">
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
          <span>{{ exporting ? "生成中" : "生成 SQL" }}</span>
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
          <article v-for="job in jobs" :key="job.id" class="history-row">
            <strong>{{ job.export_type }}</strong>
            <span>{{ job.status }} · {{ formatDateTime(job.completed_at || job.created_at) }}</span>
            <small>{{ job.id }}</small>
            <button type="button" class="text-link" :disabled="loadingTraceJobId === job.id" @click="loadTrace(job)">
              {{ loadingTraceJobId === job.id ? "加载中" : "查看追溯" }}
            </button>
          </article>
          <p v-if="!loading && jobs.length === 0" class="empty-state">暂无导出历史。</p>
        </div>
      </article>
    </section>

    <section v-if="exportResult" class="module-card sql-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Preview</p>
          <h3>SQL 预览</h3>
        </div>
        <button type="button" class="icon-button secondary" @click="downloadSql">
          <DownloadCloud :size="17" />
          <span>下载 SQL</span>
        </button>
      </div>
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
        <article v-for="item in traceResult.trace_items" :key="`${item.sql_sequence}-${item.sql_table}`" class="trace-row">
          <div>
            <strong>#{{ item.sql_sequence }} {{ item.sql_table }}</strong>
            <span>{{ item.generated_title }}</span>
            <small>{{ item.category }} · adoption {{ item.adoption_status }} · {{ item.data_source_name || "未知来源" }}</small>
          </div>
          <div class="trace-id-grid">
            <span>daily {{ item.daily_report_item_id.slice(0, 8) }}</span>
            <span>generated {{ item.generated_news_id.slice(0, 8) }}</span>
            <span>news {{ item.news_item_id.slice(0, 8) }}</span>
            <span>raw {{ item.raw_item_id ? item.raw_item_id.slice(0, 8) : "-" }}</span>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>
