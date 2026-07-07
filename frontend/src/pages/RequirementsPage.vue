<script setup lang="ts">
import { CheckCircle2, Plus, RefreshCw } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createRequirement,
  fetchRequirements,
  updateRequirement,
  type RequirementRecord
} from "../api/operations";
import { fetchWorkspaceMembers, type WorkspaceMemberRecord } from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const session = useSessionStore();
const route = useRoute();
const requirements = ref<RequirementRecord[]>([]);
const members = ref<WorkspaceMemberRecord[]>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const feedbackDrafts = reactive<Record<string, { outcome: string; reason: string }>>({});
const draft = reactive({
  title: "",
  description: "",
  priority: "medium",
  due_at: "",
  owner_user_id: "",
  source_daily_report_item_id: "",
  source_entity_milestone_id: "",
  source_note: ""
});

const openCount = computed(() => requirements.value.filter((item) => item.status === "open").length);
const doneCount = computed(() => requirements.value.filter((item) => item.status === "done").length);
const pendingRequirementAnchorId = computed(() => {
  const value = route.query.requirement_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const canManageRequirements = computed(() => {
  if (session.user?.roles.includes("super_admin")) {
    return true;
  }
  return ["owner", "admin"].includes(workspace.current?.current_user_workspace_role ?? "");
});
const assignableMembers = computed(() =>
  members.value.filter((member) => member.enabled && member.user.is_active && member.user.status === "active")
);

async function loadRequirements() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    requirements.value = await fetchRequirements(workspace.currentCode);
    for (const item of requirements.value) {
      syncFeedbackDraft(item);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载内部需求失败";
  } finally {
    loading.value = false;
  }
}

async function loadMembers() {
  if (!workspace.currentCode || !canManageRequirements.value) {
    members.value = [];
    return;
  }
  try {
    members.value = await fetchWorkspaceMembers(workspace.currentCode);
  } catch {
    members.value = [];
  }
}

async function submitRequirement() {
  if (!workspace.currentCode || !draft.title.trim()) {
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const created = await createRequirement({
      workspace_code: workspace.currentCode,
      title: draft.title.trim(),
      description: draft.description.trim(),
      priority: draft.priority,
      due_at: draft.due_at || null,
      owner_user_id: draft.owner_user_id || null,
      source_daily_report_item_id: draft.source_daily_report_item_id.trim() || null,
      source_entity_milestone_id: draft.source_entity_milestone_id.trim() || null,
      source_note: draft.source_note.trim()
    });
    syncFeedbackDraft(created);
    requirements.value.unshift(created);
    draft.title = "";
    draft.description = "";
    draft.priority = "medium";
    draft.due_at = "";
    draft.owner_user_id = "";
    draft.source_daily_report_item_id = "";
    draft.source_entity_milestone_id = "";
    draft.source_note = "";
    message.value = "内部需求已创建";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建内部需求失败";
  } finally {
    saving.value = false;
  }
}

async function setStatus(item: RequirementRecord, status: string) {
  error.value = "";
  try {
    const updated = await updateRequirement(item.id, { status });
    const index = requirements.value.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      requirements.value.splice(index, 1, updated);
      syncFeedbackDraft(updated);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新需求状态失败";
  }
}

async function assignOwner(item: RequirementRecord, ownerUserId: string) {
  error.value = "";
  try {
    const updated = await updateRequirement(item.id, { owner_user_id: ownerUserId || null });
    const index = requirements.value.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      requirements.value.splice(index, 1, updated);
      syncFeedbackDraft(updated);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新负责人失败";
  }
}

async function submitRecommendationFeedback(item: RequirementRecord) {
  if (!item.source_links.length) {
    error.value = "需求缺少来源追溯，不能反哺推荐";
    return;
  }
  const draftValue = feedbackDrafts[item.id] ?? { outcome: "positive", reason: "" };
  error.value = "";
  try {
    const updated = await updateRequirement(item.id, {
      metadata_json: {
        recommendation_feedback: {
          outcome: draftValue.outcome,
          reason: draftValue.reason.trim()
        }
      }
    });
    const index = requirements.value.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      requirements.value.splice(index, 1, updated);
      syncFeedbackDraft(updated);
    }
    message.value = "需求结论已反哺推荐";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "反哺推荐失败";
  }
}

