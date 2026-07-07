<script setup lang="ts">
import {
  Archive,
  CalendarDays,
  Crown,
  Database,
  ExternalLink,
  FileText,
  GitBranch,
  Newspaper,
  Plus,
  RefreshCw,
  Search,
  TriangleAlert
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  createRequirement,
  fetchHistoricalReportDetail,
  fetchLegacyImportGaps,
  fetchLegacyImportSummary,
  fetchReportArchive,
  fetchReportArchiveSummary,
  type HistoricalReportDetailRecord,
  type LegacyImportGapItemRecord,
  type LegacyImportMetricRecord,
  type LegacyImportSummaryRecord,
  type ReportArchiveListItem,
  type ReportArchiveSummaryRecord
} from "../api/operations";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const router = useRouter();
const workspace = useWorkspaceStore();
const session = useSessionStore();

const summary = ref<ReportArchiveSummaryRecord | null>(null);
const legacyMonths = ref<ReportArchiveSummaryRecord["months"]>([]);
const entries = ref<ReportArchiveListItem[]>([]);
const legacySummary = ref<LegacyImportSummaryRecord | null>(null);
const legacyGaps = ref<LegacyImportGapItemRecord[]>([]);
const selected = ref<ReportArchiveListItem | null>(null);
const legacyDetail = ref<HistoricalReportDetailRecord | null>(null);
const loading = ref(false);
const detailLoading = ref(false);
const savingRequirement = ref(false);
const error = ref("");
const message = ref("");
const activeMonth = ref("");
const requirementTitle = ref("");
const requirementNote = ref("");

const filters = ref({
  query: "",
  reportType: "",
  origin: ""
});

const pendingArchiveId = computed(() => routeQueryString(route.query.id));
// 月份导航降级为 legacy 视图内的旧系统资产筛选（page-specs §13.1）。
const legacyViewActive = computed(() => filters.value.origin === "legacy");
const months = computed(() => legacyMonths.value);
const publishedReportCount = computed(
  () => (summary.value?.published_daily ?? 0) + (summary.value?.published_weekly ?? 0)
);
// 无发布样本时隐藏平均采信率，不渲染 0.0/0% 占位（page-specs §13.4）。
const hasAdoptionSamples = computed(() => (summary.value?.total_items ?? 0) > 0);
const currentTopSources = computed(() => summary.value?.top_sources ?? []);
const showLegacyImportPanel = computed(
  () => (summary.value?.legacy_reports ?? 0) > 0 || legacyGaps.value.length > 0
);
const canCreateRequirement = computed(() => {
  if (session.user?.roles.includes("super_admin")) {
    return true;
  }
  return ["owner", "admin"].includes(workspace.current?.current_user_workspace_role ?? "");
});
const selectedLegacyRefs = computed(() => {
  const refs = legacyDetail.value?.source_refs_json ?? {};
  const resolved = Array.isArray(refs.resolved) ? refs.resolved : [];
  const unresolved = Array.isArray(refs.unresolved) ? refs.unresolved : [];
  return { resolved, unresolved };
});

function routeQueryString(value: unknown) {
  return Array.isArray(value) ? String(value[0] ?? "") : String(value ?? "");
}

async function loadArchive() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    if (!legacyViewActive.value) {
      // 月份筛选只作用于 legacy 视图（page-specs §13.1）
      activeMonth.value = "";
    }
    const [nextSummary, nextEntries] = await Promise.all([
      fetchReportArchiveSummary(workspace.currentCode),
      fetchReportArchive({
        workspaceCode: workspace.currentCode,
        month: activeMonth.value || undefined,
        reportType: filters.value.reportType || undefined,
        origin: filters.value.origin || undefined,
        query: filters.value.query || undefined
      })
    ]);
    summary.value = nextSummary;
    entries.value = nextEntries;
    if (legacyViewActive.value) {
      legacyMonths.value = (
        await fetchReportArchiveSummary(workspace.currentCode, { origin: "legacy" })
      ).months;
    } else {
      legacyMonths.value = [];
    }
    if ((nextSummary.legacy_reports ?? 0) > 0) {
      const [nextLegacySummary, nextLegacyGaps] = await Promise.all([
        fetchLegacyImportSummary(workspace.currentCode),
        fetchLegacyImportGaps({ workspaceCode: workspace.currentCode, limit: 8 })
      ]);
      legacySummary.value = nextLegacySummary;
      legacyGaps.value = nextLegacyGaps;
    } else {
      legacySummary.value = null;
      legacyGaps.value = [];
    }
    const anchorId = pendingArchiveId.value;
    const anchored = anchorId ? nextEntries.find((item) => item.id === anchorId) : null;
    if (anchored && anchored.origin === "legacy") {
      await selectEntry(anchored);
    } else if (anchorId && !anchored) {
      await selectLegacyById(anchorId);
    } else {
      // 页内只读 legacy 正文；已发布条目经深链在报告页阅读（page-specs §13.1）
      const firstLegacy = nextEntries.find((item) => item.origin === "legacy");
      if (firstLegacy) {
        await selectEntry(firstLegacy);
      } else {
        selected.value = null;
        legacyDetail.value = null;
      }
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载报告归档失败";
  } finally {
    loading.value = false;
  }
}

