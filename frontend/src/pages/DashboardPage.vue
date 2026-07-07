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
import { fetchSchedulerStatus, type SchedulerStatusRecord } from "../api/scheduler";
import { fetchSources, type DataSourceRecord } from "../api/sources";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const runtime = useRuntimeStore();

const health = ref<HealthResponse | null>(null);
const coverage = ref<IngestionCoverageRecord | null>(null);
const candidates = ref<DedupeGroupRecord[]>([]);
const sources = ref<DataSourceRecord[]>([]);
const dailyReports = ref<DailyReportRecord[]>([]);
const weeklyReports = ref<WeeklyReportRecord[]>([]);
const loading = ref(false);
const error = ref("");

// 调度心跳卡（§9.4 侧栏第 6 位，pipeline-jobs-design §8.5）：
// status API 查询失败/后端不可用 → schedulerStatus=null → 整卡隐藏；
// heartbeat_stale=true → 渲染离线态——两种情况都不得渲染在线绿色（假成功回归）。
const schedulerStatus = ref<SchedulerStatusRecord | null>(null);

const RUN_STATUS_LABELS: Record<string, string> = {
  succeeded: "成功",
  completed: "成功",
  failed: "失败",
  error: "失败",
  running: "运行中",
  pending: "排队中",
  skipped: "跳过",
  superseded: "已让位"
};

function formatRunAt(value: string | null | undefined) {
  if (!value) {
    return "";
  }
  return value.slice(0, 16).replace("T", " ");
}

const schedulerHeartbeat = computed(() => {
  const status = schedulerStatus.value;
  if (!status) {
    return null;
  }
  const entry =
    status.workspaces.find((item) => item.workspace_code === workspace.currentCode) ?? null;
  const lastRun = entry?.last_runs[0] ?? null;
  const pendingRetry = entry?.pending_retry ?? null;
  return {
    // 在线判定：心跳存在且未过期；stale/无心跳（scheduler 未部署）一律离线
    online: Boolean(status.heartbeat_at) && !status.heartbeat_stale,
    instanceEnabled: status.instance_enabled && status.capability_ingestion,
    effectiveEnabled: entry?.effective_enabled ?? false,
    nextRunAt: entry?.next_run_at ? formatRunAt(entry.next_run_at) : "",
    lastRunLabel: lastRun
      ? `${lastRun.day_key} ${RUN_STATUS_LABELS[lastRun.status] ?? lastRun.status}${
          lastRun.attempt > 1 ? `（第 ${lastRun.attempt} 次）` : ""
        }`
      : "",
    pendingRetryLabel: pendingRetry
      ? `失败重试排队：第 ${pendingRetry.next_attempt} 次 · ${formatRunAt(pendingRetry.next_retry_at) || "待定"}`
      : ""
  };
});

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
    { label: "入选推荐", value: value?.recommendation_selected ?? null },
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

// 头条候选集合与排序（recommendation_ranking.json ordering_consistency
// dashboard_headline_candidates）：只取 day_key=今日 且 admission ∈ {P0,P1,P2}
// 的候选 top 6，按 final_score 严格降序（并列按 news_item_id 升序）。
// 非今日候选不进集合（原「今日优先、历史混排」两层排序已按契约废除），
// 无今日候选渲染空态而非历史候选。
const topCandidates = computed(() => {
  const qualified = candidates.value.filter((group) => {
    if (!group.recommendation || !group.winner_title) {
      return false;
    }
    if (group.recommendation.day_key !== todayKey) {
      return false;
    }
    const level = (group.recommendation.admission_level || "").toUpperCase();
    return ["P0", "P1", "P2"].includes(level);
  });
  return qualified
    .sort((left, right) => {
      const scoreDelta =
        (right.recommendation?.final_score ?? 0) - (left.recommendation?.final_score ?? 0);
      if (scoreDelta !== 0) {
        return scoreDelta;
      }
      return (left.winner_news_item_id ?? "").localeCompare(right.winner_news_item_id ?? "");
    })
    .slice(0, 6);
});

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

