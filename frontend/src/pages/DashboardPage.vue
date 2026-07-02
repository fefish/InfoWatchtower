<script setup lang="ts">
import {
  ArrowRight,
  BarChart3,
  CalendarDays,
  ChevronRight,
  Database,
  FileText,
  Plus,
  Radio,
  TriangleAlert
} from "lucide-vue-next";
import { computed, ref, watch } from "vue";

import { fetchHealth, type HealthResponse } from "../api/health";
import {
  fetchIngestionCoverage,
  type IngestionCoverageRecord
} from "../api/ingestion";
import { fetchDedupeGroups, type DedupeGroupRecord } from "../api/news";
import {
  fetchDailyReports,
  fetchWeeklyReports,
  type DailyReportRecord,
  type WeeklyReportRecord
} from "../api/reports";
import { fetchSources, type DataSourceRecord } from "../api/sources";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();

const health = ref<HealthResponse | null>(null);
const coverage = ref<IngestionCoverageRecord | null>(null);
const candidates = ref<DedupeGroupRecord[]>([]);
const sources = ref<DataSourceRecord[]>([]);
const dailyReports = ref<DailyReportRecord[]>([]);
const weeklyReports = ref<WeeklyReportRecord[]>([]);
const loading = ref(false);
const error = ref("");

const todayKey = new Date().toLocaleDateString("sv-SE");

const todayLabel = computed(() => {
  const now = new Date();
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  return `${now.getFullYear()} 年 ${now.getMonth() + 1} 月 ${now.getDate()} 日 · 星期${weekdays[now.getDay()]}`;
});

const funnel = computed(() => coverage.value?.funnel ?? null);

const funnelStages = computed(() => {
  const value = funnel.value;
  return [
    { label: "启用源", value: value?.enabled_sources ?? null },
    { label: "抓取成功", value: value ? value.source_succeeded : null },
    { label: "今日新增", value: value?.raw_in_target ?? null },
    { label: "去重代表", value: value?.dedupe_winners ?? null },
    { label: "推荐候选", value: value?.recommendation_candidates ?? null },
    { label: "已采信", value: value?.daily_adopted ?? null }
  ];
});

const dailyReportStatus = computed(() => {
  if (!coverage.value?.daily_report_status) {
    return { label: "未生成", tone: "idle" };
  }
  return coverage.value.daily_report_status === "published"
    ? { label: "已发布", tone: "ok" }
    : { label: "草稿待编审", tone: "warn" };
});

const topCandidates = computed(() =>
  candidates.value
    .filter((group) => group.recommendation && group.winner_title)
    .sort((left, right) => (right.recommendation?.final_score ?? 0) - (left.recommendation?.final_score ?? 0))
    .slice(0, 6)
);

const latestDaily = computed(() => dailyReports.value[0] ?? null);
const latestWeekly = computed(() => weeklyReports.value[0] ?? null);

