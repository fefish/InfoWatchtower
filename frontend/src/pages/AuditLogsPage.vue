<script setup lang="ts">
import { RefreshCw, ShieldCheck } from "lucide-vue-next";
import { onMounted, ref, watch } from "vue";

import { fetchAuditLogs, type AuditLogRecord } from "../api/operations";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const logs = ref<AuditLogRecord[]>([]);
const loading = ref(false);
const error = ref("");

async function loadLogs() {
  loading.value = true;
  error.value = "";
  try {
    logs.value = await fetchAuditLogs();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载审计日志失败";
  } finally {
    loading.value = false;
  }
}

function detailLine(log: AuditLogRecord) {
  const detail = JSON.stringify(log.detail_json || {});
  return detail === "{}" ? "无额外详情" : detail;
}

watch(() => workspace.currentCode, loadLogs);
onMounted(loadLogs);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Governance</p>
        <h2>审计日志</h2>
        <p>查看关键管理操作、日报发布、SQL 导出、同步和权限相关记录。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadLogs">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>

    <section class="module-card ops-list">
      <div class="card-title-row">
        <div><p class="eyebrow">Audit</p><h3>操作记录</h3></div>
        <span class="metric-pill">{{ logs.length }} logs</span>
      </div>
      <article v-for="log in logs" :key="log.id" class="ops-row">
        <div class="feed-icon"><ShieldCheck :size="18" /></div>
        <div>
          <h3>{{ log.action }}</h3>
          <p>{{ log.user_name || log.user_id || "system" }} · {{ log.object_type }} · {{ log.object_id }}</p>
          <div class="coverage-metrics">
            <span>{{ new Date(log.created_at).toLocaleString("zh-CN", { hour12: false }) }}</span>
            <span>{{ detailLine(log) }}</span>
          </div>
        </div>
      </article>
      <p v-if="!loading && logs.length === 0" class="empty-state">暂无审计日志，发布、导出、同步或权限变更后会在这里留痕。</p>
    </section>
  </section>
</template>
