<script setup lang="ts">
import { Archive, Database, FileText, GitBranch, RefreshCw, Search, TriangleAlert } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";

import {
  fetchHistoricalReportDetail,
  fetchHistoricalReports,
  fetchHistoricalReportSummary,
  fetchLegacyImportGaps,
  fetchLegacyImportSummary,
  type HistoricalReportDetailRecord,
  type HistoricalReportListItem,
  type HistoricalReportSummaryRecord,
  type LegacyImportGapItemRecord,
  type LegacyImportMetricRecord,
  type LegacyImportSummaryRecord
} from "../api/operations";

const summary = ref<HistoricalReportSummaryRecord | null>(null);
const legacySummary = ref<LegacyImportSummaryRecord | null>(null);
const legacyGaps = ref<LegacyImportGapItemRecord[]>([]);
const reports = ref<HistoricalReportListItem[]>([]);
const selected = ref<HistoricalReportDetailRecord | null>(null);
const loading = ref(false);
const detailLoading = ref(false);
const error = ref("");

const filters = ref({
  reportType: "",
  status: "",
  startDate: "",
  endDate: "",
  query: "",
  unresolvedOnly: false
});

const selectedRefs = computed(() => {
  const refs = selected.value?.source_refs_json ?? {};
  const resolved = Array.isArray(refs.resolved) ? refs.resolved : [];
  const unresolved = Array.isArray(refs.unresolved) ? refs.unresolved : [];
  return { resolved, unresolved };
});

