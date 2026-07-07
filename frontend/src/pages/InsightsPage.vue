<script setup lang="ts">
import { Archive, CheckCircle2, ExternalLink, Plus, RefreshCw, Save } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  createInsight,
  createStrategicImplication,
  fetchInsights,
  fetchStrategicImplications,
  updateInsight,
  updateStrategicImplication,
  type InsightRecord,
  type StrategicImplicationRecord
} from "../api/operations";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const workspace = useWorkspaceStore();
const session = useSessionStore();
const route = useRoute();
const insights = ref<InsightRecord[]>([]);
const implications = ref<StrategicImplicationRecord[]>([]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const selectedStatus = ref("");
const query = ref("");
const editingInsightId = ref("");
const editingImplicationId = ref("");
const insightDraft = reactive({
  news_item_id: "",
  title: "",
  summary: "",
  insight_type: "trend",
  confidence_score: 0.7
});
const implicationDraft = reactive({
  insight_id: "",
  title: "",
  description: "",
  implication_type: "opportunity"
});
const editInsightDraft = reactive({
  title: "",
  summary: "",
  insight_type: "trend",
  confidence_score: 0.7
});
const editImplicationDraft = reactive({
  title: "",
  description: "",
  implication_type: "opportunity"
});
const pendingInsightAnchorId = computed(() => {
  const value = route.query.insight_id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
});
const canManageInsights = computed(() => {
  if (session.user?.roles.includes("super_admin")) {
    return true;
  }
  return ["owner", "admin", "member"].includes(workspace.current?.current_user_workspace_role ?? "");
});
const confirmedCount = computed(() => insights.value.filter((item) => item.status === "confirmed").length);
const linkedCount = computed(() => insights.value.filter((item) => item.status === "linked_to_requirement").length);
const archivedCount = computed(() => insights.value.filter((item) => item.status === "archived").length);
const activeInsights = computed(() => insights.value.filter((item) => item.status !== "archived"));

async function loadData() {
  if (!workspace.currentCode) {
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const [insightRows, implicationRows] = await Promise.all([
      fetchInsights(workspace.currentCode, {
        status: selectedStatus.value || undefined,
        q: query.value.trim() || undefined
      }),
      fetchStrategicImplications(workspace.currentCode)
    ]);
    insights.value = insightRows;
    implications.value = implicationRows;
    if (!implicationDraft.insight_id && insightRows.length > 0) {
      implicationDraft.insight_id = insightRows[0].id;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载洞察失败";
  } finally {
    loading.value = false;
  }
}

async function submitInsight() {
  if (!workspace.currentCode || !insightDraft.news_item_id.trim() || !insightDraft.title.trim()) {
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const created = await createInsight({
      workspace_code: workspace.currentCode,
      news_item_id: insightDraft.news_item_id.trim(),
      title: insightDraft.title.trim(),
      summary: insightDraft.summary.trim(),
      insight_type: insightDraft.insight_type,
      confidence_score: insightDraft.confidence_score
    });
    insights.value.unshift(created);
    implicationDraft.insight_id = created.id;
    insightDraft.news_item_id = "";
    insightDraft.title = "";
    insightDraft.summary = "";
    insightDraft.insight_type = "trend";
    insightDraft.confidence_score = 0.7;
    message.value = "洞察已创建";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建洞察失败";
  } finally {
    saving.value = false;
  }
}

async function submitImplication() {
  if (!implicationDraft.insight_id || !implicationDraft.title.trim()) {
    return;
  }
  saving.value = true;
  error.value = "";
  message.value = "";
  try {
    const created = await createStrategicImplication({
      insight_id: implicationDraft.insight_id,
      title: implicationDraft.title.trim(),
      description: implicationDraft.description.trim(),
      implication_type: implicationDraft.implication_type
    });
    implications.value.unshift(created);
    const insight = insights.value.find((item) => item.id === created.insight_id);
    if (insight) {
      insight.implication_count += 1;
    }
    implicationDraft.title = "";
    implicationDraft.description = "";
    implicationDraft.implication_type = "opportunity";
    message.value = "战略影响已创建";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建战略影响失败";
  } finally {
    saving.value = false;
  }
}

function beginEditInsight(item: InsightRecord) {
  editingInsightId.value = item.id;
  editInsightDraft.title = item.title;
  editInsightDraft.summary = item.summary;
  editInsightDraft.insight_type = item.insight_type;
  editInsightDraft.confidence_score = item.confidence_score;
}

async function saveInsight(item: InsightRecord) {
  error.value = "";
  try {
    const updated = await updateInsight(item.id, {
      title: editInsightDraft.title.trim(),
      summary: editInsightDraft.summary.trim(),
      insight_type: editInsightDraft.insight_type,
      confidence_score: editInsightDraft.confidence_score
    });
    replaceInsight(updated);
    editingInsightId.value = "";
    message.value = "洞察已更新";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新洞察失败";
  }
}

async function setInsightStatus(item: InsightRecord, status: string) {
  error.value = "";
  try {
    const updated = await updateInsight(item.id, { status });
    replaceInsight(updated);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新洞察状态失败";
  }
}

function replaceInsight(updated: InsightRecord) {
  const index = insights.value.findIndex((item) => item.id === updated.id);
  if (index >= 0) {
    insights.value.splice(index, 1, updated);
  }
}

function beginEditImplication(item: StrategicImplicationRecord) {
  editingImplicationId.value = item.id;
  editImplicationDraft.title = item.title;
  editImplicationDraft.description = item.description;
  editImplicationDraft.implication_type = item.implication_type;
}

async function saveImplication(item: StrategicImplicationRecord) {
  error.value = "";
  try {
    const updated = await updateStrategicImplication(item.id, {
      title: editImplicationDraft.title.trim(),
      description: editImplicationDraft.description.trim(),
      implication_type: editImplicationDraft.implication_type
    });
    const index = implications.value.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      implications.value.splice(index, 1, updated);
    }
    editingImplicationId.value = "";
    message.value = "战略影响已更新";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新战略影响失败";
  }
}

function isAnchoredInsight(item: InsightRecord) {
  return pendingInsightAnchorId.value === item.id;
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

watch(
  () => workspace.currentCode,
  () => {
    void loadData();
  }
);
onMounted(() => {
  void loadData();
});
</script>

<template>
  <section class="module-page">
    <header class="module-hero">
      <div>
        <p class="eyebrow">Strategy Loop</p>
        <h2>洞察研判</h2>
        <p>集中管理从外部信号沉淀出的洞察和战略影响，再继续流转为内部需求。</p>
      </div>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadData">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>
    <p v-if="message" class="form-success">{{ message }}</p>

    <div class="module-stats">
      <article><strong>{{ insights.length }}</strong><span>总洞察</span></article>
      <article><strong>{{ confirmedCount }}</strong><span>已确认</span></article>
      <article><strong>{{ linkedCount }}</strong><span>已转需求</span></article>
      <article><strong>{{ archivedCount }}</strong><span>已归档</span></article>
    </div>

    <section class="module-card toolbar-card">
      <label>状态
        <select v-model="selectedStatus" @change="loadData">
          <option value="">全部</option>
          <option value="draft">draft</option>
          <option value="confirmed">confirmed</option>
          <option value="linked_to_requirement">linked_to_requirement</option>
          <option value="archived">archived</option>
        </select>
      </label>
      <label>检索
        <input v-model="query" placeholder="按标题或摘要搜索" @keydown.enter.prevent="loadData" />
      </label>
      <button type="button" class="icon-button secondary" :disabled="loading" @click="loadData">
        <RefreshCw :size="17" />
        <span>筛选</span>
      </button>
    </section>

    <section class="module-split ops-layout">
      <form v-if="canManageInsights" class="module-card ops-form" @submit.prevent="submitInsight">
        <p class="eyebrow">Insight</p>
        <h3>新增洞察</h3>
        <label>来源 news item ID<input v-model="insightDraft.news_item_id" placeholder="从候选池或日报追溯复制 news_item_id" /></label>
        <label>标题<input v-model="insightDraft.title" placeholder="例如：Agent 记忆层进入产品化" /></label>
        <label>摘要<textarea v-model="insightDraft.summary" rows="4" /></label>
        <div class="form-grid-two">
          <label>类型
            <select v-model="insightDraft.insight_type">
              <option value="trend">trend</option>
              <option value="risk">risk</option>
              <option value="opportunity">opportunity</option>
              <option value="competitor_move">competitor_move</option>
            </select>
          </label>
          <label>置信度<input v-model.number="insightDraft.confidence_score" type="number" min="0" max="1" step="0.05" /></label>
        </div>
        <button type="submit" class="icon-button" :disabled="saving || !insightDraft.title.trim() || !insightDraft.news_item_id.trim()">
          <Plus :size="17" />
          <span>{{ saving ? "创建中" : "创建洞察" }}</span>
        </button>
      </form>

      <form v-if="canManageInsights" class="module-card ops-form" @submit.prevent="submitImplication">
        <p class="eyebrow">Implication</p>
        <h3>新增战略影响</h3>
        <label>关联洞察
          <select v-model="implicationDraft.insight_id">
            <option v-for="item in activeInsights" :key="item.id" :value="item.id">
              {{ item.title }}
            </option>
          </select>
        </label>
        <label>标题<input v-model="implicationDraft.title" placeholder="例如：内部工具链需要记忆能力评估" /></label>
        <label>说明<textarea v-model="implicationDraft.description" rows="4" /></label>
        <label>类型
          <select v-model="implicationDraft.implication_type">
            <option value="opportunity">opportunity</option>
            <option value="risk">risk</option>
            <option value="capability_gap">capability_gap</option>
            <option value="competitive_pressure">competitive_pressure</option>
          </select>
        </label>
        <button type="submit" class="icon-button" :disabled="saving || !implicationDraft.insight_id || !implicationDraft.title.trim()">
          <Plus :size="17" />
          <span>{{ saving ? "创建中" : "创建影响" }}</span>
        </button>
      </form>
    </section>

    <section class="module-split ops-layout">
      <article class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Insights</p><h3>洞察列表</h3></div>
          <span class="metric-pill">{{ insights.length }} insights</span>
        </div>
        <article
          v-for="item in insights"
          :key="item.id"
          class="ops-row insight-row"
          :class="{ anchored: isAnchoredInsight(item) }"
          :aria-current="isAnchoredInsight(item) ? 'true' : undefined"
        >
          <div>
            <template v-if="editingInsightId === item.id">
              <label>标题<input v-model="editInsightDraft.title" /></label>
              <label>摘要<textarea v-model="editInsightDraft.summary" rows="3" /></label>
              <div class="form-grid-two">
                <label>类型
                  <select v-model="editInsightDraft.insight_type">
                    <option value="trend">trend</option>
                    <option value="risk">risk</option>
                    <option value="opportunity">opportunity</option>
                    <option value="competitor_move">competitor_move</option>
                  </select>
                </label>
                <label>置信度<input v-model.number="editInsightDraft.confidence_score" type="number" min="0" max="1" step="0.05" /></label>
              </div>
            </template>
            <template v-else>
              <h3>{{ item.title }}</h3>
              <p>{{ item.summary || "暂无摘要" }}</p>
            </template>
            <div class="coverage-metrics">
              <span>{{ item.status }}</span>
              <span>{{ item.insight_type }}</span>
              <span>{{ formatPercent(item.confidence_score) }}</span>
              <span>{{ item.implication_count }} implications</span>
              <span>{{ item.data_source_name || "未知来源" }}</span>
            </div>
            <div class="requirement-source-list">
              <article class="requirement-source-item">
                <span>外部信号</span>
                <a v-if="item.source_url" :href="item.source_url" target="_blank" rel="noreferrer">
                  {{ item.source_title || item.source_url }}
                </a>
                <strong v-else>{{ item.source_title || item.news_item_id }}</strong>
                <em v-if="item.source_report_type">{{ item.source_report_type }} report item</em>
              </article>
            </div>
          </div>
          <div v-if="canManageInsights" class="task-row-actions">
            <button v-if="editingInsightId !== item.id" type="button" class="mini-action" @click="beginEditInsight(item)">
              <Save :size="15" />
              <span>编辑</span>
            </button>
            <button v-else type="button" class="mini-action active" @click="saveInsight(item)">
              <CheckCircle2 :size="15" />
              <span>保存</span>
            </button>
            <button type="button" class="mini-action" @click="setInsightStatus(item, item.status === 'confirmed' ? 'draft' : 'confirmed')">
              <CheckCircle2 :size="15" />
              <span>{{ item.status === "confirmed" ? "退回" : "确认" }}</span>
            </button>
            <button type="button" class="mini-action" :class="{ active: item.status === 'archived' }" @click="setInsightStatus(item, item.status === 'archived' ? 'draft' : 'archived')">
              <Archive :size="15" />
              <span>{{ item.status === "archived" ? "重开" : "归档" }}</span>
            </button>
          </div>
        </article>
        <p v-if="!loading && insights.length === 0" class="empty-state">暂无洞察，可从日报/周报条目沉淀或从候选新闻创建。</p>
      </article>

      <article class="module-card ops-list">
        <div class="card-title-row">
          <div><p class="eyebrow">Implications</p><h3>战略影响</h3></div>
          <span class="metric-pill">{{ implications.length }} implications</span>
        </div>
        <article v-for="item in implications" :key="item.id" class="ops-row implication-row">
          <div>
            <template v-if="editingImplicationId === item.id">
              <label>标题<input v-model="editImplicationDraft.title" /></label>
              <label>说明<textarea v-model="editImplicationDraft.description" rows="3" /></label>
              <label>类型
                <select v-model="editImplicationDraft.implication_type">
                  <option value="opportunity">opportunity</option>
                  <option value="risk">risk</option>
                  <option value="capability_gap">capability_gap</option>
                  <option value="competitive_pressure">competitive_pressure</option>
                </select>
              </label>
            </template>
            <template v-else>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description || "暂无说明" }}</p>
            </template>
            <div class="coverage-metrics">
              <span>{{ item.implication_type }}</span>
              <span>{{ item.insight_title || item.insight_id }}</span>
            </div>
          </div>
          <div v-if="canManageInsights" class="task-row-actions">
            <button v-if="editingImplicationId !== item.id" type="button" class="mini-action" @click="beginEditImplication(item)">
              <Save :size="15" />
              <span>编辑</span>
            </button>
            <button v-else type="button" class="mini-action active" @click="saveImplication(item)">
              <CheckCircle2 :size="15" />
              <span>保存</span>
            </button>
            <a class="mini-action" :href="`/requirements?insight_id=${item.insight_id}`">
              <ExternalLink :size="15" />
              <span>需求</span>
            </a>
          </div>
        </article>
        <p v-if="!loading && implications.length === 0" class="empty-state">暂无战略影响，先确认洞察后再沉淀影响判断。</p>
      </article>
    </section>
  </section>
</template>