const latestDailyCategories = computed(() => {
  if (!latestDaily.value) {
    return [] as Array<{ name: string; count: number }>;
  }
  const counts = new Map<string, number>();
  for (const item of latestDaily.value.items) {
    const category = item.generated_news?.category || "未分类";
    counts.set(category, (counts.get(category) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((left, right) => right.count - left.count)
    .slice(0, 4);
});

const weekTrend = computed(() => {
  const recent = [...dailyReports.value]
    .sort((left, right) => left.day_key.localeCompare(right.day_key))
    .slice(-7);
  const max = Math.max(1, ...recent.map((report) => report.items.length));
  return recent.map((report) => ({
    day: report.day_key.slice(5),
    count: report.items.length,
    height: Math.max(8, Math.round((report.items.length / max) * 100)),
    published: report.status === "published"
  }));
});

const failingSources = computed(() =>
  sources.value
    .filter((source) => source.workspace_link_enabled && source.last_error)
    .slice(0, 3)
);

const needsEntryCount = computed(
  () => sources.value.filter((source) => source.needs_entry || source.metadata_only).length
);

const enabledSourceCount = computed(
  () => sources.value.filter((source) => source.workspace_link_enabled).length
);

function admissionTone(level: string | undefined) {
  const value = (level || "").toUpperCase();
  if (value === "P0") return "p0";
  if (value === "P1") return "p1";
  if (value === "P2") return "p2";
  if (value === "R") return "reject";
  return "p3";
}

function scoreText(group: DedupeGroupRecord) {
  const score = group.recommendation?.final_score;
  return typeof score === "number" ? score.toFixed(1) : "-";
}

watch(
  () => workspace.currentCode,
  (code) => {
    if (code) {
      void loadBriefing(code);
    }
  },
  { immediate: true }
);

async function loadBriefing(workspaceCode: string) {
  loading.value = true;
  error.value = "";
  try {
    const [healthResult, sourceResult, dailyResult, weeklyResult, groupResult] = await Promise.all([
      fetchHealth().catch(() => null),
      fetchSources(workspaceCode),
      fetchDailyReports(workspaceCode),
      fetchWeeklyReports(workspaceCode),
      fetchDedupeGroups(workspaceCode, 40).catch(() => [] as DedupeGroupRecord[])
    ]);
    health.value = healthResult;
    sources.value = sourceResult;
    dailyReports.value = dailyResult;
    weeklyReports.value = weeklyResult;
    candidates.value = groupResult;
    coverage.value = await fetchIngestionCoverage(workspaceCode, todayKey).catch(() => null);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载今日速览失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="briefing">
    <section class="briefing-hero" aria-label="今日情报流水线">
      <header class="briefing-hero-head">
        <div>
          <p class="briefing-date">{{ todayLabel }}</p>
          <h2>今日情报速览</h2>
        </div>
        <div class="briefing-health" :data-tone="health ? 'ok' : 'warn'">
          <span class="health-dot" aria-hidden="true"></span>
          {{ health ? "系统运行正常" : "后端未连接" }}
        </div>
      </header>

      <div class="funnel-strip" role="list" aria-label="情报处理漏斗">
        <template v-for="(stage, index) in funnelStages" :key="stage.label">
          <div class="funnel-stage" role="listitem">
            <strong>{{ stage.value ?? "–" }}</strong>
            <span>{{ stage.label }}</span>
          </div>
          <ChevronRight v-if="index < funnelStages.length - 1" class="funnel-arrow" :size="16" aria-hidden="true" />
        </template>
        <div class="funnel-result" :data-tone="dailyReportStatus.tone">
          <FileText :size="15" />
          <span>今日日报 · {{ dailyReportStatus.label }}</span>
        </div>
      </div>
      <p v-if="error" class="form-error">{{ error }}</p>
    </section>

    <section class="briefing-main">
      <article class="briefing-headlines" aria-label="今日头条候选">
        <header class="briefing-card-head">
          <h3>今日头条候选</h3>
          <RouterLink class="briefing-more" to="/news">
            候选池 <ArrowRight :size="14" />
          </RouterLink>
        </header>

        <ol v-if="topCandidates.length" class="headline-list">
          <li v-for="(group, index) in topCandidates" :key="group.id" class="headline-item">
            <span class="headline-rank" :data-top="index < 3">{{ index + 1 }}</span>
            <div class="headline-body">
              <p class="headline-title">{{ group.winner_title }}</p>
              <p class="headline-meta">
                <span class="admission-tag" :data-tone="admissionTone(group.recommendation?.admission_level)">
                  {{ group.recommendation?.admission_level || "P3" }}
                </span>
                <span class="headline-score">{{ scoreText(group) }} 分</span>
                <span v-if="group.item_count > 1" class="headline-dupes">{{ group.item_count }} 源报道</span>
                <span class="headline-source">{{ group.items[0]?.source_name }}</span>
              </p>
            </div>
          </li>
        </ol>
        <div v-else class="briefing-empty">
          <p>今天还没有候选。</p>
          <RouterLink class="briefing-empty-action" to="/ingestion-runs">先跑一次抓取 →</RouterLink>
        </div>
      </article>

      <aside class="briefing-side">
        <article class="briefing-report-card" aria-label="最新日报">
          <header class="briefing-card-head">
            <h3>最新日报</h3>
            <span v-if="latestDaily" class="report-status" :data-tone="latestDaily.status === 'published' ? 'ok' : 'warn'">
              {{ latestDaily.status === "published" ? "已发布" : "草稿" }}
            </span>
          </header>
          <template v-if="latestDaily">
            <p class="report-key">{{ latestDaily.day_key }}</p>
            <p class="report-count">{{ latestDaily.items.length }} 条采信</p>
            <div class="report-cats">
              <span v-for="category in latestDailyCategories" :key="category.name" class="report-cat">
                {{ category.name }} · {{ category.count }}
              </span>
            </div>
            <RouterLink class="briefing-cta" :to="`/daily-reports/${latestDaily.id}`">
              进入编审 <ArrowRight :size="14" />
            </RouterLink>
          </template>
          <div v-else class="briefing-empty compact">
            <p>暂无日报</p>
            <RouterLink class="briefing-empty-action" to="/daily-reports">去生成 →</RouterLink>
          </div>
        </article>

        <article class="briefing-report-card" aria-label="最新周报">
          <header class="briefing-card-head">
            <h3>最新周报</h3>
            <span v-if="latestWeekly" class="report-status" :data-tone="latestWeekly.status === 'published' ? 'ok' : 'warn'">
              {{ latestWeekly.status === "published" ? "已发布" : "草稿" }}
            </span>
          </header>
          <template v-if="latestWeekly">
            <p class="report-key">{{ latestWeekly.week_key }}</p>
            <p class="report-count">{{ latestWeekly.items.length }} 条内容</p>
            <RouterLink class="briefing-cta" to="/weekly-reports">
              进入编审 <ArrowRight :size="14" />
            </RouterLink>
          </template>
          <div v-else class="briefing-empty compact">
            <p>暂无周报</p>
            <RouterLink class="briefing-empty-action" to="/weekly-reports">从日报生成 →</RouterLink>
          </div>
        </article>

        <article class="briefing-trend" aria-label="近七日采信趋势">
          <header class="briefing-card-head">
            <h3>近七日采信</h3>
            <CalendarDays :size="15" />
          </header>
          <div v-if="weekTrend.length" class="trend-bars">
            <div v-for="bar in weekTrend" :key="bar.day" class="trend-col" :title="`${bar.day}：${bar.count} 条`">
              <span class="trend-count">{{ bar.count }}</span>
              <span class="trend-bar" :style="{ height: `${bar.height}%` }" :data-published="bar.published"></span>
              <span class="trend-day">{{ bar.day }}</span>
            </div>
          </div>
          <p v-else class="briefing-empty compact">暂无日报数据</p>
        </article>
      </aside>
    </section>

    <section class="briefing-foot">
      <article class="briefing-sourcehealth" aria-label="源健康">
        <header class="briefing-card-head">
          <h3>源健康</h3>
          <span class="source-health-summary">{{ enabledSourceCount }} 启用 / {{ sources.length }} 共享</span>
        </header>
        <ul v-if="failingSources.length" class="fail-list">
          <li v-for="source in failingSources" :key="source.id">
            <TriangleAlert :size="14" />
            <strong>{{ source.name }}</strong>
            <span>{{ source.last_error.slice(0, 56) }}</span>
          </li>
        </ul>
        <p v-else class="fail-none">最近抓取没有失败源。</p>
        <RouterLink v-if="needsEntryCount > 0" class="entry-alert" to="/sources">
          {{ needsEntryCount }} 个源待补入口，去数据源管理处理 <ArrowRight :size="13" />
        </RouterLink>
      </article>

      <article class="briefing-actions" aria-label="快捷入口">
        <header class="briefing-card-head">
          <h3>快捷入口</h3>
        </header>
        <div class="action-row">
          <RouterLink class="action-tile" to="/ingestion-runs">
            <BarChart3 :size="17" />
            <strong>抓取与覆盖</strong>
            <span>跑今日流水线、看覆盖漏斗</span>
          </RouterLink>
          <RouterLink class="action-tile" to="/sources">
            <span class="action-tile-icons"><Radio :size="17" /><Plus :size="12" /></span>
            <strong>新增信息源</strong>
            <span>自建源或启用共享源</span>
          </RouterLink>
          <RouterLink class="action-tile" to="/exports">
            <Database :size="17" />
            <strong>SQL 导出</strong>
            <span>已发布日报导出公司内网</span>
          </RouterLink>
        </div>
      </article>
    </section>
  </div>
</template>