// 源健康折叠态（§9.4）：无失败源且无可见待补入口时收为一行「源健康正常」。
const sourceHealthExpanded = computed(
  () => failingSources.value.length > 0 || (runtime.canIngest && needsEntryCount.value > 0)
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
    const [healthResult, sourceResult, dailyResult, weeklyResult, groupResult, schedulerResult] =
      await Promise.all([
        fetchHealth().catch(() => null),
        fetchSources(workspaceCode),
        fetchDailyReports(workspaceCode),
        fetchWeeklyReports(workspaceCode),
        fetchDedupeGroups(workspaceCode, 40).catch(() => [] as DedupeGroupRecord[]),
        // 心跳查询失败（后端不可用/旧版后端无此路由）→ null → 整卡隐藏，不渲染假数据
        fetchSchedulerStatus().catch(() => null)
      ]);
    health.value = healthResult;
    sources.value = sourceResult;
    dailyReports.value = dailyResult;
    weeklyReports.value = weeklyResult;
    candidates.value = groupResult;
    schedulerStatus.value = schedulerResult;
    coverage.value = await fetchIngestionCoverage(workspaceCode, todayKey).catch(() => null);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载今日速览失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <!-- §9.4 dashboard 模板：页头结论行 → 主列（头条候选/最新日报）+ 固定侧栏（顺序固定六卡） -->
  <div class="briefing layout-dashboard">
    <section class="briefing-hero" aria-label="今日情报结论">
      <p class="briefing-date">{{ todayLabel }}</p>
      <div class="briefing-health" :data-tone="health ? 'ok' : 'warn'">
        <span class="health-dot" aria-hidden="true"></span>
        {{ health ? "系统运行正常" : "后端未连接" }}
      </div>
      <RouterLink class="funnel-result" :data-tone="dailyReportStatus.tone" to="/daily-reports">
        <FileText :size="15" />
        <span>今日日报 · {{ dailyReportStatus.label }}</span>
        <ChevronRight :size="14" aria-hidden="true" />
      </RouterLink>
      <p v-if="error" class="form-error">{{ error }}</p>
    </section>

    <div class="layout-columns">
      <div class="layout-main" aria-label="今天要处理的内容">
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
            <RouterLink v-if="runtime.canIngest" class="briefing-empty-action" to="/ingestion-runs">先跑一次抓取 →</RouterLink>
            <RouterLink v-else class="briefing-empty-action" to="/daily-reports">查看日报 →</RouterLink>
          </div>
        </article>

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
            <RouterLink class="briefing-cta" to="/daily-reports">
              阅读日报 <ArrowRight :size="14" />
            </RouterLink>
          </template>
          <div v-else class="briefing-empty compact">
            <p>暂无日报</p>
            <RouterLink class="briefing-empty-action" to="/daily-reports">去生成 →</RouterLink>
          </div>
        </article>
      </div>

      <aside class="layout-side" aria-label="速览侧栏">
        <article class="briefing-funnel" aria-label="流水线漏斗">
          <header class="briefing-card-head">
            <h3>流水线漏斗</h3>
          </header>
          <ol class="funnel-vlist" aria-label="情报处理漏斗">
            <li v-for="stage in funnelStages" :key="stage.label" class="funnel-vrow">
              <span>{{ stage.label }}</span>
              <strong>{{ stage.value ?? "–" }}</strong>
            </li>
          </ol>
        </article>

        <article class="briefing-actions" aria-label="快捷入口">
          <header class="briefing-card-head">
            <h3>快捷入口</h3>
          </header>
          <div class="action-row">
            <RouterLink v-if="runtime.canIngest" class="action-tile" to="/ingestion-runs">
              <BarChart3 :size="17" />
              <strong>抓取与覆盖</strong>
              <span>跑今日流水线、看覆盖漏斗</span>
            </RouterLink>
            <RouterLink v-if="runtime.canIngest" class="action-tile" to="/sources">
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
          <p v-else class="briefing-empty compact">暂无日报数据，先跑一次日报流水线或导入已校验日报。</p>
        </article>

        <article class="briefing-sourcehealth" aria-label="源健康">
          <header class="briefing-card-head">
            <h3>源健康</h3>
            <span class="source-health-summary">{{ enabledSourceCount }} 启用 / {{ sources.length }} 共享</span>
          </header>
          <p v-if="!sourceHealthExpanded" class="source-health-collapsed">
            <span class="health-dot" aria-hidden="true"></span>
            源健康正常
          </p>
          <template v-else>
            <ul v-if="failingSources.length" class="fail-list">
              <li v-for="source in failingSources" :key="source.id">
                <TriangleAlert :size="14" />
                <strong>{{ source.name }}</strong>
                <span>{{ source.last_error.slice(0, 56) }}</span>
              </li>
            </ul>
            <RouterLink v-if="runtime.canIngest && needsEntryCount > 0" class="entry-alert" to="/sources">
              {{ needsEntryCount }} 个源待补入口，去数据源管理处理 <ArrowRight :size="13" />
            </RouterLink>
          </template>
        </article>

        <!-- ⑥ 调度心跳卡（§9.4 侧栏第 6 位，pipeline-jobs-design §8.5）：
             读 GET /api/pipeline/scheduler/status；查询失败整卡隐藏，
             心跳 stale 渲染离线（data-tone=warn），不得渲染在线绿色（§4.4 看护）。 -->
        <article v-if="schedulerHeartbeat" class="briefing-heartbeat" aria-label="调度心跳">
          <header class="briefing-card-head">
            <h3>调度心跳</h3>
            <span class="report-status" :data-tone="schedulerHeartbeat.online ? 'ok' : 'warn'">
              {{ schedulerHeartbeat.online ? "在线" : "离线" }}
            </span>
          </header>
          <dl class="heartbeat-grid">
            <div>
              <dt>调度器</dt>
              <dd>{{ schedulerHeartbeat.online ? "在线" : "离线" }}</dd>
            </div>
            <div>
              <dt>本台自动调度</dt>
              <dd>{{ schedulerHeartbeat.effectiveEnabled ? "开启" : "未开启" }}</dd>
            </div>
            <div>
              <dt>下次运行</dt>
              <dd>{{ schedulerHeartbeat.nextRunAt || "—" }}</dd>
            </div>
            <div>
              <dt>最近运行</dt>
              <dd>{{ schedulerHeartbeat.lastRunLabel || "—" }}</dd>
            </div>
          </dl>
          <p v-if="schedulerHeartbeat.pendingRetryLabel" class="heartbeat-retry">
            {{ schedulerHeartbeat.pendingRetryLabel }}
          </p>
          <p v-if="!schedulerHeartbeat.instanceEnabled" class="heartbeat-note">
            实例调度总闸未开启或当前部署禁用采集，自动调度不会触发。
          </p>
        </article>
      </aside>
    </div>
  </div>
</template>

<style scoped>
/* 调度心跳卡补充行（WP3-H）：表面材质沿用 base.css 的 briefing-heartbeat /
   heartbeat-grid / report-status，这里只补两行提示的排版。 */
.heartbeat-retry,
.heartbeat-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-muted, rgba(71, 85, 105, 0.9));
}

.heartbeat-retry {
  color: var(--warn-strong, #b45309);
}
</style>
