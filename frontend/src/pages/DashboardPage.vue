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
  { label: "SQL标签", value: "10", detail: "兼容内网导出" },
  { label: "当前阶段", value: "2", detail: "登录与 RBAC" }
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
      <p class="eyebrow">阶段 2</p>
      <h2>登录与 RBAC</h2>
      <p>
        当前工作台：{{ workspace.current?.name }}。系统已接入公网账号密码登录、签名会话、
        内网 header 身份适配和本地角色权限。下一步进入数据源导入与 adapter 框架。
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