async function selectMonth(month: string) {
  activeMonth.value = month;
  await loadArchive();
}

function handleEntryClick(entry: ReportArchiveListItem) {
  // 已发布条目点击即深链跳报告页阅读成稿，不在本页渲染当前报告正文（page-specs §13.4）。
  if (entry.origin === "published") {
    openReportDetail(entry);
    return;
  }
  void selectEntry(entry);
}

async function selectEntry(entry: ReportArchiveListItem) {
  selected.value = entry;
  legacyDetail.value = null;
  if (entry.detail_kind === "historical_report") {
    detailLoading.value = true;
    try {
      legacyDetail.value = await fetchHistoricalReportDetail(entry.detail_id);
      syncRequirementDraft();
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : "加载历史报告详情失败";
    } finally {
      detailLoading.value = false;
    }
  }
}

async function selectLegacyById(id: string) {
  detailLoading.value = true;
  try {
    const detail = await fetchHistoricalReportDetail(id);
    legacyDetail.value = detail;
    selected.value = {
      id: detail.id,
      origin: "legacy",
      report_type: detail.report_type,
      workspace_code: detail.workspace_code,
      title: detail.title,
      date_key: detail.period_start_at ? detail.period_start_at.slice(0, 10) : "",
      month: detail.period_start_at ? detail.period_start_at.slice(0, 7) : "",
      status: detail.status,
      published_at: detail.period_start_at,
      item_count: detail.resolved_ref_count + detail.unresolved_ref_count,
      adopted_count: detail.resolved_ref_count + detail.unresolved_ref_count,
      headline_count: 0,
      adoption_rate: 1,
      top_sources: [],
      detail_kind: "historical_report",
      detail_id: detail.id,
      content_excerpt: detail.content_excerpt
    };
    syncRequirementDraft();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载历史报告详情失败";
  } finally {
    detailLoading.value = false;
  }
}

function openReportDetail(entry: ReportArchiveListItem) {
  if (entry.detail_kind === "daily_report") {
    void router.push({ path: "/daily-reports", query: { report_id: entry.detail_id } });
  } else if (entry.detail_kind === "weekly_report") {
    void router.push({ path: "/weekly-reports", query: { report_id: entry.detail_id } });
  }
}

function syncRequirementDraft() {
  if (!legacyDetail.value) {
    requirementTitle.value = "";
    requirementNote.value = "";
    return;
  }
  requirementTitle.value = `跟进历史报告：${legacyDetail.value.title}`;
  requirementNote.value = `历史报告 ${legacyDetail.value.legacy_id} 触发`;
}

