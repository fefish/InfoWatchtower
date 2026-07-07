<script setup lang="ts">
import { CheckCircle2, ClipboardCheck, ListFilter, Plus, RefreshCw, Search, TriangleAlert, XCircle } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createRequirement,
  fetchHistoricalFeedbackItems,
  fetchHistoricalJobRuns,
  fetchLegacyImportGaps,
  fetchQualityArchiveSummary,
  type HistoricalFeedbackItemRecord,
  type HistoricalJobRunRecord,
  type LegacyImportGapItemRecord,
  type QualityArchiveSummaryRecord
} from "../api/operations";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const workspace = useWorkspaceStore();
const session = useSessionStore();
const summary = ref<QualityArchiveSummaryRecord | null>(null);
const feedbackItems = ref<HistoricalFeedbackItemRecord[]>([]);
const jobRuns = ref<HistoricalJobRunRecord[]>([]);
const gaps = ref<LegacyImportGapItemRecord[]>([]);
const loading = ref(false);
const savingFeedbackId = ref("");
const error = ref("");
const message = ref("");

const feedbackFilters = ref({
  feedbackKind: "",
  query: "",
  unresolvedOnly: false
});
const jobFilters = ref({
  status: "",
  query: ""
});

const feedbackTypeEntries = computed(() => topEntries(summary.value?.by_feedback_type));
const qualityReasonEntries = computed(() => topEntries(summary.value?.by_quality_reason));
const jobTypeEntries = computed(() => topEntries(summary.value?.by_job_type));
const jobStatusEntries = computed(() => topEntries(summary.value?.by_job_status));
const pendingFeedbackId = computed(() => routeQueryString(route.query.feedback_id));
const canCreateRequirement = computed(() => {
  if (session.user?.roles.includes("super_admin")) {
    return true;
  }
  return ["owner", "admin"].includes(workspace.current?.current_user_workspace_role ?? "");
});

async function loadArchive() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const [nextSummary, nextFeedback, nextJobs, nextGaps] = await Promise.all([
      fetchQualityArchiveSummary(workspace.currentCode),
      fetchHistoricalFeedbackItems({
        workspaceCode: workspace.currentCode,
        feedbackKind: feedbackFilters.value.feedbackKind || undefined,
        query: feedbackFilters.value.query || undefined,
        hasUnresolvedRefs: feedbackFilters.value.unresolvedOnly ? true : null
      }),
      fetchHistoricalJobRuns({
        workspaceCode: workspace.currentCode,
        status: jobFilters.value.status || undefined,
        query: jobFilters.value.query || undefined
      }),
      fetchLegacyImportGaps({ workspaceCode: workspace.currentCode, kind: "historical_feedback", limit: 8 })
    ]);
    summary.value = nextSummary;
    feedbackItems.value = nextFeedback;
    jobRuns.value = nextJobs;
    gaps.value = nextGaps;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载质量归档失败";
  } finally {
    loading.value = false;
  }
}

function topEntries(value: Record<string, number> | undefined, limit = 6) {
  return Object.entries(value ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);
}

function routeQueryString(value: unknown) {
  return Array.isArray(value) ? String(value[0] ?? "") : String(value ?? "");
}

