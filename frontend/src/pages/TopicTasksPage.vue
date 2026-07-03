<script setup lang="ts">
import { CheckCircle2, Plus, RefreshCw } from "lucide-vue-next";
import { onMounted, reactive, ref, watch } from "vue";

import {
  createTopicTask,
  fetchTopicTasks,
  updateTopicTask,
  type TopicTaskRecord
} from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const tasks = ref<TopicTaskRecord[]>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const draft = reactive({
  title: "",
  description: "",
  status: "open",
  due_at: ""
});

async function loadTasks() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    tasks.value = await fetchTopicTasks(workspace.currentCode);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载任务失败";
  } finally {
    loading.value = false;
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
      due_at: draft.due_at || null
    });
    tasks.value.unshift(created);
    draft.title = "";
    draft.description = "";
    draft.status = "open";
    draft.due_at = "";
    message.value = "任务已创建";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建任务失败";
  } finally {
    saving.value = false;
  }
}

async function toggleTask(item: TopicTaskRecord) {
  error.value = "";
  try {
    const status = item.status === "done" ? "open" : "done";
    const updated = await updateTopicTask(item.id, { status });
    const index = tasks.value.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      tasks.value.splice(index, 1, updated);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新任务失败";
  }
}

watch(() => workspace.currentCode, loadTasks);
onMounted(loadTasks);
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
      <form class="module-card ops-form" @submit.prevent="submitTask">
        <p class="eyebrow">Create</p>
        <h3>新增任务</h3>
        <label>标题<input v-model="draft.title" placeholder="例如：整理 5 月 Agent 工程能力变化" /></label>
        <label>描述<textarea v-model="draft.description" rows="5" /></label>
        <div class="form-grid-two">
          <label>状态
            <select v-model="draft.status">
              <option value="open">open</option>
              <option value="doing">doing</option>
              <option value="done">done</option>
            </select>
          </label>
          <label>截止日期<input v-model="draft.due_at" type="date" /></label>
        </div>
        <button type="submit" class="icon-button" :disabled="saving || !draft.title.trim()">
          <Plus :size="17" />
          <span>{{ saving ? "创建中" : "创建任务" }}</span>
        </button>
      </form>

      <article class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Tasks</p><h3>任务列表</h3></div>
          <span class="metric-pill">{{ tasks.length }} tasks</span>
        </div>
        <article v-for="item in tasks" :key="item.id" class="ops-row">
          <div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description || "暂无描述" }}</p>
            <div class="coverage-metrics">
              <span>{{ item.status }}</span>
              <span>due {{ item.due_at ? item.due_at.slice(0, 10) : "未设置" }}</span>
              <span>{{ item.requirement_title || "未关联需求" }}</span>
            </div>
          </div>
          <button type="button" class="mini-action" :class="{ active: item.status === 'done' }" @click="toggleTask(item)">
            <CheckCircle2 :size="15" />
            <span>{{ item.status === "done" ? "重开" : "完成" }}</span>
          </button>
        </article>
        <p v-if="!loading && tasks.length === 0" class="empty-state">暂无指派任务，可从需求拆解或日报复盘中创建跟进行动。</p>
      </article>
    </section>
  </section>
</template>
