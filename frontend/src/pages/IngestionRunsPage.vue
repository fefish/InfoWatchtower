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
import { useRoute } from "vue-router";

import {
  createHistoricalBackfillRun,
  createIngestionRun,
  fetchFailedSourceRetrySummary,
  fetchIngestionCoverage,
  fetchIngestionCoverageTrends,
  fetchIngestionRun,
  fetchIngestionRuns,
  fetchSchedulerConfig,
  previewManualImport,
  retryFailedIngestionRun,
  type IngestionCoverageRecord,
  type IngestionCoverageSource,
  type IngestionCoverageTrendsRecord,
  type IngestionCoverageTrendPoint,
  type IngestionFailedSourceRetrySummaryRecord,
  type IngestionRunRecord,
  type IngestionSourceSummary,
  type ManualImportPreviewRecord,
  type SchedulerConfigRecord
} from "../api/ingestion";
import { fetchSources, type DataSourceRecord } from "../api/sources";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const runtime = useRuntimeStore();
const route = useRoute();
const runs = ref<IngestionRunRecord[]>([]);
const selectedRunId = ref("");
const loading = ref(false);
const creating = ref(false);
const retrying = ref(false);
const error = ref("");
const message = ref("");
const messageTone = ref<"success" | "info" | "warning">("success");
const mode = ref<"ingestion" | "backfill">("ingestion");
const coverage = ref<IngestionCoverageRecord | null>(null);
const coverageLoading = ref(false);
const coverageDayKey = ref(todayKey());
const coverageTrends = ref<IngestionCoverageTrendsRecord | null>(null);
const coverageTrendsLoading = ref(false);
const failedSourceRetrySummary = ref<IngestionFailedSourceRetrySummaryRecord | null>(null);
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
  clearManualImportPreview();
}
const backfillMode = ref("rss_window");
// 空 = 按当前工作台启用源全量抓取；0 不再允许，避免空跑被误判为成功。
const normalLimit = ref<number | null>(null);
const backfillLimit = ref<number | null>(null);
const targetDayStart = ref(todayKey());
const targetDayEnd = ref(todayKey());
const includeUndated = ref(false);
const manualSourceOptions = ref<DataSourceRecord[]>([]);
const manualImportSourceId = ref("");
const manualImportText = ref("");
const manualImportError = ref("");
const manualImportFilename = ref("");
const manualImportFormat = ref<"auto" | "csv" | "sql">("auto");
const manualImportPreview = ref<ManualImportPreviewRecord | null>(null);
const previewingManualImport = ref(false);

const selectedRun = computed(() => {
  return runs.value.find((run) => run.id === selectedRunId.value) ?? runs.value[0] ?? null;
});

const latestRun = computed(() => runs.value[0] ?? null);
const selectedSources = computed(() => (selectedRun.value ? sourceSummaries(selectedRun.value) : []));
const sourceFilter = ref<"all" | "failed" | "productive">("all");

// 推入式源语义（backend-capability-test-matrix §3.1）：manual/internal 定时抓取
// 如实返回 0 条新增是正常行为（run 里计成功源），不要被误读成源坏了。
const PUSH_BASED_HINT = "推入式源：由手工导入/内部系统写入，定时抓取 0 条是正常行为";

function isPushBasedType(type?: string) {
  return type === "manual" || type === "internal";
}

// run 摘要分组小计：部署级源类型清单跳过（skipped_type_disabled）与推入式 0 条源。
const selectedRunSkippedTypeDisabled = computed(() => {
  const run = selectedRun.value;
  if (!run) {
    return 0;
  }
  const total = summaryNumber(run, "source_skipped_type_disabled");
  if (total > 0) {
    return total;
  }
  return selectedSources.value.filter((source) => source.status === "skipped_type_disabled").length;
});

