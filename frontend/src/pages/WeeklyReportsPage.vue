<script setup lang="ts">
import {
  ArrowDown,
  ArrowUp,
  Bell,
  CalendarRange,
  CheckCircle2,
  CircleSlash2,
  ExternalLink,
  FileText,
  Pencil,
  RefreshCw,
  Save,
  Send,
  Sparkles
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createWeeklyReport,
  createWeeklyReportItemEntityMilestone,
  createWeeklyReportItemInsight,
  fetchWeeklyReport,
  fetchWeeklyReports,
  publishWeeklyReport,
  updateWeeklyReportItem,
  type WeeklyReportItemRecord,
  type WeeklyReportRecord
} from "../api/reports";
import {
  fetchReportFormats,
  weeklyRenditionExportUrl,
  type ReportFormatRecord
} from "../api/renditions";
import {
  fetchObjectWatcher,
  updateObjectWatcher,
  type ObjectWatcherRecord
} from "../api/watchers";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const route = useRoute();
const reports = ref<WeeklyReportRecord[]>([]);
const loading = ref(false);
const creating = ref(false);
const publishingId = ref("");
const actingItemId = ref("");
const strategyItemId = ref("");
const milestoneItemId = ref("");
const milestoneSavingId = ref("");
const watchingItemId = ref("");
const savingItemId = ref("");
const editingItemId = ref("");
const selectedReportId = ref("");
const error = ref("");
const message = ref("");
const weekKey = ref(currentIsoWeekKey());
const draftLimit = ref(50);
const includeUnpublishedDaily = ref(false);
const selectedBoard = ref("all");
const milestoneDrafts = ref<Record<string, string>>({});
const watchersByItem = ref<Record<string, ObjectWatcherRecord>>({});
const loadingWatcherIds = ref<Record<string, boolean>>({});
const roleRank: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3
};
const canCreateStrategyLoop = computed(
  () => roleRank[workspace.current?.current_user_workspace_role ?? ""] >= 2
);
const canCreateEntityMilestone = computed(
  () => roleRank[workspace.current?.current_user_workspace_role ?? ""] >= 1
);
// viewer（游客）纯阅读：生成/发布/采信/排序/编辑等编审操作整组隐藏。
const canManageReports = computed(
  () => roleRank[workspace.current?.current_user_workspace_role ?? ""] >= 1
);

const contentFieldLabels = [
  ["background", "背景"],
  ["effects", "效果总结"],
  ["eventSummary", "事件总结"],
  ["technologyAndInnovation", "技术和创新点总结"],
  ["valueAndImpact", "价值和影响"]
] as const;

const editorDraft = reactive({
  title: "",
  summary: "",
  contentJson: {} as Record<string, string>
});

