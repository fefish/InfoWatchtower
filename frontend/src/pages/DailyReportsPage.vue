<script setup lang="ts">
import { CheckCircle2, FileText, RefreshCw, Sparkles } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import {
  createRecommendationRun,
  fetchDailyReports,
  publishDailyReport,
  type DailyReportRecord
} from "../api/reports";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const reports = ref<DailyReportRecord[]>([]);
const loading = ref(false);
const generating = ref(false);
const publishingId = ref("");
const error = ref("");
const message = ref("");
const selectedReportId = ref("");

const selectedReport = computed(() => {
  return reports.value.find((report) => report.id === selectedReportId.value) ?? reports.value[0] ?? null;
});

async function loadReports() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    reports.value = await fetchDailyReports(workspace.currentCode);
    if (!reports.value.some((report) => report.id === selectedReportId.value)) {
      selectedReportId.value = reports.value[0]?.id ?? "";
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载日报失败";
  } finally {
    loading.value = false;
  }
}

async function generateDraft() {
  if (!workspace.currentCode) {
    return;
  }
  generating.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await createRecommendationRun({
      workspace_code: workspace.currentCode,
      limit: 15,
      source_daily_limit: 2,
      create_daily_draft: true
    });
    message.value = `已生成草稿：候选 ${result.candidates_total}，采信 ${result.selected_total}，成稿 ${result.generated_total}`;
    await loadReports();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "生成日报草稿失败";
  } finally {
    generating.value = false;
  }
}

async function publishReport(report: DailyReportRecord) {
  publishingId.value = report.id;
  error.value = "";
  message.value = "";
  try {
    await publishDailyReport(report.id);
    message.value = `已发布：${report.title}`;
    await loadReports();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "发布日报失败";
  } finally {
    publishingId.value = "";
  }
}

function displayTitle(item: DailyReportRecord["items"][number]) {
  return item.editor_title || item.generated_news.title;
}

function displaySummary(item: DailyReportRecord["items"][number]) {
  return item.editor_summary || item.generated_news.summary;
}

function statusLabel(status: string) {
  return status === "published" ? "已发布" : "草稿";
}

onMounted(loadReports);

watch(
  () => workspace.currentCode,
  () => {
    void loadReports();
  }
);
</script>

<template>
  <section class="report-command">
    <div>
      <p class="eyebrow">阶段 5 · Recommendation to Draft</p>
      <h2>日报</h2>
      <p>从去重 winner 生成推荐 run、结构化稿和日报草稿。</p>
    </div>
    <div class="toolbar-actions">
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadReports">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
      <button type="button" class="icon-button" :disabled="generating" @click="generateDraft">
        <Sparkles :size="18" />
        <span>{{ generating ? "生成中" : "生成日报草稿" }}</span>
      </button>
    </div>
  </section>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="message" class="form-success">{{ message }}</p>

  <section v-if="selectedReport" class="daily-report-layout">
    <aside class="report-timeline">
      <p class="eyebrow">Reports</p>
      <button
        v-for="report in reports"
        :key="report.id"
        type="button"
    class="report-tab"
        :class="{ active: report.id === selectedReport.id }"
        @click="selectedReportId = report.id"
      >
        <strong>{{ report.day_key }}</strong>
        <span>{{ statusLabel(report.status) }} · {{ report.items.length }} 条</span>
      </button>
    </aside>

    <article class="daily-report-card">
      <header class="daily-report-header">
        <div>
          <p class="eyebrow">{{ selectedReport.workspace_code }} · {{ selectedReport.domain_code }}</p>
          <h3>{{ selectedReport.title }}</h3>
          <p>{{ selectedReport.summary }}</p>
        </div>
        <button
          v-if="selectedReport.status !== 'published'"
          type="button"
          class="icon-button secondary"
          :disabled="publishingId === selectedReport.id"
          @click="publishReport(selectedReport)"
        >
          <CheckCircle2 :size="18" />
          <span>{{ publishingId === selectedReport.id ? "发布中" : "发布" }}</span>
        </button>
      </header>

      <div class="daily-item-list">
        <article v-for="item in selectedReport.items" :key="item.id" class="daily-item">
          <div class="daily-item-meta">
            <span>{{ item.generated_news.category }}</span>
            <span>采信 {{ item.adoption_status }}</span>
            <span>{{ item.reaction_count }} 赞</span>
            <span>{{ item.comment_count }} 评论</span>
          </div>
          <h4>{{ displayTitle(item) }}</h4>
          <p>{{ displaySummary(item) }}</p>
          <a v-if="item.generated_news.source_url" :href="item.generated_news.source_url" target="_blank">
            {{ item.generated_news.source_url }}
          </a>
        </article>
      </div>
    </article>
  </section>

  <section v-else class="placeholder-panel">
    <div>
      <p class="eyebrow">日报草稿</p>
      <h2>{{ loading ? "正在加载" : "还没有日报" }}</h2>
      <p>先完成抓取、标准化和去重，然后点击“生成日报草稿”。</p>
    </div>
    <FileText :size="42" />
  </section>
</template>
