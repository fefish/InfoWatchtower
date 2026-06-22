<script setup lang="ts">
import { GitCompareArrows, PackageCheck, RefreshCw } from "lucide-vue-next";
import { onMounted, ref } from "vue";

import { createSyncRun, fetchSyncRuns, type SyncRunRecord } from "../api/operations";

const runs = ref<SyncRunRecord[]>([]);
const loading = ref(false);
const creating = ref(false);
const error = ref("");
const message = ref("");

async function loadRuns() {
  loading.value = true;
  error.value = "";
  try {
    runs.value = await fetchSyncRuns();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载同步运行失败";
  } finally {
    loading.value = false;
  }
}

async function createPackage() {
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await createSyncRun();
    runs.value.unshift(run);
    message.value = `同步包记录已创建：${run.package_id}`;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建同步运行失败";
  } finally {
    creating.value = false;
  }
}

function countValue(run: SyncRunRecord, key: string) {
  const value = run.counts_json[key];
  return typeof value === "number" ? value : 0;
}

onMounted(loadRuns);
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Multi Environment</p>
        <h2>同步</h2>
        <p>记录公网与内网之间的同步包、方向、计数和冲突情况。</p>
      </div>
      <div class="module-actions">
        <button type="button" class="icon-button secondary" :disabled="loading" @click="loadRuns">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
        <button type="button" class="icon-button" :disabled="creating" @click="createPackage">
          <PackageCheck :size="17" />
          <span>{{ creating ? "创建中" : "创建同步记录" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="module-card ops-list">
      <div class="card-title-row">
        <div><p class="eyebrow">Sync Runs</p><h3>同步运行</h3></div>
        <span class="metric-pill">{{ runs.length }} runs</span>
      </div>
      <article v-for="run in runs" :key="run.id" class="ops-row">
        <div class="feed-icon indigo"><GitCompareArrows :size="18" /></div>
        <div>
          <h3>{{ run.package_id }}</h3>
          <p>{{ run.source_instance_id }} -> {{ run.target_instance_id }} · {{ run.direction }} · {{ run.status }}</p>
          <div class="coverage-metrics">
            <span>outbox {{ countValue(run, "pending_outbox") }}</span>
            <span>exported {{ countValue(run, "exported") }}</span>
            <span>conflicts {{ countValue(run, "conflicts") }}</span>
          </div>
        </div>
      </article>
      <p v-if="!loading && runs.length === 0" class="empty-state">暂无同步运行。</p>
    </section>
  </section>
</template>
