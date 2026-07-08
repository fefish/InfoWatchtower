<script setup lang="ts">
// 报告时间轴（frontend-product-design §13.1）：全站「按月分组竖向时间轴」的唯一实现，
// 日报/周报页共用（reportType 区分变体）。已发布层走 /api/report-archive 轻量索引
// 无限滚动到全量历史；草稿层由父页面用现有 reports API 供数（member+ 才传入渲染）。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import {
  fetchReportArchive,
  fetchReportArchiveSummary,
  type ReportArchiveListItem,
  type ReportArchiveMonthBucket
} from "../api/operations";

export interface ReportTimelineLocalReport {
  id: string;
  key: string; // daily: day_key（YYYY-MM-DD）；weekly: week_key（YYYY-Www）
  status: string;
  itemCount: number;
}

export interface ReportTimelineNode {
  key: string;
  month: string;
  status: string;
  itemCount: number;
  origin: "local" | "archive";
  detailId: string;
}

const props = withDefaults(
  defineProps<{
    reportType: "daily" | "weekly";
    workspaceCode: string;
    localReports?: ReportTimelineLocalReport[];
    selectedKey?: string;
    canViewDrafts?: boolean;
    pageSize?: number;
  }>(),
  {
    localReports: () => [],
    selectedKey: "",
    canViewDrafts: false,
    pageSize: 30
  }
);

const emit = defineEmits<{ (event: "select", node: ReportTimelineNode): void }>();

const archiveEntries = ref<ReportArchiveListItem[]>([]);
const monthBuckets = ref<ReportArchiveMonthBucket[]>([]);
const loadingMore = ref(false);
const loadError = ref("");
const exhausted = ref(false);
const offset = ref(0);
const jumpMonth = ref("");
const scrollEl = ref<HTMLElement | null>(null);
const sentinelEl = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

// ISO 周所在月份：取该 ISO 周周一所在月（与后端 week_bounds 口径一致）。
function isoWeekMonth(weekKey: string): string {
  const match = /^(\d{4})-W(\d{2})$/.exec(weekKey);
  if (!match) {
    return weekKey.slice(0, 7);
  }
  const year = Number(match[1]);
  const week = Number(match[2]);
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Weekday = jan4.getUTCDay() || 7;
  const monday = new Date(jan4);
  monday.setUTCDate(jan4.getUTCDate() - jan4Weekday + 1 + (week - 1) * 7);
  return `${monday.getUTCFullYear()}-${String(monday.getUTCMonth() + 1).padStart(2, "0")}`;
}

function nodeMonth(key: string): string {
  return props.reportType === "weekly" ? isoWeekMonth(key) : key.slice(0, 7);
}

const localNodes = computed<ReportTimelineNode[]>(() =>
  props.localReports
    // 草稿是编审层对象：viewer 时间轴只渲染已发布节点（archive-knowledge-design §5.1）。
    .filter((report) => props.canViewDrafts || report.status === "published")
    .map((report) => ({
      key: report.key,
      month: nodeMonth(report.key),
      status: report.status,
      itemCount: report.itemCount,
      origin: "local" as const,
      detailId: report.id
    }))
);

const archiveNodes = computed<ReportTimelineNode[]>(() => {
  // 合并规则：同一 day_key/week_key 以报告对象（本地层）为准去重。
  const localKeys = new Set(localNodes.value.map((node) => node.key));
  return archiveEntries.value
    .filter((entry) => !localKeys.has(entry.date_key))
    .map((entry) => ({
      key: entry.date_key,
      month: entry.month,
      status: entry.status,
      itemCount: entry.item_count,
      origin: "archive" as const,
      detailId: entry.detail_id
    }));
});

const allNodes = computed(() =>
  [...localNodes.value, ...archiveNodes.value].sort((left, right) => right.key.localeCompare(left.key))
);

const monthGroups = computed(() => {
  const groups = new Map<string, ReportTimelineNode[]>();
  for (const node of allNodes.value) {
    groups.set(node.month, [...(groups.get(node.month) ?? []), node]);
  }
  return Array.from(groups.entries())
    .map(([month, nodes]) => ({ month, nodes }))
    .sort((left, right) => right.month.localeCompare(left.month));
});

const selectedNode = computed(
  () => allNodes.value.find((node) => node.key === props.selectedKey) ?? null
);

const isEmpty = computed(
  () => !loadingMore.value && !loadError.value && exhausted.value && allNodes.value.length === 0
);

function monthTitle(month: string) {
  const [year, monthPart] = month.split("-");
  return `${year} 年 ${Number(monthPart)} 月`;
}

function nodeLabel(node: ReportTimelineNode) {
  return props.reportType === "daily" ? node.key.slice(5) : node.key;
}

function statusLabel(status: string) {
  return status === "published" ? "已发布" : "草稿";
}

function mergeEntries(page: ReportArchiveListItem[]) {
  const known = new Set(archiveEntries.value.map((entry) => entry.id));
  archiveEntries.value = [...archiveEntries.value, ...page.filter((entry) => !known.has(entry.id))];
}

