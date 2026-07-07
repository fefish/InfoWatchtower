<script setup lang="ts">
import {
  CalendarDays,
  CheckCircle2,
  PlayCircle,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Tag,
  XCircle
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import {
  createRecommendationRun,
  fetchFeedbackRollupDetail,
  fetchFeedbackRollups,
  fetchRecommendationRun,
  fetchRecommendationRuns,
  fetchScorerPolicy,
  previewScorer,
  type FeedbackRollupDetailRecord,
  type FeedbackRollupRecord,
  type RecommendationItemRecord,
  type RecommendationRunRecord,
  type ScorerPreviewRecord,
  type ScorerPolicyRecord
} from "../api/recommendations";
import { bulkAdoptDailyReportCandidates, bulkRejectDailyReportCandidates } from "../api/reports";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const session = useSessionStore();
const runs = ref<RecommendationRunRecord[]>([]);
const selectedRun = ref<RecommendationRunRecord | null>(null);
const loading = ref(false);
const creating = ref(false);
const error = ref("");
const message = ref("");
const policy = ref<ScorerPolicyRecord | null>(null);
const policyError = ref("");
const previewLoading = ref(false);
const previewError = ref("");
const previewResult = ref<ScorerPreviewRecord | null>(null);
const selectedReviewItemIds = ref<Set<string>>(new Set());
const reviewingAction = ref<"" | "adopt" | "reject">("");
const targetDayKey = ref(todayKey());
const limit = ref(10);
const sourceDailyLimit = ref(2);
const createDailyDraft = ref(false);
const previewForm = ref({
  sourceTitle: "New inference serving architecture improves agent latency benchmark",
  summary: "The release explains inference serving, KV cache, throughput and benchmark tradeoffs.",
  sourceType: "rss",
  sourceTier: "P0",
  sourceChannelType: "官方技术规范/标准/RFC/Release",
  sourceScore: 90,
  sourceTagsText: "AI基础设施, 推理服务"
});

const selectedCount = computed(() => selectedRun.value?.items.filter((item) => item.selected).length ?? 0);
const observationItems = computed(() =>
  (selectedRun.value?.items ?? []).filter(
    (item) => !item.selected && ["P2", "P3"].includes(item.admission_level)
  )
);
const selectedReviewItems = computed(() =>
  observationItems.value.filter((item) => selectedReviewItemIds.value.has(item.id))
);
// 空指标隐藏（recommendation_ranking.json ordering_consistency empty_metrics）：
// 无候选样本时返回 null 并隐藏「均分」指标，不渲染占位 0.00。
const averageScore = computed(() => {
  const items = selectedRun.value?.items ?? [];
  if (!items.length) {
    return null;
  }
  return (items.reduce((sum, item) => sum + item.final_score, 0) / items.length).toFixed(2);
});
const thresholdEntries = computed(() => {
  const thresholds = policy.value?.thresholds ?? {};
  return ["P0", "P1", "P2", "P3"]
    .filter((level) => typeof thresholds[level] === "number")
    .map((level) => [level, thresholds[level]] as const);
});
const policyWeights = computed(() => policy.value?.weights.slice(0, 6) ?? []);
const policyTopics = computed(() => policy.value?.top_topics.slice(0, 5) ?? []);
const policyConfigName = computed(() => {
  const path = policy.value?.config_path ?? "";
  return path.split("/").filter(Boolean).pop() ?? path;
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

async function loadPolicy() {
  if (!workspace.currentCode) {
    policy.value = null;
    return;
  }
  policyError.value = "";
  try {
    policy.value = await fetchScorerPolicy(workspace.currentCode);
  } catch (exc) {
    policy.value = null;
    policyError.value = exc instanceof Error ? exc.message : "加载评分策略失败";
  }
}

async function selectRun(run: RecommendationRunRecord | null) {
  selectedReviewItemIds.value = new Set();
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

async function refreshSelectedRun() {
  if (!selectedRun.value) {
    return;
  }
  selectedRun.value = await fetchRecommendationRun(selectedRun.value.id);
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

async function runScorerPreview() {
  if (!workspace.currentCode) {
    return;
  }
  const sourceTitle = previewForm.value.sourceTitle.trim();
  if (!sourceTitle) {
    previewError.value = "请填写用于评分的标题";
    return;
  }
  previewLoading.value = true;
  previewError.value = "";
  previewResult.value = null;
  try {
    previewResult.value = await previewScorer({
      workspace_code: workspace.currentCode,
      source_title: sourceTitle,
      summary: previewForm.value.summary,
      content: previewForm.value.summary,
      source_type: previewForm.value.sourceType,
      source_name: "Scorer Preview",
      source_url: "",
      source_tier: previewForm.value.sourceTier,
      source_channel_type: previewForm.value.sourceChannelType,
      source_score: previewForm.value.sourceScore,
      source_tags: splitTags(previewForm.value.sourceTagsText),
      source_secondary_tags: [],
      board_relevance_json: {},
      freshness_score: 80
    });
  } catch (exc) {
    previewError.value = exc instanceof Error ? exc.message : "评分预览失败";
  } finally {
    previewLoading.value = false;
  }
}

async function reviewObservationSelected(action: "adopt" | "reject") {
  if (!workspace.currentCode || selectedReviewItems.value.length === 0) {
    return;
  }
  reviewingAction.value = action;
  error.value = "";
  message.value = "";
  const dedupeGroupIds = selectedReviewItems.value.map((item) => item.dedupe_group_id);
  try {
    const result =
      action === "adopt"
        ? await bulkAdoptDailyReportCandidates({
            workspace_code: workspace.currentCode,
            day_key: targetDayKey.value,
            dedupe_group_ids: dedupeGroupIds
          })
        : await bulkRejectDailyReportCandidates({
            workspace_code: workspace.currentCode,
            day_key: targetDayKey.value,
            dedupe_group_ids: dedupeGroupIds
          });
    message.value =
      action === "adopt"
        ? `观察池采信完成：新增 ${result.created_total}，恢复 ${result.updated_total}，跳过 ${result.skipped_total}；日报 ${result.report.day_key}`
        : `观察池剔除完成：新增 ${result.created_total}，更新 ${result.updated_total}，跳过 ${result.skipped_total}；日报 ${result.report.day_key}`;
    selectedReviewItemIds.value = new Set();
    await refreshSelectedRun();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "观察池复核失败";
  } finally {
    reviewingAction.value = "";
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

function compactPolicyPairs(items: { name: string; value: number }[], limit = 3) {
  return items
    .slice(0, limit)
    .map((item) => `${item.name} ${item.value}`)
    .join(" / ");
}

function splitTags(value: string) {
  return value
    .split(/[,，/]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// 反馈评估卡（WP4-G，page-specs §9.3；契约 feedback_workflow.api；admin+ 只读）
// ---------------------------------------------------------------------------

const workspaceRoleRank: Record<string, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };
const canViewFeedbackEvaluation = computed(() => {
  const globalRoles = session.user?.roles ?? [];
  if (globalRoles.includes("super_admin") || globalRoles.includes("editor_admin")) {
    return true;
  }
  return (workspaceRoleRank[workspace.currentRole ?? "viewer"] ?? 0) >= workspaceRoleRank.admin;
});

const feedbackPeriod = ref<"weekly" | "monthly">("weekly");
const feedbackRollups = ref<FeedbackRollupRecord[]>([]);
const feedbackRollupsError = ref("");
const feedbackRollupsLoading = ref(false);
const expandedRollupId = ref("");
const rollupDetails = ref<Record<string, FeedbackRollupDetailRecord>>({});

async function loadFeedbackRollups() {
  if (!workspace.currentCode || !canViewFeedbackEvaluation.value) {
    feedbackRollups.value = [];
    return;
  }
  feedbackRollupsLoading.value = true;
  feedbackRollupsError.value = "";
  expandedRollupId.value = "";
  try {
    const result = await fetchFeedbackRollups(workspace.currentCode, feedbackPeriod.value, 8);
    feedbackRollups.value = result.items;
  } catch (exc) {
    feedbackRollups.value = [];
    feedbackRollupsError.value = exc instanceof Error ? exc.message : "加载反馈评估失败";
  } finally {
    feedbackRollupsLoading.value = false;
  }
}

async function toggleRollupDetail(rollup: FeedbackRollupRecord) {
  if (expandedRollupId.value === rollup.id) {
    expandedRollupId.value = "";
    return;
  }
  expandedRollupId.value = rollup.id;
  if (!rollupDetails.value[rollup.id] && workspace.currentCode) {
    try {
      const detail = await fetchFeedbackRollupDetail(workspace.currentCode, rollup.id);
      rollupDetails.value = { ...rollupDetails.value, [rollup.id]: detail };
    } catch (exc) {
      feedbackRollupsError.value = exc instanceof Error ? exc.message : "加载评估详情失败";
    }
  }
}

// 空指标规则（契约 empty_sample_rule）：null 指标整项隐藏，页面不出现 0.0 占位。
function rollupMetricEntries(rollup: FeedbackRollupRecord): [string, string][] {
  const metrics = rollup.metrics ?? {};
  const candidates: [string, unknown][] = [
    ["precision@6", metrics.precision_at_6],
    ["precision@12", metrics.precision_at_12],
    ["rerank uplift", metrics.rerank_uplift],
    ["来源覆盖", metrics.source_coverage],
    ["主题熵", metrics.topic_entropy],
    ["位次去偏采信率", metrics.normalized_adopt_rate],
    ["edit_rate", metrics.edit_rate]
  ];
  return candidates
    .filter(([, value]) => typeof value === "number")
    .map(([label, value]) => [label, (value as number).toFixed(4)]);
}

function rollupSuggestionLabel(suggestion: string) {
  return (
    {
      suggest_promote: "建议升档",
      suggest_demote: "建议降档",
      insufficient_data: "低数据",
      keep: "维持"
    }[suggestion] ?? suggestion
  );
}

watch(feedbackPeriod, () => {
  void loadFeedbackRollups();
});

function toggleReviewItem(item: RecommendationItemRecord, event: Event) {
  const checked = event.target instanceof HTMLInputElement && event.target.checked;
  const next = new Set(selectedReviewItemIds.value);
  if (checked) {
    next.add(item.id);
  } else {
    next.delete(item.id);
  }
  selectedReviewItemIds.value = next;
}

function dailyReviewLabel(item: RecommendationItemRecord) {
  if (!item.daily_report) {
    return "未处理";
  }
  if (item.daily_report.adoption_status === 2) {
    return `已采信 · ${item.daily_report.day_key}`;
  }
  if (item.daily_report.adoption_status === 0) {
    return `已剔除 · ${item.daily_report.day_key}`;
  }
  return `日报候选 · ${item.daily_report.day_key}`;
}

watch(
  () => workspace.currentCode,
  () => {
    runs.value = [];
    selectedRun.value = null;
    rollupDetails.value = {};
    void loadRuns();
    void loadPolicy();
    void loadFeedbackRollups();
  }
);

onMounted(() => {
  void loadRuns();
  void loadPolicy();
  void loadFeedbackRollups();
});
</script>

<template>
  <section class="layout-list">
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
        <RouterLink
          class="icon-button secondary"
          to="/workspace-settings#labels"
          title="候选池分类口径由工作台标签策略决定，在工作台配置中维护"
        >
          <Tag :size="17" />
          <span>标签策略</span>
        </RouterLink>
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
    <p v-if="policyError" class="form-warning">{{ policyError }}</p>

    <section v-if="policy" class="scorer-policy module-card compact" aria-label="评分策略">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Scorer Policy</p>
          <h3><SlidersHorizontal :size="18" /> 内容评分器</h3>
        </div>
        <span :class="policy.config_loaded && policy.enabled ? 'status-on' : 'status-off'">
          {{ policy.config_loaded && policy.enabled ? "规则已启用" : "规则未启用" }}
        </span>
      </div>
      <div class="policy-grid">
        <div>
          <span>版本</span>
          <strong>{{ policy.config_version || "baseline" }}</strong>
          <small>{{ policyConfigName }}</small>
        </div>
        <div>
          <span>准入阈值</span>
          <strong>{{ thresholdEntries.map(([level, score]) => `${level}≥${score}`).join(" / ") }}</strong>
          <small>低于 P3 进入 R 或拒绝池</small>
        </div>
        <div>
          <span>日报准入</span>
          <strong>{{ policy.daily_levels.join(" / ") || "未配置" }}</strong>
          <small>周报：{{ policy.weekly_levels.join(" / ") || "未配置" }}</small>
        </div>
        <div>
          <span>权重 Top</span>
          <strong>{{ compactPolicyPairs(policyWeights, 3) || "未配置" }}</strong>
          <small>主题：{{ compactPolicyPairs(policyTopics, 2) || "未配置" }}</small>
        </div>
        <div>
          <span>噪声治理</span>
          <strong>{{ policy.noise_rule_count }} 条规则</strong>
          <small>{{ compactList(policy.direct_reject_noise_types, 3) || "无直接拒绝规则" }}</small>
        </div>
      </div>
      <p v-if="policy.formula_notes[0]" class="muted-line">{{ policy.formula_notes[0] }}</p>
    </section>

    <section class="module-card compact scorer-preview" aria-label="评分预览">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Scorer Preview</p>
          <h3><Sparkles :size="18" /> 在线校验</h3>
        </div>
        <span class="metric-pill">只读预览</span>
      </div>
      <div class="run-command preview-command">
        <label>
          标题
          <input v-model="previewForm.sourceTitle" type="text" />
        </label>
        <label>
          摘要
          <input v-model="previewForm.summary" type="text" />
        </label>
        <label>
          源类型
          <select v-model="previewForm.sourceType">
            <option value="rss">RSS</option>
            <option value="paper_rss">论文 RSS</option>
            <option value="paper_api">论文 API</option>
            <option value="page_manual">页面手工</option>
          </select>
        </label>
        <label>
          源等级
          <input v-model="previewForm.sourceTier" type="text" />
        </label>
        <label>
          渠道
          <input v-model="previewForm.sourceChannelType" type="text" />
        </label>
        <label>
          源分
          <input v-model.number="previewForm.sourceScore" type="number" min="0" max="100" />
        </label>
        <label>
          标签
          <input v-model="previewForm.sourceTagsText" type="text" />
        </label>
        <button type="button" class="icon-button" :disabled="previewLoading" @click="runScorerPreview">
          <Sparkles :size="16" />
          <span>{{ previewLoading ? "校验中" : "校验" }}</span>
        </button>
      </div>
      <p v-if="previewError" class="form-error">{{ previewError }}</p>
      <article v-if="previewResult" class="preview-result">
        <div>
          <span>准入等级</span>
          <strong>{{ previewResult.admission_level }} · {{ previewResult.admission_score.toFixed(2) }}</strong>
          <small>{{ previewResult.admission_pool }} · {{ previewResult.eligible_for_daily ? "可进日报候选" : "不进日报候选" }}</small>
        </div>
        <div>
          <span>噪声</span>
          <strong>{{ compactList(previewResult.noise_types, 3) || "无" }}</strong>
          <small>{{ compactList(previewResult.reject_reasons, 2) || "无限制原因" }}</small>
        </div>
        <div>
          <span>专家路由</span>
          <strong>{{ compactList(previewResult.expert_routes, 3) || "未命中" }}</strong>
          <small>{{ previewResult.persistence === "not_persisted" ? "未写入推荐 run" : previewResult.persistence }}</small>
        </div>
      </article>
    </section>

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

    <section v-if="selectedRun" class="module-card compact" aria-label="观察池复核">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Observation Pool</p>
          <h3>观察池复核</h3>
        </div>
        <div class="module-mini-stats">
          <span>{{ observationItems.length }} 条 P2/P3</span>
          <span>{{ selectedReviewItems.length }} 已选</span>
        </div>
      </div>
      <p v-if="observationItems.length === 0" class="empty-state">
        当前推荐运行没有待复核的 P2/P3 未入选候选。
      </p>
      <div v-else class="review-feed">
        <label v-for="item in observationItems" :key="item.id" class="review-row">
          <input
            type="checkbox"
            :checked="selectedReviewItemIds.has(item.id)"
            @change="toggleReviewItem(item, $event)"
          />
          <span class="review-copy">
            <strong>{{ item.source_title }}</strong>
            <small>
              {{ item.admission_level }} · {{ item.admission_pool }} · 最终分 {{ item.final_score.toFixed(2) }}
            </small>
          </span>
          <span :class="item.daily_report?.adoption_status === 2 ? 'status-on' : 'status-off'">
            {{ dailyReviewLabel(item) }}
          </span>
        </label>
      </div>
      <div v-if="observationItems.length" class="module-actions">
        <button
          type="button"
          class="icon-button"
          :disabled="selectedReviewItems.length === 0 || reviewingAction !== ''"
          @click="reviewObservationSelected('adopt')"
        >
          <CheckCircle2 :size="16" />
          <span>{{ reviewingAction === "adopt" ? "采信中" : "采信到日报" }}</span>
        </button>
        <button
          type="button"
          class="icon-button secondary"
          :disabled="selectedReviewItems.length === 0 || reviewingAction !== ''"
          @click="reviewObservationSelected('reject')"
        >
          <XCircle :size="16" />
          <span>{{ reviewingAction === "reject" ? "剔除中" : "标记剔除" }}</span>
        </button>
      </div>
    </section>

    <!-- 反馈评估卡（WP4-G，page-specs §9.3：只读展示，admin+ 可见） -->
    <section
      v-if="canViewFeedbackEvaluation"
      class="module-card compact feedback-evaluation"
      aria-label="反馈评估"
    >
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Feedback Evaluation</p>
          <h3>反馈评估</h3>
        </div>
        <div class="feedback-period-toggle" role="group" aria-label="评估周期切换">
          <button
            type="button"
            class="icon-button"
            :class="feedbackPeriod === 'weekly' ? '' : 'secondary'"
            @click="feedbackPeriod = 'weekly'"
          >
            周
          </button>
          <button
            type="button"
            class="icon-button"
            :class="feedbackPeriod === 'monthly' ? '' : 'secondary'"
            @click="feedbackPeriod = 'monthly'"
          >
            月
          </button>
        </div>
      </div>
      <p v-if="feedbackRollupsError" class="form-error">{{ feedbackRollupsError }}</p>
      <p
        v-if="!feedbackRollupsLoading && feedbackRollups.length === 0 && !feedbackRollupsError"
        class="empty-state"
      >
        尚未生成反馈评估。
      </p>
      <div v-else class="rollup-list">
        <article v-for="rollup in feedbackRollups" :key="rollup.id" class="rollup-row">
          <button type="button" class="rollup-head" @click="toggleRollupDetail(rollup)">
            <strong>{{ rollup.period_key }}</strong>
            <span>{{ rollup.status }}</span>
            <span>提案 {{ rollup.proposal_status }}</span>
            <span v-if="rollup.metrics.drift_flag" class="status-off">漂移告警</span>
            <span class="rollup-expand-hint">
              {{ expandedRollupId === rollup.id ? "收起" : "展开" }}
            </span>
          </button>
          <div v-if="expandedRollupId === rollup.id" class="rollup-detail">
            <div v-if="rollupMetricEntries(rollup).length" class="policy-grid">
              <div v-for="[label, value] in rollupMetricEntries(rollup)" :key="label">
                <span>{{ label }}</span>
                <strong>{{ value }}</strong>
              </div>
            </div>
            <p v-else class="empty-state">本周期无可用指标（空样本指标不渲染占位值）。</p>
            <template v-if="rollupDetails[rollup.id]">
              <div
                v-if="rollupDetails[rollup.id].source_breakdown.sources?.length"
                class="rollup-sources"
              >
                <h4>源分层建议（advisory，只读）</h4>
                <ul>
                  <li
                    v-for="source in rollupDetails[rollup.id].source_breakdown.sources"
                    :key="source.data_source_id"
                  >
                    <strong>{{ source.name }}</strong>
                    <span>推荐 {{ source.recommended_count }} / 采信 {{ source.adopted_count }}</span>
                    <span class="metric-pill">{{ rollupSuggestionLabel(source.suggestion) }}</span>
                  </li>
                </ul>
              </div>
              <div
                v-if="rollupDetails[rollup.id].source_breakdown.stale_source_suggestions?.length"
                class="rollup-sources"
              >
                <h4>失效源清理建议（不自动禁用）</h4>
                <ul>
                  <li
                    v-for="stale in rollupDetails[rollup.id].source_breakdown.stale_source_suggestions"
                    :key="stale.id"
                  >
                    <strong>{{ stale.name }}</strong>
                    <span>{{ stale.reason }}</span>
                    <span class="metric-pill">{{ stale.suggestion }}</span>
                  </li>
                </ul>
              </div>
            </template>
          </div>
        </article>
      </div>
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
            <span v-if="averageScore !== null">{{ averageScore }} 均分</span>
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

<style scoped>
/* WP4-G 反馈评估卡：表面材质沿用 base.css module-card / policy-grid / metric-pill，
   这里只补列表与行展开的排布。 */
.feedback-period-toggle {
  display: flex;
  gap: 6px;
}

.rollup-list {
  display: grid;
  gap: 8px;
}

.rollup-row {
  border: 1px solid rgba(100, 116, 139, 0.22);
  border-radius: 12px;
  overflow: hidden;
}

.rollup-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
  padding: 10px 14px;
  border: none;
  background: rgba(148, 163, 184, 0.08);
  cursor: pointer;
  text-align: left;
  font: inherit;
}

.rollup-expand-hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted, rgba(71, 85, 105, 0.9));
}

.rollup-detail {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
}

.rollup-sources h4 {
  margin: 0 0 6px;
  font-size: 13px;
}

.rollup-sources ul {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.rollup-sources li {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 13px;
}
</style>
