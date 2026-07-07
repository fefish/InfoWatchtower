<script setup lang="ts">
import { ArrowLeft, ExternalLink, RefreshCw, Save } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  fetchSource,
  fetchSourceDetail,
  updateSourceWorkspaceConfig,
  type SourceDetailRecord
} from "../api/sources";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const route = useRoute();
const router = useRouter();
const workspace = useWorkspaceStore();
const runtime = useRuntimeStore();
const detail = ref<SourceDetailRecord | null>(null);
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

const source = computed(() => detail.value?.source ?? null);
const canManageIngestion = computed(() => runtime.canIngest);
const maxTrendCount = computed(() =>
  Math.max(1, ...((detail.value?.raw_trend ?? []).map((item) => item.raw_count)))
);

async function loadSource() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    detail.value = await fetchSourceDetail(String(route.params.id), workspace.currentCode);
    syncForm();
  } catch (exc) {
    detail.value = null;
    error.value = exc instanceof Error ? exc.message : "加载数据源详情失败";
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
  if (!canManageIngestion.value) {
    error.value = "当前部署形态为只读消费模式，不能抓取数据源。";
    return;
  }
  fetching.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await fetchSource(source.value.id, workspace.currentCode || undefined);
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
    paper_api: "论文 API",
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
        <button
          v-if="canManageIngestion"
          type="button"
          class="icon-button"
          :disabled="fetching || !source"
          @click="runFetch"
        >
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

    <section v-if="detail" class="module-grid two">
      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Content Flow</p>
            <h3>内容入库概览</h3>
          </div>
          <span class="metric-pill">{{ detail.raw_count }} raw</span>
        </div>
        <div class="scope-panel">
          <div>
            <span>Raw 累计</span>
            <strong>{{ detail.raw_count }}</strong>
          </div>
          <div>
            <span>News 累计</span>
            <strong>{{ detail.news_count }}</strong>
          </div>
          <div>
            <span>工作台状态</span>
            <strong>{{ detail.source.workspace_link_enabled ? "已启用" : "未启用" }}</strong>
          </div>
        </div>
        <div v-if="detail.raw_trend.length" class="mini-trend" aria-label="最近 raw 趋势">
          <span
            v-for="point in detail.raw_trend"
            :key="point.day_key"
            class="mini-trend-bar"
            :style="{ height: `${Math.max(12, Math.round((point.raw_count / maxTrendCount) * 64))}px` }"
            :title="`${point.day_key}: ${point.raw_count}`"
          ></span>
        </div>
        <p v-else class="empty-state compact">暂无 raw 趋势。</p>
      </article>

      <article class="module-card">
        <div class="card-title-row">
          <div>
            <p class="eyebrow">Run Logs</p>
            <h3>最近运行与错误</h3>
          </div>
          <span class="metric-pill">{{ detail.recent_runs.length }} runs</span>
        </div>
        <div v-if="detail.error_logs.length" class="history-list">
          <article v-for="run in detail.error_logs" :key="run.run_id" class="history-row">
            <strong>{{ run.status }} · {{ run.run_key }}</strong>
            <span>{{ run.error }}</span>
            <small>{{ formatDateTime(run.completed_at) }}</small>
          </article>
        </div>
        <p v-else class="empty-state compact">暂无错误日志。</p>
      </article>
    </section>

    <section v-if="detail" class="module-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Recent Raw</p>
          <h3>最近原始条目</h3>
        </div>
        <span class="metric-pill">{{ detail.recent_raw_items.length }} 条</span>
      </div>
      <div v-if="detail.recent_raw_items.length" class="history-list">
        <article v-for="item in detail.recent_raw_items" :key="item.id" class="history-row">
          <strong>{{ item.source_title || "未命名 raw" }}</strong>
          <a v-if="item.source_url" class="source-open-link" :href="item.source_url" target="_blank" rel="noreferrer">
            <ExternalLink :size="14" />
            {{ item.source_url }}
          </a>
          <span>{{ item.raw_content_excerpt || "无正文摘要" }}</span>
          <small>抓取 {{ formatDateTime(item.fetched_at) }} · 发布 {{ formatDateTime(item.published_at) }}</small>
        </article>
      </div>
      <p v-else class="empty-state compact">暂无 raw 入库记录。</p>
    </section>

    <section v-else class="module-card">
      <p class="empty-state">{{ loading ? "加载中..." : "没有找到这个数据源，请回到数据源列表选择或新建信息源。" }}</p>
    </section>
  </section>
</template>
