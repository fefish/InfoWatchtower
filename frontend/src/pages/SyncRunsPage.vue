<script setup lang="ts">
import { AlertTriangle, CheckCheck, Clock, DownloadCloud, GitCompareArrows, PackageCheck, RefreshCw } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createSyncPullRun,
  createSyncRun,
  fetchSyncConflicts,
  fetchSyncHealth,
  fetchSyncPackageDownload,
  fetchSyncRuns,
  resolveSyncConflict,
  retryFailedSyncInbox,
  type SyncConflictRecord,
  type SyncConflictResolveStrategy,
  type SyncHealthRecord,
  type SyncHealthStatus,
  type SyncRunRecord
} from "../api/operations";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const runtime = useRuntimeStore();
const route = useRoute();
const runs = ref<SyncRunRecord[]>([]);
const conflicts = ref<SyncConflictRecord[]>([]);
const health = ref<SyncHealthRecord | null>(null);
const loading = ref(false);
const creating = ref(false);
const pulling = ref(false);
const retryingInbox = ref(false);
const downloadingPackageId = ref("");
const resolvingConflictId = ref("");
const manualMergeDrafts = ref<Record<string, string>>({});
const error = ref("");
const message = ref("");

const canPublish = computed(() => runtime.capabilities.sync_publisher);
const canConsume = computed(() => runtime.capabilities.sync_consumer);
const pendingConflictAnchorId = computed(() => {
  const value = route.query.conflict_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const pendingSyncRunAnchorId = computed(() => {
  const value = route.query.sync_run_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const deployModeText = computed(() => runtime.deployModeBadge || "本地");
const capabilitySummary = computed(() => {
  if (canPublish.value && canConsume.value) {
    return "当前实例同时启用发布和拉取能力，通常只用于本地联调。";
  }
  if (canPublish.value) {
    return "当前实例是外网发布者：负责采集、成稿，并向内网开放 feed；可生成手工同步包。";
  }
  if (canConsume.value) {
    return "当前实例是内网消费者：不运行外网采集，只从外网发布者拉取公开数据。";
  }
  return "当前实例未启用同步发布或拉取角色，只保留同步运行和冲突记录查看。";
});

async function loadRuns() {
  loading.value = true;
  error.value = "";
  try {
    const [runList, conflictList, healthSummary] = await Promise.all([
      fetchSyncRuns(),
      fetchSyncConflicts({ status: "open", limit: 50 }),
      fetchSyncHealth()
    ]);
    runs.value = runList;
    conflicts.value = conflictList;
    health.value = healthSummary;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载同步运行失败";
  } finally {
    loading.value = false;
  }
}

async function createPackage() {
  if (!canPublish.value) {
    error.value = "当前部署形态未启用 sync_publisher，不能导出发布同步包";
    return;
  }
  creating.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await createSyncRun();
    runs.value.unshift(run);
    message.value = `同步包已导出：${run.package_id}`;
    const [conflictList, healthSummary] = await Promise.all([
      fetchSyncConflicts({ status: "open", limit: 50 }),
      fetchSyncHealth()
    ]);
    conflicts.value = conflictList;
    health.value = healthSummary;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "导出同步包失败";
  } finally {
    creating.value = false;
  }
}

async function createPullRun() {
  if (!canConsume.value) {
    error.value = "当前部署形态未启用 sync_consumer，不能触发同步拉取";
    return;
  }
  pulling.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await createSyncPullRun();
    runs.value.unshift(run);
    message.value = `同步拉取已完成：${run.package_id}`;
    const [conflictList, healthSummary] = await Promise.all([
      fetchSyncConflicts({ status: "open", limit: 50 }),
      fetchSyncHealth()
    ]);
    conflicts.value = conflictList;
    health.value = healthSummary;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "触发同步拉取失败";
  } finally {
    pulling.value = false;
  }
}

async function retryInboxFailures() {
  if (!canConsume.value) {
    error.value = "当前部署形态未启用 sync_consumer，不能重试 failed inbox";
    return;
  }
  retryingInbox.value = true;
  error.value = "";
  message.value = "";
  try {
    const run = await retryFailedSyncInbox();
    runs.value.unshift(run);
    message.value = `failed inbox 已重试：${run.package_id}`;
    const [conflictList, healthSummary] = await Promise.all([
      fetchSyncConflicts({ status: "open", limit: 50 }),
      fetchSyncHealth()
    ]);
    conflicts.value = conflictList;
    health.value = healthSummary;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "重试 failed inbox 失败";
  } finally {
    retryingInbox.value = false;
  }
}

async function downloadPackage(run: SyncRunRecord) {
  downloadingPackageId.value = run.package_id;
  error.value = "";
  try {
    const blob = await fetchSyncPackageDownload(run.package_id);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${run.package_id}.zip`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "下载同步包失败";
  } finally {
    downloadingPackageId.value = "";
  }
}

async function resolveConflict(conflict: SyncConflictRecord, strategy: SyncConflictResolveStrategy) {
  resolvingConflictId.value = conflict.id;
  error.value = "";
  message.value = "";
  const reasonByStrategy: Record<SyncConflictResolveStrategy, string> = {
    keep_local: "保留本地已确认版本",
    ignored: "确认本冲突无需处理",
    retry_after_dependency: "等待依赖对象同步后重试",
    use_incoming: "接受外网发布者传入版本",
    manual_merge: "按人工合并 JSON 写入新修订"
  };
  try {
    let mergedJson: Record<string, unknown> | null = null;
    if (strategy === "manual_merge") {
      try {
        const draft = manualMergeDrafts.value[conflict.id] || jsonPreviewFull(conflict.incoming_value_json);
        const parsed = JSON.parse(draft);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("manual_merge payload must be object");
        }
        mergedJson = parsed as Record<string, unknown>;
      } catch {
        error.value = "人工合并 JSON 格式不正确";
        return;
      }
    }
    await resolveSyncConflict(conflict.id, {
      strategy,
      reason: reasonByStrategy[strategy],
      merged_json: mergedJson
    });
    conflicts.value = conflicts.value.filter((item) => item.id !== conflict.id);
    health.value = await fetchSyncHealth();
    message.value = "同步冲突已记录处置结果";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "处置同步冲突失败";
  } finally {
    resolvingConflictId.value = "";
  }
}

function countValue(run: SyncRunRecord, key: string) {
  const value = run.counts_json[key];
  return typeof value === "number" ? value : 0;
}

function manifestValue(run: SyncRunRecord, key: string) {
  const manifest = run.counts_json.package_manifest;
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    return "";
  }
  const value = (manifest as Record<string, unknown>)[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function jsonPreview(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2).slice(0, 520);
}

function jsonPreviewFull(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2);
}

function manualMergeSupported(conflict: SyncConflictRecord) {
  return ["data_sources", "daily_reports", "weekly_reports"].includes(conflict.object_type);
}

function healthStatusText(status: SyncHealthStatus) {
  const labels: Record<SyncHealthStatus, string> = {
    ok: "正常",
    warning: "提醒",
    critical: "严重",
    inactive: "未启用"
  };
  return labels[status];
}

function cursorStatusText(status: SyncHealthStatus) {
  return healthStatusText(status);
}

function failedInboxBreakdown(healthSummary: SyncHealthRecord) {
  const entries = Object.entries(healthSummary.failed_inbox_by_object_type || {}).filter(([, count]) => count > 0);
  if (!entries.length) {
    return "无失败 inbox";
  }
  return entries.map(([objectType, count]) => `${objectType} ${count}`).join(" / ");
}

function failedInboxRetryPolicyText(healthSummary: SyncHealthRecord) {
  const policy = healthSummary.failed_inbox_retry_policy || {};
  if (!policy.enabled) {
    return "自动重试关闭";
  }
  const base = Number(policy.base_delay_seconds || 0);
  const maxDelay = Number(policy.max_delay_seconds || 0);
  const maxAttempts = Number(policy.max_attempts || 0);
  const limit = Number(policy.limit || 0);
  return `自动重试开启：${base} 秒起步，最长 ${maxDelay} 秒，最多 ${maxAttempts} 次，每批 ${limit} 条`;
}

function failedInboxRetryStateText(healthSummary: SyncHealthRecord) {
  const dueCount = healthSummary.failed_inbox_retry_due_count || 0;
  const blockedCount = healthSummary.failed_inbox_retry_blocked_count || 0;
  if (blockedCount > 0) {
    return `${blockedCount} 条已达自动重试上限，需要人工检查`;
  }
  if (dueCount > 0) {
    return `${dueCount} 条已到期，等待 scheduler 自动重试`;
  }
  if (healthSummary.failed_inbox_next_retry_at) {
    return `下一次到期：${formatTimestamp(healthSummary.failed_inbox_next_retry_at)}`;
  }
  return "暂无到期重试";
}

function formatDuration(seconds: number | null) {
  if (seconds === null) {
    return "未拉取";
  }
  if (seconds < 60) {
    return `${seconds} 秒`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)} 分钟`;
  }
  if (seconds < 86400) {
    return `${Math.round(seconds / 3600)} 小时`;
  }
  return `${Math.round(seconds / 86400)} 天`;
}

function formatTimestamp(value: string | null) {
  if (!value) {
    return "未记录";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function manualMergeDraft(conflict: SyncConflictRecord) {
  if (!manualMergeDrafts.value[conflict.id]) {
    manualMergeDrafts.value[conflict.id] = jsonPreviewFull(conflict.incoming_value_json);
  }
  return manualMergeDrafts.value[conflict.id];
}

function updateManualMergeDraft(conflict: SyncConflictRecord, value: string) {
  manualMergeDrafts.value = {
    ...manualMergeDrafts.value,
    [conflict.id]: value
  };
}

function isAnchoredConflict(conflict: SyncConflictRecord) {
  return pendingConflictAnchorId.value === conflict.id;
}

function isAnchoredRun(run: SyncRunRecord) {
  return pendingSyncRunAnchorId.value === run.id;
}

watch(() => workspace.currentCode, loadRuns);
onMounted(loadRuns);
</script>

<template>
  <section class="layout-list">
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
        <button v-if="canConsume" type="button" class="icon-button" :disabled="pulling" @click="createPullRun">
          <DownloadCloud :size="17" />
          <span>{{ pulling ? "拉取中" : "立即拉取" }}</span>
        </button>
        <button v-if="canPublish" type="button" class="icon-button" :disabled="creating" @click="createPackage">
          <PackageCheck :size="17" />
          <span>{{ creating ? "导出中" : "导出同步包" }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <section class="module-card sync-capability-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Runtime Role</p>
          <h3>{{ deployModeText }}同步角色</h3>
        </div>
        <span class="metric-pill">{{ runtime.instanceId || "local" }}</span>
      </div>
      <p class="sync-capability-summary">{{ capabilitySummary }}</p>
      <div class="sync-capability-grid">
        <div class="sync-capability-item">
          <span :class="canPublish ? 'status-on' : 'status-off'">{{ canPublish ? "已启用" : "未启用" }}</span>
          <div>
            <strong>发布者 sync_publisher</strong>
            <p>开放 feed 给内网拉取，并允许生成面向内网的手工同步包。</p>
          </div>
        </div>
        <div class="sync-capability-item">
          <span :class="canConsume ? 'status-on' : 'status-off'">{{ canConsume ? "已启用" : "未启用" }}</span>
          <div>
            <strong>消费者 sync_consumer</strong>
            <p>从外网发布者拉取数据；内网评论、点赞、评分和采信仍留在本地。</p>
          </div>
        </div>
      </div>
    </section>

    <section v-if="health" class="module-card sync-health-card" :class="`sync-health-${health.status}`">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Health</p>
          <h3>同步健康</h3>
        </div>
        <span
          class="metric-pill"
          :class="{ enabled: health.status === 'ok', danger: health.status === 'critical' }"
        >
          {{ healthStatusText(health.status) }}
        </span>
      </div>
      <p class="sync-capability-summary">{{ health.summary }}</p>

      <div class="sync-health-metrics">
        <div>
          <strong>{{ health.cursor_count }}</strong>
          <span>已有水位</span>
        </div>
        <div>
          <strong>{{ health.missing_cursor_count }}</strong>
          <span>缺失水位</span>
        </div>
        <div>
          <strong>{{ health.failed_cursor_count }}</strong>
          <span>失败水位</span>
        </div>
        <div>
          <strong>{{ health.failed_inbox_count }}</strong>
          <span>失败 inbox</span>
        </div>
        <div>
          <strong>{{ health.open_conflict_count }}</strong>
          <span>待处理冲突</span>
        </div>
      </div>

      <div v-if="health.failed_inbox_count > 0" class="sync-inbox-retry-panel">
        <div>
          <strong>failed inbox 可重试</strong>
          <p>{{ failedInboxBreakdown(health) }}</p>
          <p>{{ failedInboxRetryPolicyText(health) }}</p>
          <p>{{ failedInboxRetryStateText(health) }}</p>
        </div>
        <button
          v-if="canConsume"
          type="button"
          class="mini-action active"
          :disabled="retryingInbox"
          @click="retryInboxFailures"
        >
          <RefreshCw :size="15" />
          <span>{{ retryingInbox ? "重试中" : "重试 failed inbox" }}</span>
        </button>
      </div>

      <div v-if="health.alerts.length" class="sync-alert-list">
        <article v-for="alert in health.alerts" :key="`${alert.code}-${alert.object_type || 'all'}`" class="sync-alert-row">
          <span :class="['sync-alert-severity', alert.severity]">{{ alert.severity }}</span>
          <div>
            <strong>{{ alert.code }}</strong>
            <p>{{ alert.message }}</p>
          </div>
        </article>
      </div>

      <div v-if="health.cursors.length" class="sync-cursor-grid">
        <article v-for="cursor in health.cursors" :key="cursor.object_type" class="sync-cursor-card">
          <div class="card-title-row compact">
            <strong>{{ cursor.object_type }}</strong>
            <span :class="['cursor-status', cursor.status]">{{ cursorStatusText(cursor.status) }}</span>
          </div>
          <p>上次拉取：{{ formatTimestamp(cursor.last_pulled_at) }}</p>
          <div class="coverage-metrics">
            <span>距离 {{ formatDuration(cursor.age_seconds) }}</span>
            <span>{{ cursor.last_status || "unknown" }}</span>
            <span v-if="cursor.cursor">cursor {{ cursor.cursor.slice(0, 10) }}</span>
          </div>
          <p v-if="cursor.last_error" class="sync-cursor-error">{{ cursor.last_error }}</p>
        </article>
      </div>
      <p v-if="!health.cursors.length" class="empty-state">
        当前还没有同步水位；内网 consumer 完成第一次拉取后会生成每类对象的 cursor。
      </p>
    </section>

    <section class="module-card ops-list sync-conflict-card">
      <div class="card-title-row">
        <div><p class="eyebrow">Conflicts</p><h3>同步冲突处置</h3></div>
        <span class="metric-pill" :class="{ enabled: conflicts.length === 0 }">{{ conflicts.length }} open</span>
      </div>
      <article
        v-for="conflict in conflicts"
        :key="conflict.id"
        class="ops-row sync-conflict-row"
        :class="{ anchored: isAnchoredConflict(conflict) }"
        :aria-current="isAnchoredConflict(conflict) ? 'true' : undefined"
      >
        <div class="feed-icon orange"><AlertTriangle :size="18" /></div>
        <div>
          <h3>{{ conflict.object_type }} · {{ conflict.object_id }}</h3>
          <p>
            {{ conflict.conflict_reason || "需要人工确认" }} · {{ conflict.package_id || conflict.sync_run_id }}
          </p>
          <div class="coverage-metrics">
            <span>local r{{ conflict.local_revision }}</span>
            <span>incoming r{{ conflict.incoming_revision }}</span>
            <span>{{ conflict.status }}</span>
            <span>{{ conflict.direction || "import" }}</span>
          </div>
          <div class="sync-conflict-preview">
            <pre><strong>本地</strong>{{ jsonPreview(conflict.local_value_json) }}</pre>
            <pre><strong>传入</strong>{{ jsonPreview(conflict.incoming_value_json) }}</pre>
          </div>
          <div v-if="manualMergeSupported(conflict)" class="manual-merge-panel">
            <label>
              人工合并 JSON
              <textarea
                :value="manualMergeDraft(conflict)"
                @input="updateManualMergeDraft(conflict, ($event.target as HTMLTextAreaElement).value)"
              ></textarea>
            </label>
          </div>
          <div class="sync-conflict-actions">
            <button
              type="button"
              class="mini-action active"
              :disabled="resolvingConflictId === conflict.id"
              @click="resolveConflict(conflict, 'keep_local')"
            >
              <CheckCheck :size="15" />
              <span>保留本地</span>
            </button>
            <button
              type="button"
              class="mini-action active"
              :disabled="resolvingConflictId === conflict.id"
              @click="resolveConflict(conflict, 'use_incoming')"
            >
              <CheckCheck :size="15" />
              <span>使用传入</span>
            </button>
            <button
              v-if="manualMergeSupported(conflict)"
              type="button"
              class="mini-action"
              :disabled="resolvingConflictId === conflict.id"
              @click="resolveConflict(conflict, 'manual_merge')"
            >
              <GitCompareArrows :size="15" />
              <span>人工合并</span>
            </button>
            <button
              type="button"
              class="mini-action"
              :disabled="resolvingConflictId === conflict.id"
              @click="resolveConflict(conflict, 'ignored')"
            >
              <CheckCheck :size="15" />
              <span>忽略</span>
            </button>
            <button
              type="button"
              class="mini-action"
              :disabled="resolvingConflictId === conflict.id"
              @click="resolveConflict(conflict, 'retry_after_dependency')"
            >
              <Clock :size="15" />
              <span>等待依赖</span>
            </button>
          </div>
        </div>
      </article>
      <p v-if="!loading && conflicts.length === 0" class="empty-state">
        当前没有 open 同步冲突。出现 revision/hash 冲突时，这里会显示本地与传入对象供管理员处置。
      </p>
    </section>

    <section class="module-card ops-list">
      <div class="card-title-row">
        <div><p class="eyebrow">Sync Runs</p><h3>同步运行</h3></div>
        <span class="metric-pill">{{ runs.length }} runs</span>
      </div>
      <article
        v-for="run in runs"
        :key="run.id"
        class="ops-row sync-run-row"
        :class="{ anchored: isAnchoredRun(run) }"
        :aria-current="isAnchoredRun(run) ? 'true' : undefined"
      >
        <div class="feed-icon indigo"><GitCompareArrows :size="18" /></div>
        <div>
          <h3>{{ run.package_id }}</h3>
          <p>{{ run.source_instance_id }} -> {{ run.target_instance_id }} · {{ run.direction }} · {{ run.status }}</p>
          <div class="coverage-metrics">
            <span>outbox {{ countValue(run, "pending_outbox") }}</span>
            <span>exported {{ countValue(run, "exported") }}</span>
            <span>conflicts {{ countValue(run, "conflicts") }}</span>
            <span v-if="manifestValue(run, 'records_sha256')">sha256 {{ manifestValue(run, "records_sha256").slice(0, 12) }}</span>
          </div>
          <button
            v-if="run.counts_json.package_manifest"
            type="button"
            class="text-link"
            :disabled="downloadingPackageId === run.package_id"
            @click="downloadPackage(run)"
          >
            <DownloadCloud :size="15" />
            <span>{{ downloadingPackageId === run.package_id ? "下载中" : "下载同步包" }}</span>
          </button>
        </div>
      </article>
      <p v-if="!loading && runs.length === 0" class="empty-state">暂无同步运行，点击“导出同步包”生成第一份跨环境同步记录。</p>
    </section>
  </section>
</template>
