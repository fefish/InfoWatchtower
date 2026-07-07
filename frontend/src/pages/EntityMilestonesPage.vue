<script setup lang="ts">
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDot,
  CircleSlash2,
  Clock3,
  ExternalLink,
  GitBranch,
  Link2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  UserRound,
  UserRoundPlus
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  createEntityMilestone,
  createRequirement,
  createTrackedEntity,
  fetchEntityMilestoneDetail,
  fetchEntityTimelineSummary,
  fetchTrackedEntities,
  fetchTrackedEntityTimeline,
  updateEntityMilestone,
  type EntityMilestoneDetailRecord,
  type EntityMilestoneListItem,
  type EntityTimelineSummaryRecord,
  type TrackedEntityListItem,
  type TrackedEntityTimelineRecord
} from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const router = useRouter();
const workspace = useWorkspaceStore();

const summary = ref<EntityTimelineSummaryRecord | null>(null);
const entities = ref<TrackedEntityListItem[]>([]);
const timeline = ref<TrackedEntityTimelineRecord | null>(null);
const selectedEntityId = ref("");
const selected = ref<EntityMilestoneDetailRecord | null>(null);
const expandedMilestoneId = ref("");
const loading = ref(false);
const detailLoading = ref(false);
const savingId = ref("");
const editing = ref(false);
const showEntityForm = ref(false);
const showManualForm = ref(false);
const entityQuery = ref("");
const error = ref("");
const message = ref("");

const entityDraft = reactive({
  name: "",
  entityType: "company",
  aliases: ""
});

const manualDraft = reactive({
  title: "",
  eventType: "release",
  eventDate: "",
  brief: ""
});

const editDraft = reactive({
  title: "",
  eventType: "",
  eventBrief: "",
  impactBrief: "",
  board: "",
  importanceLevel: "medium",
  importanceScore: 70
});

const selectedEntity = computed(() => entities.value.find((item) => item.id === selectedEntityId.value) ?? null);
const pendingEntityId = computed(() => routeQueryString(route.query.entity_id));
const pendingMilestoneId = computed(() => routeQueryString(route.query.milestone_id));
const roleRank: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3
};
const canManage = computed(() => roleRank[workspace.current?.current_user_workspace_role ?? ""] >= 2);
const canGovernSelected = computed(() => canManage.value && selected.value?.legacy_system === "current");
const selectedCurrentRefs = computed(() => {
  const refs = (selected.value?.metadata_json as Record<string, unknown> | undefined)?.current_refs;
  return refs && typeof refs === "object" ? (refs as Record<string, unknown>) : {};
});
const selectedReportId = computed(() => {
  const value = selectedCurrentRefs.value.source_report_id;
  return typeof value === "string" && value ? value : "";
});

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
      fetchTrackedEntities({ workspaceCode: workspace.currentCode, query: entityQuery.value || undefined })
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
    } else if (
      (!selectedEntityId.value || !nextEntities.some((item) => item.id === selectedEntityId.value)) &&
      nextEntities.length > 0
    ) {
      selectedEntityId.value = nextEntities[0].id;
    }
    await loadTimeline();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载实体大事记失败";
  } finally {
    loading.value = false;
  }
}