async function createRequirementFromHistoricalReport() {
  if (!legacyDetail.value || !requirementTitle.value.trim()) {
    return;
  }
  savingRequirement.value = true;
  error.value = "";
  message.value = "";
  try {
    const contentExcerpt = legacyDetail.value.content.slice(0, 1000);
    const created = await createRequirement({
      workspace_code: legacyDetail.value.workspace_code,
      title: requirementTitle.value.trim(),
      description: `由历史报告触发。\n\n${contentExcerpt}`,
      priority: "medium",
      status: "open",
      source_historical_report_id: legacyDetail.value.id,
      source_note: requirementNote.value.trim() || `历史报告 ${legacyDetail.value.legacy_id} 触发`
    });
    message.value = `已创建需求：${created.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "从历史报告创建需求失败";
  } finally {
    savingRequirement.value = false;
  }
}

function isAnchoredEntry(entry: ReportArchiveListItem) {
  return pendingArchiveId.value === entry.id;
}

function originLabel(entry: ReportArchiveListItem) {
  if (entry.origin === "legacy") {
    return "旧系统导入";
  }
  return entry.report_type === "weekly" ? "已发布周报" : "已发布日报";
}

function adoptionRateLabel(entry: ReportArchiveListItem) {
  if (entry.item_count === 0) {
    return "—";
  }
  return `${Math.round(entry.adoption_rate * 100)}%`;
}

function monthLabel(month: string) {
  if (!month) {
    return "未标注";
  }
  const [year, mon] = month.split("-");
  return `${year}年${mon}月`;
}

function formatDate(value: string | null) {
  if (!value) return "未记录";
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function compactJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function metricStatus(metric: LegacyImportMetricRecord) {
  if (metric.status === "complete") return "完成";
  if (metric.status === "partial") return "部分";
  return "待导入";
}

function metricPercent(metric: LegacyImportMetricRecord) {
  return `${Math.min(Math.round(metric.coverage_rate * 100), 100)}%`;
}

function gapKindLabel(item: LegacyImportGapItemRecord) {
  if (item.kind === "entity_milestones") return "实体事件";
  if (item.kind === "historical_feedback") return "历史反馈";
  return "历史报告";
}

watch(() => workspace.currentCode, loadArchive);
watch(pendingArchiveId, (id) => {
  if (!id || selected.value?.id === id) {
    return;
  }
  const entry = entries.value.find((item) => item.id === id);
  if (!entry) {
    void selectLegacyById(id);
  } else if (entry.origin === "legacy") {
    // 已发布条目只做锚点高亮，正文经深链在报告页阅读
    void selectEntry(entry);
  }
});
onMounted(loadArchive);
</script>

<template>
  <section class="layout-list">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Report Library</p>
        <h2>历史报告库</h2>
        <p>跨来源报告资产库：旧系统导入资产的归档、验收与跨来源统计对比；日常按天/周回溯请直接用日报/周报页的时间轴。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadArchive">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="module-card archive-compare">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Cross-source</p>
          <h3>跨来源统计对比</h3>
        </div>
        <span class="metric-pill">
          最近发布 {{ summary?.latest_published_at ? formatDate(summary.latest_published_at).slice(0, 10) : "暂无" }}
        </span>
      </div>
      <div class="archive-compare-grid">
        <article class="archive-compare-col">
          <p class="eyebrow">本系统已发布</p>
          <strong>{{ publishedReportCount }}</strong>
          <span>份报告（日报 {{ summary?.published_daily ?? 0 }} · 周报 {{ summary?.published_weekly ?? 0 }}）</span>
          <p v-if="hasAdoptionSamples" class="archive-compare-adoption">
            平均采信率 {{ Math.round((summary?.average_adoption_rate ?? 0) * 100) }}% ·
            采信 {{ summary?.total_adopted ?? 0 }} / {{ summary?.total_items ?? 0 }} 条目
          </p>
          <p v-else class="archive-compare-adoption-empty">暂无已发布采信样本</p>
          <div v-if="currentTopSources.length > 0" class="archive-compare-sources">
            <span v-for="source in currentTopSources" :key="source.name">
              <Database :size="13" />{{ source.name }} ×{{ source.count }}
            </span>
          </div>
        </article>
        <article class="archive-compare-col legacy">
          <p class="eyebrow">旧系统导入</p>
          <strong>{{ summary?.legacy_reports ?? 0 }}</strong>
          <span>份导入报告</span>
          <p v-if="legacySummary" class="archive-compare-refs">
            报告引用解析 {{ legacySummary.report_refs.resolved }} / {{ legacySummary.report_refs.total }}
          </p>
          <p v-else class="archive-compare-adoption-empty">暂无导入验收数据</p>
          <p class="archive-compare-note">旧系统未记录来源分布，正文在本页阅读</p>
        </article>
      </div>
    </section>

    <nav v-if="legacyViewActive" class="archive-month-nav" aria-label="按月份筛选旧系统资产">
      <button type="button" :class="{ active: activeMonth === '' }" @click="selectMonth('')">全部月份</button>
      <button
        v-for="bucket in months"
        :key="bucket.month"
        type="button"
        :class="{ active: activeMonth === bucket.month }"
        @click="selectMonth(bucket.month)"
      >
        {{ monthLabel(bucket.month) }} · {{ bucket.count }}
      </button>
    </nav>

    <section class="module-card archive-filters">
      <label class="archive-search">
        <span>搜索</span>
        <span>
          <Search :size="15" />
          <input v-model.trim="filters.query" type="search" placeholder="标题或正文关键词" @keyup.enter="loadArchive" />
        </span>
      </label>
      <label>
        <span>类型</span>
        <select v-model="filters.reportType">
          <option value="">日报 + 周报</option>
          <option value="daily">日报</option>
          <option value="weekly">周报</option>
        </select>
      </label>
      <label>
        <span>来源</span>
        <select v-model="filters.origin" class="archive-origin-filter">
          <option value="">全部来源</option>
          <option value="published">本系统发布</option>
          <option value="legacy">旧系统资产（可按月筛选）</option>
        </select>
      </label>
      <button type="button" class="icon-button" :disabled="loading" @click="loadArchive">
        <Search :size="16" />
        <span>筛选</span>
      </button>
    </section>

    <section class="module-grid archive-layout">
      <section class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Archive List</p><h3>归档报告</h3></div>
          <span class="metric-pill">{{ entries.length }} 份</span>
        </div>
        <article
          v-for="entry in entries"
          :key="entry.id"
          class="ops-row archive-row"
          :class="{ selected: selected?.id === entry.id, anchored: isAnchoredEntry(entry) }"
          :aria-current="isAnchoredEntry(entry) ? 'true' : undefined"
          @click="handleEntryClick(entry)"
        >
          <div class="feed-icon indigo">
            <Newspaper v-if="entry.report_type === 'weekly'" :size="18" />
            <FileText v-else :size="18" />
          </div>
          <div>
            <div class="archive-row-meta">
              <span class="archive-date"><CalendarDays :size="13" />{{ entry.date_key || "未标注日期" }}</span>
              <span class="archive-origin" :class="entry.origin">{{ originLabel(entry) }}</span>
              <span v-if="entry.origin === 'published'" class="archive-jump-hint">
                <ExternalLink :size="12" />{{ entry.report_type === "weekly" ? "在周报页阅读" : "在日报页阅读" }}
              </span>
            </div>
            <h3>{{ entry.title }}</h3>
            <p class="archive-excerpt">{{ entry.content_excerpt || "暂无摘要" }}</p>
            <div class="coverage-metrics">
              <template v-if="entry.origin === 'legacy'">
                <span>{{ entry.item_count }} 个旧引用</span>
              </template>
              <template v-else>
                <span>{{ entry.item_count }} 条目</span>
                <span>采信 {{ entry.adopted_count }} · {{ adoptionRateLabel(entry) }}</span>
                <span v-if="entry.headline_count > 0"><Crown :size="12" /> 头条 {{ entry.headline_count }}</span>
                <span v-for="source in entry.top_sources" :key="source.name">{{ source.name }} ×{{ source.count }}</span>
              </template>
            </div>
          </div>
        </article>
        <p v-if="!loading && entries.length === 0" class="empty-state">
          这里还没有归档资产。发布日报/周报后会自动进入跨来源统计与合并检索（成稿正文在报告页阅读）；
          旧系统的历史报告通过导入脚本
          （scripts/tech_insight_loop_import_verify.py --execute）进入同一列表。
        </p>
      </section>

      <section class="module-card archive-detail">
        <div v-if="selected" class="archive-detail-body">
          <div class="card-title-row">
            <div>
              <p class="eyebrow">{{ originLabel(selected) }} · {{ selected.status }}</p>
              <h3>{{ selected.title }}</h3>
            </div>
            <span class="metric-pill">{{ detailLoading ? "loading" : selected.date_key || "未标注" }}</span>
          </div>

          <div class="coverage-strip">
            <span>期次 {{ formatDate(selected.published_at) }}</span>
            <span>{{ selected.item_count }} 个旧引用</span>
            <span v-if="legacyDetail">
              解析 {{ legacyDetail.resolved_ref_count }} · 未解析 {{ legacyDetail.unresolved_ref_count }}
            </span>
          </div>

          <template v-if="selected.detail_kind === 'historical_report' && legacyDetail">
            <article class="archive-legacy-content">
              <pre>{{ legacyDetail.content }}</pre>
            </article>

            <section v-if="canCreateRequirement" class="archive-requirement-form">
              <div>
                <p class="eyebrow">Requirement</p>
                <h4>素材复用：转为内部需求</h4>
              </div>
              <label>
                <span>需求标题</span>
                <input v-model="requirementTitle" />
              </label>
              <label>
                <span>来源说明</span>
                <textarea v-model="requirementNote" rows="2" />
              </label>
              <button
                type="button"
                class="mini-action"
                :disabled="savingRequirement || !requirementTitle.trim()"
                @click="createRequirementFromHistoricalReport"
              >
                <Plus :size="15" />
                <span>{{ savingRequirement ? "创建中" : "转需求" }}</span>
              </button>
            </section>

            <section class="archive-ref-panel">
              <div>
                <p class="eyebrow">Resolved refs</p>
                <pre>{{ compactJson(selectedLegacyRefs.resolved) }}</pre>
              </div>
              <div>
                <p class="eyebrow">Unresolved refs</p>
                <pre>{{ compactJson(selectedLegacyRefs.unresolved) }}</pre>
              </div>
            </section>
          </template>
        </div>
        <div v-else class="archive-empty-detail">
          <Archive :size="36" />
          <h3>没有可在本页阅读的旧系统报告</h3>
          <p>本页只读 legacy 导入正文；已发布日报/周报点击条目即跳转报告页阅读成稿。归档是只读视图，不影响当前日报、推荐或公司 SQL 导出。</p>
        </div>
      </section>
    </section>

    <section v-if="showLegacyImportPanel" class="module-card legacy-import-panel">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Import QA</p>
          <h3>旧系统导入验收</h3>
        </div>
        <span class="metric-pill">{{ legacySummary ? formatDate(legacySummary.generated_at) : "未加载" }}</span>
      </div>

      <div class="legacy-metric-grid">
        <article v-for="metric in legacySummary?.metrics ?? []" :key="metric.key" class="legacy-metric">
          <div>
            <span>{{ metric.label }}</span>
            <strong>{{ metric.actual }} / {{ metric.expected }}</strong>
          </div>
          <small :class="metric.status">{{ metricStatus(metric) }} · 缺 {{ metric.missing }}</small>
          <div class="legacy-progress" aria-hidden="true">
            <span :style="{ width: metricPercent(metric) }"></span>
          </div>
        </article>
      </div>

      <div class="legacy-ref-grid">
        <div>
          <Database :size="17" />
          <span>报告引用</span>
          <strong>{{ legacySummary?.report_refs.resolved ?? 0 }}/{{ legacySummary?.report_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.report_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <Archive :size="17" />
          <span>事件素材引用</span>
          <strong>{{ legacySummary?.milestone_article_refs.resolved ?? 0 }}/{{ legacySummary?.milestone_article_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.milestone_article_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <GitBranch :size="17" />
          <span>事件报告引用</span>
          <strong>{{ legacySummary?.milestone_report_refs.resolved ?? 0 }}/{{ legacySummary?.milestone_report_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.milestone_report_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <FileText :size="17" />
          <span>反馈素材引用</span>
          <strong>{{ legacySummary?.feedback_article_refs.resolved ?? 0 }}/{{ legacySummary?.feedback_article_refs.total ?? 0 }}</strong>
          <small>未解析 {{ legacySummary?.feedback_article_refs.unresolved ?? 0 }}</small>
        </div>
        <div>
          <TriangleAlert :size="17" />
          <span>缺口条目</span>
          <strong>{{ legacySummary?.gap_item_count ?? 0 }}</strong>
          <small>引用 {{ legacySummary?.total_unresolved_refs ?? 0 }}</small>
        </div>
      </div>

      <div class="legacy-gap-list">
        <article v-for="gap in legacyGaps" :key="`${gap.kind}-${gap.id}`">
          <span>{{ gapKindLabel(gap) }} · legacy {{ gap.legacy_id }}</span>
          <strong>{{ gap.title }}</strong>
          <small>{{ gap.ref_type }} · unresolved {{ gap.unresolved_count }}</small>
        </article>
        <p v-if="legacyGaps.length === 0" class="empty-state small">
          暂无未解析引用缺口。导入完成后，这里用于抽查报告和实体事件的旧引用映射。
        </p>
      </div>
    </section>
  </section>
</template>

<style scoped>
.archive-compare {
  margin-bottom: 16px;
}

.archive-compare-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.archive-compare-col {
  display: grid;
  gap: 6px;
  min-width: 0;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  padding: 14px;
  background: #eff6ff;
}

.archive-compare-col.legacy {
  border-color: #e2e8f0;
  background: #f8fafc;
}

.archive-compare-col strong {
  display: block;
  color: #0f172a;
  font-size: 26px;
  line-height: 1.1;
}

.archive-compare-col > span {
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.archive-compare-adoption,
.archive-compare-refs,
.archive-compare-adoption-empty,
.archive-compare-note {
  margin: 0;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
}

.archive-compare-adoption-empty,
.archive-compare-note {
  color: #94a3b8;
}

.archive-compare-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.archive-compare-sources span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  padding: 4px 10px;
  background: #fff;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

.archive-month-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.archive-month-nav button {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  padding: 7px 14px;
  background: transparent;
  color: #475569;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
}

.archive-month-nav button.active {
  border-color: rgba(10, 132, 255, 0.4);
  background: rgba(10, 132, 255, 0.1);
  color: #0a84ff;
}

.archive-filters {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr) auto;
  align-items: end;
  gap: 12px;
  margin-bottom: 18px;
}

.archive-filters label {
  display: grid;
  gap: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 800;
}

.archive-filters input,
.archive-filters select {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
  color: #0f172a;
  font: inherit;
}

.archive-search > span:last-child {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 0 10px;
  background: #fff;
}

.archive-search input {
  border: 0;
  padding-inline: 0;
}

.archive-layout {
  grid-template-columns: minmax(340px, 1fr) minmax(0, 1fr);
  align-items: start;
  margin-bottom: 18px;
}

.archive-row {
  cursor: pointer;
  align-items: start;
}

.archive-row.selected {
  border-color: #818cf8;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.archive-row-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.archive-date {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #475569;
  font-size: 12px;
  font-weight: 800;
}

.archive-origin {
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 800;
}

.archive-origin.published {
  background: rgba(10, 132, 255, 0.1);
  color: #0a6ddd;
}

.archive-origin.legacy {
  background: rgba(148, 163, 184, 0.18);
  color: #475569;
}

.archive-excerpt {
  display: -webkit-box;
  margin: 6px 0 !important;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.archive-detail {
  position: sticky;
  top: 92px;
  min-height: 420px;
}

.archive-jump-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 999px;
  padding: 3px 9px;
  background: rgba(10, 132, 255, 0.08);
  color: #0a6ddd;
  font-size: 11px;
  font-weight: 800;
}

.archive-legacy-content {
  max-height: 380px;
  overflow: auto;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
  margin-top: 12px;
}

.archive-legacy-content pre,
.archive-ref-panel pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: #1e293b;
  font: 13px/1.7 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.archive-legacy-content pre {
  padding: 16px;
}

.archive-requirement-form {
  display: grid;
  gap: 10px;
  margin: 14px 0;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  padding: 12px;
  background: #eff6ff;
}

.archive-requirement-form h4 {
  margin: 0;
  color: #0f172a;
}

.archive-requirement-form label {
  display: grid;
  gap: 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 800;
}

.archive-requirement-form input,
.archive-requirement-form textarea {
  width: 100%;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff;
  color: #0f172a;
  font: inherit;
}

.archive-ref-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.archive-ref-panel > div {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.archive-empty-detail {
  display: grid;
  place-items: center;
  min-height: 360px;
  text-align: center;
  color: #64748b;
}

.archive-empty-detail h3,
.archive-empty-detail p {
  margin: 0;
}

.legacy-import-panel {
  display: grid;
  gap: 16px;
  margin-bottom: 16px;
}

.legacy-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.legacy-metric {
  display: grid;
  gap: 8px;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #f8fafc;
}

.legacy-metric div:first-child {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.legacy-metric span,
.legacy-ref-grid span {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
}

.legacy-metric strong,
.legacy-ref-grid strong {
  color: #0f172a;
  font-size: 18px;
}

.legacy-metric small,
.legacy-ref-grid small,
.legacy-gap-list small {
  color: #64748b;
  font-weight: 800;
}

.legacy-metric small.complete {
  color: #047857;
}

.legacy-metric small.partial {
  color: #b45309;
}

.legacy-progress {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.legacy-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #4f46e5;
}

.legacy-ref-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.legacy-ref-grid > div {
  display: grid;
  gap: 4px;
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.legacy-ref-grid svg {
  color: #4f46e5;
}

.legacy-gap-list {
  display: grid;
  gap: 8px;
}

.legacy-gap-list article {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr) 150px;
  align-items: center;
  gap: 10px;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fffbeb;
}

.legacy-gap-list article strong {
  overflow: hidden;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-state.small {
  min-height: auto;
  padding: 8px 0;
  text-align: left;
}

@media (max-width: 1200px) {
  .archive-compare-grid,
  .legacy-metric-grid,
  .legacy-ref-grid,
  .archive-layout,
  .archive-ref-panel {
    grid-template-columns: 1fr;
  }

  .legacy-gap-list article {
    grid-template-columns: 1fr;
  }

  .archive-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .archive-detail {
    position: static;
  }
}
</style>
