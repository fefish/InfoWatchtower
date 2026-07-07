<script setup lang="ts">
import {
  CalendarDays,
  CheckSquare,
  Eye,
  ExternalLink,
  GitBranch,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  XCircle
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  fetchDedupeGroups,
  fetchNewsItems,
  normalizeNewsItems,
  type DedupeGroupRecord,
  type NewsItemRecord
} from "../api/news";
import { bulkAdoptDailyReportCandidates, bulkRejectDailyReportCandidates } from "../api/reports";
import { fetchObjectWatcher, updateObjectWatcher, type ObjectWatcherRecord } from "../api/watchers";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const workspace = useWorkspaceStore();
const groups = ref<DedupeGroupRecord[]>([]);
const newsItems = ref<NewsItemRecord[]>([]);
const loading = ref(false);
const normalizing = ref(false);
const error = ref("");
const message = ref("");
const search = ref("");
const recommendationStatus = ref("all");
const dailyStatus = ref("all");
const admissionLevel = ref("");
const sourceType = ref("");
// 候选池默认排序（recommendation_ranking.json ordering_consistency candidate_pool）：
// 默认 score_desc（final_score 降序），其他排序仅显式选择时生效。
const sortMode = ref("score_desc");
const activeOnly = ref(true);
const targetDayKey = ref(todayKey());
const selectedGroupIds = ref<Set<string>>(new Set());
const adopting = ref(false);
const rejecting = ref(false);
const watchersByGroup = ref<Record<string, ObjectWatcherRecord>>({});
const loadingWatcherIds = ref<Record<string, boolean>>({});
const watchingGroupId = ref("");

const recommendationStatusOptions = [
  { value: "all", label: "全部推荐" },
  { value: "recommended", label: "有推荐" },
  { value: "selected", label: "已选入" },
  { value: "unrecommended", label: "未推荐" }
];
const dailyStatusOptions = [
  { value: "all", label: "全部日报" },
  { value: "adopted", label: "已采信" },
  { value: "candidate", label: "日报候选" },
  { value: "rejected", label: "已剔除" },
  { value: "not_in_report", label: "未入日报" }
];
const admissionLevelOptions = [
  { value: "", label: "全部准入" },
  { value: "P0", label: "P0" },
  { value: "P1", label: "P1" },
  { value: "P2", label: "P2" },
  { value: "P3", label: "P3" },
  { value: "R", label: "R" }
];
const sourceTypeOptions = [
  { value: "", label: "全部来源" },
  { value: "rss", label: "RSS" },
  { value: "paper_rss", label: "论文 RSS" },
  { value: "wiseflow", label: "Wiseflow" },
  { value: "page_manual", label: "页面手工" },
  { value: "page_monitor", label: "页面监控" }
];
const sortOptions = [
  { value: "score_desc", label: "推荐分高" },
  { value: "updated_desc", label: "最近更新" },
  { value: "score_asc", label: "推荐分低" },
  { value: "published_desc", label: "发布时间" },
  { value: "source_count_desc", label: "来源数" }
];

const filteredGroups = computed(() => groups.value);

const activeNewsCount = computed(() => newsItems.value.filter((item) => item.active).length);
const duplicateCount = computed(() =>
  groups.value.reduce((total, group) => total + Math.max(0, group.item_count - 1), 0)
);
const sourceCount = computed(() => {
  const names = new Set<string>();
  for (const group of groups.value) {
    for (const item of group.items) {
      if (item.source_name) {
        names.add(item.source_name);
      }
    }
  }
  return names.size;
});
const newsById = computed(() => new Map(newsItems.value.map((item) => [item.id, item])));
const pendingNewsItemId = computed(() => routeQueryString(route.query.news_item_id));
const pendingRawItemId = computed(() => routeQueryString(route.query.raw_item_id));
const pendingDedupeGroupId = computed(() => routeQueryString(route.query.dedupe_group_id));
const selectedGroups = computed(() => groups.value.filter((group) => selectedGroupIds.value.has(group.id)));
const selectedAdoptableGroups = computed(() =>
  selectedGroups.value.filter((group) => group.recommendation && group.daily_report?.adoption_status !== 2)
);
const selectedRejectableGroups = computed(() =>
  selectedGroups.value.filter((group) => group.recommendation && group.daily_report?.adoption_status !== 0)
);
const selectedAdoptableCount = computed(() => selectedAdoptableGroups.value.length);
const selectedRejectableCount = computed(() => selectedRejectableGroups.value.length);
const roleRank: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3
};
const currentWorkspaceRole = computed(() => workspace.current?.current_user_workspace_role ?? "");
const canEditCandidates = computed(() => (roleRank[currentWorkspaceRole.value] ?? -1) >= 1);