async function loadReports() {
  loading.value = true;
  error.value = "";
  try {
    const [nextSummary, nextReports, nextLegacySummary, nextLegacyGaps] = await Promise.all([
      fetchHistoricalReportSummary(),
      fetchHistoricalReports({
        reportType: filters.value.reportType || undefined,
        status: filters.value.status || undefined,
        startDate: filters.value.startDate || undefined,
        endDate: filters.value.endDate || undefined,
        query: filters.value.query || undefined,
        hasUnresolvedRefs: filters.value.unresolvedOnly ? true : null
      }),
      fetchLegacyImportSummary(),
      fetchLegacyImportGaps({ limit: 8 })
    ]);
    summary.value = nextSummary;
    legacySummary.value = nextLegacySummary;
    legacyGaps.value = nextLegacyGaps;
    reports.value = nextReports;
    if (nextReports.length > 0) {
      await selectReport(nextReports[0].id);
    } else {
      selected.value = null;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载历史归档失败";
  } finally {
    loading.value = false;
  }
}

async function selectReport(id: string) {
  detailLoading.value = true;
  error.value = "";
  try {
    selected.value = await fetchHistoricalReportDetail(id);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载历史报告详情失败";
  } finally {
    detailLoading.value = false;
  }
}

function formatDate(value: string | null) {
  if (!value) return "未记录";
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function compactJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function metricStatus(metric: LegacyImportMetricRecord) {
  if (metric.status === "complete") return "完成";
  if (metric.status === "partial") return "部分";
  return "待导入";
}

function metricPercent(metric: LegacyImportMetricRecord) {
  return `${Math.min(Math.round(metric.coverage_rate * 100), 100)}%`;
}

function gapKindLabel(item: LegacyImportGapItemRecord) {
  if (item.kind === "entity_milestones") return "实体事件";
  if (item.kind === "historical_feedback") return "历史反馈";
  return "历史报告";
}

onMounted(loadReports);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Report Library</p>
        <h2>历史报告库</h2>
        <p>本工作台的报告资产库：从旧系统或历史批次导入的日报/周报在这里长期可查，每条可追溯到导入前的原始记录。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadReports">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>

    <section class="module-card legacy-import-panel">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Import QA</p>
          <h3>旧系统导入验收</h3>
        </div>
        <span class="metric-pill">{{ legacySummary ? formatDate(legacySummary.generated_at) : "未加载" }}</span>
      </div>

      <div class="legacy-metric-grid">
        <article v-for="metric in legacySummary?.metrics ?? []" :key="metric.key" class="legacy-metric">
          <div>
            <span>{{ metric.label }}</span>
            <strong>{{ metric.actual }} / {{ metric.expected }}</strong>
          </div>
          <small :class="metric.status">{{ metricStatus(metric) }} · 缺 {{ metric.missing }}</small>
          <div class="legacy-progress" aria-hidden="true">
            <span :style="{ width: metricPercent(metric) }"></span>
          </div>
        </article>
      </div>

      <div class="legacy-ref-grid">
        <div>
          <Database :size="17" />
          <span>报告引用</span>
          <strong>{{ legacySummary?.report_refs.resolved ?? 0 }}/{{ legacySummary?.report_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.report_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <Archive :size="17" />
          <span>事件素材引用</span>
          <strong>{{ legacySummary?.milestone_article_refs.resolved ?? 0 }}/{{ legacySummary?.milestone_article_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.milestone_article_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <GitBranch :size="17" />
          <span>事件报告引用</span>
          <strong>{{ legacySummary?.milestone_report_refs.resolved ?? 0 }}/{{ legacySummary?.milestone_report_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.milestone_report_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <FileText :size="17" />
          <span>反馈素材引用</span>
          <strong>{{ legacySummary?.feedback_article_refs.resolved ?? 0 }}/{{ legacySummary?.feedback_article_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.feedback_article_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <TriangleAlert :size="17" />
          <span>缺口条目</span>
          <strong>{{ legacySummary?.gap_item_count ?? 0 }}</strong>
          <small>引用 {{ legacySummary?.total_unresolved_refs ?? 0 }}</small>
        </div>
      </div>

      <div class="legacy-gap-list">
        <article v-for="gap in legacyGaps" :key="`${gap.kind}-${gap.id}`">
          <span>{{ gapKindLabel(gap) }} · legacy {{ gap.legacy_id }}</span>
          <strong>{{ gap.title }}</strong>
          <small>{{ gap.ref_type }} · unresolved {{ gap.unresolved_count }}</small>
        </article>
        <p v-if="legacyGaps.length === 0" class="empty-state small">
          暂无未解析引用缺口。真实导入完成后，这里用于抽查报告和实体事件的旧引用映射。
        </p>
      </div>
    </section>

    <section class="historical-summary-grid">
      <article class="module-card compact">
        <p class="eyebrow">Reports</p>
        <strong>{{ summary?.total ?? 0 }}</strong>
        <span>归档报告</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Types</p>
        <strong>{{ summary?.by_report_type.daily ?? 0 }} / {{ summary?.by_report_type.weekly ?? 0 }}</strong>
        <span>日报 / 周报</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Refs</p>
        <strong>{{ summary?.unresolved_ref_count ?? 0 }}</strong>
        <span>未解析引用</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Range</p>
        <strong>{{ summary?.earliest_period_start_at ? formatDate(summary.earliest_period_start_at).slice(0, 10) : "暂无" }}</strong>
        <span>{{ summary?.latest_period_start_at ? formatDate(summary.latest_period_start_at).slice(0, 10) : "待导入" }}</span>
      </article>
    </section>

    <section class="module-card historical-filters">
      <label>
        <span>类型</span>
        <select v-model="filters.reportType">
          <option value="">全部</option>
          <option value="daily">daily</option>
          <option value="weekly">weekly</option>
        </select>
      </label>
      <label>
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option value="published_imported">published_imported</option>
          <option value="imported">imported</option>
        </select>
      </label>
      <label>
        <span>开始日期</span>
        <input v-model="filters.startDate" type="date" />
      </label>
      <label>
        <span>结束日期</span>
        <input v-model="filters.endDate" type="date" />
      </label>
      <label class="historical-search">
        <span>搜索</span>
        <span>
          <Search :size="15" />
          <input v-model.trim="filters.query" type="search" placeholder="标题或正文" />
        </span>
      </label>
      <label class="historical-check">
        <input v-model="filters.unresolvedOnly" type="checkbox" />
        <span>仅未解析引用</span>
      </label>
      <button type="button" class="icon-button" :disabled="loading" @click="loadReports">
        <Search :size="16" />
        <span>筛选</span>
      </button>
    </section>

    <section class="module-grid historical-layout">
      <section class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Archive List</p><h3>历史报告</h3></div>
          <span class="metric-pill">{{ reports.length }} items</span>
        </div>
        <article
          v-for="report in reports"
          :key="report.id"
          class="ops-row historical-row"
          :class="{ selected: selected?.id === report.id }"
          @click="selectReport(report.id)"
        >
          <div class="feed-icon indigo"><FileText :size="18" /></div>
          <div>
            <h3>{{ report.title }}</h3>
            <p>{{ report.report_type }} · {{ report.status }} · {{ formatDate(report.period_start_at) }}</p>
            <p class="historical-excerpt">{{ report.content_excerpt || "暂无正文摘要" }}</p>
            <div class="coverage-metrics">
              <span>legacy {{ report.legacy_id }}</span>
              <span>resolved {{ report.resolved_ref_count }}</span>
              <span :class="{ danger: report.unresolved_ref_count > 0 }">unresolved {{ report.unresolved_ref_count }}</span>
            </div>
          </div>
          <TriangleAlert v-if="report.unresolved_ref_count > 0" :size="18" class="warning-icon" />
        </article>
        <p v-if="!loading && reports.length === 0" class="empty-state">
          这个工作台还没有历史报告。报告库用于沉淀迁移进来的旧系统资产：运行导入脚本
          （scripts/tech_insight_loop_import_verify.py --execute）后，旧日报/周报会出现在这里，
          支持按日期、类型、关键词检索正文，并在上方验收面板核对导入覆盖率与旧引用缺口。
        </p>
      </section>

      <section class="module-card historical-detail">
        <div v-if="selected" class="historical-detail-body">
          <div class="card-title-row">
            <div>
              <p class="eyebrow">{{ selected.report_type }} · {{ selected.status }}</p>
              <h3>{{ selected.title }}</h3>
            </div>
            <span class="metric-pill">{{ detailLoading ? "loading" : selected.legacy_id }}</span>
          </div>

          <div class="coverage-strip">
            <span>{{ formatDate(selected.period_start_at) }}</span>
            <span>{{ formatDate(selected.period_end_at) }}</span>
            <span>resolved {{ selected.resolved_ref_count }}</span>
            <span :class="{ danger: selected.unresolved_ref_count > 0 }">unresolved {{ selected.unresolved_ref_count }}</span>
          </div>

          <article class="historical-content">
            <pre>{{ selected.content }}</pre>
          </article>

          <section class="historical-ref-panel">
            <div>
              <p class="eyebrow">Resolved refs</p>
              <pre>{{ compactJson(selectedRefs.resolved) }}</pre>
            </div>
            <div>
              <p class="eyebrow">Unresolved refs</p>
              <pre>{{ compactJson(selectedRefs.unresolved) }}</pre>
            </div>
          </section>
        </div>
        <div v-else class="historical-empty-detail">
          <Archive :size="36" />
          <h3>没有可查看的历史报告</h3>
          <p>历史归档是只读视图，不会影响当前日报、推荐或 SQL 导出。</p>
        </div>
      </section>
    </section>
  </section>
</template>

<style scoped>
.historical-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.legacy-import-panel {
  display: grid;
  gap: 16px;
  margin-bottom: 16px;
}

.legacy-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.legacy-metric {
  display: grid;
  gap: 8px;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #f8fafc;
}

.legacy-metric div:first-child {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.legacy-metric span,
.legacy-ref-grid span {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.legacy-metric strong,
.legacy-ref-grid strong {
  color: #0f172a;
  font-size: 18px;
}

.legacy-metric small,
.legacy-ref-grid small,
.legacy-gap-list small {
  color: #64748b;
  font-weight: 800;
}

.legacy-metric small.complete {
  color: #047857;
}

.legacy-metric small.partial {
  color: #b45309;
}

.legacy-progress {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.legacy-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #4f46e5;
}

.legacy-ref-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.legacy-ref-grid > div {
  display: grid;
  gap: 4px;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.legacy-ref-grid svg {
  color: #4f46e5;
}

.legacy-gap-list {
  display: grid;
  gap: 8px;
}

.legacy-gap-list article {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr) 150px;
  align-items: center;
  gap: 10px;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fffbeb;
}

.legacy-gap-list article strong {
  overflow: hidden;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-state.small {
  min-height: auto;
  padding: 8px 0;
  text-align: left;
}

.historical-summary-grid strong {
  display: block;
  color: #0f172a;
  font-size: 26px;
  line-height: 1.1;
}

.historical-summary-grid span {
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.historical-filters {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr)) auto;
  align-items: end;
  gap: 12px;
  margin-bottom: 18px;
}

.historical-filters label {
  display: grid;
  gap: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 800;
}

.historical-filters input,
.historical-filters select {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
  color: #0f172a;
  font: inherit;
}

.historical-search > span:last-child {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 0 10px;
  background: #fff;
}

.historical-search input {
  border: 0;
  padding-inline: 0;
}

.historical-check {
  align-self: center;
  display: flex !important;
  grid-template-columns: none !important;
  flex-direction: row;
  align-items: center;
  min-height: 42px;
}

.historical-check input {
  width: auto;
}

.historical-layout {
  grid-template-columns: minmax(340px, 0.9fr) minmax(0, 1.1fr);
  align-items: start;
}

.historical-row {
  cursor: pointer;
  align-items: start;
}

.historical-row.selected {
  border-color: #818cf8;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.historical-excerpt {
  display: -webkit-box;
  margin: 8px 0 !important;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.warning-icon,
.danger {
  color: #b45309 !important;
}

.historical-detail {
  position: sticky;
  top: 92px;
  min-height: 560px;
}

.historical-content {
  max-height: 420px;
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}

.historical-content pre,
.historical-ref-panel pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1e293b;
  font: 13px/1.7 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.historical-content pre {
  padding: 16px;
}

.historical-ref-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.historical-ref-panel > div {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.historical-empty-detail {
  display: grid;
  place-items: center;
  min-height: 440px;
  text-align: center;
  color: #64748b;
}

.historical-empty-detail h3,
.historical-empty-detail p {
  margin: 0;
}

@media (max-width: 1200px) {
  .historical-summary-grid,
  .legacy-metric-grid,
  .legacy-ref-grid,
  .historical-layout,
  .historical-ref-panel {
    grid-template-columns: 1fr;
  }

  .legacy-gap-list article {
    grid-template-columns: 1fr;
  }

  .historical-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .historical-detail {
    position: static;
  }
}
</style>