async function loadMore() {
  if (!props.workspaceCode || loadingMore.value || exhausted.value) {
    return;
  }
  loadingMore.value = true;
  loadError.value = "";
  try {
    const page = await fetchReportArchive({
      workspaceCode: props.workspaceCode,
      reportType: props.reportType,
      origin: "published",
      offset: offset.value,
      limit: props.pageSize
    });
    mergeEntries(page);
    offset.value += props.pageSize;
    if (page.length < props.pageSize) {
      exhausted.value = true;
    }
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : "加载报告时间轴失败";
  } finally {
    loadingMore.value = false;
  }
}

async function loadMonths() {
  if (!props.workspaceCode) {
    return;
  }
  try {
    monthBuckets.value = (await fetchReportArchiveSummary(props.workspaceCode)).months;
  } catch {
    // 跳月条是增强能力：summary 失败不阻断时间轴主链路。
    monthBuckets.value = [];
  }
}

async function jumpToMonth() {
  const month = jumpMonth.value;
  if (!month) {
    return;
  }
  if (!monthGroups.value.some((group) => group.month === month)) {
    // 该月尚未随分页加载：按 month 直取该月已发布索引后再定位。
    loadingMore.value = true;
    loadError.value = "";
    try {
      mergeEntries(
        await fetchReportArchive({
          workspaceCode: props.workspaceCode,
          reportType: props.reportType,
          origin: "published",
          month,
          limit: 300
        })
      );
    } catch (exc) {
      loadError.value = exc instanceof Error ? exc.message : "跳转月份失败";
    } finally {
      loadingMore.value = false;
    }
  }
  await nextTick();
  const target = scrollEl.value?.querySelector<HTMLElement>(`[data-month="${month}"]`);
  if (target && typeof target.scrollIntoView === "function") {
    target.scrollIntoView({ block: "start" });
  }
}

function retryLoad() {
  void loadMore();
}

function reset() {
  archiveEntries.value = [];
  monthBuckets.value = [];
  offset.value = 0;
  exhausted.value = false;
  loadError.value = "";
  jumpMonth.value = "";
  void loadMore();
  void loadMonths();
}

function setupObserver() {
  if (typeof IntersectionObserver === "undefined" || !sentinelEl.value) {
    return;
  }
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        void loadMore();
      }
    },
    { root: scrollEl.value ?? undefined, rootMargin: "120px" }
  );
  observer.observe(sentinelEl.value);
}

function selectFromCompact(event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  const node = allNodes.value.find((candidate) => candidate.detailId === value);
  if (node) {
    emit("select", node);
  }
}

watch(
  () => props.workspaceCode,
  () => reset()
);

onMounted(() => {
  reset();
  setupObserver();
});

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
});
</script>

<template>
  <aside class="report-timeline-card" aria-label="报告时间轴">
    <div class="timeline-head">
      <p class="eyebrow">Timeline</p>
      <select
        v-if="monthBuckets.length"
        v-model="jumpMonth"
        class="timeline-month-jump"
        aria-label="跳转月份"
        @change="jumpToMonth"
      >
        <option value="">跳转月份</option>
        <option v-for="bucket in monthBuckets" :key="bucket.month" :value="bucket.month">
          {{ monthTitle(bucket.month) }} · {{ bucket.count }}
        </option>
      </select>
    </div>

    <!-- ≤1180px 坍缩形态：报告下拉保持全量可达（不回退成“只有最近 20 份”） -->
    <label class="timeline-compact">
      <span>选择报告</span>
      <select :value="selectedNode?.detailId ?? ''" aria-label="选择报告" @change="selectFromCompact">
        <option
          v-for="node in allNodes"
          :key="`${node.origin}-${node.detailId}`"
          :value="node.detailId"
        >
          {{ nodeLabel(node) }} · {{ statusLabel(node.status) }} · {{ node.itemCount }} 条
        </option>
      </select>
    </label>

    <div ref="scrollEl" class="timeline-scroll">
      <section
        v-for="group in monthGroups"
        :key="group.month"
        class="timeline-month"
        :data-month="group.month"
      >
        <header class="timeline-month-head">{{ monthTitle(group.month) }} · {{ group.nodes.length }} 份</header>
        <button
          v-for="node in group.nodes"
          :key="`${node.origin}-${node.detailId}`"
          type="button"
          class="report-tab timeline-node"
          :class="{ active: node.key === selectedKey }"
          @click="emit('select', node)"
        >
          <span
            class="timeline-dot"
            :class="node.status === 'published' ? 'published' : 'draft'"
            :title="statusLabel(node.status)"
          ></span>
          <strong>{{ nodeLabel(node) }}</strong>
          <span class="timeline-count">{{ node.itemCount }} 条</span>
          <span class="timeline-status">{{ statusLabel(node.status) }}</span>
        </button>
      </section>

      <p v-if="loadingMore" class="timeline-loading">正在加载更多报告…</p>
      <div v-else-if="loadError" class="timeline-error" role="alert">
        <span>{{ loadError }}</span>
        <button type="button" class="table-action" @click="retryLoad">重试</button>
      </div>
      <p v-else-if="isEmpty" class="empty-state">
        还没有报告，生成第一份{{ reportType === "daily" ? "日报" : "周报" }}后会出现在这里
      </p>
      <div ref="sentinelEl" class="timeline-sentinel" aria-hidden="true"></div>
    </div>
  </aside>
</template>