function routeQueryString(value: unknown) {
  return Array.isArray(value) ? String(value[0] ?? "") : String(value ?? "");
}

function todayKey() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date());
}

async function loadCandidatePool() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const [nextGroups, nextNewsItems] = await Promise.all([
      fetchDedupeGroups(workspace.currentCode, 100, {
        q: search.value.trim(),
        recommendationStatus: recommendationStatus.value,
        dailyStatus: dailyStatus.value,
        admissionLevel: admissionLevel.value,
        sourceType: sourceType.value,
        sort: sortMode.value
      }),
      fetchNewsItems(workspace.currentCode, activeOnly.value, 200)
    ]);
    groups.value = nextGroups;
    newsItems.value = nextNewsItems;
    selectedGroupIds.value = new Set([...selectedGroupIds.value].filter((id) => nextGroups.some((group) => group.id === id)));
    const nextGroupIds = new Set(nextGroups.map((group) => group.id));
    watchersByGroup.value = Object.fromEntries(
      Object.entries(watchersByGroup.value).filter(([groupId]) => nextGroupIds.has(groupId))
    );
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载候选池失败";
  } finally {
    loading.value = false;
  }
}

async function bulkAdoptSelected() {
  if (!canEditCandidates.value || !workspace.currentCode || selectedAdoptableGroups.value.length === 0) {
    return;
  }
  adopting.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await bulkAdoptDailyReportCandidates({
      workspace_code: workspace.currentCode,
      day_key: targetDayKey.value,
      dedupe_group_ids: selectedAdoptableGroups.value.map((group) => group.id)
    });
    message.value = `批量采信完成：新增 ${result.created_total}，恢复采信 ${result.updated_total}，跳过 ${result.skipped_total}；日报 ${result.report.day_key}`;
    selectedGroupIds.value = new Set();
    await loadCandidatePool();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "批量采信失败";
  } finally {
    adopting.value = false;
  }
}

async function bulkRejectSelected() {
  if (!canEditCandidates.value || !workspace.currentCode || selectedRejectableGroups.value.length === 0) {
    return;
  }
  rejecting.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await bulkRejectDailyReportCandidates({
      workspace_code: workspace.currentCode,
      day_key: targetDayKey.value,
      dedupe_group_ids: selectedRejectableGroups.value.map((group) => group.id)
    });
    message.value = `批量剔除完成：新增 ${result.created_total}，更新剔除 ${result.updated_total}，跳过 ${result.skipped_total}；日报 ${result.report.day_key}`;
    selectedGroupIds.value = new Set();
    await loadCandidatePool();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "批量剔除失败";
  } finally {
    rejecting.value = false;
  }
}

function toggleGroupSelection(group: DedupeGroupRecord, checked: boolean) {
  if (!canEditCandidates.value) {
    return;
  }
  const next = new Set(selectedGroupIds.value);
  if (checked) {
    next.add(group.id);
  } else {
    next.delete(group.id);
  }
  selectedGroupIds.value = next;
}

function onGroupSelectionChange(group: DedupeGroupRecord, event: Event) {
  toggleGroupSelection(group, (event.target as HTMLInputElement | null)?.checked ?? false);
}

function isGroupSelected(group: DedupeGroupRecord) {
  return selectedGroupIds.value.has(group.id);
}

function selectableGroup(group: DedupeGroupRecord) {
  return Boolean(group.recommendation);
}

async function ensureGroupWatcher(group: DedupeGroupRecord) {
  if (watchersByGroup.value[group.id] || loadingWatcherIds.value[group.id]) {
    return;
  }
  loadingWatcherIds.value = { ...loadingWatcherIds.value, [group.id]: true };
  try {
    const watcher = await fetchObjectWatcher("dedupe_group", group.id);
    watchersByGroup.value = { ...watchersByGroup.value, [group.id]: watcher };
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载候选关注状态失败";
  } finally {
    const nextLoading = { ...loadingWatcherIds.value };
    delete nextLoading[group.id];
    loadingWatcherIds.value = nextLoading;
  }
}

