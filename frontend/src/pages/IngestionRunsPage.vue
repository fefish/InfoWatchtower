<script setup lang="ts">
import { CheckCircle2, PlayCircle, RefreshCw, Rss } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";

import { createIngestionRun, fetchIngestionRuns, type IngestionRunRecord } from "../api/ingestion";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const runs = ref<IngestionRunRecord[]>([]);
const loading = ref(false);
const creating = ref(false);
const error = ref("");
const message = ref("");
const sourceTypes = ref(["rss", "paper_rss"]);
const limit = ref<number | null>(0);

const latestRun = computed(() => runs.value[0] ?? null);

async function loadRuns() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    runs.value = await fetchIngestionRuns(workspace.currentCode, 40);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载抓取运行失败";
  } finally {
    loading.value = false;
  }
}

async function runDryIngestion() {
  if (!workspace.currentCode) {
    return;
  }
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await createIngestionRun({
      workspace_code: workspace.currentCode,
      source_types: sourceTypes.value,
      limit: limit.value
    });
    message.value = `抓取运行已完成：尝试 ${run.source_total} 个源，成功 ${run.source_succeeded}，失败 ${run.source_failed}`;
    await loadRuns();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建抓取运行失败";
  } finally {
    creating.value = false;
  }
}

function formatDateTime(value: string | null) {
  if (!value) {
    return "未完成";
  }
  return new Date(value).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function successRate(run: IngestionRunRecord) {
  if (!run.source_total) {
    return "0%";
  }
  return `${Math.round((run.source_succeeded / run.source_total) * 100)}%`;
}

watch(
  () => workspace.currentCode,
  () => {
    runs.value = [];
    void loadRuns();
  }
);

onMounted(loadRuns);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Ingestion Coverage</p>
        <h2>抓取覆盖率</h2>
        <p>解释数据源是否真实抓取、哪些源失败、raw 新增更新多少，避免误判推荐器漏选。</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadRuns">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button type="button" class="icon-button" :disabled="creating" @click="runDryIngestion">
          <PlayCircle :size="17" />
          <span>{{ creating ? "运行中" : "运行抓取" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="run-command module-card compact">
      <label>
        源类型
        <select v-model="sourceTypes" multiple>
          <option value="rss">RSS</option>
          <option value="paper_rss">论文 RSS</option>
          <option value="page_manual">页面手工</option>
          <option value="page_monitor">页面监控</option>
        </select>
      </label>
      <label>
        源数量上限
        <input v-model.number="limit" type="number" min="0" placeholder="0 为验收链路" />
      </label>
      <p class="muted-line">默认 limit=0，只验收接口和权限，不触发真实外网抓取。</p>
    </section>

    <div v-if="latestRun" class="module-stats">
      <article>
        <strong>{{ latestRun.source_total }}</strong>
        <span>尝试源</span>
      </article>
      <article>
        <strong>{{ latestRun.source_succeeded }}</strong>
        <span>成功源</span>
      </article>
      <article>
        <strong>{{ latestRun.source_failed }}</strong>
        <span>失败源</span>
      </article>
      <article>
        <strong>{{ successRate(latestRun) }}</strong>
        <span>成功率</span>
      </article>
    </div>

    <section class="module-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Run History</p>
          <h3>抓取运行历史</h3>
        </div>
        <span class="metric-pill">{{ runs.length }} runs</span>
      </div>
      <div class="history-list expanded">
        <article v-for="run in runs" :key="run.id" class="history-row">
          <div class="feed-icon">
            <Rss :size="18" />
          </div>
          <div>
            <strong>{{ run.run_key }}</strong>
            <span>{{ run.status }} · {{ formatDateTime(run.completed_at || run.started_at) }}</span>
            <small>
              源 {{ run.source_succeeded }}/{{ run.source_total }} · fetched {{ run.items_fetched }} · raw +{{ run.raw_created }}/{{ run.raw_updated }}
            </small>
          </div>
          <CheckCircle2 v-if="run.status === 'completed'" :size="18" />
        </article>
        <p v-if="!loading && runs.length === 0" class="empty-state">暂无抓取运行。</p>
      </div>
    </section>
  </section>
</template>
