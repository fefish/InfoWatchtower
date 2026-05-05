<script setup lang="ts">
import { DownloadCloud, RefreshCw } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import { fetchSources, importLegacySources, type DataSourceRecord } from "../api/sources";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const sources = ref<DataSourceRecord[]>([]);
const loading = ref(false);
const importing = ref(false);
const error = ref("");
const lastImportMessage = ref("");

const counts = computed(() => {
  const next = new Map<string, number>();
  for (const source of sources.value) {
    next.set(source.source_type, (next.get(source.source_type) ?? 0) + 1);
  }
  return Array.from(next.entries()).sort(([left], [right]) => left.localeCompare(right));
});

async function loadSources() {
  loading.value = true;
  error.value = "";
  try {
    sources.value = await fetchSources();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载数据源失败";
  } finally {
    loading.value = false;
  }
}

async function importSeeds() {
  importing.value = true;
  error.value = "";
  lastImportMessage.value = "";
  try {
    const result = await importLegacySources();
    lastImportMessage.value = `导入完成：新增 ${result.created}，更新 ${result.updated}，总计 ${result.total}`;
    await loadSources();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导入旧种子源失败";
  } finally {
    importing.value = false;
  }
}

onMounted(loadSources);
watch(() => workspace.currentCode, loadSources);
</script>

<template>
  <section class="toolbar-band">
    <div>
      <p class="eyebrow">阶段 3</p>
      <h2>数据源</h2>
      <p>数据源先进入共享池，各工作台通过启用链接复用这些源并配置标签策略。</p>
    </div>
    <div class="toolbar-actions">
      <button type="button" class="icon-button" :disabled="loading" @click="loadSources" title="刷新">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
      <button type="button" class="icon-button" :disabled="importing" @click="importSeeds" title="导入旧种子源">
        <DownloadCloud :size="18" />
        <span>{{ importing ? "导入中" : "导入旧源" }}</span>
      </button>
    </div>
  </section>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="lastImportMessage" class="form-success">{{ lastImportMessage }}</p>

  <section class="summary-strip">
    <div>
      <span>当前工作台</span>
      <strong>{{ workspace.current?.name }}</strong>
    </div>
    <div>
      <span>共享源</span>
      <strong>{{ sources.length }}</strong>
    </div>
    <div v-for="[type, count] in counts" :key="type">
      <span>{{ type }}</span>
      <strong>{{ count }}</strong>
    </div>
  </section>

  <section class="data-table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th>名称</th>
          <th>类型</th>
          <th>标签线索</th>
          <th>抓取配置</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="source in sources" :key="source.id">
          <td>
            <strong>{{ source.name }}</strong>
            <span>{{ source.url || "-" }}</span>
          </td>
          <td>
            <strong>{{ source.source_type }}</strong>
            <span>{{ source.domain_code }}</span>
          </td>
          <td>
            <strong>{{ source.info_category || "未设置" }}</strong>
            <span>{{ source.primary_category || "默认标签集：ai_sql_categories" }}</span>
          </td>
          <td>
            <strong>{{ source.backfill_days }} 天回溯</strong>
            <span>focus {{ source.default_focus_id }}</span>
          </td>
          <td>
            <strong>{{ source.enabled ? "启用" : "停用" }}</strong>
            <span>{{ source.last_error || "暂无错误" }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && sources.length === 0" class="empty-state">暂无数据源，可先导入旧种子源。</p>
  </section>
</template>
