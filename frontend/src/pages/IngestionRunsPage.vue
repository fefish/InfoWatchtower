<script setup lang="ts">
import {
  AlertCircle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Database,
  PlayCircle,
  RefreshCw,
  Rss,
  SearchCheck
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import {
  createHistoricalBackfillRun,
  createIngestionRun,
  fetchIngestionCoverage,
  fetchIngestionRun,
  fetchIngestionRuns,
  type IngestionCoverageRecord,
  type IngestionCoverageSource,
  type IngestionRunRecord,
  type IngestionSourceSummary
} from "../api/ingestion";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const runs = ref<IngestionRunRecord[]>([]);
const selectedRunId = ref("");
const loading = ref(false);
const creating = ref(false);
const error = ref("");
const message = ref("");
const mode = ref<"ingestion" | "backfill">("ingestion");
const coverage = ref<IngestionCoverageRecord | null>(null);
const coverageLoading = ref(false);
const coverageDayKey = ref(todayKey());
const normalSourceTypes = ref(["rss", "paper_rss"]);
const backfillSourceTypes = ref(["rss", "paper_rss"]);
const normalTypeOptions = [
  ["rss", "RSS"],
  ["paper_rss", "论文 RSS"],
  ["page_manual", "页面手工"],
  ["page_monitor", "页面监控"]
] as const;
const backfillTypeOptions = [
  ["rss", "RSS"],
  ["paper_rss", "论文 RSS"],
  ["paper_api", "论文 API"],
  ["page_manual", "页面手工"],
  ["page_monitor", "页面监控"]
] as const;

function toggleTypeIn(current: string[], value: string): string[] {
  if (current.includes(value)) {
    return current.length > 1 ? current.filter((item) => item !== value) : current;
  }
  return [...current, value];
}

function toggleNormalType(value: string) {
  normalSourceTypes.value = toggleTypeIn(normalSourceTypes.value, value);
}

function toggleBackfillType(value: string) {
  backfillSourceTypes.value = toggleTypeIn(backfillSourceTypes.value, value);
}
const backfillMode = ref("rss_window");
const normalLimit = ref<number | null>(0);
const backfillLimit = ref<number | null>(0);
const targetDayStart = ref(todayKey());
const targetDayEnd = ref(todayKey());
const includeUndated = ref(false);

const selectedRun = computed(() => {
  return runs.value.find((run) => run.id === selectedRunId.value) ?? runs.value[0] ?? null;
});

const latestRun = computed(() => runs.value[0] ?? null);
const selectedSources = computed(() => (selectedRun.value ? sourceSummaries(selectedRun.value) : []));
const sourceFilter = ref<"all" | "failed" | "productive">("all");

const topCoverageSources = computed(() => {
  const all = coverage.value?.sources ?? [];
  if (sourceFilter.value === "failed") {
    return all.filter((source) => source.run_status === "failed").slice(0, 60);
  }
  if (sourceFilter.value === "productive") {
    return all
      .filter((source) => source.run_status !== "failed" && (source.run_fetched > 0 || source.raw_in_target > 0))
      .slice(0, 60);
  }
  return all.slice(0, 36);
});

const failedSourceCount = computed(
  () => (coverage.value?.sources ?? []).filter((source) => source.run_status === "failed").length
);

function shortError(error: string) {
  const first = (error || "").split("\n")[0];
  return first
    .replace(/^HTTPStatusError:\s*Client error\s*/i, "")
    .replace(/^HTTPStatusError:\s*/i, "")
    .replace(/^ConnectError:\s*$/i, "连接失败")
    .replace(/^ConnectError:\s*/i, "连接失败：")
    .replace(/^ReadTimeout:.*$/i, "读取超时")
    .replace(/^TimeoutError:.*$/i, "抓取超时")
    .replace(/^RemoteProtocolError:.*$/i, "对端断开连接")
    .replace(/\s*for url\s+'([^']+)'.*$/i, "")
    .slice(0, 80);
}
const coverageFunnel = computed(() => {
  const funnel = coverage.value?.funnel;
  if (!funnel) {
    return [];
  }
  return [
    ["启用源", funnel.enabled_sources],
    ["本次运行源", funnel.run_sources],
    ["成功源", funnel.source_succeeded],
    ["目标日 raw", funnel.raw_in_target],
    ["新闻结构", funnel.news_items],
    ["去重 winner", funnel.dedupe_winners],
    ["推荐候选", funnel.recommendation_candidates],
    ["采信成稿", funnel.daily_adopted]
  ];
});
const selectedRunTargetRange = computed(() => {
  const run = selectedRun.value;
  if (!run) {
    return "";
  }
  const start = stringParam(run, "target_day_start");
  const end = stringParam(run, "target_day_end");
  if (!start && !end) {
    return "非补采运行";
  }
  return start === end ? start : `${start} 至 ${end}`;
});

