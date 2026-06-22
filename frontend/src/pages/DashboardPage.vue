<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { fetchHealth, type HealthResponse } from "../api/health";
import { fetchDailyReports, fetchWeeklyReports, type DailyReportRecord, type WeeklyReportRecord } from "../api/reports";
import { fetchSources, type DataSourceRecord } from "../api/sources";
import { useWorkspaceStore } from "../stores/workspace";

const health = ref<HealthResponse | null>(null);
const sources = ref<DataSourceRecord[]>([]);
const dailyReports = ref<DailyReportRecord[]>([]);
const weeklyReports = ref<WeeklyReportRecord[]>([]);
const loading = ref(false);
const error = ref("");
const workspace = useWorkspaceStore();

const enabledSourceCount = computed(() => sources.value.filter((source) => source.workspace_link_enabled).length);
const metadataOnlyCount = computed(() => sources.value.filter((source) => source.needs_entry || source.metadata_only).length);
const fetchableSourceCount = computed(() =>
  sources.value.filter(
    (source) =>
      source.workspace_link_enabled &&
      source.enabled &&
      ["rss", "paper_rss", "page_manual", "page_monitor"].includes(source.source_type)
  ).length
);
const latestDailyReport = computed(() => dailyReports.value[0] ?? null);
const latestWeeklyReport = computed(() => weeklyReports.value[0] ?? null);

const metrics = computed(() => [
  {
    label: "共享源",
    value: loading.value && sources.value.length === 0 ? "..." : String(sources.value.length),
    detail: `${enabledSourceCount.value} 已启用 · ${metadataOnlyCount.value} 待补入口`
  },
  {
    label: "可抓取源",
    value: loading.value && sources.value.length === 0 ? "..." : String(fetchableSourceCount.value),
    detail: "RSS / 论文 RSS / 页面源"
  },
  {
    label: "最新日报",
    value: latestDailyReport.value?.day_key ?? "暂无",
    detail: latestDailyReport.value
      ? `${statusLabel(latestDailyReport.value.status)} · ${latestDailyReport.value.items.length} 条`
      : "先生成或回填日报"
  },
  {
    label: "最新周报",
    value: latestWeeklyReport.value?.week_key ?? "暂无",
    detail: latestWeeklyReport.value
      ? `${statusLabel(latestWeeklyReport.value.status)} · ${latestWeeklyReport.value.items.length} 条`
      : "从已发布日报生成"
  }
]);

onMounted(async () => {
  await loadDashboard();
});

async function loadDashboard() {
  loading.value = true;
  error.value = "";
  try {
    const workspaceCode = workspace.currentCode || "planning_intel";
    const [healthResult, sourceResult, dailyResult, weeklyResult] = await Promise.all([
      fetchHealth(),
      fetchSources(workspaceCode),
      fetchDailyReports(workspaceCode),
      fetchWeeklyReports(workspaceCode)
    ]);
    health.value = healthResult;
    sources.value = sourceResult;
    dailyReports.value = dailyResult;
    weeklyReports.value = weeklyResult;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载工作台概览失败";
  } finally {
    loading.value = false;
  }
}

function statusLabel(status: string) {
  return status === "published" ? "已发布" : "草稿";
}
</script>

<template>
  <section class="dashboard-grid">
    <article v-for="metric in metrics" :key="metric.label" class="metric-card">
      <span>{{ metric.label }}</span>
      <strong>{{ metric.value }}</strong>
      <small>{{ metric.detail }}</small>
    </article>
  </section>

  <section class="work-band">
    <div>
      <p class="eyebrow">当前工作台状态</p>
      <h2>源治理、日报周报与归档闭环</h2>
      <p>
        当前工作台：{{ workspace.current?.name }}。系统已完成源治理融合、抓取覆盖率、候选池、
        推荐准入评分、日报采信、周报板块管理、历史归档、实体大事记、质量归档和公司 SQL 导出。
        如果日报或周报为空，优先检查当前数据库是否已经生成或回填对应日期的数据，再检查抓取覆盖率和推荐链路。
      </p>
      <p v-if="error" class="form-error">{{ error }}</p>
    </div>

    <div class="health-panel">
      <span>后端健康状态</span>
      <strong v-if="loading">检查中</strong>
      <strong v-else-if="health">{{ health.database.status }}</strong>
      <strong v-else>未连接</strong>
      <small v-if="health">{{ health.service }} · {{ health.environment }}</small>
      <small v-else-if="error">{{ error }}</small>
    </div>
  </section>
</template>
