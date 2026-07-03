<script setup lang="ts">
import { CheckCircle2, Plus, RefreshCw } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";

import {
  createRequirement,
  fetchRequirements,
  updateRequirement,
  type RequirementRecord
} from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const requirements = ref<RequirementRecord[]>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const draft = reactive({
  title: "",
  description: "",
  priority: "medium",
  due_at: ""
});

const openCount = computed(() => requirements.value.filter((item) => item.status === "open").length);
const doneCount = computed(() => requirements.value.filter((item) => item.status === "done").length);

async function loadRequirements() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    requirements.value = await fetchRequirements(workspace.currentCode);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载内部需求失败";
  } finally {
    loading.value = false;
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
      due_at: draft.due_at || null
    });
    requirements.value.unshift(created);
    draft.title = "";
    draft.description = "";
    draft.priority = "medium";
    draft.due_at = "";
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
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新需求状态失败";
  }
}

function formatDate(value: string | null) {
  return value ? value.slice(0, 10) : "未设置";
}

watch(() => workspace.currentCode, loadRequirements);
onMounted(loadRequirements);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Strategic Loop</p>
        <h2>内部需求</h2>
        <p>把日报里的外部信号沉淀为规划部可跟踪的需求入口。</p>
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
      <form class="module-card ops-form" @submit.prevent="submitRequirement">
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
        <button type="submit" class="icon-button" :disabled="saving || !draft.title.trim()">
          <Plus :size="17" />
          <span>{{ saving ? "创建中" : "创建需求" }}</span>
        </button>
      </form>

      <article class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Requirements</p><h3>需求列表</h3></div>
        </div>
        <article v-for="item in requirements" :key="item.id" class="ops-row">
          <div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description || "暂无描述" }}</p>
            <div class="coverage-metrics">
              <span>{{ item.priority }}</span>
              <span>{{ item.status }}</span>
              <span>due {{ formatDate(item.due_at) }}</span>
              <span>{{ item.task_count }} tasks</span>
            </div>
          </div>
          <button type="button" class="mini-action" :class="{ active: item.status === 'done' }" @click="setStatus(item, item.status === 'done' ? 'open' : 'done')">
            <CheckCircle2 :size="15" />
            <span>{{ item.status === "done" ? "重开" : "完成" }}</span>
          </button>
        </article>
        <p v-if="!loading && requirements.length === 0" class="empty-state">暂无内部需求，可从日报/周报复盘中新增需要跟进的问题。</p>
      </article>
    </section>
  </section>
</template>