async function loadRuns() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    runs.value = await fetchIngestionRuns(workspace.currentCode, 60);
    if (!runs.value.some((run) => run.id === selectedRunId.value)) {
      selectedRunId.value = runs.value[0]?.id ?? "";
    }
    await loadCoverage();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载抓取运行失败";
  } finally {
    loading.value = false;
  }
}

async function selectRun(run: IngestionRunRecord) {
  selectedRunId.value = run.id;
  error.value = "";
  try {
    replaceRun(await fetchIngestionRun(run.id));
    await loadCoverage();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载运行详情失败";
  }
}

async function loadCoverage() {
  if (!workspace.currentCode) {
    return;
  }
  coverageLoading.value = true;
  try {
    coverage.value = await fetchIngestionCoverage(
      workspace.currentCode,
      coverageDayKey.value,
      selectedRunId.value || undefined
    );
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载覆盖率详情失败";
  } finally {
    coverageLoading.value = false;
  }
}

async function runIngestion() {
  if (!workspace.currentCode) {
    return;
  }
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await createIngestionRun({
      workspace_code: workspace.currentCode,
      source_types: normalSourceTypes.value,
      limit: normalLimit.value
    });
    message.value = `抓取运行已完成：尝试 ${run.source_total} 个源，成功 ${run.source_succeeded}，失败 ${run.source_failed}`;
    await loadRuns();
    selectedRunId.value = run.id;
    await loadCoverage();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建抓取运行失败";
  } finally {
    creating.value = false;
  }
}

async function runBackfill() {
  if (!workspace.currentCode) {
    return;
  }
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await createHistoricalBackfillRun({
      workspace_code: workspace.currentCode,
      target_day_start: targetDayStart.value,
      target_day_end: targetDayEnd.value,
      source_types: backfillSourceTypes.value,
      limit: backfillLimit.value,
      include_undated: includeUndated.value,
      backfill_mode: backfillMode.value
    });
    message.value = `补采运行已完成：目标窗口 ${targetDayStart.value} 至 ${targetDayEnd.value}，入窗 ${summaryNumber(run, "items_in_target_range")}，新建 raw ${run.raw_created}`;
    coverageDayKey.value = targetDayStart.value;
    await loadRuns();
    selectedRunId.value = run.id;
    await loadCoverage();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建历史补采失败";
  } finally {
    creating.value = false;
  }
}