const reportFormats = ref<ReportFormatRecord[]>([]);
const pendingReportAnchorId = computed(() => {
  const value = route.query.report_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingWeeklyItemAnchorId = computed(() => {
  const value = route.query.item_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingRenditionAnchorId = computed(() => {
  const value = route.query.rendition_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingRenditionFormatCode = computed(() => {
  const value = route.query.format_code;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});

const exportableFormats = computed(() =>
  reportFormats.value.filter((fmt) => fmt.enabled && fmt.export_targets.length > 0)
);

async function loadReportFormats() {
  if (!workspace.currentCode) {
    return;
  }
  reportFormats.value = await fetchReportFormats(workspace.currentCode).catch(() => []);
}

function weeklyExportHref(formatCode: string, target: "md" | "html") {
  const report = selectedReport.value;
  return report ? weeklyRenditionExportUrl(report.id, formatCode, target) : "#";
}

const selectedReport = computed(() => {
  return reports.value.find((report) => report.id === selectedReportId.value) ?? reports.value[0] ?? null;
});

const reportItems = computed(() => selectedReport.value?.items ?? []);
const adoptedCount = computed(() => reportItems.value.filter((item) => item.adoption_status === 2).length);
const candidateCount = computed(() => reportItems.value.filter((item) => item.adoption_status === 1).length);
const rejectedCount = computed(() => reportItems.value.filter((item) => item.adoption_status === 0).length);
const weeklyBoards = computed(() => {
  const boards = new Map<string, WeeklyReportItemRecord[]>();
  for (const item of reportItems.value) {
    const key = boardName(item);
    boards.set(key, [...(boards.get(key) ?? []), item]);
  }
  return Array.from(boards.entries())
    .map(([name, items]) => ({
      name,
      items: [...items].sort((left, right) => left.sort_order - right.sort_order),
      adopted: items.filter((item) => item.adoption_status === 2).length,
      candidate: items.filter((item) => item.adoption_status === 1).length,
      rejected: items.filter((item) => item.adoption_status === 0).length
    }))
    .sort((left, right) => {
      const leftFirst = left.items[0]?.sort_order ?? 0;
      const rightFirst = right.items[0]?.sort_order ?? 0;
      return leftFirst - rightFirst || left.name.localeCompare(right.name, "zh-CN");
    });
});
const visibleBoards = computed(() => {
  if (selectedBoard.value === "all") {
    return weeklyBoards.value;
  }
  return weeklyBoards.value.filter((board) => board.name === selectedBoard.value);
});

async function loadReports() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    reports.value = await fetchWeeklyReports(workspace.currentCode);
    if (!reports.value.some((report) => report.id === selectedReportId.value)) {
      selectedReportId.value = reports.value[0]?.id ?? "";
    }
    applyPendingAnchors();
    await loadWatcherStatuses();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载周报失败";
  } finally {
    loading.value = false;
  }
}

function applyPendingAnchors() {
  const itemId = pendingWeeklyItemAnchorId.value;
  if (itemId && reports.value.length > 0) {
    const report = reports.value.find((candidate) => candidate.items.some((item) => item.id === itemId));
    const item = report?.items.find((candidate) => candidate.id === itemId);
    if (report && item) {
      selectedReportId.value = report.id;
      selectedBoard.value = boardName(item);
      return;
    }
  }
  const reportId = pendingReportAnchorId.value;
  if (!reportId || reports.value.length === 0) {
    return;
  }
  const report = reports.value.find((candidate) => candidate.id === reportId);
  if (report) {
    selectedReportId.value = report.id;
  }
}

async function createDraft() {
  if (!workspace.currentCode) {
    return;
  }
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const report = await createWeeklyReport({
      workspace_code: workspace.currentCode,
      week_key: weekKey.value,
      limit: draftLimit.value,
      include_unpublished_daily: includeUnpublishedDaily.value
    });
    message.value = `已生成 ${report.week_key} 周报草稿：${report.items.length} 条候选`;
    await loadReports();
    selectedReportId.value = report.id;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建周报草稿失败";
  } finally {
    creating.value = false;
  }
}

async function selectReport(report: WeeklyReportRecord) {
  selectedReportId.value = report.id;
  editingItemId.value = "";
  selectedBoard.value = "all";
  error.value = "";
  try {
    const updated = await fetchWeeklyReport(report.id);
    replaceReport(updated);
    await loadWatcherStatuses(updated.items);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载周报详情失败";
  }
}

async function publishReport(report: WeeklyReportRecord) {
  publishingId.value = report.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await publishWeeklyReport(report.id);
    replaceReport(updated);
    message.value = `已发布：${updated.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "发布周报失败";
  } finally {
    publishingId.value = "";
  }
}

async function setAdoption(item: WeeklyReportItemRecord, status: number) {
  actingItemId.value = item.id;
  error.value = "";
  try {
    replaceItem(await updateWeeklyReportItem(item.id, { adoption_status: status }));
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新周报条目失败";
  } finally {
    actingItemId.value = "";
  }
}

async function loadWatcherStatus(item: WeeklyReportItemRecord) {
  if (watchersByItem.value[item.id] || loadingWatcherIds.value[item.id]) {
    return;
  }
  loadingWatcherIds.value = { ...loadingWatcherIds.value, [item.id]: true };
  try {
    watchersByItem.value = {
      ...watchersByItem.value,
      [item.id]: await fetchObjectWatcher("weekly_report_item", item.id)
    };
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载关注状态失败";
  } finally {
    const { [item.id]: _finished, ...rest } = loadingWatcherIds.value;
    loadingWatcherIds.value = rest;
  }
}

async function loadWatcherStatuses(items: WeeklyReportItemRecord[] = reportItems.value) {
  await Promise.all(items.map((item) => loadWatcherStatus(item)));
}

function watcherStatus(item: WeeklyReportItemRecord) {
  return watchersByItem.value[item.id] ?? null;
}

async function toggleWatchItem(item: WeeklyReportItemRecord) {
  const current = watcherStatus(item);
  watchingItemId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateObjectWatcher("weekly_report_item", item.id, !(current?.watching ?? false));
    watchersByItem.value = {
      ...watchersByItem.value,
      [item.id]: updated
    };
    message.value = updated.watching ? "已关注该周报条目" : "已取消关注该周报条目";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新关注状态失败";
  } finally {
    watchingItemId.value = "";
  }
}

async function createStrategyLoop(item: WeeklyReportItemRecord) {
  if (!canCreateStrategyLoop.value) {
    return;
  }
  strategyItemId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const result = await createWeeklyReportItemInsight(item.id, {
      insight_title: displayTitle(item),
      insight_summary: displaySummary(item),
      implication_title: `研判：${displayTitle(item)}`,
      implication_description: displaySummary(item),
      requirement_title: `跟进：${displayTitle(item)}`,
      requirement_description: displaySummary(item),
      requirement_status: "draft",
      source_note: selectedReport.value ? `由 ${selectedReport.value.week_key} 周报条目沉淀` : "由周报条目沉淀"
    });
    message.value = `已沉淀内部需求：${result.requirement.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "沉淀内部需求失败";
  } finally {
    strategyItemId.value = "";
  }
}

function toggleMilestoneForm(item: WeeklyReportItemRecord) {
  milestoneItemId.value = milestoneItemId.value === item.id ? "" : item.id;
  milestoneDrafts.value = {
    ...milestoneDrafts.value,
    [item.id]: milestoneDrafts.value[item.id] ?? ""
  };
}

async function createEntityMilestone(item: WeeklyReportItemRecord) {
  if (!canCreateEntityMilestone.value) {
    return;
  }
  const entityName = (milestoneDrafts.value[item.id] || "").trim();
  if (!entityName) {
    error.value = "请先填写实体名称";
    return;
  }
  milestoneSavingId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    const result = await createWeeklyReportItemEntityMilestone(item.id, {
      entity_name: entityName,
      event_title: displayTitle(item),
      event_brief: displaySummary(item),
      impact_brief: displaySummary(item),
      board: boardName(item),
      source_note: selectedReport.value ? `由 ${selectedReport.value.week_key} 周报条目登记` : "由周报条目登记"
    });
    milestoneDrafts.value = { ...milestoneDrafts.value, [item.id]: "" };
    milestoneItemId.value = "";
    message.value = `已登记实体事件：${result.entity_name} · ${result.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登记实体事件失败";
  } finally {
    milestoneSavingId.value = "";
  }
}

async function moveItem(item: WeeklyReportItemRecord, direction: -1 | 1) {
  const items = boardItemsFor(item);
  const currentIndex = items.findIndex((candidate) => candidate.id === item.id);
  const neighbor = items[currentIndex + direction];
  if (!neighbor) {
    return;
  }
  actingItemId.value = item.id;
  error.value = "";
  try {
    await updateWeeklyReportItem(item.id, { sort_order: neighbor.sort_order });
    await updateWeeklyReportItem(neighbor.id, { sort_order: item.sort_order });
    if (selectedReport.value) {
      replaceReport(await fetchWeeklyReport(selectedReport.value.id));
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "调整排序失败";
  } finally {
    actingItemId.value = "";
  }
}

function beginEdit(item: WeeklyReportItemRecord) {
  editingItemId.value = item.id;
  editorDraft.title = displayTitle(item);
  editorDraft.summary = displaySummary(item);
  const content = item.editor_content_json || item.generated_news?.content_json || {};
  editorDraft.contentJson = Object.fromEntries(
    contentFieldLabels.map(([key]) => {
      const value = content[key];
      return [key, typeof value === "string" ? value : ""];
    })
  );
}

function cancelEdit() {
  editingItemId.value = "";
}

async function saveEdit(item: WeeklyReportItemRecord) {
  savingItemId.value = item.id;
  error.value = "";
  message.value = "";
  try {
    replaceItem(
      await updateWeeklyReportItem(item.id, {
        editor_title: editorDraft.title,
        editor_summary: editorDraft.summary,
        editor_content_json: {
          ...(item.generated_news?.content_json ?? {}),
          ...(item.editor_content_json ?? {}),
          ...editorDraft.contentJson
        }
      })
    );
    editingItemId.value = "";
    message.value = "周报条目已保存";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存周报条目失败";
  } finally {
    savingItemId.value = "";
  }
}

function replaceReport(updated: WeeklyReportRecord) {
  const index = reports.value.findIndex((report) => report.id === updated.id);
  if (index >= 0) {
    reports.value.splice(index, 1, updated);
  } else {
    reports.value.unshift(updated);
  }
}

function replaceItem(updated: WeeklyReportItemRecord) {
  const report = selectedReport.value;
  if (!report) {
    return;
  }
  const index = report.items.findIndex((item) => item.id === updated.id);
  if (index >= 0) {
    report.items.splice(index, 1, updated);
    report.items.sort((left, right) => left.sort_order - right.sort_order);
  }
}

function displayTitle(item: WeeklyReportItemRecord) {
  return item.editor_title || item.generated_news?.title || "未关联生成稿";
}

function displaySummary(item: WeeklyReportItemRecord) {
  return item.editor_summary || item.generated_news?.summary || "该周报条目暂未关联日报生成稿。";
}

function briefSummary(item: WeeklyReportItemRecord) {
  const summary = displaySummary(item).replace(/\s+/g, " ").trim();
  if (summary.length <= 120) {
    return summary;
  }
  return `${summary.slice(0, 120)}...`;
}

function boardName(item: WeeklyReportItemRecord) {
  return item.generated_news?.category || "未分类";
}

function boardItemsFor(item: WeeklyReportItemRecord) {
  const targetBoard = boardName(item);
  return reportItems.value
    .filter((candidate) => boardName(candidate) === targetBoard)
    .sort((left, right) => left.sort_order - right.sort_order);
}

function canMoveItem(item: WeeklyReportItemRecord, direction: -1 | 1) {
  const items = boardItemsFor(item);
  const currentIndex = items.findIndex((candidate) => candidate.id === item.id);
  return Boolean(items[currentIndex + direction]);
}

function isAnchoredWeeklyItem(item: WeeklyReportItemRecord) {
  return pendingWeeklyItemAnchorId.value === item.id;
}

function isAnchoredRenditionFormat(fmt: ReportFormatRecord) {
  return Boolean(pendingRenditionAnchorId.value && pendingRenditionFormatCode.value === fmt.format_code);
}

function adoptionLabel(status: number) {
  if (status === 2) {
    return "采信";
  }
  if (status === 1) {
    return "候选";
  }
  return "剔除";
}

function statusLabel(status: string) {
  return status === "published" ? "已发布" : "草稿";
}

function sourceHost(item: WeeklyReportItemRecord) {
  const url = item.generated_news?.source_url;
  if (!url) {
    return "";
  }
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function formatScore(value: number) {
  return Number.isFinite(value) ? value.toFixed(1) : "0.0";
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "未发布";
  }
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function currentIsoWeekKey() {
  const now = new Date();
  const date = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  const dayNumber = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - dayNumber);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const weekNumber = Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${date.getUTCFullYear()}-W${String(weekNumber).padStart(2, "0")}`;
}

watch(
  () => workspace.currentCode,
  () => {
    selectedReportId.value = "";
    editingItemId.value = "";
    selectedBoard.value = "all";
    watchersByItem.value = {};
    loadingWatcherIds.value = {};
    void loadReports();
    void loadReportFormats();
  }
);

onMounted(() => {
  void loadReports();
  void loadReportFormats();
});
</script>

<template>
  <section class="layout-list">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Weekly Intelligence</p>
        <h2>周报</h2>
        <p>从已发布日报中采信的条目生成周报候选，管理员最终调整采信、排序和发布。</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadReports">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button
          v-if="canManageReports"
          type="button"
          class="icon-button"
          :disabled="creating"
          @click="createDraft"
        >
          <Sparkles :size="17" />
          <span>{{ creating ? "生成中" : "生成周报草稿" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section v-if="canManageReports" class="run-command module-card compact">
      <label>
        周期
        <span class="input-with-icon">
          <CalendarRange :size="16" />
          <input v-model="weekKey" placeholder="2026-W19" />
        </span>
      </label>
      <label>
        候选上限
        <input v-model.number="draftLimit" type="number" min="1" max="200" />
      </label>
      <label class="switch-row">
        <input v-model="includeUnpublishedDaily" type="checkbox" />
        包含未发布日报
      </label>
      <p class="muted-line">
        默认只读取已发布日报中采信状态为 2 的条目；单次草稿最多 200 条，周报正文生成暂不在本阶段启用。
      </p>
    </section>

    <div v-if="selectedReport" class="module-stats">
      <article>
        <strong>{{ reportItems.length }}</strong>
        <span>周报条目</span>
      </article>
      <article>
        <strong>{{ candidateCount }}</strong>
        <span>候选</span>
      </article>
      <article>
        <strong>{{ adoptedCount }}</strong>
        <span>采信</span>
      </article>
      <article>
        <strong>{{ rejectedCount }}</strong>
        <span>剔除</span>
      </article>
    </div>

    <section class="module-split weekly-layout">
      <aside class="module-card run-list">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Reports</p>
            <h3>周报草稿</h3>
          </div>
          <span class="metric-pill">{{ reports.length }} reports</span>
        </div>
        <button
          v-for="report in reports"
          :key="report.id"
          type="button"
          class="run-tab"
          :class="{ active: selectedReport?.id === report.id }"
          @click="selectReport(report)"
        >
          <strong>{{ report.week_key }}</strong>
          <span>{{ statusLabel(report.status) }} · {{ report.items.length }} 条 · {{ formatDateTime(report.published_at) }}</span>
        </button>
        <p v-if="loading && reports.length === 0" class="empty-state">
          正在加载周报列表。
        </p>
        <p v-if="!loading && reports.length === 0" class="empty-state">
          暂无周报。先发布日报，并把日报条目设为采信，再生成周报草稿；已校验 SQL 预览回填的日报也会进入这里。
        </p>
      </aside>

      <article class="module-card weekly-detail">
        <div v-if="selectedReport" class="card-title-row">
          <div>
            <p class="eyebrow">{{ selectedReport.workspace_code }} · {{ selectedReport.domain_code }}</p>
            <h3>{{ selectedReport.title }}</h3>
          </div>
          <div class="module-actions">
            <span class="metric-pill">{{ statusLabel(selectedReport.status) }}</span>
            <template v-for="fmt in exportableFormats" :key="fmt.format_code">
              <a
                v-for="target in fmt.export_targets"
                :key="`${fmt.format_code}-${target}`"
                class="table-action"
                :class="{ anchored: isAnchoredRenditionFormat(fmt) }"
                :href="weeklyExportHref(fmt.format_code, target as 'md' | 'html')"
                target="_blank"
                :aria-current="isAnchoredRenditionFormat(fmt) ? 'true' : undefined"
                :title="`${fmt.name} 导出 ${target.toUpperCase()}`"
              >
                {{ fmt.name }} {{ target.toUpperCase() }}
              </a>
            </template>
            <button
              v-if="canManageReports && selectedReport.status !== 'published'"
              type="button"
              class="icon-button"
              :disabled="publishingId === selectedReport.id || reportItems.length === 0"
              @click="publishReport(selectedReport)"
            >
              <Send :size="16" />
              <span>{{ publishingId === selectedReport.id ? "发布中" : "发布周报" }}</span>
            </button>
          </div>
        </div>

        <div v-if="loading && !selectedReport" class="empty-state">正在加载周报详情。</div>
        <div v-else-if="!selectedReport" class="empty-state">选择或创建一次周报草稿查看详情。</div>
        <div v-else-if="reportItems.length === 0" class="empty-state">
          这个周报草稿没有候选条目。请确认该周内存在已发布日报，且日报条目 `adoption_status = 2`。
        </div>
        <div v-else class="weekly-board-workspace">
          <section class="weekly-generated-summary" aria-label="周报摘要">
            <p class="eyebrow">Weekly Summary</p>
            <p>{{ selectedReport.summary }}</p>
          </section>

          <div class="weekly-board-tabs">
            <button type="button" :class="{ active: selectedBoard === 'all' }" @click="selectedBoard = 'all'">
              <strong>全部板块</strong>
              <span>{{ reportItems.length }} 条</span>
            </button>
            <button
              v-for="board in weeklyBoards"
              :key="board.name"
              type="button"
              :class="{ active: selectedBoard === board.name }"
              @click="selectedBoard = board.name"
            >
              <strong>{{ board.name }}</strong>
              <span>{{ board.items.length }} 条 · 采信 {{ board.adopted }}</span>
            </button>
          </div>

          <div class="weekly-board-summary">
            <article v-for="board in weeklyBoards" :key="board.name" class="weekly-board-card">
              <div>
                <p class="eyebrow">Section</p>
                <h4>{{ board.name }}</h4>
              </div>
              <div class="weekly-board-counts">
                <span>{{ board.items.length }} 条</span>
                <span>{{ board.adopted }} 采信</span>
                <span>{{ board.candidate }} 候选</span>
                <span v-if="board.rejected">{{ board.rejected }} 剔除</span>
              </div>
            </article>
          </div>

          <div class="weekly-section-stack">
            <section v-for="board in visibleBoards" :key="board.name" class="weekly-section">
              <header class="weekly-section-header">
                <div>
                  <p class="eyebrow">Weekly Section</p>
                  <h4>{{ board.name }}</h4>
                </div>
                <div class="weekly-board-counts">
                  <span>{{ board.items.length }} 条</span>
                  <span>{{ board.adopted }} 采信</span>
                  <span>{{ board.candidate }} 候选</span>
                </div>
              </header>

              <article
                v-for="item in board.items"
                :key="item.id"
                class="weekly-brief-card weekly-item-row"
                :class="{ anchored: isAnchoredWeeklyItem(item) }"
                :aria-current="isAnchoredWeeklyItem(item) ? 'true' : undefined"
              >
                <div class="weekly-brief-main">
                  <div class="candidate-meta">
                    <span class="state-chip">{{ adoptionLabel(item.adoption_status) }}</span>
                    <span>{{ item.daily_day_key || "无日报日期" }}</span>
                    <span>排序 {{ item.sort_order }}</span>
                    <span>周报分 {{ formatScore(item.weekly_score) }}</span>
                    <span>热度 {{ formatScore(item.heat_score) }}</span>
                    <span>反馈 {{ formatScore(item.feedback_score) }}</span>
                    <a
                      v-if="item.generated_news?.source_url"
                      class="weekly-source-link"
                      :href="item.generated_news.source_url"
                      target="_blank"
                    >
                      <ExternalLink :size="13" />
                      <span>{{ sourceHost(item) }}</span>
                    </a>
                  </div>
                  <h3>{{ displayTitle(item) }}</h3>
                  <p>{{ briefSummary(item) }}</p>
                </div>

                <div class="weekly-brief-actions">
                  <button
                    type="button"
                    class="mini-action"
                    :class="{ active: watcherStatus(item)?.watching }"
                    :disabled="watchingItemId === item.id || loadingWatcherIds[item.id]"
                    :aria-pressed="watcherStatus(item)?.watching ? 'true' : 'false'"
                    @click="toggleWatchItem(item)"
                  >
                    <Bell :size="15" />
                    <span>{{ watcherStatus(item)?.watching ? "已关注" : "关注" }}</span>
                    <span v-if="watcherStatus(item)">· {{ watcherStatus(item)?.watcher_count }}</span>
                  </button>
                  <button
                    v-if="canManageReports"
                    type="button"
                    class="mini-action"
                    :class="{ active: item.adoption_status === 2 }"
                    :disabled="actingItemId === item.id"
                    @click="setAdoption(item, 2)"
                  >
                    <CheckCircle2 :size="15" />
                    <span>采信</span>
                  </button>
                  <button
                    v-if="canManageReports"
                    type="button"
                    class="mini-action"
                    :class="{ active: item.adoption_status === 1 }"
                    :disabled="actingItemId === item.id"
                    @click="setAdoption(item, 1)"
                  >
                    <FileText :size="15" />
                    <span>候选</span>
                  </button>
                  <button
                    v-if="canManageReports"
                    type="button"
                    class="mini-action"
                    :class="{ active: item.adoption_status === 0 }"
                    :disabled="actingItemId === item.id"
                    @click="setAdoption(item, 0)"
                  >
                    <CircleSlash2 :size="15" />
                    <span>剔除</span>
                  </button>
                  <button
                    v-if="canManageReports"
                    type="button"
                    class="mini-action"
                    :disabled="!canMoveItem(item, -1)"
                    @click="moveItem(item, -1)"
                  >
                    <ArrowUp :size="15" />
                  </button>
                  <button
                    v-if="canManageReports"
                    type="button"
                    class="mini-action"
                    :disabled="!canMoveItem(item, 1)"
                    @click="moveItem(item, 1)"
                  >
                    <ArrowDown :size="15" />
                  </button>
                  <button
                    v-if="canManageReports && editingItemId !== item.id"
                    type="button"
                    class="mini-action"
                    @click="beginEdit(item)"
                  >
                    <Pencil :size="15" />
                    <span>编辑</span>
                  </button>
                  <button
                    v-if="canCreateStrategyLoop"
                    type="button"
                    class="mini-action"
                    :disabled="strategyItemId === item.id"
                    @click="createStrategyLoop(item)"
                  >
                    <Sparkles :size="15" />
                    <span>{{ strategyItemId === item.id ? "沉淀中" : "沉淀需求" }}</span>
                  </button>
                  <button
                    v-if="canCreateEntityMilestone"
                    type="button"
                    class="mini-action"
                    :class="{ active: milestoneItemId === item.id }"
                    @click="toggleMilestoneForm(item)"
                  >
                    <FileText :size="15" />
                    <span>登记事件</span>
                  </button>
                </div>

                <form
                  v-if="milestoneItemId === item.id"
                  class="inline-milestone-form"
                  @submit.prevent="createEntityMilestone(item)"
                >
                  <label>
                    实体名称
                    <input v-model="milestoneDrafts[item.id]" placeholder="公司、模型、产品或技术名" />
                  </label>
                  <button type="submit" class="icon-button" :disabled="milestoneSavingId === item.id">
                    <Save :size="15" />
                    <span>{{ milestoneSavingId === item.id ? "登记中" : "保存事件" }}</span>
                  </button>
                </form>

                <div v-if="editingItemId === item.id" class="editor-form weekly-editor">
                  <label>
                    标题
                    <input v-model="editorDraft.title" />
                  </label>
                  <label>
                    摘要
                    <textarea v-model="editorDraft.summary" rows="4" />
                  </label>
                  <div class="editor-content-fields">
                    <label v-for="[fieldKey, fieldLabel] in contentFieldLabels" :key="fieldKey">
                      {{ fieldLabel }}
                      <textarea v-model="editorDraft.contentJson[fieldKey]" rows="3" />
                    </label>
                  </div>
                  <div class="editor-actions">
                    <button
                      type="button"
                      class="mini-action active"
                      :disabled="savingItemId === item.id"
                      @click="saveEdit(item)"
                    >
                      <Save :size="15" />
                      <span>{{ savingItemId === item.id ? "保存中" : "保存" }}</span>
                    </button>
                    <button type="button" class="mini-action" @click="cancelEdit">取消</button>
                  </div>
                </div>
              </article>
            </section>
          </div>
        </div>
      </article>
    </section>
  </section>
</template>