function onCandidateDetailsToggle(group: DedupeGroupRecord, event: Event) {
  if ((event.target as HTMLDetailsElement | null)?.open) {
    void ensureGroupWatcher(group);
  }
}

function watcherStatus(group: DedupeGroupRecord) {
  return watchersByGroup.value[group.id] ?? null;
}

async function toggleGroupWatcher(group: DedupeGroupRecord) {
  await ensureGroupWatcher(group);
  const current = watcherStatus(group);
  watchingGroupId.value = group.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateObjectWatcher("dedupe_group", group.id, !(current?.watching ?? false));
    watchersByGroup.value = { ...watchersByGroup.value, [group.id]: updated };
    message.value = updated.watching ? "已关注该候选" : "已取消关注该候选";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新候选关注失败";
  } finally {
    watchingGroupId.value = "";
  }
}

async function runNormalization() {
  if (!workspace.currentCode) {
    return;
  }
  normalizing.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await normalizeNewsItems(workspace.currentCode, [], 200);
    message.value = `标准化完成：扫描 ${result.raw_scanned}，新增 ${result.news_created}，更新 ${result.news_updated}，去重组 ${result.dedupe_groups_updated}`;
    await loadCandidatePool();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "标准化失败";
  } finally {
    normalizing.value = false;
  }
}

function winnerOf(group: DedupeGroupRecord) {
  return group.items.find((item) => item.is_winner) ?? group.items[0] ?? null;
}

function winnerNews(group: DedupeGroupRecord) {
  const winner = winnerOf(group);
  if (!winner) {
    return null;
  }
  return newsById.value.get(winner.news_item_id) ?? null;
}

function groupContainsNewsItem(group: DedupeGroupRecord, newsItemId: string) {
  if (!newsItemId) {
    return false;
  }
  return group.winner_news_item_id === newsItemId || group.items.some((item) => item.news_item_id === newsItemId);
}

function groupContainsRawItem(group: DedupeGroupRecord, rawItemId: string) {
  if (!rawItemId) {
    return false;
  }
  return (
    winnerNews(group)?.raw_item_id === rawItemId ||
    group.lineage.nodes.some((node) => node.object_type === "raw_item" && node.object_id === rawItemId)
  );
}

function isAnchoredGroup(group: DedupeGroupRecord) {
  return (
    group.id === pendingDedupeGroupId.value ||
    groupContainsNewsItem(group, pendingNewsItemId.value) ||
    groupContainsRawItem(group, pendingRawItemId.value)
  );
}

function displayCandidateTitle(group: DedupeGroupRecord) {
  const news = winnerNews(group);
  return news?.normalized_title || news?.source_title || group.winner_title || "未选择 winner";
}

function displayCandidateSummary(group: DedupeGroupRecord) {
  const summary = winnerNews(group)?.summary?.trim();
  if (summary) {
    return summary;
  }
  const winner = winnerOf(group);
  const reason = winner?.duplicate_reason?.trim();
  if (reason && reason !== "winner") {
    return reason;
  }
  return `该候选由 ${winner?.source_name || "未知来源"} 作为代表新闻，当前去重组包含 ${group.item_count} 个来源；进入推荐后会生成正式 brief 和五段正文。`;
}

function displaySourceType(type?: string) {
  const labels: Record<string, string> = {
    rss: "RSS",
    paper_rss: "论文 RSS",
    wiseflow: "Wiseflow",
    page_manual: "页面手工",
    page_monitor: "页面监控"
  };
  return type ? labels[type] ?? type : "未知来源";
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "未知时间";
  }
  return new Date(value).toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit"
  });
}

function duplicateSourceNames(group: DedupeGroupRecord) {
  const winner = winnerOf(group);
  const names: string[] = [];
  for (const item of group.items) {
    if (item.id === winner?.id || !item.source_name || names.includes(item.source_name)) {
      continue;
    }
    names.push(item.source_name);
  }
  return names.slice(0, 4);
}

function duplicateSourceRemainder(group: DedupeGroupRecord) {
  const count = Math.max(0, group.items.length - 1);
  return Math.max(0, count - duplicateSourceNames(group).length);
}

function scoreText(score: number) {
  return score.toFixed(2);
}

function recommendationLabel(group: DedupeGroupRecord) {
  if (!group.recommendation) {
    return "未推荐";
  }
  return group.recommendation.selected ? "已选入推荐" : "推荐候选";
}

