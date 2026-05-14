<script setup lang="ts">
import { ArrowLeft, ExternalLink, RefreshCw, Save } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  fetchSource,
  fetchSources,
  updateSourceWorkspaceConfig,
  type DataSourceRecord
} from "../api/sources";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const router = useRouter();
const workspace = useWorkspaceStore();
const sources = ref<DataSourceRecord[]>([]);
const loading = ref(false);
const saving = ref(false);
const fetching = ref(false);
const error = ref("");
const message = ref("");

const form = reactive({
  enabled: true,
  weight: 1,
  dailyLimit: ""
});

const source = computed(() => sources.value.find((item) => item.id === String(route.params.id)) ?? null);

async function loadSource() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    sources.value = await fetchSources(workspace.currentCode);
    syncForm();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载数据源失败";
  } finally {
    loading.value = false;
  }
}

function syncForm() {
  if (!source.value) {
    return;
  }
  form.enabled = Boolean(source.value.workspace_link_enabled);
  form.weight = source.value.workspace_source_weight ?? 1;
  form.dailyLimit = source.value.workspace_daily_limit == null ? "" : String(source.value.workspace_daily_limit);
}

async function saveConfig() {
  if (!source.value || !workspace.currentCode) {
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    await updateSourceWorkspaceConfig(source.value.id, {
      workspace_code: workspace.currentCode,
      enabled: form.enabled,
      source_weight: form.weight,
      daily_limit: form.dailyLimit === "" ? null : Number(form.dailyLimit)
    });
    message.value = "数据源工作台配置已保存";
    await loadSource();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存配置失败";
  } finally {
    saving.value = false;
  }
}

async function runFetch() {
  if (!source.value) {
    return;
  }
  fetching.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await fetchSource(source.value.id);
    message.value = `抓取完成：fetched ${result.fetched}，新增 ${result.created}，更新 ${result.updated}`;
    await loadSource();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "抓取失败";
  } finally {
    fetching.value = false;
  }
}

function sourceTypeLabel(type: string) {
  const labels: Record<string, string> = {
    rss: "RSS",
    paper_rss: "论文 RSS",
    wiseflow: "Wiseflow",
    page_manual: "页面手工",
    page_monitor: "页面监控"
  };
  return labels[type] ?? type;
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "暂无";
  }
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

watch(source, syncForm);
watch(
  () => workspace.currentCode,
  () => {
    void loadSource();
  }
);

onMounted(loadSource);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Source Detail</p>
        <h2>{{ source?.name || "数据源详情" }}</h2>
        <p>{{ source?.url || "展示单个数据源的工作台启用状态、权重、抓取状态和追溯信息。" }}</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" @click="router.push('/sources')">
          <ArrowLeft :size="17" />
          <span>返回数据源</span>
        </button>
        <button type="button" class="icon-button" :disabled="fetching || !source" @click="runFetch">
          <RefreshCw :size="17" />
          <span>{{ fetching ? "抓取中" : "抓取" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <div v-if="source" class="module-grid two">
      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Workspace Link</p>
            <h3>工作台配置</h3>
          </div>
          <span :class="form.enabled ? 'status-on' : 'status-off'">{{ form.enabled ? "启用" : "停用" }}</span>
        </div>
        <div class="config-grid">
          <label class="switch-row">
            <input v-model="form.enabled" type="checkbox" />
            启用
          </label>
          <label>
            权重
            <input v-model.number="form.weight" type="number" min="0" step="0.1" />
          </label>
          <label>
            日报上限
            <input v-model="form.dailyLimit" type="number" min="0" placeholder="不限" />
          </label>
        </div>
        <button type="button" class="icon-button" :disabled="saving" @click="saveConfig">
          <Save :size="17" />
          <span>{{ saving ? "保存中" : "保存配置" }}</span>
        </button>
      </article>

      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Runtime</p>
            <h3>抓取状态</h3>
          </div>
          <span class="metric-pill">{{ sourceTypeLabel(source.source_type) }}</span>
        </div>
        <div class="scope-panel">
          <div>
            <span>最近抓取</span>
            <strong>{{ formatDateTime(source.last_fetch_at) }}</strong>
          </div>
          <div>
            <span>最近成功</span>
            <strong>{{ formatDateTime(source.last_success_at) }}</strong>
          </div>
          <div>
            <span>来源评分</span>
            <strong>{{ source.source_score.toFixed(2) }}</strong>
          </div>
          <div>
            <span>默认 Focus</span>
            <strong>{{ source.default_focus_id }}</strong>
          </div>
        </div>
        <a v-if="source.url" class="source-open-link" :href="source.url" target="_blank">
          <ExternalLink :size="15" />
          打开来源
        </a>
        <p v-if="source.last_error" class="form-error">{{ source.last_error }}</p>
      </article>
    </div>

    <section v-else class="module-card">
      <p class="empty-state">{{ loading ? "加载中..." : "没有找到这个数据源。" }}</p>
    </section>
  </section>
</template>