function handleOwnerChange(item: RequirementRecord, event: Event) {
  const target = event.target as HTMLSelectElement | null;
  void assignOwner(item, target?.value ?? "");
}

function syncFeedbackDraft(item: RequirementRecord) {
  const feedback = recommendationFeedback(item);
  feedbackDrafts[item.id] = {
    outcome: feedback.outcome || "positive",
    reason: feedback.reason || ""
  };
}

function recommendationFeedback(item: RequirementRecord): { outcome: string; reason: string } {
  const value = item.metadata_json?.recommendation_feedback;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { outcome: "", reason: "" };
  }
  const feedback = value as Record<string, unknown>;
  return {
    outcome: typeof feedback.outcome === "string" ? feedback.outcome : "",
    reason: typeof feedback.reason === "string" ? feedback.reason : ""
  };
}

function feedbackLabel(outcome: string) {
  const labels: Record<string, string> = {
    positive: "正向",
    negative: "负向",
    neutral: "中性"
  };
  return labels[outcome] ?? outcome;
}

function formatDate(value: string | null) {
  return value ? value.slice(0, 10) : "未设置";
}

function sourceLabel(sourceObjectType: string) {
  const labels: Record<string, string> = {
    daily_report_item: "日报条目",
    weekly_report_item: "周报条目",
    entity_milestone: "实体事件",
    historical_report: "历史报告",
    historical_feedback: "历史反馈",
    insight: "洞察",
    news_item: "新闻",
    raw_item: "原始信号"
  };
  return labels[sourceObjectType] ?? sourceObjectType;
}

function sourceHref(link: RequirementRecord["source_links"][number]) {
  if (link.daily_report_item_id) {
    return `/daily-reports?daily_report_item_id=${link.daily_report_item_id}`;
  }
  if (link.weekly_report_item_id) {
    return `/weekly-reports?weekly_report_item_id=${link.weekly_report_item_id}`;
  }
  if (link.entity_milestone_id) {
    return `/entity-milestones?milestone_id=${link.entity_milestone_id}`;
  }
  if (link.historical_report_id) {
    return `/historical-reports?id=${link.historical_report_id}`;
  }
  if (link.historical_feedback_item_id) {
    return `/quality-archive?feedback_id=${link.historical_feedback_item_id}`;
  }
  if (link.news_item_id) {
    return `/news?news_item_id=${link.news_item_id}`;
  }
  if (link.raw_item_id) {
    return `/news?raw_item_id=${link.raw_item_id}`;
  }
  return "";
}

function isAnchoredRequirement(item: RequirementRecord) {
  return pendingRequirementAnchorId.value === item.id;
}

