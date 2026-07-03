<script setup lang="ts">
import { CalendarDays, CheckCircle2, PlayCircle, RefreshCw, Sparkles } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import {
  createRecommendationRun,
  fetchRecommendationRun,
  fetchRecommendationRuns,
  type RecommendationItemRecord,
  type RecommendationRunRecord
} from "../api/recommendations";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const runs = ref<RecommendationRunRecord[]>([]);
const selectedRun = ref<RecommendationRunRecord | null>(null);
const loading = ref(false);
const creating = ref(false);
const error = ref("");
const message = ref("");
const targetDayKey = ref(todayKey());
const limit = ref(10);
const sourceDailyLimit = ref(2);
const createDailyDraft = ref(false);

const selectedCount = computed(() => selectedRun.value?.items.filter((item) => item.selected).length ?? 0);
const averageScore = computed(() => {
  const items = selectedRun.value?.items ?? [];
  if (!items.length) {
    return "0.00";
  }
  return (items.reduce((sum, item) => sum + item.final_score, 0) / items.length).toFixed(2);
});

async function loadRuns() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    runs.value = await fetchRecommendationRuns(workspace.currentCode, 30);
    if (!selectedRun.value || !runs.value.some((run) => run.id === selectedRun.value?.id)) {
      await selectRun(runs.value[0] ?? null);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载推荐运行失败";
  } finally {
    loading.value = false;
  }
}

async function selectRun(run: RecommendationRunRecord | null) {
  if (!run) {
    selectedRun.value = null;
    return;
  }
  error.value = "";
  try {
    selectedRun.value = await fetchRecommendationRun(run.id);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载推荐详情失败";
  }
}

async function createRun() {
  if (!workspace.currentCode) {
    return;
  }
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await createRecommendationRun({
      workspace_code: workspace.currentCode,
      day_key: targetDayKey.value || null,
      limit: limit.value,
      source_daily_limit: sourceDailyLimit.value,
      create_daily_draft: createDailyDraft.value
    });
    message.value = `推荐完成：候选 ${result.candidates_total}，选择 ${result.selected_total}，生成稿 ${result.generated_total}`;
    selectedRun.value = result.run;
    await loadRuns();
    await selectRun(result.run);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建推荐运行失败";
  } finally {
    creating.value = false;
  }
}

function todayKey() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date());
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

function pct(score: number) {
  const value = score <= 1 ? score * 100 : score;
  return `${Math.max(0, Math.min(100, value)).toFixed(0)}%`;
}

function scoreParts(item: RecommendationItemRecord) {
  return [
    ["质量", item.quality_score],
    ["主题", item.topic_score],
    ["时效", item.freshness_score],
    ["反馈", item.feedback_score],
    ["多样性", item.diversity_score],
    ["来源", item.source_score],
    ["热度", item.heat_score]
  ] as const;
}

function compactList(items: string[], limit = 2) {
  return items.slice(0, limit).join(" / ");
}

watch(
  () => workspace.currentCode,
  () => {
    runs.value = [];
    selectedRun.value = null;
    void loadRuns();
  }
);

onMounted(loadRuns);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Recommendation Runs</p>
        <h2>推荐运行</h2>
        <p>查看推荐 run、分数拆解、推荐理由，以及是否进入日报草稿。</p>
      </div>
      <div class="module-actions">
        <label class="date-control">
          <CalendarDays :size="16" />
          <input v-model="targetDayKey" type="date" />
        </label>
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadRuns">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button type="button" class="icon-button" :disabled="creating" @click="createRun">
          <PlayCircle :size="17" />
          <span>{{ creating ? "运行中" : "新建推荐" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="run-command module-card compact">
      <label>
        推荐条数
        <input v-model.number="limit" type="number" min="1" max="100" />
      </label>
      <label>
        单来源上限
        <input v-model.number="sourceDailyLimit" type="number" min="1" max="20" />
      </label>
      <label class="switch-row">
        <input v-model="createDailyDraft" type="checkbox" />
        同时生成日报草稿
      </label>
    </section>

    <section class="module-split">
      <aside class="module-card run-list">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">History</p>
            <h3>运行历史</h3>
          </div>
          <span class="metric-pill">{{ runs.length }} runs</span>
        </div>
        <button
          v-for="run in runs"
          :key="run.id"
          type="button"
          class="run-tab"
          :class="{ active: selectedRun?.id === run.id }"
          @click="selectRun(run)"
        >
          <strong>{{ run.run_key }}</strong>
          <span>{{ run.status }} · {{ formatDateTime(run.completed_at) }}</span>
        </button>
        <p v-if="!loading && runs.length === 0" class="empty-state">暂无推荐运行，先完成抓取与去重后再运行推荐。</p>
      </aside>

      <article class="module-card run-detail">
        <div v-if="selectedRun" class="card-title-row">
          <div>
            <p class="eyebrow">{{ selectedRun.workspace_code }} · {{ selectedRun.domain_code }}</p>
            <h3>{{ selectedRun.run_key }}</h3>
          </div>
          <div class="module-mini-stats">
            <span>{{ selectedRun.items.length }} 候选</span>
            <span>{{ selectedCount }} 已选</span>
            <span>{{ averageScore }} 均分</span>
          </div>
        </div>
        <div v-if="!selectedRun" class="empty-state">选择一次推荐运行查看详情。</div>
        <div v-else class="recommendation-feed">
          <article v-for="item in selectedRun.items" :key="item.id" class="recommendation-card">
            <div class="rank-badge">{{ item.rank }}</div>
            <div class="recommendation-body">
              <div class="candidate-meta">
                <span :class="item.selected ? 'status-on' : 'status-off'">
                  {{ item.selected ? "进入日报" : "未入选" }}
                </span>
                <span class="admission-pill">{{ item.admission_level || "未评分" }} · {{ item.admission_pool || "unknown" }}</span>
                <span>准入分 {{ item.admission_score.toFixed(2) }}</span>
                <span>最终分 {{ item.final_score.toFixed(2) }}</span>
                <span>{{ item.source_name }}</span>
              </div>
              <h3>{{ item.source_title }}</h3>
              <p>{{ item.recommendation_reason || "暂无推荐理由" }}</p>
              <div
                v-if="item.noise_types.length || item.reject_reasons.length || item.expert_routes.length"
                class="admission-line"
              >
                <span v-if="item.noise_types.length">噪声：{{ compactList(item.noise_types, 3) }}</span>
                <span v-if="item.reject_reasons.length">限制：{{ compactList(item.reject_reasons, 2) }}</span>
                <span v-if="item.expert_routes.length">专家：{{ compactList(item.expert_routes, 2) }}</span>
              </div>
              <div class="score-grid">
                <div v-for="[label, score] in scoreParts(item)" :key="label" class="score-cell">
                  <span>{{ label }}</span>
                  <div><i :style="{ width: pct(score) }"></i></div>
                  <strong>{{ score.toFixed(2) }}</strong>
                </div>
              </div>
            </div>
          </article>
        </div>
      </article>
    </section>
  </section>
</template>
