<script setup lang="ts">
import { AlertTriangle, CheckCircle2, ExternalLink, Plus, RefreshCw } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  batchUpdateTopicTasks,
  createTopicTask,
  fetchTopicTask,
  fetchTopicTasks,
  updateTopicTask,
  type TopicTaskFilters,
  type TopicTaskRecord
} from "../api/operations";
import { fetchWorkspaceMembers, type WorkspaceMemberRecord } from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const session = useSessionStore();
const route = useRoute();
const tasks = ref<TopicTaskRecord[]>([]);
const members = ref<WorkspaceMemberRecord[]>([]);
const detailTask = ref<TopicTaskRecord | null>(null);
const loading = ref(false);
const loadingDetail = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const taskView = ref<"all" | "mine" | "overdue" | "blocked">("all");
const blockedDrafts = reactive<Record<string, string>>({});
const selectedTaskIds = ref<string[]>([]);
const bulkStatus = ref("done");
const bulkBlockedReason = ref("");
const draft = reactive({
  title: "",
  description: "",
  status: "open",
  due_at: "",
  assignee_user_id: ""
});
const pendingTaskAnchorId = computed(() => {
  const value = route.query.task_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const assignableMembers = computed(() =>
  members.value.filter((member) => member.enabled && member.user.is_active && member.user.status === "active")
);
const canAssignTasks = computed(() => {
  if (session.user?.roles.includes("super_admin")) {
    return true;
  }
  return ["owner", "admin"].includes(workspace.current?.current_user_workspace_role ?? "");
});
const taskFilters = computed<TopicTaskFilters>(() => {
  if (taskView.value === "mine") {
    return { assignedToMe: true };
  }
  if (taskView.value === "overdue") {
    return { due: "overdue" };
  }
  if (taskView.value === "blocked") {
    return { status: "blocked" };
  }
  return {};
});
const overdueCount = computed(() => tasks.value.filter((item) => item.is_overdue).length);
const blockedCount = computed(() => tasks.value.filter((item) => item.status === "blocked").length);
const selectableTasks = computed(() => tasks.value.filter((item) => canUpdateTaskStatus(item)));
const selectableTaskIds = computed(() => selectableTasks.value.map((item) => item.id));
const selectedTasks = computed(() =>
  selectedTaskIds.value
    .map((taskId) => tasks.value.find((item) => item.id === taskId))
    .filter((item): item is TopicTaskRecord => Boolean(item))
);
const allSelectableSelected = computed(
  () => selectableTaskIds.value.length > 0 && selectableTaskIds.value.every((taskId) => selectedTaskIds.value.includes(taskId))
);

async function loadTasks() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    tasks.value = await fetchTopicTasks(workspace.currentCode, taskFilters.value);
    for (const item of tasks.value) {
      blockedDrafts[item.id] = item.blocked_reason || "";
    }
    selectedTaskIds.value = selectedTaskIds.value.filter((taskId) => selectableTaskIds.value.includes(taskId));
    if (pendingTaskAnchorId.value) {
      const anchored = tasks.value.find((item) => item.id === pendingTaskAnchorId.value);
      if (anchored) {
        detailTask.value = anchored;
      }
      void openTaskDetail(pendingTaskAnchorId.value);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载任务失败";
  } finally {
    loading.value = false;
  }
}

async function openTaskDetail(taskId: string) {
  if (!taskId) {
    return;
  }
  loadingDetail.value = true;
  error.value = "";
  try {
    detailTask.value = await fetchTopicTask(taskId);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载任务详情失败";
  } finally {
    loadingDetail.value = false;
  }
}

function closeTaskDetail() {
  detailTask.value = null;
}

async function loadMembers() {
  if (!workspace.currentCode || !canAssignTasks.value) {
    members.value = [];
    return;
  }
  try {
    members.value = await fetchWorkspaceMembers(workspace.currentCode);
  } catch {
    members.value = [];
  }
}

async function submitTask() {
  if (!workspace.currentCode || !draft.title.trim()) {
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const created = await createTopicTask({
      workspace_code: workspace.currentCode,
      title: draft.title.trim(),
      description: draft.description.trim(),
      status: draft.status,
      due_at: draft.due_at || null,
      assignee_user_id: draft.assignee_user_id || null
    });
    tasks.value.unshift(created);
    draft.title = "";
    draft.description = "";
    draft.status = "open";
    draft.due_at = "";
    draft.assignee_user_id = "";
    message.value = "任务已创建";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建任务失败";
  } finally {
    saving.value = false;
  }
}

async function setTaskStatus(item: TopicTaskRecord, status: string, blockedReason?: string) {
  error.value = "";
  try {
    const payload: Parameters<typeof updateTopicTask>[1] = { status };
    if (blockedReason !== undefined) {
      payload.metadata_json = { blocked_reason: blockedReason };
    }
    const updated = await updateTopicTask(item.id, payload);
    const index = tasks.value.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      tasks.value.splice(index, 1, updated);
    }
    blockedDrafts[item.id] = updated.blocked_reason || "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新任务失败";
  }
}