function replaceRun(updated: IngestionRunRecord) {
  const index = runs.value.findIndex((run) => run.id === updated.id);
  if (index >= 0) {
    runs.value.splice(index, 1, updated);
  }
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

function successRate(run: IngestionRunRecord) {
  if (!run.source_total) {
    return "0%";
  }
  return `${Math.round((run.source_succeeded / run.source_total) * 100)}%`;
}

function sourceSummaries(run: IngestionRunRecord): IngestionSourceSummary[] {
  const sources = run.summary_json.sources;
  if (!Array.isArray(sources)) {
    return [];
  }
  return sources.filter((source): source is IngestionSourceSummary => {
    return source !== null && typeof source === "object";
  });
}

function summaryNumber(run: IngestionRunRecord, key: string) {
  const value = run.summary_json[key];
  return typeof value === "number" ? value : 0;
}

function stringParam(run: IngestionRunRecord, key: string) {
  const value = run.params_json[key] ?? run.summary_json[key];
  return typeof value === "string" ? value : "";
}

function sourceNumber(source: IngestionSourceSummary, key: keyof IngestionSourceSummary) {
  const value = source[key];
  return typeof value === "number" ? value : 0;
}

function coverageNumber(source: IngestionCoverageSource, key: keyof IngestionCoverageSource) {
  const value = source[key];
  return typeof value === "number" ? value : 0;
}

function runTypeLabel(runType: string) {
  return runType === "historical_backfill" ? "历史补采" : "常规抓取";
}

function runStatusLabel(status: string) {
  if (status === "completed") {
    return "完成";
  }
  if (status === "failed") {
    return "失败";
  }
  return status;
}

function sourceStatusLabel(status?: string) {
  if (status === "succeeded" || status === "completed") {
    return "成功";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "skipped") {
    return "跳过";
  }
  if (status === "not_run") {
    return "未运行";
  }
  return status || "未知";
}

function sourceTypesLine(run: IngestionRunRecord) {
  const value = run.params_json.source_types;
  return Array.isArray(value) ? value.join(", ") : "未记录";
}

function backfillModeLabel(run: IngestionRunRecord) {
  const value = run.params_json.backfill_mode ?? run.summary_json.backfill_mode;
  return typeof value === "string" ? value : "workspace_fetch";
}

function todayKey() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date());
}

watch(
  () => workspace.currentCode,
  () => {
    runs.value = [];
    selectedRunId.value = "";
    void loadRuns();
  }
);

watch(coverageDayKey, () => {
  void loadCoverage();
});

