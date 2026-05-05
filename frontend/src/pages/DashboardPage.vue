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
  { label: "当前阶段", value: "3", detail: "RSS raw 入库" }
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
      <p class="eyebrow">阶段 3</p>
      <h2>数据源与 RSS raw 入库</h2>
      <p>
        当前工作台：{{ workspace.current?.name }}。系统已完成登录与 RBAC、数据库驱动工作台、
        共享数据源导入、adapter 注册，以及 RSS/paper RSS 手动抓取到 raw_items 的最小链路。
        下一步补抓取调度，再进入 raw 到 news 的标准化和去重。
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
