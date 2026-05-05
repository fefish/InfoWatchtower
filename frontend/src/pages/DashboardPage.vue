<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { fetchHealth, type HealthResponse } from "../api/health";

const health = ref<HealthResponse | null>(null);
const loading = ref(false);
const error = ref("");

const metrics = computed(() => [
  { label: "种子源", value: "113", detail: "wiseflow/RSS/page" },
  { label: "论文源", value: "17", detail: "14 个启用" },
  { label: "SQL标签", value: "10", detail: "兼容内网导出" },
  { label: "当前阶段", value: "1", detail: "数据库追溯链路" }
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
      <p class="eyebrow">阶段 1</p>
      <h2>数据库模型与追溯链路</h2>
      <p>
        当前已建好 33 张业务表和 Alembic 初始迁移，日报条目可以沿外键追回 raw 原始数据。
        下一步接入登录、身份适配和 RBAC。
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