const selectedRunPushBasedZero = computed(() =>
  selectedSources.value.filter(
    (source) =>
      isPushBasedType(source.source_type) &&
      source.status !== "failed" &&
      sourceNumber(source, "fetched") === 0
  ).length
);

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
const messageClass = computed(() => {
  if (messageTone.value === "warning") {
    return "form-warning";
  }
  if (messageTone.value === "info") {
    return "form-info";
  }
  return "form-success";
});

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
const coverageTrendPoints = computed(() => coverageTrends.value?.points ?? []);
const trendMaxRawCreated = computed(() => Math.max(1, ...coverageTrendPoints.value.map((point) => point.raw_created)));
const trendMaxFailures = computed(() => Math.max(1, ...coverageTrendPoints.value.map((point) => point.source_failed)));
const recentTrendSummary = computed(() => {
  const trends = coverageTrends.value;
  if (!trends) {
    return "暂无趋势数据";
  }
  return `近 ${trends.days} 天 ${trends.total_runs} 次运行，新增 raw ${trends.total_raw_created}，失败源 ${trends.total_source_failed}，平均成功率 ${percent(trends.average_success_rate)}`;
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
    const anchored = await applyRouteRunAnchor();
    if (!anchored && !runs.value.some((run) => run.id === selectedRunId.value)) {
      selectedRunId.value = runs.value[0]?.id ?? "";
    }
    await loadCoverage();
    await loadCoverageTrends();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载抓取运行失败";
  } finally {
    loading.value = false;
  }
}

