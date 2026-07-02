<script setup lang="ts">
import { ExternalLink, GitBranch, Layers, RefreshCw, Search, Sparkles } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import {
  fetchDedupeGroups,
  fetchNewsItems,
  normalizeNewsItems,
  type DedupeGroupRecord,
  type NewsItemRecord
} from "../api/news";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const groups = ref<DedupeGroupRecord[]>([]);
const newsItems = ref<NewsItemRecord[]>([]);
const loading = ref(false);
const normalizing = ref(false);
const error = ref("");
const message = ref("");
const search = ref("");
const activeOnly = ref(true);

const filteredGroups = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  if (!keyword) {
    return groups.value;
  }
  return groups.value.filter((group) => {
    const text = [
      group.winner_title,
      group.dedupe_key,
      group.status,
      group.recommendation?.day_key,
      group.recommendation?.recommendation_reason,
      group.daily_report?.day_key,
      group.daily_report?.category,
      ...group.items.flatMap((item) => [item.title, item.source_name, item.duplicate_reason])
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return text.includes(keyword);
  });
});

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

async function loadCandidatePool() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const [nextGroups, nextNewsItems] = await Promise.all([
      fetchDedupeGroups(workspace.currentCode, 100),
      fetchNewsItems(workspace.currentCode, activeOnly.value, 200)
    ]);
    groups.value = nextGroups;
    newsItems.value = nextNewsItems;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载候选池失败";
  } finally {
    loading.value = false;
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
  if (daily.adoption_status === -1) {
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

watch(
  () => workspace.currentCode,
  () => {
    groups.value = [];
    newsItems.value = [];
    void loadCandidatePool();
  }
);

watch(activeOnly, loadCandidatePool);

onMounted(loadCandidatePool);
</script>

<template>
  <section class="module-page">
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
        <label class="switch-row compact">
          <input v-model="activeOnly" type="checkbox" />
          只看 winner
        </label>
      </div>

      <div v-if="loading" class="empty-state">候选池加载中...</div>
      <div v-else-if="filteredGroups.length === 0" class="empty-state">
        暂无候选。请先完成数据源抓取、raw 标准化和去重。
      </div>
      <div v-else class="candidate-feed readable">
        <article v-for="(group, index) in filteredGroups" :key="group.id" class="candidate-card readable">
          <div class="candidate-number">
            {{ String(index + 1).padStart(2, "0") }}
          </div>
          <div class="candidate-body">
            <div class="candidate-heading">
              <div class="candidate-main-copy">
                <div class="candidate-meta">
                  <span class="status-pill">去重 {{ group.status }}</span>
                  <span>{{ group.item_count }} 个来源</span>
                  <span>{{ displaySourceType(winnerNews(group)?.source_type) }}</span>
                  <span>{{ formatDate(winnerNews(group)?.published_at) }}</span>
                  <span class="state-chip">{{ recommendationLabel(group) }}</span>
                  <span class="category-chip">{{ dailyLabel(group) }}</span>
                </div>
                <h3>{{ displayCandidateTitle(group) }}</h3>
                <p class="candidate-summary">{{ displayCandidateSummary(group) }}</p>
              </div>
              <aside class="candidate-judge">
                <span class="score-badge">{{ group.recommendation ? "recommend" : "winner" }}</span>
                <strong>{{ groupScore(group) !== null ? scoreText(groupScore(group)!) : "—" }}</strong>
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

            <details class="inline-details candidate-details">
              <summary>
                <GitBranch :size="15" />
                查看去重依据、重复来源和工程追溯
              </summary>
              <div class="candidate-lineage">
                <span>dedupe_key</span>
                <code>{{ group.dedupe_key }}</code>
                <span>dedupe_group_id</span>
                <code>{{ group.id }}</code>
                <span>recommendation_item_id</span>
                <code>{{ group.recommendation?.recommendation_item_id || "未进入推荐" }}</code>
                <span>daily_report_item_id</span>
                <code>{{ group.daily_report?.daily_report_item_id || "未进入日报" }}</code>
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