function dailyLabel(group: DedupeGroupRecord) {
  const daily = group.daily_report;
  if (!daily) {
    return "未入日报";
  }
  if (daily.adoption_status === 2) {
    return `日报采信 · ${daily.day_key}`;
  }
  if (daily.adoption_status === 0) {
    return `日报剔除 · ${daily.day_key}`;
  }
  return `日报候选 · ${daily.day_key}`;
}

function groupScore(group: DedupeGroupRecord) {
  // 推荐分是 0-100；去重 rank_score 是无上限的内部排序权重，两者不可混显
  return group.recommendation?.final_score ?? null;
}

function scoreParts(group: DedupeGroupRecord): [string, number][] {
  const recommendation = group.recommendation;
  if (!recommendation) {
    return [];
  }
  return [
    ["质量", recommendation.quality_score],
    ["主题", recommendation.topic_score],
    ["时效", recommendation.freshness_score],
    ["反馈", recommendation.feedback_score],
    ["多样性", recommendation.diversity_score],
    ["来源", recommendation.source_score],
    ["热度", recommendation.heat_score]
  ];
}

function compactList(items: string[], limit = 2) {
  return items.slice(0, limit).join(" / ");
}

function traceNodeTypeLabel(type: string) {
  const labels: Record<string, string> = {
    data_source: "数据源",
    raw_item: "Raw",
    news_item: "News",
    dedupe_group: "去重组",
    recommendation_item: "推荐",
    generated_news: "成稿",
    daily_report_item: "日报条目"
  };
  return labels[type] ?? type;
}

function traceNodeMetaLine(node: DedupeGroupRecord["lineage"]["nodes"][number]) {
  const metadata = node.metadata;
  if (node.object_type === "raw_item" && Array.isArray(metadata.payload_keys)) {
    return `payload: ${metadata.payload_keys.slice(0, 4).join(" / ") || "无 key"}`;
  }
  if (node.object_type === "recommendation_item") {
    return `${metadata.admission_level || "未评分"} · ${metadata.admission_pool || "unknown"} · ${metadata.final_score ?? "—"}`;
  }
  if (node.object_type === "daily_report_item") {
    return `${metadata.day_key || ""} · adoption ${metadata.adoption_status ?? "—"}`;
  }
  if (node.object_type === "data_source") {
    return `${metadata.source_type || ""} · ${metadata.domain_code || ""}`;
  }
  return node.occurred_at ? formatDate(node.occurred_at) : "";
}

watch(
  () => workspace.currentCode,
  () => {
    groups.value = [];
    newsItems.value = [];
    void loadCandidatePool();
  }
);

watch(activeOnly, loadCandidatePool);

watch(
  [search, recommendationStatus, dailyStatus, admissionLevel, sourceType, sortMode],
  () => {
    void loadCandidatePool();
  }
);

onMounted(loadCandidatePool);
</script>