async function applyRouteRunAnchor() {
  const runId = routeRunId();
  if (!runId) {
    return false;
  }
  let run = runs.value.find((candidate) => candidate.id === runId);
  if (!run) {
    try {
      const fetched = await fetchIngestionRun(runId);
      if (fetched.workspace_code !== workspace.currentCode) {
        return false;
      }
      runs.value = [fetched, ...runs.value.filter((candidate) => candidate.id !== fetched.id)];
      run = fetched;
    } catch {
      return false;
    }
  }
  selectedRunId.value = run.id;
  return true;
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

async function loadCoverageTrends() {
  if (!workspace.currentCode) {
    return;
  }
  coverageTrendsLoading.value = true;
  try {
    coverageTrends.value = await fetchIngestionCoverageTrends(workspace.currentCode, 14);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载覆盖趋势失败";
  } finally {
    coverageTrendsLoading.value = false;
  }
}

async function runIngestion() {
  if (!workspace.currentCode) {
    return;
  }
  if (!(await canStartRun(normalSourceTypes.value, normalLimit.value))) {
    return;
  }
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await createIngestionRun({
      workspace_code: workspace.currentCode,
      source_types: normalSourceTypes.value,
      limit: typeof normalLimit.value === "number" ? normalLimit.value : null
    });
    setRunMessage(run, "抓取运行");
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
  let manualItems: Record<string, unknown>[] = [];
  if (backfillMode.value === "manual_import") {
    await loadManualSourceOptions();
  }
  if (!(await canStartRun(backfillSourceTypes.value, backfillLimit.value))) {
    return;
  }
  if (backfillMode.value === "manual_import") {
    const preview = manualImportPreview.value;
    if (!preview || preview.accepted_count <= 0) {
      const warning = "请先预览手工导入，并确保至少有 1 条可导入记录。";
      manualImportError.value = warning;
      messageTone.value = "warning";
      message.value = warning;
      return;
    }
    manualItems = preview.accepted_items;
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
      limit: typeof backfillLimit.value === "number" ? backfillLimit.value : null,
      include_undated: includeUndated.value,
      backfill_mode: backfillMode.value,
      manual_items: backfillMode.value === "manual_import" ? manualItems : undefined
    });
    if (run.status === "no_sources") {
      setRunMessage(run, "补采运行");
    } else if (backfillMode.value === "manual_import") {
      messageTone.value = "success";
      message.value = `手工导入已完成：提交 ${manualItems.length} 条，入窗 ${summaryNumber(run, "items_in_target_range")}，新建 raw ${run.raw_created}`;
      manualImportPreview.value = null;
    } else {
      messageTone.value = "success";
      message.value = `补采运行已完成：目标窗口 ${targetDayStart.value} 至 ${targetDayEnd.value}，入窗 ${summaryNumber(run, "items_in_target_range")}，新建 raw ${run.raw_created}`;
    }
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

async function loadManualSourceOptions() {
  if (!workspace.currentCode) {
    manualSourceOptions.value = [];
    return [];
  }
  const sources = await fetchSources(workspace.currentCode);
  const enabled = enabledSourcesForTypes(sources, backfillSourceTypes.value);
  manualSourceOptions.value = enabled;
  if (!enabled.some((source) => source.id === manualImportSourceId.value)) {
    manualImportSourceId.value = enabled.length === 1 ? enabled[0].id : "";
  }
  return enabled;
}

async function retryFailedSources() {
  const run = selectedRun.value;
  if (!run) {
    return;
  }
  if (!runtime.canIngest) {
    messageTone.value = "warning";
    message.value = "当前部署形态为只读消费模式，不能在本地重试失败源。";
    return;
  }
  retrying.value = true;
  error.value = "";
  message.value = "";
  try {
    const retryRun = await retryFailedIngestionRun(run.id);
    setRunMessage(retryRun, "失败源重试");
    await loadRuns();
    selectedRunId.value = retryRun.id;
    await loadCoverage();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "重试失败源失败";
  } finally {
    retrying.value = false;
  }
}

async function canStartRun(sourceTypes: string[], limit: number | null) {
  if (!runtime.canIngest) {
    messageTone.value = "warning";
    message.value = "当前部署形态为只读消费模式，不能在本地发起抓取或补采。";
    return false;
  }
  if (typeof limit === "number" && limit < 1) {
    messageTone.value = "warning";
    message.value = "本次运行源数上限必须为空或大于 0。空表示全部启用源。";
    return false;
  }
  if (!workspace.currentCode) {
    return false;
  }
  const allSources = await fetchSources(workspace.currentCode);
  const enabled = enabledSourcesForTypes(allSources, sourceTypes);
  if (enabled.length === 0) {
    messageTone.value = "warning";
    message.value = "当前工作台在所选源类型下没有启用源，请先到数据源管理启用或补入口。";
    return false;
  }
  return true;
}

function enabledSourcesForTypes(sources: DataSourceRecord[], sourceTypes: string[]) {
  return sources.filter(
    (source) =>
      source.enabled &&
      source.workspace_link_enabled &&
      sourceTypes.includes(source.source_type)
  );
}

async function previewManualImportRows() {
  manualImportError.value = "";
  manualImportPreview.value = null;
  if (!workspace.currentCode) {
    return;
  }
  if (!manualImportText.value.trim()) {
    const warning = "请上传或粘贴 CSV/SQL 内容后再预览。";
    manualImportError.value = warning;
    messageTone.value = "warning";
    message.value = warning;
    return;
  }
  previewingManualImport.value = true;
  error.value = "";
  try {
    const preview = await previewManualImport({
      workspace_code: workspace.currentCode,
      source_types: backfillSourceTypes.value,
      default_data_source_id: manualImportSourceId.value.trim(),
      input_text: manualImportText.value,
      input_format: manualImportFormat.value,
      filename: manualImportFilename.value
    });
    manualImportPreview.value = preview;
    if (preview.accepted_count > 0) {
      messageTone.value = preview.rejected_count > 0 ? "info" : "success";
      message.value = `手工导入预览完成：可导入 ${preview.accepted_count} 条，需修正 ${preview.rejected_count} 条。`;
    } else {
      const warning = "手工导入预览没有可导入记录，请下载错误报告并修正后重试。";
      manualImportError.value = warning;
      messageTone.value = "warning";
      message.value = warning;
    }
  } catch (exc) {
    const warning = exc instanceof Error ? exc.message : "手工导入预览失败";
    manualImportError.value = warning;
    messageTone.value = "warning";
    message.value = warning;
  } finally {
    previewingManualImport.value = false;
  }
}

async function handleManualImportFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) {
    return;
  }
  manualImportFilename.value = file.name;
  manualImportText.value = await file.text();
  if (manualImportFormat.value === "auto") {
    const lowerName = file.name.toLowerCase();
    if (lowerName.endsWith(".sql")) {
      manualImportFormat.value = "sql";
    } else if (lowerName.endsWith(".csv")) {
      manualImportFormat.value = "csv";
    }
  }
  clearManualImportPreview();
}

