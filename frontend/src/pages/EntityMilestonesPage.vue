<script setup lang="ts">
import {
  CheckCircle2,
  CircleDot,
  CircleSlash2,
  Clock3,
  GitBranch,
  Link2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  TriangleAlert,
  UserRound
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createRequirement,
  fetchEntityMilestoneDetail,
  fetchEntityMilestones,
  fetchEntityTimelineSummary,
  fetchTrackedEntities,
  updateEntityMilestone,
  type EntityMilestoneDetailRecord,
  type EntityMilestoneListItem,
  type EntityTimelineSummaryRecord,
  type TrackedEntityListItem
} from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const workspace = useWorkspaceStore();
const summary = ref<EntityTimelineSummaryRecord | null>(null);
const entities = ref<TrackedEntityListItem[]>([]);
const milestones = ref<EntityMilestoneListItem[]>([]);
const selectedEntityId = ref("");
const selected = ref<EntityMilestoneDetailRecord | null>(null);
const loading = ref(false);
const detailLoading = ref(false);
const savingId = ref("");
const editing = ref(false);
const error = ref("");
const message = ref("");

const editDraft = reactive({
  title: "",
  eventType: "",
  eventBrief: "",
  impactBrief: "",
  board: "",
  importanceLevel: "medium",
  importanceScore: 70
});

const filters = ref({
  entityQuery: "",
  eventQuery: "",
  eventType: "",
  importanceLevel: "",
  board: "",
  unresolvedOnly: false
});

const selectedEntity = computed(() => entities.value.find((item) => item.id === selectedEntityId.value) ?? null);
const eventTypes = computed(() => Object.keys(summary.value?.by_event_type ?? {}).sort());
const entityTypes = computed(() => Object.keys(summary.value?.by_entity_type ?? {}).sort());
const importanceLevels = computed(() => Object.keys(summary.value?.by_importance_level ?? {}).sort());
const pendingEntityId = computed(() => routeQueryString(route.query.entity_id));
const pendingMilestoneId = computed(() => routeQueryString(route.query.milestone_id));
const roleRank: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3
};
const canManageMilestone = computed(
  () => roleRank[workspace.current?.current_user_workspace_role ?? ""] >= 2
);
const canGovernSelected = computed(() => canManageMilestone.value && selected.value?.legacy_system === "current");

function routeQueryString(value: unknown) {
  return Array.isArray(value) ? String(value[0] ?? "") : String(value ?? "");
}

async function loadAll() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const [nextSummary, nextEntities] = await Promise.all([
      fetchEntityTimelineSummary(workspace.currentCode),
      fetchTrackedEntities({ workspaceCode: workspace.currentCode, query: filters.value.entityQuery || undefined })
    ]);
    summary.value = nextSummary;
    entities.value = nextEntities;
    const routeMilestoneId = pendingMilestoneId.value;
    if (routeMilestoneId) {
      const anchoredMilestone = await fetchEntityMilestoneDetail(routeMilestoneId);
      selected.value = anchoredMilestone;
      selectedEntityId.value = anchoredMilestone.tracked_entity_id;
    } else if (pendingEntityId.value && nextEntities.some((item) => item.id === pendingEntityId.value)) {
      selectedEntityId.value = pendingEntityId.value;
    } else if ((!selectedEntityId.value || !nextEntities.some((item) => item.id === selectedEntityId.value)) && nextEntities.length > 0) {
      selectedEntityId.value = nextEntities[0].id;
    }
    await loadMilestones();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载实体大事记失败";
  } finally {
    loading.value = false;
  }
}