async function toggleTask(item: TopicTaskRecord) {
  const status = item.status === "done" ? "open" : "done";
  await setTaskStatus(item, status);
}

async function markBlocked(item: TopicTaskRecord) {
  const reason = (blockedDrafts[item.id] || "").trim();
  if (!reason) {
    error.value = "请先填写阻塞原因";
    return;
  }
  await setTaskStatus(item, "blocked", reason);
}

async function submitBatchUpdate() {
  if (!workspace.currentCode || selectedTaskIds.value.length === 0) {
    return;
  }
  const reason = bulkBlockedReason.value.trim();
  if (bulkStatus.value === "blocked" && !reason) {
    error.value = "批量标记阻塞前请填写阻塞原因";
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await batchUpdateTopicTasks({
      workspace_code: workspace.currentCode,
      task_ids: [...selectedTaskIds.value],
      status: bulkStatus.value,
      blocked_reason: bulkStatus.value === "blocked" || reason ? reason : null
    });
    const updates = new Map(result.tasks.map((item) => [item.id, item]));
    tasks.value = tasks.value.map((item) => updates.get(item.id) ?? item);
    for (const item of result.tasks) {
      blockedDrafts[item.id] = item.blocked_reason || "";
    }
    selectedTaskIds.value = [];
    bulkBlockedReason.value = "";
    message.value = `已批量更新 ${result.updated_count} 个任务`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "批量更新任务失败";
  } finally {
    saving.value = false;
  }
}

async function assignTask(item: TopicTaskRecord, assigneeUserId: string) {
  error.value = "";
  try {
    const updated = await updateTopicTask(item.id, { assignee_user_id: assigneeUserId || null });
    const index = tasks.value.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      tasks.value.splice(index, 1, updated);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新负责人失败";
  }
}

function handleAssignChange(item: TopicTaskRecord, event: Event) {
  const target = event.target as HTMLSelectElement | null;
  void assignTask(item, target?.value ?? "");
}

function setTaskView(nextView: typeof taskView.value) {
  taskView.value = nextView;
  void loadTasks();
}

function isAnchoredTask(item: TopicTaskRecord) {
  return pendingTaskAnchorId.value === item.id;
}

function canUpdateTaskStatus(item: TopicTaskRecord) {
  return canAssignTasks.value || item.assignee_user_id === session.user?.id;
}

function isTaskSelected(item: TopicTaskRecord) {
  return selectedTaskIds.value.includes(item.id);
}

function toggleTaskSelection(item: TopicTaskRecord, event: Event) {
  const target = event.target as HTMLInputElement | null;
  if (!canUpdateTaskStatus(item)) {
    return;
  }
  if (target?.checked) {
    if (!selectedTaskIds.value.includes(item.id)) {
      selectedTaskIds.value = [...selectedTaskIds.value, item.id];
    }
  } else {
    selectedTaskIds.value = selectedTaskIds.value.filter((taskId) => taskId !== item.id);
  }
}

function toggleSelectAll(event: Event) {
  const target = event.target as HTMLInputElement | null;
  selectedTaskIds.value = target?.checked ? [...selectableTaskIds.value] : [];
}

function requirementHref(item: TopicTaskRecord) {
  return item.requirement_id ? `/requirements?requirement_id=${item.requirement_id}` : "";
}

