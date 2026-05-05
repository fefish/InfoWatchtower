<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { fetchHealth, type HealthResponse } from "../api/health";
import { useWorkspaceStore } from "../stores/workspace";

const health = ref<HealthResponse | null>(null);
const loading = ref(false);
const error = ref("");
const workspace = useWorkspaceStore();

const metrics = computed(() => [
  { label: "种子源", value: "113", detail: "wiseflow/RSS/page" },
  { label: "论文源", value: "17", detail: "14 个启用" },
  { label: "工作台源链接", value: "113", detail: "每个默认工作台" },
  { label: "当前阶段", value: "4", detail: "标准化去重" }
]);

onMounted(async () => {
  loading.value = true;
  try {
    health.value = await fetchHealth();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "health check failed";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="dashboard-grid">
    <article v-for="metric in metrics" :key="metric.label" class="metric-card">
      <span>{{ metric.label }}</span>
      <strong>{{ metric.value }}</strong>
      <small>{{ metric.detail }}</small>
    </article>
  </section>

  <section class="work-band">
    <div>
      <p class="eyebrow">阶段 4</p>
      <h2>raw 标准化、工作台隔离去重与候选池底座</h2>
      <p>
        当前工作台：{{ workspace.current?.name }}。系统已完成登录与 RBAC、数据库驱动工作台、
        共享数据源导入、工作台统一标签策略、adapter 注册、RSS/paper RSS 手动抓取到 raw_items，
        以及 raw_items 到 news_items 的标准化和硬去重。下一步进入推荐、日报草稿和反馈链路。
      </p>
    </div>

    <div class="health-panel">
      <span>后端健康状态</span>
      <strong v-if="loading">检查中</strong>
      <strong v-else-if="health">{{ health.database.status }}</strong>
      <strong v-else>未连接</strong>
      <small v-if="health">{{ health.service }} · {{ health.environment }}</small>
      <small v-else-if="error">{{ error }}</small>
    </div>
  </section>
</template>