async function loadTimeline() {
  if (!selectedEntityId.value) {
    timeline.value = null;
    return;
  }
  try {
    timeline.value = await fetchTrackedEntityTimeline(selectedEntityId.value);
    if (!selected.value || selected.value.tracked_entity_id !== selectedEntityId.value) {
      const first = timeline.value.groups[0]?.milestones[0];
      if (first) {
        await selectMilestone(first.id);
      } else {
        selected.value = null;
      }
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载实体时间线失败";
  }
}

async function selectEntity(id: string) {
  selectedEntityId.value = id;
  selected.value = null;
  expandedMilestoneId.value = "";
  await loadTimeline();
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

function toggleTrace(id: string) {
  expandedMilestoneId.value = expandedMilestoneId.value === id ? "" : id;
}

async function submitEntity() {
  if (!workspace.currentCode || !entityDraft.name.trim()) {
    return;
  }
  savingId.value = "entity-form";
  error.value = "";
  message.value = "";
  try {
    const created = await createTrackedEntity({
      workspace_code: workspace.currentCode,
      name: entityDraft.name.trim(),
      entity_type: entityDraft.entityType.trim() || "company",
      aliases: entityDraft.aliases
        .split(/[,，、]/)
        .map((alias) => alias.trim())
        .filter((alias) => alias.length > 0)
    });
    message.value = `已添加跟踪实体：${created.name}，发布日报时将自动为它抽取候选事件`;
    entityDraft.name = "";
    entityDraft.aliases = "";
    showEntityForm.value = false;
    await loadAll();
    await selectEntity(created.id);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "添加实体失败";
  } finally {
    savingId.value = "";
  }
}

async function submitManualMilestone() {
  if (!selectedEntityId.value || !manualDraft.title.trim()) {
    return;
  }
  savingId.value = "manual-form";
  error.value = "";
  message.value = "";
  try {
    await createEntityMilestone({
      tracked_entity_id: selectedEntityId.value,
      event_title: manualDraft.title.trim(),
      event_type: manualDraft.eventType.trim() || "manual",
      event_time: manualDraft.eventDate ? new Date(`${manualDraft.eventDate}T00:00:00Z`).toISOString() : null,
      event_brief: manualDraft.brief.trim()
    });
    message.value = "已补录里程碑";
    manualDraft.title = "";
    manualDraft.brief = "";
    manualDraft.eventDate = "";
    showManualForm.value = false;
    await loadTimeline();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "补录里程碑失败";
  } finally {
    savingId.value = "";
  }
}

async function setCurationStatus(milestoneId: string, status: "confirmed" | "revoked") {
  if (!canManage.value) {
    return;
  }
  savingId.value = milestoneId;
  error.value = "";
  message.value = "";
  try {
    const updated = await updateEntityMilestone(milestoneId, {
      curation_status: status,
      selected_for_timeline: status === "confirmed",
      curation_note: status === "confirmed" ? "人工确认进入时间线" : "人工驳回候选/撤销展示"
    });
    if (selected.value?.id === milestoneId) {
      selected.value = updated;
    }
    message.value = status === "confirmed" ? "已确认进入时间线" : "已驳回/撤销";
    await loadTimeline();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新事件状态失败";
  } finally {
    savingId.value = "";
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
    await loadTimeline();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新实体事件失败";
  } finally {
    savingId.value = "";
  }
}

async function createRequirementFromMilestone() {
  if (!selected.value || !workspace.currentCode || !canManage.value) {
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

function openSourceReport() {
  if (selectedReportId.value) {
    void router.push(`/daily-reports/${selectedReportId.value}`);
  }
}

function isAnchoredEntity(entity: TrackedEntityListItem) {
  return (
    pendingEntityId.value === entity.id ||
    (selected.value?.tracked_entity_id === entity.id && pendingMilestoneId.value === selected.value?.id)
  );
}

function isAnchoredMilestone(item: EntityMilestoneListItem) {
  return pendingMilestoneId.value === item.id;
}

function isCandidate(item: EntityMilestoneListItem) {
  return item.curation_status === "candidate";
}

function statusLabel(status: string) {
  if (status === "candidate") return "待确认";
  if (status === "confirmed") return "已确认";
  if (status === "revoked") return "已撤销";
  if (status === "draft") return "草稿";
  return "旧系统导入";
}

function monthLabel(month: string) {
  if (!month || month === "未标注时间") {
    return "未标注时间";
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
  <section class="layout-list">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Entity Timeline</p>
        <h2>实体大事记</h2>
        <p>跟踪重点公司/产品/组织的关键事件时间线：发布日报时自动从已采信条目抽取候选事件（可追溯到触发新闻），管理员确认后进入时间线，也可人工补录。</p>
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
        <span>跟踪实体</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Milestones</p>
        <strong>{{ summary?.total_milestones ?? 0 }}</strong>
        <span>时间线事件</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Pending</p>
        <strong>{{ timeline?.candidate_count ?? 0 }}</strong>
        <span>当前实体待确认候选</span>
      </article>
      <article class="module-card compact">
        <p class="eyebrow">Range</p>
        <strong>{{ summary?.earliest_event_time ? formatDate(summary.earliest_event_time).slice(0, 10) : "暂无" }}</strong>
        <span>{{ summary?.latest_event_time ? formatDate(summary.latest_event_time).slice(0, 10) : "待沉淀" }}</span>
      </article>
    </section>

    <section class="module-grid timeline-layout">
      <aside class="module-card entity-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Tracked</p><h3>实体</h3></div>
          <button
            v-if="canManage"
            type="button"
            class="mini-action entity-add-toggle"
            @click="showEntityForm = !showEntityForm"
          >
            <UserRoundPlus :size="15" />
            <span>新增实体</span>
          </button>
        </div>

        <form v-if="showEntityForm && canManage" class="entity-create-form" @submit.prevent="submitEntity">
          <label>
            <span>名称</span>
            <input v-model="entityDraft.name" placeholder="OpenAI / 昇腾 / Kimi" />
          </label>
          <label>
            <span>类型</span>
            <select v-model="entityDraft.entityType">
              <option value="company">company</option>
              <option value="product">product</option>
              <option value="organization">organization</option>
              <option value="technology">technology</option>
            </select>
          </label>
          <label>
            <span>别名（逗号分隔，命中标题/摘要即抽取候选）</span>
            <input v-model="entityDraft.aliases" placeholder="OpenAI, 欧宾AI" />
          </label>
          <button type="submit" class="icon-button" :disabled="savingId === 'entity-form' || !entityDraft.name.trim()">
            <Plus :size="15" />
            <span>{{ savingId === "entity-form" ? "添加中" : "添加并开始跟踪" }}</span>
          </button>
        </form>

        <label class="entity-search">
          <Search :size="14" />
          <input
            v-model.trim="entityQuery"
            type="search"
            placeholder="搜索实体名称或类型"
            @keyup.enter="loadAll"
          />
        </label>

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
            <em>{{ entity.milestone_count }} 事件 · 最近 {{ entity.latest_event_time ? formatDate(entity.latest_event_time).slice(0, 10) : "暂无" }}</em>
          </span>
        </button>
        <p v-if="!loading && entities.length === 0" class="empty-state entity-empty">
          还没有在跟踪的实体。先添加要跟踪的公司/产品（含别名），之后每次发布日报，
          已采信条目里命中这些名称的新闻会自动生成“待确认”里程碑候选。
        </p>
      </aside>

      <section class="module-card milestone-list">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">{{ selectedEntity?.entity_type || "Timeline" }}</p>
            <h3>{{ selectedEntity?.name || "事件时间线" }}</h3>
          </div>
          <div class="timeline-header-actions">
            <span class="metric-pill">{{ timeline?.total_milestones ?? 0 }} 事件</span>
            <button
              v-if="canManage && selectedEntityId"
              type="button"
              class="mini-action manual-add-toggle"
              @click="showManualForm = !showManualForm"
            >
              <Plus :size="15" />
              <span>补录里程碑</span>
            </button>
          </div>
        </div>

        <form v-if="showManualForm && canManage" class="manual-milestone-form" @submit.prevent="submitManualMilestone">
          <label>
            <span>事件标题</span>
            <input v-model="manualDraft.title" placeholder="发布新一代旗舰模型" />
          </label>
          <label>
            <span>类型</span>
            <input v-model="manualDraft.eventType" placeholder="release / funding / partnership" />
          </label>
          <label>
            <span>事件日期</span>
            <input v-model="manualDraft.eventDate" type="date" />
          </label>
          <label class="wide">
            <span>事件摘要</span>
            <textarea v-model="manualDraft.brief" rows="2" />
          </label>
          <button type="submit" class="icon-button" :disabled="savingId === 'manual-form' || !manualDraft.title.trim()">
            <Save :size="15" />
            <span>{{ savingId === "manual-form" ? "保存中" : "保存里程碑" }}</span>
          </button>
        </form>

        <template v-for="group in timeline?.groups ?? []" :key="group.month">
          <div class="timeline-month">
            <span>{{ monthLabel(group.month) }}</span>
            <small>{{ group.milestone_count }} 件<template v-if="group.candidate_count"> · {{ group.candidate_count }} 待确认</template></small>
          </div>
          <article
            v-for="item in group.milestones"
            :key="item.id"
            class="milestone-row"
            :class="{
              selected: selected?.id === item.id,
              anchored: isAnchoredMilestone(item),
              candidate: isCandidate(item)
            }"
            :aria-current="isAnchoredMilestone(item) ? 'true' : undefined"
            @click="selectMilestone(item.id)"
          >
            <span class="timeline-dot"><CircleDot :size="16" /></span>
            <div>
              <div class="milestone-meta">
                <span>{{ formatDate(item.event_time) }}</span>
                <span>{{ item.event_type || "未分类" }}</span>
                <span class="status-chip" :class="item.curation_status">{{ statusLabel(item.curation_status) }}</span>
              </div>
              <h3>{{ item.title }}</h3>
              <p>{{ item.timeline_brief || item.board || item.source_name || "暂无摘要" }}</p>
              <div v-if="isCandidate(item) && canManage" class="candidate-actions">
                <button
                  type="button"
                  class="mini-action confirm"
                  :disabled="savingId === item.id"
                  @click.stop="setCurationStatus(item.id, 'confirmed')"
                >
                  <CheckCircle2 :size="14" />
                  <span>确认</span>
                </button>
                <button
                  type="button"
                  class="mini-action reject"
                  :disabled="savingId === item.id"
                  @click.stop="setCurationStatus(item.id, 'revoked')"
                >
                  <CircleSlash2 :size="14" />
                  <span>驳回</span>
                </button>
              </div>
              <button type="button" class="trace-toggle" @click.stop="toggleTrace(item.id)">
                <component :is="expandedMilestoneId === item.id ? ChevronUp : ChevronDown" :size="14" />
                <span>触发新闻追溯</span>
              </button>
              <div v-if="expandedMilestoneId === item.id" class="trace-block">
                <span>{{ item.source_name || "未知来源" }}</span>
                <a
                  v-if="item.source_url"
                  :href="item.source_url"
                  target="_blank"
                  rel="noreferrer"
                  @click.stop
                >
                  <Link2 :size="13" />打开触发新闻
                </a>
                <span v-else>暂无来源链接，可在详情中查看引用</span>
              </div>
            </div>
          </article>
        </template>
        <p v-if="!loading && selectedEntityId && (timeline?.total_milestones ?? 0) === 0" class="empty-state">
          该实体还没有时间线事件。发布日报时命中它的已采信条目会自动生成候选；也可以点击“补录里程碑”手工添加。
        </p>
        <p v-if="!loading && !selectedEntityId" class="empty-state">
          先在左侧添加要跟踪的实体，这里会按月展示它的事件时间线。
        </p>
      </section>

      <section class="module-card milestone-detail">
        <div v-if="selected">
          <div class="card-title-row">
            <div>
              <p class="eyebrow">{{ selected.entity_name }} · {{ selected.importance_level }} · {{ statusLabel(selected.curation_status) }}</p>
              <h3>{{ selected.title }}</h3>
            </div>
            <span class="metric-pill">{{ detailLoading ? "loading" : selected.event_type || "event" }}</span>
          </div>

          <div class="detail-strip">
            <span><Clock3 :size="15" />{{ formatDate(selected.event_time) }}</span>
            <span><GitBranch :size="15" />{{ selected.source_name || "未知来源" }}</span>
            <a v-if="selected.source_url" :href="selected.source_url" target="_blank" rel="noreferrer">
              <Link2 :size="15" />触发新闻
            </a>
            <button v-if="selectedReportId" type="button" class="detail-report-link" @click="openSourceReport">
              <ExternalLink :size="14" />
              <span>回溯来源日报</span>
            </button>
          </div>

          <div v-if="canGovernSelected" class="milestone-actions">
            <button type="button" class="mini-action" @click="editing = !editing">
              <Pencil :size="15" />
              <span>{{ editing ? "收起编辑" : "编辑事件" }}</span>
            </button>
            <button type="button" class="mini-action" :disabled="savingId === selected.id" @click="setCurationStatus(selected.id, 'confirmed')">
              <CheckCircle2 :size="15" />
              <span>确认</span>
            </button>
            <button type="button" class="mini-action" :disabled="savingId === selected.id" @click="setCurationStatus(selected.id, 'revoked')">
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
          <section v-if="selected.curation_status === 'candidate'" class="detail-block candidate-hint">
            <p class="eyebrow">Candidate</p>
            <p>该事件由发布日报时自动抽取（命中实体名称/别名），确认后进入时间线，驳回则不再展示。</p>
          </section>
        </div>
        <div v-else class="timeline-empty-detail">
          <GitBranch :size="36" />
          <h3>没有可查看的事件</h3>
          <p>实体大事记沉淀已采信素材，不影响当前日报、推荐或 SQL 导出。</p>
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

.timeline-layout {
  align-items: start;
  grid-template-columns: minmax(240px, 0.7fr) minmax(360px, 1.35fr) minmax(320px, 1fr);
}

.entity-list,
.milestone-detail {
  position: sticky;
  top: 18px;
}

.entity-add-toggle {
  white-space: nowrap;
}

.entity-create-form,
.manual-milestone-form {
  display: grid;
  gap: 10px;
  margin: 10px 0 14px;
  border: 1px solid rgba(10, 132, 255, 0.22);
  border-radius: 12px;
  padding: 12px;
  background: rgba(10, 132, 255, 0.05);
}

.manual-milestone-form {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.manual-milestone-form .wide,
.manual-milestone-form button {
  grid-column: 1 / -1;
}

.entity-create-form label,
.manual-milestone-form label {
  color: var(--color-slate-500);
  display: grid;
  font-size: 12px;
  font-weight: 800;
  gap: 6px;
}

.entity-create-form input,
.entity-create-form select,
.manual-milestone-form input,
.manual-milestone-form textarea {
  border: 1px solid rgba(148, 163, 184, 0.4);
  border-radius: 10px;
  padding: 9px 10px;
  font: inherit;
}

.entity-search {
  align-items: center;
  border: 1px solid var(--color-slate-200);
  border-radius: 8px;
  color: var(--color-slate-500);
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
  min-height: 36px;
  padding: 0 10px;
}

.entity-search input {
  border: 0;
  min-height: auto;
  padding: 0;
  width: 100%;
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

.entity-empty {
  padding: 12px;
  text-align: left;
}

.timeline-header-actions {
  align-items: center;
  display: flex;
  gap: 8px;
}

.milestone-list {
  display: grid;
  gap: 10px;
}

.timeline-month {
  align-items: baseline;
  border-bottom: 1px solid var(--color-slate-200);
  display: flex;
  gap: 10px;
  justify-content: space-between;
  margin-top: 4px;
  padding-bottom: 6px;
}

.timeline-month span {
  color: var(--color-slate-950);
  font-size: 13px;
  font-weight: 800;
}

.timeline-month small {
  color: var(--color-slate-500);
  font-weight: 800;
}

.milestone-row {
  border: 1px solid var(--color-slate-200);
  border-radius: 8px;
  cursor: pointer;
  display: grid;
  gap: 12px;
  grid-template-columns: 24px 1fr;
  padding: 14px;
}

.milestone-row.selected,
.milestone-row:hover {
  border-color: rgba(79, 70, 229, 0.28);
  box-shadow: 0 8px 26px rgba(15, 23, 42, 0.06);
}

.milestone-row.candidate {
  background: rgba(245, 158, 11, 0.06);
  border-color: rgba(217, 119, 6, 0.3);
  border-style: dashed;
}

.timeline-dot {
  color: var(--color-indigo-600);
  padding-top: 2px;
}

.milestone-meta,
.detail-strip {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.status-chip {
  border-radius: 999px;
  font-weight: 800;
  padding: 2px 8px;
}

.status-chip.candidate {
  background: rgba(245, 158, 11, 0.16);
  color: #b45309;
}

.status-chip.confirmed {
  background: rgba(16, 185, 129, 0.14);
  color: #047857;
}

.status-chip.revoked {
  background: rgba(148, 163, 184, 0.2);
  color: #475569;
}

.status-chip.draft,
.status-chip.imported {
  background: var(--color-slate-100);
  color: var(--color-slate-600);
}

.candidate-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.candidate-actions .confirm {
  color: #047857;
}

.candidate-actions .reject {
  color: #b45309;
}

.trace-toggle {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--color-slate-500);
  cursor: pointer;
  display: inline-flex;
  font-size: 12px;
  font-weight: 800;
  gap: 4px;
  margin-top: 8px;
  padding: 0;
}

.trace-block {
  align-items: center;
  background: var(--color-slate-100);
  border-radius: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  padding: 8px 10px;
}

.trace-block span {
  color: var(--color-slate-600);
  font-size: 12px;
  font-weight: 700;
}

.trace-block a {
  align-items: center;
  color: #0a84ff;
  display: inline-flex;
  font-size: 12px;
  font-weight: 800;
  gap: 4px;
  text-decoration: none;
}

.detail-strip {
  margin: 12px 0;
}

.detail-strip span,
.detail-strip a,
.detail-report-link {
  align-items: center;
  background: var(--color-slate-100);
  border: 0;
  border-radius: 999px;
  color: var(--color-slate-600);
  cursor: pointer;
  display: inline-flex;
  font-size: 12px;
  font-weight: 700;
  gap: 5px;
  padding: 5px 8px;
  text-decoration: none;
}

.detail-report-link {
  color: #0a6ddd;
  background: rgba(10, 132, 255, 0.1);
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

.candidate-hint p:last-child {
  color: #b45309;
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
  .timeline-layout,
  .manual-milestone-form {
    grid-template-columns: 1fr;
  }

  .entity-list,
  .milestone-detail {
    position: static;
  }
}
</style>