function isAnchoredFeedback(item: HistoricalFeedbackItemRecord) {
  return pendingFeedbackId.value === item.id;
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

function feedbackKindLabel(value: string) {
  if (value === "quality_feedback") return "质量反馈";
  if (value === "feedback") return "普通反馈";
  return value || "未标注";
}

function refLabel(value: boolean | null) {
  if (value === true) return "已解析";
  if (value === false) return "未解析";
  return "无引用";
}

function jobStatusLabel(value: string) {
  if (value === "completed") return "完成";
  if (value === "failed") return "失败";
  if (value === "running") return "运行中";
  return value || "unknown";
}

async function createRequirementFromFeedback(item: HistoricalFeedbackItemRecord) {
  savingFeedbackId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const reasonText = item.reason || item.comment || item.feedback_type || item.legacy_id;
    const created = await createRequirement({
      workspace_code: item.workspace_code,
      title: `复盘${feedbackKindLabel(item.feedback_kind)}：${reasonText}`,
      description: `由历史质量归档触发。\n\n用户：${item.user_name || "unknown"}\n类型：${item.feedback_type || "未标注"}\n原因：${item.reason || "无"}\n评论：${item.comment || "无"}`,
      priority: "medium",
      status: "open",
      source_historical_feedback_item_id: item.id,
      source_note: `${feedbackKindLabel(item.feedback_kind)} ${item.legacy_id} 触发`
    });
    message.value = `已创建需求：${created.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "从历史反馈创建需求失败";
  } finally {
    savingFeedbackId.value = "";
  }
}

watch(() => workspace.currentCode, loadArchive);
onMounted(loadArchive);
</script>

<template>
  <section class="layout-list quality-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Quality Archive</p>
        <h2>质量归档</h2>
        <p>本工作台的质量运营档案：历史反馈、质量复核记录和旧任务运行统计在这里沉淀，用于源治理复盘与导入验收。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadArchive">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="quality-summary-grid">
      <article class="module-card compact">
        <p class="eyebrow">Feedback</p>
        <strong>{{ summary?.total_feedback ?? 0 }}</strong>
        <span>普通反馈</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Quality</p>
        <strong>{{ summary?.total_quality_feedback ?? 0 }}</strong>
        <span>质量反馈</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Jobs</p>
        <strong>{{ summary?.total_job_runs ?? 0 }}</strong>
        <span>旧任务记录</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Refs</p>
        <strong>{{ summary?.unresolved_feedback_ref_count ?? 0 }}</strong>
        <span>反馈未解析引用</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Failures</p>
        <strong>{{ summary?.total_job_failures ?? 0 }}</strong>
        <span>旧任务失败源</span>
      </article>
    </section>

    <section class="quality-insight-strip">
      <article class="module-card">
        <div class="card-title-row">
          <div><p class="eyebrow">Feedback Type</p><h3>反馈类型</h3></div>
          <ClipboardCheck :size="18" />
        </div>
        <div class="tag-cloud">
          <span v-for="[key, count] in feedbackTypeEntries" :key="key">{{ key }} · {{ count }}</span>
          <small v-if="feedbackTypeEntries.length === 0">尚无记录，导入历史质量归档后这里会出现分布。</small>
        </div>
      </article>
      <article class="module-card">
        <div class="card-title-row">
          <div><p class="eyebrow">Quality Reason</p><h3>质量原因</h3></div>
          <ListFilter :size="18" />
        </div>
        <div class="tag-cloud">
          <span v-for="[key, count] in qualityReasonEntries" :key="key">{{ key }} · {{ count }}</span>
          <small v-if="qualityReasonEntries.length === 0">尚无记录，质量反馈导入后这里会展示原因分布。</small>
        </div>
      </article>
      <article class="module-card">
        <div class="card-title-row">
          <div><p class="eyebrow">Job Type</p><h3>任务类型</h3></div>
          <CheckCircle2 :size="18" />
        </div>
        <div class="tag-cloud">
          <span v-for="[key, count] in jobTypeEntries" :key="key">{{ key }} · {{ count }}</span>
          <small v-if="jobTypeEntries.length === 0">尚无记录，旧任务运行导入后这里会展示类型。</small>
        </div>
      </article>
      <article class="module-card">
        <div class="card-title-row">
          <div><p class="eyebrow">Job Status</p><h3>任务状态</h3></div>
          <XCircle :size="18" />
        </div>
        <div class="tag-cloud">
          <span v-for="[key, count] in jobStatusEntries" :key="key">{{ jobStatusLabel(key) }} · {{ count }}</span>
          <small v-if="jobStatusEntries.length === 0">尚无记录，旧任务运行导入后这里会展示状态。</small>
        </div>
      </article>
    </section>

    <section class="module-card quality-note">
      <TriangleAlert :size="18" />
      <span>
        这里展示的是历史质量归档，不写入当前评论、任务、推荐或公司 SQL。未解析引用用于判断旧反馈是否还缺历史素材映射。
      </span>
    </section>

    <section class="module-grid quality-layout">
      <section class="module-card quality-panel">
        <div class="card-title-row">
          <div><p class="eyebrow">Feedback Archive</p><h3>旧反馈</h3></div>
          <span class="metric-pill">{{ feedbackItems.length }} items</span>
        </div>
        <div class="quality-filters">
          <label>
            <span>类型</span>
            <select v-model="feedbackFilters.feedbackKind">
              <option value="">全部</option>
              <option value="feedback">普通反馈</option>
              <option value="quality_feedback">质量反馈</option>
            </select>
          </label>
          <label class="quality-search">
            <span>搜索</span>
            <span>
              <Search :size="15" />
              <input v-model.trim="feedbackFilters.query" type="search" placeholder="原因、评论或用户" @keyup.enter="loadArchive" />
            </span>
          </label>
          <label class="quality-check">
            <input v-model="feedbackFilters.unresolvedOnly" type="checkbox" />
            <span>仅未解析</span>
          </label>
          <button type="button" class="icon-button" :disabled="loading" @click="loadArchive">
            <Search :size="16" />
            <span>筛选</span>
          </button>
        </div>

        <article
          v-for="item in feedbackItems"
          :key="item.id"
          class="quality-row"
          :class="{ anchored: isAnchoredFeedback(item) }"
          :aria-current="isAnchoredFeedback(item) ? 'true' : undefined"
        >
          <div class="quality-row-icon" :class="{ danger: item.article_ref_resolved === false }">
            <TriangleAlert v-if="item.article_ref_resolved === false" :size="17" />
            <ClipboardCheck v-else :size="17" />
          </div>
          <div>
            <h3>{{ feedbackKindLabel(item.feedback_kind) }} · {{ item.feedback_type || "未标注" }}</h3>
            <p>{{ item.reason || item.comment || "无文字说明" }}</p>
            <div class="coverage-metrics">
              <span>legacy {{ item.legacy_id }}</span>
              <span>{{ item.user_name || "unknown" }}</span>
              <span :class="{ danger: item.article_ref_resolved === false }">{{ refLabel(item.article_ref_resolved) }}</span>
              <span>{{ formatDate(item.feedback_at) }}</span>
            </div>
            <button
              v-if="canCreateRequirement"
              type="button"
              class="mini-action"
              :disabled="savingFeedbackId === item.id"
              @click="createRequirementFromFeedback(item)"
            >
              <Plus :size="15" />
              <span>{{ savingFeedbackId === item.id ? "创建中" : "转需求" }}</span>
            </button>
          </div>
        </article>

        <p v-if="!loading && feedbackItems.length === 0" class="empty-state">
          暂无旧反馈归档。执行质量归档导入后，这里会展示普通反馈和质量反馈。
        </p>
      </section>

      <section class="module-card quality-panel">
        <div class="card-title-row">
          <div><p class="eyebrow">Job Archive</p><h3>旧任务记录</h3></div>
          <span class="metric-pill">{{ jobRuns.length }} items</span>
        </div>
        <div class="quality-filters job">
          <label>
            <span>状态</span>
            <select v-model="jobFilters.status">
              <option value="">全部</option>
              <option value="completed">完成</option>
              <option value="failed">失败</option>
              <option value="running">运行中</option>
            </select>
          </label>
          <label class="quality-search">
            <span>搜索</span>
            <span>
              <Search :size="15" />
              <input v-model.trim="jobFilters.query" type="search" placeholder="类型、状态或消息" @keyup.enter="loadArchive" />
            </span>
          </label>
          <button type="button" class="icon-button" :disabled="loading" @click="loadArchive">
            <Search :size="16" />
            <span>筛选</span>
          </button>
        </div>

        <article v-for="run in jobRuns" :key="run.id" class="quality-row">
          <div class="quality-row-icon" :class="{ danger: run.failed_count > 0 || run.status === 'failed' }">
            <XCircle v-if="run.failed_count > 0 || run.status === 'failed'" :size="17" />
            <CheckCircle2 v-else :size="17" />
          </div>
          <div>
            <h3>{{ run.job_type || "unknown" }} · {{ jobStatusLabel(run.status) }}</h3>
            <p>{{ run.message || "无消息" }}</p>
            <div class="coverage-metrics">
              <span>legacy {{ run.legacy_id }}</span>
              <span>sources {{ run.processed_sources }}/{{ run.total_sources }}</span>
              <span>inserted {{ run.inserted_count }}</span>
              <span :class="{ danger: run.failed_count > 0 }">failed {{ run.failed_count }}</span>
              <span>{{ formatDate(run.started_at) }}</span>
            </div>
          </div>
        </article>

        <p v-if="!loading && jobRuns.length === 0" class="empty-state">
          暂无旧任务记录。执行质量归档导入后，这里会展示旧抓取和处理任务的结果。
        </p>
      </section>
    </section>

    <section class="module-card quality-gap-panel">
      <div class="card-title-row">
        <div><p class="eyebrow">Unresolved Feedback</p><h3>反馈引用缺口</h3></div>
        <span class="metric-pill">{{ gaps.length }} gaps</span>
      </div>
      <article v-for="gap in gaps" :key="gap.id" class="quality-gap-row">
        <span>legacy {{ gap.legacy_id }}</span>
        <strong>{{ gap.title }}</strong>
        <small>{{ gap.ref_type }} · unresolved {{ gap.unresolved_count }}</small>
      </article>
      <p v-if="gaps.length === 0" class="empty-state small">
        暂无反馈引用缺口。
      </p>
    </section>
  </section>
</template>

<style scoped>
.quality-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.quality-summary-grid strong {
  display: block;
  color: #0f172a;
  font-size: 26px;
  line-height: 1.1;
}

.quality-summary-grid span {
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.quality-insight-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.quality-insight-strip .module-card {
  display: grid;
  gap: 12px;
}

.quality-insight-strip svg {
  color: #4f46e5;
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-cloud span,
.tag-cloud small {
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 6px 10px;
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
  font-weight: 800;
}

.quality-note {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
  border-color: #c7d2fe;
  background: #eef2ff;
  color: #3730a3;
  font-weight: 800;
}

.quality-layout {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
}

.quality-panel {
  display: grid;
  gap: 12px;
}

.quality-filters {
  display: grid;
  grid-template-columns: minmax(120px, 0.7fr) minmax(180px, 1fr) auto auto;
  align-items: end;
  gap: 10px;
}

.quality-filters.job {
  grid-template-columns: minmax(120px, 0.7fr) minmax(180px, 1fr) auto;
}

.quality-filters label {
  display: grid;
  gap: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 800;
}

.quality-filters select,
.quality-filters input {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
  color: #0f172a;
  font: inherit;
}

.quality-search > span:last-child {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 0 10px;
  background: #fff;
}

.quality-search input {
  border: 0;
  padding-inline: 0;
}

.quality-check {
  display: flex !important;
  grid-template-columns: none !important;
  flex-direction: row;
  align-items: center;
  min-height: 42px;
}

.quality-check input {
  width: auto;
}

.quality-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.quality-row-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: #eef2ff;
  color: #4f46e5;
}

.quality-row-icon.danger {
  background: #fff7ed;
  color: #c2410c;
}

.quality-row h3 {
  margin: 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quality-row p {
  display: -webkit-box;
  margin: 5px 0 8px;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  color: #475569;
}

.danger {
  color: #b45309 !important;
}

.quality-gap-panel {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.quality-gap-row {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr) 160px;
  align-items: center;
  gap: 10px;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fffbeb;
}

.quality-gap-row span,
.quality-gap-row small {
  color: #92400e;
  font-size: 12px;
  font-weight: 800;
}

.quality-gap-row strong {
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

@media (max-width: 1200px) {
  .quality-summary-grid,
  .quality-insight-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quality-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .quality-summary-grid,
  .quality-insight-strip,
  .quality-filters,
  .quality-filters.job,
  .quality-gap-row {
    grid-template-columns: 1fr;
  }
}
</style>