async function loadMilestones(options: { useRouteAnchor?: boolean } = {}) {
  if (!workspace.currentCode) {
    return;
  }
  const useRouteAnchor = options.useRouteAnchor ?? true;
  loading.value = true;
  error.value = "";
  try {
    const nextMilestones = await fetchEntityMilestones({
      workspaceCode: workspace.currentCode,
      trackedEntityId: selectedEntityId.value || undefined,
      eventType: filters.value.eventType || undefined,
      importanceLevel: filters.value.importanceLevel || undefined,
      board: filters.value.board || undefined,
      query: filters.value.eventQuery || undefined,
      hasUnresolvedRefs: filters.value.unresolvedOnly ? true : null
    });
    milestones.value = nextMilestones;
    const routeMilestoneId = useRouteAnchor ? pendingMilestoneId.value : "";
    if (routeMilestoneId && nextMilestones.some((item) => item.id === routeMilestoneId)) {
      await selectMilestone(routeMilestoneId);
    } else if (nextMilestones.length > 0 && (!routeMilestoneId || selected.value?.id !== routeMilestoneId)) {
      await selectMilestone(nextMilestones[0].id);
    } else {
      selected.value = routeMilestoneId && selected.value?.id === routeMilestoneId ? selected.value : null;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载实体事件失败";
  } finally {
    loading.value = false;
  }
}

async function selectEntity(id: string) {
  selectedEntityId.value = id;
  await loadMilestones({ useRouteAnchor: false });
}

async function selectMilestone(id: string) {
  detailLoading.value = true;
  error.value = "";
  try {
    selected.value = await fetchEntityMilestoneDetail(id);
    syncEditDraft();
    editing.value = false;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载事件详情失败";
  } finally {
    detailLoading.value = false;
  }
}

function syncEditDraft() {
  if (!selected.value) {
    return;
  }
  editDraft.title = selected.value.title;
  editDraft.eventType = selected.value.event_type;
  editDraft.eventBrief = selected.value.event_brief || selected.value.event_content || "";
  editDraft.impactBrief = selected.value.impact_brief || selected.value.impact || "";
  editDraft.board = selected.value.board;
  editDraft.importanceLevel = selected.value.importance_level;
  editDraft.importanceScore = selected.value.importance_score;
}

async function saveMilestoneEdit() {
  if (!selected.value || !canGovernSelected.value) {
    return;
  }
  savingId.value = selected.value.id;
  error.value = "";
  message.value = "";
  try {
    selected.value = await updateEntityMilestone(selected.value.id, {
      event_title: editDraft.title,
      event_type: editDraft.eventType,
      event_brief: editDraft.eventBrief,
      impact_brief: editDraft.impactBrief,
      timeline_brief: editDraft.eventBrief,
      board: editDraft.board,
      importance_level: editDraft.importanceLevel,
      importance_score: Number(editDraft.importanceScore)
    });
    editing.value = false;
    message.value = "实体事件已更新";
    await loadMilestones({ useRouteAnchor: false });
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新实体事件失败";
  } finally {
    savingId.value = "";
  }
}

async function setCurationStatus(status: "confirmed" | "revoked") {
  if (!selected.value || !canGovernSelected.value) {
    return;
  }
  savingId.value = selected.value.id;
  error.value = "";
  message.value = "";
  try {
    selected.value = await updateEntityMilestone(selected.value.id, {
      curation_status: status,
      selected_for_timeline: status === "confirmed",
      curation_note: status === "confirmed" ? "人工确认进入时间线" : "人工撤销时间线展示"
    });
    message.value = status === "confirmed" ? "实体事件已确认" : "实体事件已撤销";
    await loadMilestones({ useRouteAnchor: false });
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新实体事件状态失败";
  } finally {
    savingId.value = "";
  }
}

async function createRequirementFromMilestone() {
  if (!selected.value || !workspace.currentCode || !canManageMilestone.value) {
    return;
  }
  savingId.value = selected.value.id;
  error.value = "";
  message.value = "";
  try {
    const created = await createRequirement({
      workspace_code: workspace.currentCode,
      title: `跟进：${selected.value.title}`,
      description: selected.value.event_brief || selected.value.event_content || selected.value.timeline_brief,
      priority: selected.value.importance_level === "high" ? "high" : "medium",
      source_entity_milestone_id: selected.value.id,
      source_note: "由实体大事记事件触发"
    });
    message.value = `已创建跟进需求：${created.title}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建跟进需求失败";
  } finally {
    savingId.value = "";
  }
}

function isAnchoredEntity(entity: TrackedEntityListItem) {
  return pendingEntityId.value === entity.id || selected.value?.tracked_entity_id === entity.id && pendingMilestoneId.value === selected.value?.id;
}

function isAnchoredMilestone(item: EntityMilestoneListItem) {
  return pendingMilestoneId.value === item.id;
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

watch(
  () => workspace.currentCode,
  () => {
    selectedEntityId.value = "";
    void loadAll();
  }
);
watch(
  () => [pendingEntityId.value, pendingMilestoneId.value] as const,
  () => {
    void loadAll();
  }
);
onMounted(loadAll);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Entity Timeline</p>
        <h2>实体大事记</h2>
        <p>公司/组织/项目的事件时间线：沉淀关键实体的里程碑事件，支持从旧系统导入，未来从日报采信项持续积累。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadAll">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="timeline-summary-grid">
      <article class="module-card compact">
        <p class="eyebrow">Entities</p>
        <strong>{{ summary?.total_entities ?? 0 }}</strong>
        <span>归档实体</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Milestones</p>
        <strong>{{ summary?.total_milestones ?? 0 }}</strong>
        <span>时间线事件</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Refs</p>
        <strong>{{ summary?.unresolved_ref_count ?? 0 }}</strong>
        <span>未解析引用</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Range</p>
        <strong>{{ summary?.earliest_event_time ? formatDate(summary.earliest_event_time).slice(0, 10) : "暂无" }}</strong>
        <span>{{ summary?.latest_event_time ? formatDate(summary.latest_event_time).slice(0, 10) : "待导入" }}</span>
      </article>
    </section>

    <section class="module-card timeline-filters">
      <label>
        <span>实体</span>
        <span class="inline-search">
          <Search :size="15" />
          <input v-model.trim="filters.entityQuery" type="search" placeholder="名称或类型" />
        </span>
      </label>
      <label>
        <span>事件</span>
        <span class="inline-search">
          <Search :size="15" />
          <input v-model.trim="filters.eventQuery" type="search" placeholder="标题或正文" />
        </span>
      </label>
      <label>
        <span>类型</span>
        <select v-model="filters.eventType">
          <option value="">全部</option>
          <option v-for="item in eventTypes" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label>
        <span>等级</span>
        <select v-model="filters.importanceLevel">
          <option value="">全部</option>
          <option v-for="item in importanceLevels" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label>
        <span>板块</span>
        <input v-model.trim="filters.board" type="text" placeholder="AI模型" />
      </label>
      <label class="timeline-check">
        <input v-model="filters.unresolvedOnly" type="checkbox" />
        <span>仅未解析引用</span>
      </label>
      <button type="button" class="icon-button" :disabled="loading" @click="loadAll">
        <Search :size="16" />
        <span>筛选</span>
      </button>
    </section>

    <section class="timeline-type-strip" aria-label="实体类型">
      <span v-for="item in entityTypes" :key="item">{{ item }} · {{ summary?.by_entity_type[item] ?? 0 }}</span>
    </section>

    <section class="module-grid timeline-layout">
      <aside class="module-card entity-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Tracked</p><h3>实体</h3></div>
          <span class="metric-pill">{{ entities.length }} items</span>
        </div>
        <button
          v-for="entity in entities"
          :key="entity.id"
          type="button"
          class="entity-row"
          :class="{ selected: selectedEntityId === entity.id, anchored: isAnchoredEntity(entity) }"
          :aria-current="isAnchoredEntity(entity) ? 'true' : undefined"
          @click="selectEntity(entity.id)"
        >
          <span class="feed-icon indigo"><UserRound :size="17" /></span>
          <span>
            <strong>{{ entity.name }}</strong>
            <small>{{ entity.entity_type }} · {{ entity.rank || "未分级" }}</small>
            <em>{{ entity.milestone_count }} events · score {{ entity.influence_score.toFixed(0) }}</em>
          </span>
        </button>
        <p v-if="!loading && entities.length === 0" class="empty-state">暂无实体归档，执行历史实体导入后这里会展示公司/项目时间线。</p>
      </aside>

      <section class="module-card milestone-list">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">{{ selectedEntity?.entity_type || "Timeline" }}</p>
            <h3>{{ selectedEntity?.name || "事件时间线" }}</h3>
          </div>
          <span class="metric-pill">{{ milestones.length }} events</span>
        </div>

        <article
          v-for="item in milestones"
          :key="item.id"
          class="milestone-row"
          :class="{ selected: selected?.id === item.id, anchored: isAnchoredMilestone(item) }"
          :aria-current="isAnchoredMilestone(item) ? 'true' : undefined"
          @click="selectMilestone(item.id)"
        >
          <span class="timeline-dot"><CircleDot :size="16" /></span>
          <div>
            <div class="milestone-meta">
              <span>{{ formatDate(item.event_time) }}</span>
              <span>{{ item.event_type || "未分类" }}</span>
              <span>{{ item.importance_level }} · {{ item.importance_score.toFixed(0) }}</span>
              <span>{{ item.curation_status }}</span>
            </div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.timeline_brief || item.board || item.source_name || "暂无摘要" }}</p>
            <div class="coverage-metrics">
              <span>{{ item.board || "未分板块" }}</span>
              <span>{{ item.source_name || "未知来源" }}</span>
              <span :class="{ danger: item.article_ref_resolved === false || item.report_ref_resolved === false }">
                refs {{ item.article_ref_resolved === false || item.report_ref_resolved === false ? "gap" : "ok" }}
              </span>
            </div>
          </div>
          <TriangleAlert
            v-if="item.article_ref_resolved === false || item.report_ref_resolved === false"
            :size="18"
            class="warning-icon"
          />
        </article>
        <p v-if="!loading && milestones.length === 0" class="empty-state">暂无事件，选择其他实体或导入实体大事记后再查看。</p>
      </section>

      <section class="module-card milestone-detail">
        <div v-if="selected">
          <div class="card-title-row">
            <div>
              <p class="eyebrow">{{ selected.entity_name }} · {{ selected.importance_level }} · {{ selected.curation_status }}</p>
              <h3>{{ selected.title }}</h3>
            </div>
            <span class="metric-pill">{{ detailLoading ? "loading" : selected.legacy_id }}</span>
          </div>

          <div class="detail-strip">
            <span><Clock3 :size="15" />{{ formatDate(selected.event_time) }}</span>
            <span><GitBranch :size="15" />{{ selected.event_dedupe_key || "no dedupe" }}</span>
            <a v-if="selected.source_url" :href="selected.source_url" target="_blank" rel="noreferrer">
              <Link2 :size="15" />来源
            </a>
          </div>

          <div v-if="canGovernSelected" class="milestone-actions">
            <button type="button" class="mini-action" @click="editing = !editing">
              <Pencil :size="15" />
              <span>{{ editing ? "收起编辑" : "编辑事件" }}</span>
            </button>
            <button type="button" class="mini-action" :disabled="savingId === selected.id" @click="setCurationStatus('confirmed')">
              <CheckCircle2 :size="15" />
              <span>确认</span>
            </button>
            <button type="button" class="mini-action" :disabled="savingId === selected.id" @click="setCurationStatus('revoked')">
              <CircleSlash2 :size="15" />
              <span>撤销</span>
            </button>
            <button type="button" class="mini-action" :disabled="savingId === selected.id" @click="createRequirementFromMilestone">
              <Plus :size="15" />
              <span>转需求</span>
            </button>
          </div>

          <form v-if="editing && canGovernSelected" class="milestone-edit-form" @submit.prevent="saveMilestoneEdit">
            <label>标题<input v-model="editDraft.title" /></label>
            <label>类型<input v-model="editDraft.eventType" /></label>
            <label>板块<input v-model="editDraft.board" /></label>
            <label>等级
              <select v-model="editDraft.importanceLevel">
                <option value="high">high</option>
                <option value="medium">medium</option>
                <option value="low">low</option>
              </select>
            </label>
            <label>重要分<input v-model.number="editDraft.importanceScore" type="number" min="0" max="100" /></label>
            <label class="wide">事件摘要<textarea v-model="editDraft.eventBrief" rows="3" /></label>
            <label class="wide">影响摘要<textarea v-model="editDraft.impactBrief" rows="3" /></label>
            <button type="submit" class="icon-button" :disabled="savingId === selected.id || !editDraft.title.trim()">
              <Save :size="16" />
              <span>{{ savingId === selected.id ? "保存中" : "保存事件" }}</span>
            </button>
          </form>

          <section class="detail-block">
            <p class="eyebrow">Event</p>
            <p>{{ selected.event_brief || selected.event_content || "暂无事件正文" }}</p>
          </section>
          <section class="detail-block">
            <p class="eyebrow">Impact</p>
            <p>{{ selected.impact_brief || selected.impact || "暂无影响说明" }}</p>
          </section>
          <section class="detail-block">
            <p class="eyebrow">Legacy Refs</p>
            <pre>{{ compactJson(selected.legacy_refs) }}</pre>
          </section>
        </div>
        <div v-else class="timeline-empty-detail">
          <GitBranch :size="36" />
          <h3>没有可查看的事件</h3>
          <p>实体大事记是历史时间线资产，不影响当前日报、推荐或 SQL 导出。</p>
        </div>
      </section>
    </section>
  </section>
</template>

<style scoped>
.timeline-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.timeline-summary-grid strong {
  display: block;
  color: var(--color-slate-950);
  font-size: 28px;
  line-height: 1.1;
  margin: 6px 0 3px;
}

.timeline-filters {
  align-items: end;
  display: grid;
  gap: 12px;
  grid-template-columns: 1.1fr 1.2fr 1fr 0.8fr 1fr auto auto;
  margin-bottom: 14px;
}

.timeline-filters label {
  color: var(--color-slate-500);
  display: grid;
  font-size: 12px;
  gap: 6px;
}

.timeline-filters input,
.timeline-filters select {
  border: 1px solid var(--color-slate-200);
  border-radius: 8px;
  color: var(--color-slate-700);
  min-height: 38px;
  padding: 0 10px;
}

.inline-search {
  align-items: center;
  border: 1px solid var(--color-slate-200);
  border-radius: 8px;
  display: flex;
  gap: 6px;
  min-height: 38px;
  padding: 0 10px;
}

.inline-search input {
  border: 0;
  min-height: auto;
  padding: 0;
  width: 100%;
}

.timeline-check {
  align-items: center;
  display: flex !important;
  flex-direction: row;
  gap: 7px !important;
  min-height: 38px;
}

.timeline-check input {
  min-height: auto;
}

.timeline-type-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 16px;
}

.timeline-type-strip span {
  background: var(--color-slate-100);
  border: 1px solid var(--color-slate-200);
  border-radius: 999px;
  color: var(--color-slate-600);
  font-size: 12px;
  padding: 6px 10px;
}

.timeline-layout {
  align-items: start;
  grid-template-columns: minmax(220px, 0.65fr) minmax(360px, 1.35fr) minmax(320px, 1fr);
}

.entity-list,
.milestone-detail {
  position: sticky;
  top: 18px;
}

.entity-row {
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  gap: 10px;
  padding: 10px;
  text-align: left;
  width: 100%;
}

.entity-row + .entity-row {
  margin-top: 6px;
}

.entity-row.selected,
.entity-row:hover {
  background: rgba(79, 70, 229, 0.06);
  border-color: rgba(79, 70, 229, 0.18);
}

.entity-row span:last-child {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.entity-row strong,
.milestone-row h3 {
  color: var(--color-slate-950);
  font-size: 14px;
  line-height: 1.35;
}

.entity-row small,
.entity-row em,
.milestone-row p,
.milestone-meta {
  color: var(--color-slate-500);
  font-size: 12px;
  font-style: normal;
}

.milestone-list {
  display: grid;
  gap: 10px;
}

.milestone-row {
  border: 1px solid var(--color-slate-200);
  border-radius: 8px;
  cursor: pointer;
  display: grid;
  gap: 12px;
  grid-template-columns: 24px 1fr auto;
  padding: 14px;
}

.milestone-row.selected,
.milestone-row:hover {
  border-color: rgba(79, 70, 229, 0.28);
  box-shadow: 0 8px 26px rgba(15, 23, 42, 0.06);
}

.timeline-dot {
  color: var(--color-indigo-600);
  padding-top: 2px;
}

.milestone-meta,
.coverage-metrics,
.detail-strip {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.coverage-metrics span,
.detail-strip span,
.detail-strip a {
  align-items: center;
  background: var(--color-slate-100);
  border-radius: 999px;
  color: var(--color-slate-600);
  display: inline-flex;
  font-size: 12px;
  gap: 5px;
  padding: 5px 8px;
  text-decoration: none;
}

.coverage-metrics .danger {
  background: rgba(239, 68, 68, 0.1);
  color: #b91c1c;
}

.warning-icon {
  color: #d97706;
}

.detail-strip {
  margin: 12px 0;
}

.milestone-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}

.milestone-edit-form {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 12px 0 16px;
}

.milestone-edit-form label {
  color: var(--color-slate-500);
  display: grid;
  font-size: 12px;
  font-weight: 800;
  gap: 6px;
}

.milestone-edit-form input,
.milestone-edit-form select,
.milestone-edit-form textarea {
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 10px;
  padding: 9px 10px;
}

.milestone-edit-form .wide,
.milestone-edit-form button {
  grid-column: 1 / -1;
}

.detail-block {
  border-top: 1px solid var(--color-slate-200);
  padding: 14px 0;
}

.detail-block p:last-child {
  color: var(--color-slate-700);
  font-size: 14px;
  line-height: 1.7;
  margin: 0;
}

.detail-block pre {
  background: var(--color-slate-950);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.6;
  max-height: 260px;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
}

.timeline-empty-detail {
  align-items: center;
  color: var(--color-slate-500);
  display: grid;
  justify-items: center;
  min-height: 360px;
  text-align: center;
}

@media (max-width: 1180px) {
  .timeline-summary-grid,
  .timeline-filters,
  .timeline-layout {
    grid-template-columns: 1fr;
  }

  .entity-list,
  .milestone-detail {
    position: static;
  }
}
</style>