function clearManualImportPreview() {
  manualImportPreview.value = null;
  manualImportError.value = "";
}

function downloadManualImportErrorReport() {
  const report = manualImportPreview.value?.error_report_csv || "";
  if (!report) {
    return;
  }
  const blob = new Blob([report], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${manualImportFilename.value || "manual-import"}-error-report.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function setRunMessage(run: IngestionRunRecord, prefix: string) {
  if (run.status === "no_sources") {
    messageTone.value = "warning";
    message.value = `${prefix}未执行：${String((run.summary_json ?? {}).hint || "没有匹配的启用源。")}`;
    return;
  }
  const skipped = summaryNumber(run, "source_skipped_unimplemented");
  if (run.status === "skipped_unimplemented" || skipped > 0) {
    messageTone.value = run.items_fetched > 0 ? "info" : "warning";
    message.value = `${prefix}包含 ${skipped || run.source_total} 个尚未实现的源类型：这些源未计入成功或失败，请查看每源明细。`;
    return;
  }
  const typeDisabled = summaryNumber(run, "source_skipped_type_disabled");
  if (typeDisabled > 0) {
    messageTone.value = "info";
    message.value = `${prefix}已完成：${typeDisabled} 个源因部署级源类型允许清单被跳过（类型停用），成功 ${run.source_succeeded}，失败 ${run.source_failed}，请查看每源明细。`;
    return;
  }
  if (run.items_fetched === 0) {
    messageTone.value = "info";
    message.value = `${prefix}已完成但未返回条目：尝试 ${run.source_total} 个源，成功 ${run.source_succeeded}，失败 ${run.source_failed}。请查看每源明细和 RSS 窗口。`;
    return;
  }
  messageTone.value = "success";
  message.value = `${prefix}已完成：尝试 ${run.source_total} 个源，成功 ${run.source_succeeded}，失败 ${run.source_failed}`;
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
  const sources = (run.summary_json ?? {}).sources;
  if (!Array.isArray(sources)) {
    return [];
  }
  return sources.filter((source): source is IngestionSourceSummary => {
    return source !== null && typeof source === "object";
  });
}

function summaryNumber(run: IngestionRunRecord, key: string) {
  const value = (run.summary_json ?? {})[key];
  return typeof value === "number" ? value : 0;
}

function stringParam(run: IngestionRunRecord, key: string) {
  const value = (run.params_json ?? {})[key] ?? (run.summary_json ?? {})[key];
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

function trendRawHeight(point: IngestionCoverageTrendPoint) {
  return `${Math.max(4, Math.round((point.raw_created / trendMaxRawCreated.value) * 100))}%`;
}

function trendFailureHeight(point: IngestionCoverageTrendPoint) {
  return `${Math.max(3, Math.round((point.source_failed / trendMaxFailures.value) * 100))}%`;
}

function percent(value: number) {
  return `${Math.round((value || 0) * 100)}%`;
}

function runTypeLabel(runType: string) {
  return runType === "historical_backfill" ? "历史补采" : "常规抓取";
}

function runStatusLabel(status: string) {
  if (status === "completed") {
    return "完成";
  }
  if (status === "partial") {
    return "部分完成";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "no_sources") {
    return "无可用源";
  }
  if (status === "skipped_unimplemented") {
    return "源类型未实现";
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
  if (status === "skipped_unimplemented") {
    return "尚未实现";
  }
  if (status === "skipped_type_disabled") {
    return "类型停用";
  }
  if (status === "not_run") {
    return "未运行";
  }
  return status || "未知";
}

function sourceTypesLine(run: IngestionRunRecord) {
  const value = (run.params_json ?? {}).source_types;
  return Array.isArray(value) ? value.join(", ") : "未记录";
}

function backfillModeLabel(run: IngestionRunRecord) {
  const value = (run.params_json ?? {}).backfill_mode ?? (run.summary_json ?? {}).backfill_mode;
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

function routeRunId() {
  const value = route.query.run_id;
  return typeof value === "string" ? value : "";
}

watch(
  () => workspace.currentCode,
  () => {
    runs.value = [];
    selectedRunId.value = "";
    clearManualImportPreview();
    void loadRuns();
    void loadCoverageTrends();
    void loadFailedSourceRetrySummary();
  }
);

watch(
  () => route.query.run_id,
  async () => {
    if (await applyRouteRunAnchor()) {
      await loadCoverage();
    }
  }
);

watch(coverageDayKey, () => {
  void loadCoverage();
});

watch(
  [backfillMode, backfillSourceTypes],
  () => {
    if (backfillMode.value === "manual_import") {
      void loadManualSourceOptions();
    }
    clearManualImportPreview();
  },
  { deep: true }
);

const schedulerConfig = ref<SchedulerConfigRecord | null>(null);

async function loadSchedulerConfig() {
  schedulerConfig.value = await fetchSchedulerConfig().catch(() => null);
}

async function loadFailedSourceRetrySummary() {
  if (!workspace.currentCode) {
    failedSourceRetrySummary.value = null;
    return;
  }
  failedSourceRetrySummary.value = await fetchFailedSourceRetrySummary(workspace.currentCode).catch(() => null);
}

function retryPolicyLine() {
  const summary = failedSourceRetrySummary.value;
  const policy = summary?.policy ?? {};
  const enabled = Boolean(policy.enabled ?? schedulerConfig.value?.failed_source_auto_retry_enabled);
  const attempts = policy.max_attempts ?? schedulerConfig.value?.failed_source_retry_max_attempts ?? 0;
  const limit = policy.limit ?? schedulerConfig.value?.failed_source_retry_limit ?? 0;
  if (!summary) {
    return "状态未知";
  }
  return `${enabled ? "已开启" : "未开启"} · 到期 ${summary.due_count} · 阻塞 ${summary.blocked_count} · 上限 ${attempts} 次 / ${limit} run`;
}

onMounted(() => {
  void loadRuns();
  void loadSchedulerConfig();
  void loadCoverageTrends();
  void loadFailedSourceRetrySummary();
});
</script>

<template>
  <section class="layout-list">
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
          v-if="runtime.canIngest && mode === 'ingestion'"
          type="button"
          class="icon-button"
          :disabled="creating"
          @click="runIngestion"
        >
          <PlayCircle :size="17" />
          <span>{{ creating ? "运行中" : "运行抓取" }}</span>
        </button>
        <button v-else-if="runtime.canIngest" type="button" class="icon-button" :disabled="creating" @click="runBackfill">
          <SearchCheck :size="17" />
          <span>{{ creating ? "补采中" : "运行补采" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" :class="messageClass">{{ message }}</p>

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
          本次运行源数上限
          <input v-model.number="normalLimit" type="number" min="1" placeholder="空 = 全部启用源" />
        </label>
        <p class="muted-line">留空按当前工作台全部启用源真实抓取；源数上限必须大于 0。自动定时抓取见下方「自动调度」卡片。</p>
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
          本次运行源数上限
          <input v-model.number="backfillLimit" type="number" min="1" placeholder="空 = 全部启用源" />
        </label>
        <template v-if="backfillMode === 'manual_import'">
          <label>
            手工条目归属源
            <select v-model="manualImportSourceId" @focus="loadManualSourceOptions" @change="clearManualImportPreview">
              <option value="">选择已启用数据源</option>
              <option v-for="source in manualSourceOptions" :key="source.id" :value="source.id">
                {{ source.name }} · {{ source.source_type }}
              </option>
            </select>
          </label>
          <label>
            导入格式
            <select v-model="manualImportFormat" @change="clearManualImportPreview">
              <option value="auto">自动识别</option>
              <option value="csv">CSV</option>
              <option value="sql">SQL INSERT</option>
            </select>
          </label>
          <label>
            上传文件
            <input type="file" accept=".csv,.sql,.txt,text/csv,text/plain" @change="handleManualImportFile" />
          </label>
          <label class="manual-import-field">
            CSV / SQL / 粘贴条目
            <textarea
              v-model="manualImportText"
              rows="5"
              @input="clearManualImportPreview"
              placeholder="source_title,source_url,raw_content,published_at&#10;示例新闻,https://example.com/news,正文,2026-07-05T09:00:00Z"
            />
          </label>
          <div class="inline-actions">
            <button type="button" class="mini-action active" :disabled="previewingManualImport" @click="previewManualImportRows">
              <SearchCheck :size="15" />
              <span>{{ previewingManualImport ? "预览中" : "预览导入" }}</span>
            </button>
            <button
              v-if="manualImportPreview?.error_report_csv"
              type="button"
              class="mini-action"
              @click="downloadManualImportErrorReport"
            >
              下载错误报告
            </button>
          </div>
          <div v-if="manualImportPreview" class="manual-preview-summary">
            <strong>预览结果：可导入 {{ manualImportPreview.accepted_count }} 条，需修正 {{ manualImportPreview.rejected_count }} 条</strong>
            <p>{{ manualImportPreview.filename || "粘贴内容" }} · {{ manualImportPreview.input_format }} · 共 {{ manualImportPreview.total_rows }} 行</p>
            <ul v-if="manualImportPreview.errors.length">
              <li v-for="item in manualImportPreview.errors.slice(0, 3)" :key="`${item.row_number}-${item.code}`">
                第 {{ item.row_number }} 行：{{ item.message }}
              </li>
            </ul>
          </div>
          <p v-if="manualImportError" class="form-warning">{{ manualImportError }}</p>
          <p class="muted-line">
            CSV 第一行必须是表头；SQL v1 只支持带列名的 INSERT ... VALUES。支持 data_source_id/source_id、source_title/title、source_url/url、raw_content/content/summary、published_at、entry_key。未提供 data_source_id 时使用上方归属源。
          </p>
        </template>
        <label class="switch-row">
          <input v-model="includeUndated" type="checkbox" />
          纳入无发布日期条目
        </label>
        <p class="muted-line">
          rss_window 只能补回当前 feed 窗口中仍存在的历史条目；sitemap/归档页依赖数据源 fetch_config 中配置的 sitemap_url、archive_url 或 page_url；manual_import 会把粘贴条目写入 raw_items 并保留原始 payload。
        </p>
      </div>
    </section>

    <section class="module-card compact scheduler-card" aria-label="自动调度">
      <div class="scheduler-card-head">
        <div>
          <p class="eyebrow">Scheduler</p>
          <h3>自动调度</h3>
        </div>
        <span class="report-status" :data-tone="schedulerConfig?.enabled ? 'ok' : 'warn'">
          {{ schedulerConfig ? (schedulerConfig.enabled ? "已开启" : "未开启") : "未知" }}
        </span>
      </div>
      <div v-if="schedulerConfig" class="scheduler-facts">
        <span>每日 {{ schedulerConfig.daily_time || "—" }}（{{ schedulerConfig.timezone }}）</span>
        <span>模式：{{ schedulerConfig.job_mode === "daily_pipeline" ? "抓取→去重→推荐→日报全链路" : "仅抓取" }}</span>
        <span>目标日偏移：{{ schedulerConfig.day_offset_days }} 天</span>
        <span>单源上限：{{ schedulerConfig.max_items_per_source ?? "不限" }}</span>
        <span>失败源自动重试：{{ retryPolicyLine() }}</span>
      </div>
      <div v-if="failedSourceRetrySummary?.runs.length" class="coverage-strip">
        <span v-for="run in failedSourceRetrySummary.runs.slice(0, 3)" :key="run.run_id">
          {{ run.due ? "到期" : run.blocked ? "阻塞" : "等待" }} · {{ run.failed_source_count }} 源 · {{ run.run_key }}
        </span>
      </div>
      <p class="muted-line">{{ schedulerConfig?.config_hint || "固定抓取时间通过部署 env 的 INGESTION_SCHEDULER_* 配置，改后重启 scheduler 服务生效。" }}</p>
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

    <section class="module-card compact coverage-trends" aria-label="近14日覆盖趋势">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Coverage Trend</p>
          <h3>近 14 日覆盖趋势</h3>
          <p class="muted-line">{{ recentTrendSummary }}</p>
        </div>
        <span class="metric-pill">{{ percent(coverageTrends?.average_success_rate ?? 0) }} 成功率</span>
      </div>
      <div v-if="coverageTrendsLoading" class="empty-state compact">覆盖趋势加载中...</div>
      <template v-else-if="coverageTrends">
        <div class="coverage-trend-bars" role="list" aria-label="每日 raw 新增和失败源趋势">
          <article v-for="point in coverageTrendPoints" :key="point.day_key" role="listitem" class="coverage-trend-day">
            <div class="coverage-trend-columns">
              <span class="coverage-trend-bar raw" :style="{ height: trendRawHeight(point) }" :title="`raw 新增 ${point.raw_created}`" />
              <span class="coverage-trend-bar failed" :style="{ height: trendFailureHeight(point) }" :title="`失败源 ${point.source_failed}`" />
            </div>
            <strong>{{ point.raw_created }}</strong>
            <span>{{ point.day_key.slice(5) }}</span>
          </article>
        </div>
        <div v-if="coverageTrends.top_failed_sources.length" class="coverage-failure-list">
          <article v-for="source in coverageTrends.top_failed_sources.slice(0, 4)" :key="source.data_source_id">
            <div>
              <strong>{{ source.name }}</strong>
              <span>{{ source.source_type }} · {{ source.failure_count }} 次失败</span>
            </div>
            <p>{{ shortError(source.last_error) || "无错误摘要" }}</p>
          </article>
        </div>
        <p v-else class="empty-state compact">近 14 日没有失败源记录。</p>
      </template>
      <p v-else class="empty-state compact">暂无趋势数据。</p>
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
            <button
              v-if="runtime.canIngest && selectedRun.source_failed > 0"
              type="button"
              class="icon-button compact"
              :disabled="retrying"
              @click="retryFailedSources"
            >
              <RefreshCw :size="15" />
              <span>{{ retrying ? "重试中" : `重试失败源 ${selectedRun.source_failed}` }}</span>
            </button>
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

          <div
            v-if="selectedRunSkippedTypeDisabled > 0 || selectedRunPushBasedZero > 0"
            class="coverage-strip run-semantics-strip"
            aria-label="run 语义分组提示"
          >
            <span v-if="selectedRunSkippedTypeDisabled > 0">
              类型停用跳过 {{ selectedRunSkippedTypeDisabled }} 源：部署级源类型允许清单未包含，未计成功或失败
            </span>
            <span v-if="selectedRunPushBasedZero > 0" :title="PUSH_BASED_HINT">
              推入式 0 条 {{ selectedRunPushBasedZero }} 源：由手工导入/内部系统写入，定时抓取不产出属正常
            </span>
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
              :class="{
                failed: source.run_status === 'failed',
                skipped:
                  source.run_status === 'skipped_unimplemented' ||
                  source.run_status === 'skipped_type_disabled'
              }"
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
                  <span
                    v-if="isPushBasedType(source.source_type)"
                    class="meta-chip push-based-chip"
                    :title="PUSH_BASED_HINT"
                  >
                    推入式
                  </span>
                  <span
                    class="status-on"
                    :class="{
                      failed: source.run_status === 'failed',
                      skipped:
                        source.run_status === 'skipped_unimplemented' ||
                        source.run_status === 'skipped_type_disabled'
                    }"
                  >
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
            <p v-if="topCoverageSources.length === 0" class="empty-state">这次运行没有每源明细，可能是没有匹配启用源或旧运行记录。</p>
          </div>
        </template>
      </article>
    </section>
  </section>
</template>