<template>
  <section class="layout-list">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Dedupe Workspace</p>
        <h2>候选池</h2>
        <p>候选池展示去重后的 winner、重复来源、来源分和进入推荐前的候选状态。</p>
      </div>
      <div class="module-actions">
        <label class="search-control">
          <Search :size="16" />
          <input v-model="search" type="search" placeholder="搜索标题、来源、去重 key" />
        </label>
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadCandidatePool">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button type="button" class="icon-button" :disabled="normalizing" @click="runNormalization">
          <Sparkles :size="17" />
          <span>{{ normalizing ? "处理中" : "标准化 200 条" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <div class="module-stats">
      <article>
        <strong>{{ groups.length }}</strong>
        <span>去重组</span>
      </article>
      <article>
        <strong>{{ activeNewsCount }}</strong>
        <span>winner 新闻</span>
      </article>
      <article>
        <strong>{{ duplicateCount }}</strong>
        <span>重复来源</span>
      </article>
      <article>
        <strong>{{ sourceCount }}</strong>
        <span>覆盖来源</span>
      </article>
    </div>

    <section class="module-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Candidate Groups</p>
          <h3>去重候选</h3>
        </div>
        <div class="candidate-bulk-actions">
          <template v-if="canEditCandidates">
            <label class="date-control compact">
              <CalendarDays :size="15" />
              <input v-model="targetDayKey" type="date" />
            </label>
            <button
              type="button"
              class="icon-button secondary"
              :disabled="adopting || selectedAdoptableCount === 0"
              @click="bulkAdoptSelected"
            >
              <CheckSquare :size="16" />
              <span>{{ adopting ? "采信中" : `批量采信 ${selectedAdoptableCount}` }}</span>
            </button>
            <button
              type="button"
              class="icon-button secondary danger-soft"
              :disabled="rejecting || selectedRejectableCount === 0"
              @click="bulkRejectSelected"
            >
              <XCircle :size="16" />
              <span>{{ rejecting ? "剔除中" : `批量剔除 ${selectedRejectableCount}` }}</span>
            </button>
          </template>
          <label class="switch-row compact">
            <input v-model="activeOnly" type="checkbox" />
            只看 winner
          </label>
        </div>
      </div>

      <div class="candidate-filter-row">
        <SlidersHorizontal :size="16" />
        <label class="filter-control">
          <select v-model="recommendationStatus" aria-label="推荐状态">
            <option v-for="option in recommendationStatusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="filter-control">
          <select v-model="dailyStatus" aria-label="日报状态">
            <option v-for="option in dailyStatusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="filter-control">
          <select v-model="admissionLevel" aria-label="准入等级">
            <option v-for="option in admissionLevelOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="filter-control">
          <select v-model="sourceType" aria-label="来源类型">
            <option v-for="option in sourceTypeOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label class="filter-control">
          <select v-model="sortMode" aria-label="排序方式">
            <option v-for="option in sortOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="empty-state">候选池加载中...</div>
      <div v-else-if="filteredGroups.length === 0" class="empty-state">
        暂无候选。请先完成数据源抓取、raw 标准化和去重。
      </div>
      <div v-else class="candidate-feed readable">
        <article
          v-for="(group, index) in filteredGroups"
          :key="group.id"
          class="candidate-card readable"
          :class="{ anchored: isAnchoredGroup(group) }"
          :aria-current="isAnchoredGroup(group) ? 'true' : undefined"
        >
          <div class="candidate-number">
            <label v-if="canEditCandidates" class="candidate-select">
              <input
                type="checkbox"
                :checked="isGroupSelected(group)"
                :disabled="!selectableGroup(group)"
                :aria-label="`选择候选 ${displayCandidateTitle(group)}`"
                @change="onGroupSelectionChange(group, $event)"
              />
              <span>{{ String(index + 1).padStart(2, "0") }}</span>
            </label>
            <span v-else>{{ String(index + 1).padStart(2, "0") }}</span>
          </div>
          <div class="candidate-body">
            <div class="candidate-heading">
              <div class="candidate-main-copy">
                <div class="candidate-meta">
                  <span class="state-chip">去重 {{ group.status }}</span>
                  <span>{{ group.item_count }} 个来源</span>
                  <span>{{ displaySourceType(winnerNews(group)?.source_type ?? group.winner_source_type ?? undefined) }}</span>
                  <span>{{ formatDate(winnerNews(group)?.published_at ?? group.winner_published_at) }}</span>
                  <span class="state-chip">{{ recommendationLabel(group) }}</span>
                  <span class="category-chip">{{ dailyLabel(group) }}</span>
                </div>
                <h3>{{ displayCandidateTitle(group) }}</h3>
                <p class="candidate-summary">{{ displayCandidateSummary(group) }}</p>
              </div>
              <aside class="candidate-judge">
                <span class="score-badge">{{ group.recommendation ? "recommend" : "winner" }}</span>
                <!-- 空指标（ordering_consistency empty_metrics）：final_score 缺失显示「未评分」，不渲染占位 0.0 -->
                <strong>{{ groupScore(group) !== null ? scoreText(groupScore(group)!) : "未评分" }}</strong>
                <small>{{ group.recommendation ? "推荐分（0-100）" : "待推荐评分" }}</small>
              </aside>
            </div>

            <div v-if="winnerOf(group)" class="candidate-source-line">
              <span>代表来源</span>
              <strong>{{ winnerOf(group)?.source_name }}</strong>
              <a v-if="winnerOf(group)?.source_url" :href="winnerOf(group)?.source_url || '#'" target="_blank">
                <ExternalLink :size="13" />
                原文
              </a>
              <span v-if="group.recommendation">推荐排序 #{{ group.recommendation.rank }}</span>
              <span v-if="group.daily_report">{{ group.daily_report.category }} · {{ group.daily_report.generation_status }}</span>
            </div>

            <div v-if="duplicateSourceNames(group).length > 0" class="duplicate-source-cloud">
              <span>重复来源</span>
              <strong v-for="name in duplicateSourceNames(group)" :key="name">{{ name }}</strong>
              <strong v-if="duplicateSourceRemainder(group) > 0">+{{ duplicateSourceRemainder(group) }}</strong>
            </div>

            <details class="inline-details candidate-details" @toggle="onCandidateDetailsToggle(group, $event)">
              <summary>
                <GitBranch :size="15" />
                查看去重依据、重复来源和工程追溯
              </summary>
              <div class="candidate-detail-actions feedback-row">
                <button
                  type="button"
                  class="mini-action"
                  :class="{ active: watcherStatus(group)?.watching }"
                  :disabled="watchingGroupId === group.id || loadingWatcherIds[group.id]"
                  :aria-pressed="watcherStatus(group)?.watching ? 'true' : 'false'"
                  @click="toggleGroupWatcher(group)"
                >
                  <Eye :size="14" />
                  <span>{{ watcherStatus(group)?.watching ? "已关注候选" : "关注候选" }}</span>
                  <span v-if="watcherStatus(group)">· {{ watcherStatus(group)?.watcher_count }}</span>
                </button>
              </div>
              <div class="candidate-lineage">
                <span>dedupe_key</span>
                <code>{{ group.dedupe_key }}</code>
                <span>dedupe_group_id</span>
                <code>{{ group.id }}</code>
                <span>winner_news_item_id</span>
                <code>{{ group.winner_news_item_id || "未选择 winner" }}</code>
                <span>raw_item_id</span>
                <code>{{ winnerNews(group)?.raw_item_id || "未加载" }}</code>
                <span>data_source_id</span>
                <code>{{ winnerNews(group)?.data_source_id || "未加载" }}</code>
                <span>recommendation_item_id</span>
                <code>{{ group.recommendation?.recommendation_item_id || "未进入推荐" }}</code>
                <span>daily_report_item_id</span>
                <code>{{ group.daily_report?.daily_report_item_id || "未进入日报" }}</code>
              </div>
              <div v-if="group.lineage.nodes.length" class="lineage-flow" aria-label="候选追溯链">
                <div v-for="node in group.lineage.nodes" :key="`${node.object_type}:${node.object_id}`" class="lineage-node">
                  <span>{{ traceNodeTypeLabel(node.object_type) }}</span>
                  <strong>{{ node.label }}</strong>
                  <p>{{ node.review_note }}</p>
                  <small>{{ node.status }}<template v-if="traceNodeMetaLine(node)"> · {{ traceNodeMetaLine(node) }}</template></small>
                  <RouterLink v-if="node.target_path" :to="node.target_path">定位</RouterLink>
                </div>
              </div>
              <div v-if="group.recommendation" class="score-grid trace-score-grid">
                <div v-for="[label, score] in scoreParts(group)" :key="label" class="score-cell">
                  <span>{{ label }}</span>
                  <div><i :style="{ width: `${Math.min(100, Math.max(0, score * 100))}%` }"></i></div>
                  <strong>{{ scoreText(score) }}</strong>
                </div>
              </div>
              <p v-if="group.recommendation?.recommendation_reason" class="muted-line">
                推荐理由：{{ group.recommendation.recommendation_reason }}
              </p>
              <div v-if="group.recommendation" class="admission-line">
                <span>
                  准入：{{ group.recommendation.admission_level || "未评分" }}
                  · {{ group.recommendation.admission_pool || "unknown" }}
                  · {{ group.recommendation.admission_score.toFixed(2) }}
                </span>
                <span v-if="group.recommendation.noise_types.length">
                  噪声：{{ compactList(group.recommendation.noise_types, 3) }}
                </span>
                <span v-if="group.recommendation.expert_routes.length">
                  专家：{{ compactList(group.recommendation.expert_routes, 2) }}
                </span>
              </div>
              <div class="duplicate-list">
                <div v-for="item in group.items" :key="item.id" class="duplicate-row">
                  <span :class="item.is_winner ? 'status-on' : 'status-off'">
                    {{ item.is_winner ? "winner" : "重复" }}
                  </span>
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.source_name }} · 去重权重 {{ scoreText(item.rank_score) }}</small>
                  <a v-if="item.source_url" :href="item.source_url" target="_blank">打开</a>
                </div>
              </div>
            </details>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>