watch(
  () => workspace.currentCode,
  () => {
    void loadRequirements();
    void loadMembers();
  }
);
onMounted(() => {
  void loadRequirements();
  void loadMembers();
});
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Strategic Loop</p>
        <h2>内部需求</h2>
        <p>把日报里的外部信号沉淀为当前工作台可跟踪的需求入口。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadRequirements">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <div class="module-stats">
      <article><strong>{{ requirements.length }}</strong><span>总需求</span></article>
      <article><strong>{{ openCount }}</strong><span>进行中</span></article>
      <article><strong>{{ doneCount }}</strong><span>已完成</span></article>
    </div>

    <section class="module-split ops-layout">
      <form v-if="canManageRequirements" class="module-card ops-form" @submit.prevent="submitRequirement">
        <p class="eyebrow">Create</p>
        <h3>新增需求</h3>
        <label>标题<input v-model="draft.title" placeholder="例如：跟踪 Agent 编排能力对内部工具链的影响" /></label>
        <label>描述<textarea v-model="draft.description" rows="5" /></label>
        <div class="form-grid-two">
          <label>优先级
            <select v-model="draft.priority">
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
          </label>
          <label>截止日期<input v-model="draft.due_at" type="date" /></label>
        </div>
        <label>负责人
          <select v-model="draft.owner_user_id">
            <option value="">暂不指定</option>
            <option v-for="member in assignableMembers" :key="member.user.id" :value="member.user.id">
              {{ member.user.display_name }} · {{ member.workspace_role }}
            </option>
          </select>
        </label>
        <label>来源日报条目 ID<input v-model="draft.source_daily_report_item_id" placeholder="从日报采信条目复制 ID，可留空" /></label>
        <label>来源实体事件 ID<input v-model="draft.source_entity_milestone_id" placeholder="从实体大事记复制 ID，可留空" /></label>
        <label>来源说明<textarea v-model="draft.source_note" rows="3" placeholder="记录为什么这条情报触发该需求" /></label>
        <button type="submit" class="icon-button" :disabled="saving || !draft.title.trim()">
          <Plus :size="17" />
          <span>{{ saving ? "创建中" : "创建需求" }}</span>
        </button>
      </form>

      <article class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Requirements</p><h3>需求列表</h3></div>
        </div>
        <article
          v-for="item in requirements"
          :key="item.id"
          class="ops-row requirement-row"
          :class="{ anchored: isAnchoredRequirement(item) }"
          :aria-current="isAnchoredRequirement(item) ? 'true' : undefined"
        >
          <div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description || "暂无描述" }}</p>
            <div class="coverage-metrics">
              <span>{{ item.priority }}</span>
              <span>{{ item.status }}</span>
              <span>due {{ formatDate(item.due_at) }}</span>
              <span>{{ item.task_count }} tasks</span>
              <span>{{ item.owner_name || "未指定负责人" }}</span>
              <span v-if="recommendationFeedback(item).outcome">
                推荐反哺 {{ feedbackLabel(recommendationFeedback(item).outcome) }}
              </span>
            </div>
            <div v-if="item.source_links.length" class="requirement-source-list" aria-label="来源追溯">
              <article v-for="link in item.source_links" :key="link.id" class="requirement-source-item">
                <span>{{ sourceLabel(link.source_object_type) }}</span>
                <a v-if="link.source_url" :href="link.source_url" target="_blank" rel="noreferrer">
                  {{ link.source_title || link.source_url }}
                </a>
                <strong v-else>{{ link.source_title || link.news_item_id || link.raw_item_id || "未命名来源" }}</strong>
                <em v-if="link.data_source_name">{{ link.data_source_name }}</em>
                <p v-if="link.note">{{ link.note }}</p>
                <a v-if="sourceHref(link)" class="text-link" :href="sourceHref(link)">定位对象</a>
              </article>
            </div>
          </div>
          <div v-if="canManageRequirements" class="task-row-actions">
            <label class="compact-field">
              <span>负责人</span>
              <select :value="item.owner_user_id || ''" @change="handleOwnerChange(item, $event)">
                <option v-if="!item.owner_user_id" value="">未指定</option>
                <option v-for="member in assignableMembers" :key="member.user.id" :value="member.user.id">
                  {{ member.user.display_name }}
                </option>
              </select>
            </label>
            <button type="button" class="mini-action" :class="{ active: item.status === 'done' }" @click="setStatus(item, item.status === 'done' ? 'open' : 'done')">
              <CheckCircle2 :size="15" />
              <span>{{ item.status === "done" ? "重开" : "完成" }}</span>
            </button>
            <label class="compact-field">
              <span>推荐反哺</span>
              <select v-model="feedbackDrafts[item.id].outcome">
                <option value="positive">正向</option>
                <option value="negative">负向</option>
                <option value="neutral">中性</option>
              </select>
            </label>
            <label class="compact-field">
              <span>结论原因</span>
              <input v-model="feedbackDrafts[item.id].reason" placeholder="形成建议或不采纳原因" />
            </label>
            <button type="button" class="mini-action" @click="submitRecommendationFeedback(item)">
              <CheckCircle2 :size="15" />
              <span>反哺</span>
            </button>
          </div>
          <span v-else class="metric-pill">{{ item.status }}</span>
        </article>
        <p v-if="!loading && requirements.length === 0" class="empty-state">暂无内部需求，可从日报/周报复盘中新增需要跟进的问题。</p>
      </article>
    </section>
  </section>
</template>