function requirementSourceHref(link: TopicTaskRecord["requirement_source_links"][number]) {
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

watch(
  () => workspace.currentCode,
  () => {
    void loadTasks();
    void loadMembers();
  }
);
onMounted(() => {
  void loadTasks();
  void loadMembers();
});
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Strategic Loop</p>
        <h2>指派任务</h2>
        <p>管理员把待观察议题和遗留问题分派出去，形成持续跟踪闭环。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadTasks">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="module-split ops-layout">
      <form v-if="canAssignTasks" class="module-card ops-form" @submit.prevent="submitTask">
        <p class="eyebrow">Create</p>
        <h3>新增任务</h3>
        <label>标题<input v-model="draft.title" placeholder="例如：整理 5 月 Agent 工程能力变化" /></label>
        <label>描述<textarea v-model="draft.description" rows="5" /></label>
        <div class="form-grid-two">
          <label>状态
            <select v-model="draft.status">
              <option value="open">open</option>
              <option value="doing">doing</option>
              <option value="blocked">blocked</option>
              <option value="done">done</option>
              <option value="canceled">canceled</option>
            </select>
          </label>
          <label>截止日期<input v-model="draft.due_at" type="date" /></label>
        </div>
        <label>负责人
          <select v-model="draft.assignee_user_id">
            <option value="">暂不指派</option>
            <option v-for="member in assignableMembers" :key="member.user.id" :value="member.user.id">
              {{ member.user.display_name }} · {{ member.workspace_role }}
            </option>
          </select>
        </label>
        <button type="submit" class="icon-button" :disabled="saving || !draft.title.trim()">
          <Plus :size="17" />
          <span>{{ saving ? "创建中" : "创建任务" }}</span>
        </button>
      </form>

      <article class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Tasks</p><h3>任务列表</h3></div>
          <div class="coverage-metrics">
            <span>{{ tasks.length }} tasks</span>
            <span>{{ overdueCount }} overdue</span>
            <span>{{ blockedCount }} blocked</span>
          </div>
        </div>
        <div class="coverage-filter" role="tablist" aria-label="任务视图">
          <button type="button" :class="{ active: taskView === 'all' }" @click="setTaskView('all')">全部</button>
          <button type="button" :class="{ active: taskView === 'mine' }" @click="setTaskView('mine')">我的</button>
          <button type="button" :class="{ active: taskView === 'overdue' }" @click="setTaskView('overdue')">逾期</button>
          <button type="button" :class="{ active: taskView === 'blocked' }" @click="setTaskView('blocked')">阻塞</button>
        </div>
        <div v-if="selectableTasks.length" class="task-batch-toolbar">
          <label class="compact-field select-field">
            <span>选择</span>
            <input type="checkbox" :checked="allSelectableSelected" @change="toggleSelectAll" />
          </label>
          <label class="compact-field">
            <span>批量状态</span>
            <select v-model="bulkStatus">
              <option value="open">open</option>
              <option value="doing">doing</option>
              <option value="blocked">blocked</option>
              <option value="done">done</option>
              <option value="canceled">canceled</option>
            </select>
          </label>
          <label class="compact-field">
            <span>阻塞原因</span>
            <input v-model="bulkBlockedReason" placeholder="批量 blocked 时必填" />
          </label>
          <button
            type="button"
            class="mini-action"
            :disabled="saving || selectedTasks.length === 0"
            @click="submitBatchUpdate"
          >
            <CheckCircle2 :size="15" />
            <span>批量更新 {{ selectedTasks.length }}</span>
          </button>
        </div>
        <article
          v-for="item in tasks"
          :key="item.id"
          class="ops-row topic-task-row"
          :class="{ anchored: isAnchoredTask(item) }"
          :aria-current="isAnchoredTask(item) ? 'true' : undefined"
        >
          <div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description || "暂无描述" }}</p>
            <div class="coverage-metrics">
              <span>{{ item.status }}</span>
              <span v-if="item.is_overdue" class="metric-pill danger">逾期</span>
              <span>due {{ item.due_at ? item.due_at.slice(0, 10) : "未设置" }}</span>
              <span>{{ item.requirement_title || "未关联需求" }}</span>
              <span>{{ item.assignee_name || "未指派" }}</span>
            </div>
            <p v-if="item.blocked_reason" class="form-warning">阻塞原因：{{ item.blocked_reason }}</p>
            <div v-if="item.requirement_id || item.requirement_source_links.length" class="requirement-source-list">
              <a v-if="item.requirement_id" class="requirement-source-item" :href="requirementHref(item)">
                <span>需求</span>
                <strong>{{ item.requirement_title || item.requirement_id }}</strong>
                <em><ExternalLink :size="13" /> 查看</em>
              </a>
              <article
                v-for="link in item.requirement_source_links"
                :key="link.id"
                class="requirement-source-item"
              >
                <span>{{ sourceLabel(link.source_object_type) }}</span>
                <a v-if="link.source_url" :href="link.source_url" target="_blank" rel="noreferrer">
                  {{ link.source_title || link.source_url }}
                </a>
                <strong v-else>{{ link.source_title || link.news_item_id || link.raw_item_id || "未命名来源" }}</strong>
                <em v-if="link.data_source_name">{{ link.data_source_name }}</em>
                <a v-if="requirementSourceHref(link)" class="text-link" :href="requirementSourceHref(link)">
                  <ExternalLink :size="13" />
                  <span>定位对象</span>
                </a>
              </article>
            </div>
          </div>
          <div class="task-row-actions">
            <button type="button" class="mini-action" @click="openTaskDetail(item.id)">
              <ExternalLink :size="15" />
              <span>{{ loadingDetail && detailTask?.id === item.id ? "加载中" : "详情" }}</span>
            </button>
            <label v-if="canUpdateTaskStatus(item)" class="compact-field select-field">
              <span>选择</span>
              <input type="checkbox" :checked="isTaskSelected(item)" @change="toggleTaskSelection(item, $event)" />
            </label>
            <label v-if="canAssignTasks" class="compact-field assignee-field">
              <span>负责人</span>
              <select :value="item.assignee_user_id || ''" @change="handleAssignChange(item, $event)">
                <option v-if="!item.assignee_user_id" value="">未指派</option>
                <option v-for="member in assignableMembers" :key="member.user.id" :value="member.user.id">
                  {{ member.user.display_name }}
                </option>
              </select>
            </label>
            <span v-else class="metric-pill">{{ item.assignee_name || "未指派" }}</span>
            <button
              v-if="canUpdateTaskStatus(item)"
              type="button"
              class="mini-action"
              :class="{ active: item.status === 'done' }"
              @click="toggleTask(item)"
            >
              <CheckCircle2 :size="15" />
              <span>{{ item.status === "done" ? "重开" : "完成" }}</span>
            </button>
            <label v-if="canUpdateTaskStatus(item)" class="compact-field">
              <span>阻塞原因</span>
              <input v-model="blockedDrafts[item.id]" placeholder="等待接口或决策" />
            </label>
            <button
              v-if="canUpdateTaskStatus(item)"
              type="button"
              class="mini-action"
              :class="{ active: item.status === 'blocked' }"
              @click="markBlocked(item)"
            >
              <AlertTriangle :size="15" />
              <span>阻塞</span>
            </button>
          </div>
        </article>
        <p v-if="!loading && tasks.length === 0" class="empty-state">暂无指派任务，可从需求拆解或日报复盘中创建跟进行动。</p>
      </article>
    </section>

    <div v-if="detailTask" class="report-modal-backdrop" @click.self="closeTaskDetail">
      <section class="report-detail-modal task-detail-modal" role="dialog" aria-modal="true" aria-labelledby="task-detail-title">
        <header class="report-modal-header">
          <div>
            <p class="eyebrow">Task Detail</p>
            <h3 id="task-detail-title">{{ detailTask.title }}</h3>
            <div class="headline-chip-row">
              <span class="chip-blue">{{ detailTask.status }}</span>
              <span v-if="detailTask.is_overdue" class="chip-orange">逾期</span>
              <span>{{ detailTask.assignee_name || "未指派" }}</span>
            </div>
          </div>
          <button type="button" class="mini-action" @click="closeTaskDetail">关闭</button>
        </header>
        <div class="task-detail-body">
          <section class="modal-story-detail">
            <article>
              <h4>任务说明</h4>
              <p>{{ detailTask.description || "暂无描述" }}</p>
              <div class="coverage-metrics">
                <span>截止 {{ detailTask.due_at ? detailTask.due_at.slice(0, 10) : "未设置" }}</span>
                <span>负责人 {{ detailTask.assignee_name || "未指派" }}</span>
                <span>更新 {{ detailTask.updated_at.slice(0, 10) }}</span>
              </div>
              <p v-if="detailTask.blocked_reason" class="form-warning">阻塞原因：{{ detailTask.blocked_reason }}</p>
            </article>
            <article>
              <h4>关联需求</h4>
              <a v-if="detailTask.requirement_id" class="requirement-source-item" :href="requirementHref(detailTask)">
                <span>需求</span>
                <strong>{{ detailTask.requirement_title || detailTask.requirement_id }}</strong>
                <em><ExternalLink :size="13" /> 查看需求</em>
              </a>
              <p v-else class="empty-state">该任务尚未关联需求，后续可由管理员在任务编辑中补充。</p>
            </article>
            <article>
              <h4>来源证据</h4>
              <div v-if="detailTask.requirement_source_links.length" class="requirement-source-list">
                <article
                  v-for="link in detailTask.requirement_source_links"
                  :key="link.id"
                  class="requirement-source-item"
                >
                  <span>{{ sourceLabel(link.source_object_type) }}</span>
                  <a v-if="link.source_url" :href="link.source_url" target="_blank" rel="noreferrer">
                    {{ link.source_title || link.source_url }}
                  </a>
                  <strong v-else>{{ link.source_title || link.news_item_id || link.raw_item_id || "未命名来源" }}</strong>
                  <em v-if="link.data_source_name">{{ link.data_source_name }}</em>
                  <a v-if="requirementSourceHref(link)" class="text-link" :href="requirementSourceHref(link)">
                    <ExternalLink :size="13" />
                    <span>定位对象</span>
                  </a>
                </article>
              </div>
              <p v-else class="empty-state">该任务没有来源证据；不能把它视为已完成的情报追溯链。</p>
            </article>
          </section>
        </div>
      </section>
    </div>
  </section>
</template>