onMounted(loadRuns);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Ingestion Coverage</p>
        <h2>抓取覆盖率</h2>
        <p>解释数据源是否真实抓取、哪些源失败、raw 新增更新多少，避免误判推荐器漏选。</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadRuns">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button
          v-if="mode === 'ingestion'"
          type="button"
          class="icon-button"
          :disabled="creating"
          @click="runIngestion"
        >
          <PlayCircle :size="17" />
          <span>{{ creating ? "运行中" : "运行抓取" }}</span>
        </button>
        <button v-else type="button" class="icon-button" :disabled="creating" @click="runBackfill">
          <SearchCheck :size="17" />
          <span>{{ creating ? "补采中" : "运行补采" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="module-card compact ingestion-command">
      <div class="policy-tabs ingestion-tabs">
        <button type="button" :class="{ active: mode === 'ingestion' }" @click="mode = 'ingestion'">
          常规抓取
        </button>
        <button type="button" :class="{ active: mode === 'backfill' }" @click="mode = 'backfill'">
          历史补采
        </button>
      </div>

      <div v-if="mode === 'ingestion'" class="run-command">
        <div class="run-field">
          <span class="run-field-label">源类型</span>
          <div class="type-toggle-group" role="group" aria-label="源类型">
            <button
              v-for="[value, label] in normalTypeOptions"
              :key="value"
              type="button"
              :class="{ active: normalSourceTypes.includes(value) }"
              @click="toggleNormalType(value)"
            >
              {{ label }}
            </button>
          </div>
        </div>
        <label>
          源数量上限
          <input v-model.number="normalLimit" type="number" min="0" placeholder="0 为验收链路" />
        </label>
        <p class="muted-line">limit=0 只验收接口和权限，不触发真实外网抓取；空值表示按当前工作台启用源全量抓取。</p>
      </div>

      <div v-else class="run-command backfill-command">
        <label>
          开始日期
          <span class="input-with-icon">
            <CalendarDays :size="16" />
            <input v-model="targetDayStart" type="date" />
          </span>
        </label>
        <label>
          结束日期
          <span class="input-with-icon">
            <CalendarDays :size="16" />
            <input v-model="targetDayEnd" type="date" />
          </span>
        </label>
        <label>
          补采模式
          <select v-model="backfillMode">
            <option value="rss_window">RSS 当前窗口</option>
            <option value="paper_api">论文 API / 论文源</option>
            <option value="archive_page">归档页面</option>
            <option value="sitemap">站点 Sitemap</option>
            <option value="manual_import">手工导入</option>
          </select>
        </label>
        <div class="run-field">
          <span class="run-field-label">源类型</span>
          <div class="type-toggle-group" role="group" aria-label="补采源类型">
            <button
              v-for="[value, label] in backfillTypeOptions"
              :key="value"
              type="button"
              :class="{ active: backfillSourceTypes.includes(value) }"
              @click="toggleBackfillType(value)"
            >
              {{ label }}
            </button>
          </div>
        </div>
        <label>
          源数量上限
          <input v-model.number="backfillLimit" type="number" min="0" placeholder="0 为安全验收" />
        </label>
        <label class="switch-row">
          <input v-model="includeUndated" type="checkbox" />
          纳入无发布日期条目
        </label>
        <p class="muted-line">
          rss_window 只能补回当前 feed 窗口中仍存在的历史条目；sitemap/归档页依赖数据源 fetch_config 中配置的 sitemap_url、archive_url 或 page_url；manual_import 预留后端入口，当前页面暂不上传文件。
        </p>
      </div>
    </section>

    <section class="module-card compact coverage-overview">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Coverage Funnel</p>
          <h3>目标日链路覆盖</h3>
          <p class="muted-line">
            从启用源、本次抓取、目标日 raw、新闻结构、去重 winner、推荐候选到日报采信逐层追溯。
          </p>
        </div>
        <label class="input-with-icon coverage-day">
          <CalendarDays :size="16" />
          <input v-model="coverageDayKey" type="date" />
        </label>
      </div>

      <div v-if="coverageLoading" class="empty-state compact">覆盖率加载中...</div>
      <template v-else-if="coverage">
        <div class="coverage-funnel">
          <template v-for="([label, value], index) in coverageFunnel" :key="label">
            <article>
              <strong>{{ value }}</strong>
              <span>{{ label }}</span>
            </article>
            <ArrowRight v-if="index < coverageFunnel.length - 1" :size="16" />
          </template>
        </div>
        <div class="coverage-strip">
          <span>运行：{{ coverage.run_key || "未选择" }}</span>
          <span>窗口：{{ coverage.target_range }}</span>
          <span>推荐：{{ coverage.recommendation_run_key || "未生成" }}</span>
          <span>日报：{{ coverage.daily_report_status || "未生成" }}</span>
        </div>
      </template>
      <p v-else class="empty-state compact">选择工作台和日期后查看覆盖漏斗。</p>
    </section>

    <div v-if="latestRun" class="module-stats">
      <article>
        <strong>{{ latestRun.source_total }}</strong>
        <span>尝试源</span>
      </article>
      <article>
        <strong>{{ latestRun.source_succeeded }}</strong>
        <span>成功源</span>
      </article>
      <article>
        <strong>{{ latestRun.source_failed }}</strong>
        <span>失败源</span>
      </article>
      <article>
        <strong>{{ successRate(latestRun) }}</strong>
        <span>成功率</span>
      </article>
    </div>

    <section class="module-split ingestion-layout">
      <aside class="module-card run-list">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Run History</p>
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
          <span>{{ runTypeLabel(run.run_type) }} · {{ runStatusLabel(run.status) }} · {{ formatDateTime(run.completed_at || run.started_at) }}</span>
        </button>
        <p v-if="!loading && runs.length === 0" class="empty-state">暂无抓取运行，点击“新建抓取”或由 scheduler 生成第一次运行。</p>
      </aside>

      <article class="module-card run-detail">
        <div v-if="selectedRun" class="card-title-row">
          <div>
            <p class="eyebrow">{{ runTypeLabel(selectedRun.run_type) }} · {{ selectedRun.workspace_code }}</p>
            <h3>{{ selectedRun.run_key }}</h3>
            <p class="muted-line">
              {{ sourceTypesLine(selectedRun) }} · {{ selectedRunTargetRange }} · {{ backfillModeLabel(selectedRun) }}
            </p>
          </div>
          <div class="module-mini-stats">
            <span>fetched {{ selectedRun.items_fetched }}</span>
            <span>raw +{{ selectedRun.raw_created }}/{{ selectedRun.raw_updated }}</span>
            <span v-if="selectedRun.run_type === 'historical_backfill'">
              入窗 {{ summaryNumber(selectedRun, "items_in_target_range") }}
            </span>
          </div>
        </div>
        <div v-if="!selectedRun" class="empty-state">选择一次运行查看每源覆盖详情。</div>
        <template v-else>
          <div v-if="selectedRun.run_type === 'historical_backfill'" class="coverage-strip">
            <span>目标窗口：{{ selectedRunTargetRange }}</span>
            <span>入窗 {{ summaryNumber(selectedRun, "items_in_target_range") }}</span>
            <span>窗外 {{ summaryNumber(selectedRun, "items_out_of_target_range") }}</span>
            <span>缺日期 {{ summaryNumber(selectedRun, "items_missing_published_at") }}</span>
          </div>

          <div class="coverage-filter" role="tablist" aria-label="源明细筛选">
            <button type="button" :class="{ active: sourceFilter === 'all' }" @click="sourceFilter = 'all'">全部</button>
            <button type="button" :class="{ active: sourceFilter === 'productive' }" @click="sourceFilter = 'productive'">
              有产出
            </button>
            <button type="button" :class="{ active: sourceFilter === 'failed' }" @click="sourceFilter = 'failed'">
              失败 {{ failedSourceCount }}
            </button>
          </div>

          <div class="source-coverage-list">
            <article
              v-for="source in topCoverageSources"
              :key="source.data_source_id"
              class="source-coverage-row"
              :class="{ failed: source.run_status === 'failed' }"
            >
              <div class="feed-icon" :class="{ indigo: source.run_status === 'succeeded' || source.run_status === 'completed' }">
                <Rss v-if="source.source_type === 'rss' || source.source_type === 'paper_rss'" :size="18" />
                <Database v-else :size="18" />
              </div>
              <div class="source-coverage-main">
                <div class="candidate-heading">
                  <div>
                    <h3>{{ source.name || "未命名数据源" }}</h3>
                    <p class="muted-line">{{ source.source_type || "unknown" }}</p>
                  </div>
                  <span class="status-on" :class="{ failed: source.run_status === 'failed' }">
                    {{ sourceStatusLabel(source.run_status) }}
                  </span>
                </div>
                <div v-if="source.run_status !== 'failed'" class="coverage-metrics">
                  <span>抓取 {{ coverageNumber(source, "run_fetched") }}</span>
                  <span>新建 {{ coverageNumber(source, "run_created") }}</span>
                  <span>入窗 {{ coverageNumber(source, "in_target_range") || coverageNumber(source, "raw_in_target") }}</span>
                  <span>新闻 {{ coverageNumber(source, "news_items") }}</span>
                  <span>winner {{ coverageNumber(source, "dedupe_winners") }}</span>
                  <span>推荐 {{ coverageNumber(source, "recommendation_selected") }}/{{ coverageNumber(source, "recommendation_candidates") }}</span>
                  <span>采信 {{ coverageNumber(source, "daily_adopted") }}</span>
                </div>
                <details v-if="source.error" class="source-error-fold">
                  <summary>
                    <AlertCircle :size="13" />
                    <span>{{ shortError(source.error) }}</span>
                  </summary>
                  <p>{{ source.error }}</p>
                </details>
              </div>
              <CheckCircle2 v-if="source.run_status === 'succeeded' || source.run_status === 'completed'" :size="18" />
            </article>
            <p v-if="topCoverageSources.length === 0" class="empty-state">这次运行没有每源明细，可能是 limit=0 或旧运行记录。</p>
          </div>
        </template>
      </article>
    </section>
  </section>
</template>
