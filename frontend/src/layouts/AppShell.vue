<script setup lang="ts">
import {
  Activity,
  Archive,
  BarChart3,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Database,
  FileText,
  GitBranch,
  Layers,
  LogOut,
  Plus,
  Radio,
  Search,
  ShieldCheck,
  SquareStack,
  GitCompareArrows,
  KeyRound,
  ListChecks,
  Users,
  X
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import {
  createSource,
  fetchSources,
  updateSourceWorkspaceConfig,
  type DataSourceRecord
} from "../api/sources";
import {
  updateWorkspaceLabelPolicy,
  type WorkspaceLabelPolicyUpdate
} from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const router = useRouter();
const session = useSessionStore();
const workspace = useWorkspaceStore();

const canCreateWorkspace = computed(
  () => session.user?.roles.some((role) => role === "super_admin" || role === "editor_admin") ?? false
);
const showWorkspaceForm = ref(false);
const creatingWorkspace = ref(false);
const workspaceFormError = ref("");
const wizardStep = ref(1);
const wizardFinished = ref(false);
const wizardSources = ref<DataSourceRecord[]>([]);
const loadingWizardSources = ref(false);
const selectedWizardSourceIds = ref<Set<string>>(new Set());
const workspaceForm = reactive({
  code: "",
  name: "",
  description: "",
  default_domain_code: "hardware",
  policy_preset: "blank" as "ai_sql" | "ai_tools" | "blank",
  custom_categories: "算力芯片\n端侧设备\n供应链与制造",
  custom_source_name: "",
  custom_source_type: "rss",
  custom_source_url: ""
});

const companySqlContentFields = [
  "background",
  "effects",
  "eventSummary",
  "technologyAndInnovation",
  "valueAndImpact"
];
const aiSqlPrimaryCategories = [
  "AI Infra",
  "AI 应用",
  "测评技术",
  "大厂动态",
  "模型",
  "算法",
  "推理加速",
  "训练技术",
  "智能体",
  "基础竞争力"
];
const aiToolPrimaryCategories = ["工具新功能", "工具新案例", "工具新技术"];
const aiToolSecondaryLabels = ["cursor", "claude code", "opencode", "codex"];

function openWorkspaceForm() {
  workspaceFormError.value = "";
  wizardStep.value = 1;
  wizardFinished.value = false;
  workspaceForm.code = "";
  workspaceForm.name = "";
  workspaceForm.description = "";
  workspaceForm.default_domain_code = "hardware";
  workspaceForm.policy_preset = "blank";
  workspaceForm.custom_categories = "算力芯片\n端侧设备\n供应链与制造";
  workspaceForm.custom_source_name = "";
  workspaceForm.custom_source_type = "rss";
  workspaceForm.custom_source_url = "";
  selectedWizardSourceIds.value = new Set();
  showWorkspaceForm.value = true;
  void loadWizardSources();
}

function closeWorkspaceForm() {
  showWorkspaceForm.value = false;
}

async function loadWizardSources() {
  loadingWizardSources.value = true;
  try {
    wizardSources.value = await fetchSources();
  } catch (exc) {
    workspaceFormError.value = exc instanceof Error ? exc.message : "加载共享源失败";
  } finally {
    loadingWizardSources.value = false;
  }
}

function isWizardSourceSelected(sourceId: string) {
  return selectedWizardSourceIds.value.has(sourceId);
}

function toggleWizardSource(sourceId: string, checked: boolean) {
  const next = new Set(selectedWizardSourceIds.value);
  if (checked) {
    next.add(sourceId);
  } else {
    next.delete(sourceId);
  }
  selectedWizardSourceIds.value = next;
}

function validateWorkspaceBasics() {
  const code = workspaceForm.code.trim();
  const name = workspaceForm.name.trim();
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(code)) {
    workspaceFormError.value = "标识需以小写字母开头，只含小写字母、数字和下划线";
    return false;
  }
  if (!name) {
    workspaceFormError.value = "请填写工作台名称";
    return false;
  }
  workspaceFormError.value = "";
  return true;
}

function nextWizardStep() {
  if (wizardStep.value === 1 && !validateWorkspaceBasics()) {
    return;
  }
  wizardStep.value = Math.min(3, wizardStep.value + 1);
}

function previousWizardStep() {
  wizardStep.value = Math.max(1, wizardStep.value - 1);
  workspaceFormError.value = "";
}

async function submitWorkspaceForm() {
  const code = workspaceForm.code.trim();
  const name = workspaceForm.name.trim();
  if (!validateWorkspaceBasics()) {
    return;
  }
  creatingWorkspace.value = true;
  workspaceFormError.value = "";
  try {
    await workspace.createWorkspace({
      code,
      name,
      description: workspaceForm.description.trim(),
      default_domain_code: workspaceForm.default_domain_code.trim() || "ai"
    });
    for (const sourceId of selectedWizardSourceIds.value) {
      const source = wizardSources.value.find((item) => item.id === sourceId);
      if (!source) {
        continue;
      }
      await updateSourceWorkspaceConfig(source.id, {
        workspace_code: code,
        enabled: true,
        source_weight: source.workspace_source_weight ?? 1,
        daily_limit: source.workspace_daily_limit ?? null
      });
    }
    if (workspaceForm.custom_source_name.trim() && workspaceForm.custom_source_url.trim()) {
      await createSource({
        workspace_code: code,
        name: workspaceForm.custom_source_name.trim(),
        source_type: workspaceForm.custom_source_type,
        url: workspaceForm.custom_source_url.trim(),
        domain_code: workspaceForm.default_domain_code.trim() || "ai"
      });
    }
    await updateWorkspaceLabelPolicy(code, await buildWizardPolicyPayload(code));
    wizardFinished.value = true;
    await workspace.setWorkspace(code);
  } catch (exc) {
    workspaceFormError.value = exc instanceof Error ? exc.message : "创建工作台失败";
  } finally {
    creatingWorkspace.value = false;
  }
}

async function buildWizardPolicyPayload(workspaceCode: string): Promise<WorkspaceLabelPolicyUpdate> {
  if (workspaceForm.policy_preset === "ai_sql") {
    return {
      label_set_code: "ai_sql_categories",
      news_format_code: "company_sql_v1",
      export_category_mode: "news_primary",
      required_content_fields: [...companySqlContentFields],
      allowed_primary_categories: [...aiSqlPrimaryCategories],
      secondary_labels_by_primary: {},
      default_category: "AI 应用",
      fallback_category: "AI 应用"
    };
  }
  if (workspaceForm.policy_preset === "ai_tools") {
    return {
      label_set_code: "ai_tools_categories",
      news_format_code: "tool_intel_v1",
      export_category_mode: "news_primary",
      required_content_fields: [...companySqlContentFields],
      allowed_primary_categories: [...aiToolPrimaryCategories],
      secondary_labels_by_primary: Object.fromEntries(
        aiToolPrimaryCategories.map((category) => [category, [...aiToolSecondaryLabels]])
      ) as Record<string, string[]>,
      default_category: "工具新功能",
      fallback_category: "工具新功能"
    };
  }
  const categories = workspaceForm.custom_categories
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  const fallback = categories[0] ?? "AI 应用";
  return {
    label_set_code: `${workspaceCode}_custom_categories`,
    news_format_code: "custom_intel_v1",
    export_category_mode: "news_primary",
    required_content_fields: [
      ...companySqlContentFields
    ],
    allowed_primary_categories: categories.length > 0 ? categories : [fallback],
    secondary_labels_by_primary: {},
    default_category: fallback,
    fallback_category: fallback
  };
}

const sectionIcons = {
  dashboard: Activity,
  source_management: Radio,
  ingestion_coverage: BarChart3,
  candidate_pool: Layers,
  daily_reports: FileText,
  weekly_reports: CalendarDays,
  historical_reports: Archive,
  entity_milestones: GitBranch,
  quality_archive: ClipboardCheck,
  requirements: ListChecks,
  topic_tasks: SquareStack,
  sync: GitCompareArrows,
  exports: Database,
  users: Users,
  audit_logs: ShieldCheck
} as const;

const navItems = computed(() =>
  workspace.sections.map((section) => ({
    key: section.section_key,
    label: section.name,
    icon: sectionIcons[section.section_key as keyof typeof sectionIcons] ?? SquareStack,
    path: section.route_path,
    group: section.group || "system"
  }))
);

const navGroupMeta = [
  { key: "today", label: "今日" },
  { key: "collect", label: "情报采集" },
  { key: "curate", label: "编审工作流" },
  { key: "library", label: "资料库" },
  { key: "collab", label: "协作" },
  { key: "system", label: "系统" }
];

const navGroups = computed(() =>
  navGroupMeta
    .map((group) => ({
      ...group,
      items: navItems.value.filter((item) => item.group === group.key)
    }))
    .filter((group) => group.items.length > 0)
);

onMounted(() => {
  void workspace.loadWorkspaces();
});

async function logout() {
  await session.logout();
  router.push("/login");
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">IW</span>
        <span class="brand-name">InfoWatchtower</span>
      </div>

      <nav class="nav-list" aria-label="主导航">
        <label class="workspace-switcher">
          <span>工作台</span>
          <select
            :value="workspace.currentCode"
            @change="workspace.setWorkspace(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="item in workspace.options" :key="item.code" :value="item.code">
              {{ item.name }}
            </option>
          </select>
        </label>
        <button
          v-if="canCreateWorkspace"
          type="button"
          class="workspace-create-button"
          @click="openWorkspaceForm"
          title="新建工作台"
        >
          <Plus :size="14" />
          <span>新建工作台</span>
        </button>

        <div v-for="group in navGroups" :key="group.key" class="nav-group">
          <p class="nav-group-title">{{ group.label }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.key"
            class="nav-item"
            :to="item.path"
            :title="item.label"
          >
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar-user">
        <div class="user-avatar">{{ session.user?.display_name?.slice(0, 1) || "U" }}</div>
        <div>
          <strong>{{ session.user?.display_name }}</strong>
          <span>{{ session.user?.roles[0] }}</span>
        </div>
        <RouterLink class="sidebar-action" to="/account" aria-label="账号">
          <KeyRound :size="17" />
        </RouterLink>
        <button class="sidebar-action" type="button" @click="logout" aria-label="退出登录">
          <LogOut :size="17" />
        </button>
      </div>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div class="topbar-title">
          <h1>{{ workspace.current?.name || "工作台" }}</h1>
          <p class="topbar-subtitle">{{ workspace.error || workspace.current?.description || "" }}</p>
        </div>

        <div class="topbar-tools">
          <select
            class="topbar-workspace-select"
            :value="workspace.currentCode"
            aria-label="切换工作台"
            @change="workspace.setWorkspace(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="item in workspace.options" :key="item.code" :value="item.code">
              {{ item.name }}
            </option>
          </select>
          <label class="global-search" aria-label="搜索资源">
            <Search :size="16" />
            <input type="search" placeholder="搜索资源..." />
          </label>
          <button class="notification-button" type="button" title="通知">
            <Bell :size="19" />
            <span aria-hidden="true"></span>
          </button>
          <div class="user-pill" :title="`${session.user?.display_name} · ${session.user?.roles[0]}`">
            <span class="user-pill-avatar">{{ session.user?.display_name?.slice(0, 1) || "U" }}</span>
            <span class="user-pill-name">{{ session.user?.display_name }}</span>
          </div>
        </div>
      </header>

      <router-view />
    </main>
  </div>

  <div v-if="showWorkspaceForm" class="config-backdrop" @click="closeWorkspaceForm"></div>
  <aside v-if="showWorkspaceForm" class="config-panel" aria-label="新建工作台">
    <header>
      <div>
        <p class="eyebrow">工作台扩展</p>
        <h3>{{ wizardFinished ? "工作台已创建" : "新建工作台" }}</h3>
      </div>
      <button type="button" class="panel-close" @click="closeWorkspaceForm" title="关闭">
        <X :size="18" />
      </button>
    </header>

    <div v-if="!wizardFinished" class="workspace-wizard">
      <div class="wizard-steps" aria-label="创建步骤">
        <span :class="{ active: wizardStep === 1, done: wizardStep > 1 }"><i>1</i>基本信息</span>
        <span :class="{ active: wizardStep === 2, done: wizardStep > 2 }"><i>2</i>选择信息源</span>
        <span :class="{ active: wizardStep === 3 }"><i>3</i>标签策略</span>
      </div>

      <section v-if="wizardStep === 1" class="wizard-page">
        <p class="workspace-form-hint">
          给新工作台起名。「标识」是系统内部代号（小写英文，建成后不可改）；「默认主题域」
          用于给内容打主题归属（如 ai / hardware / policy），不确定就保留 ai。
        </p>
        <div class="config-grid">
          <label>
            <span>标识（英文小写）</span>
            <input v-model="workspaceForm.code" placeholder="例如 hardware_intel" />
          </label>
          <label>
            <span>名称</span>
            <input v-model="workspaceForm.name" placeholder="例如 硬件情报工作台" />
          </label>
          <label>
            <span>默认主题域</span>
            <input v-model="workspaceForm.default_domain_code" placeholder="ai / hardware / policy" />
          </label>
          <label>
            <span>描述</span>
            <input v-model="workspaceForm.description" placeholder="这个工作台负责什么" />
          </label>
        </div>
      </section>

      <section v-else-if="wizardStep === 2" class="wizard-page">
        <p class="workspace-form-hint">
          选这个工作台要抓取的信息源：可勾选共享池里已有的源（此处仅展示部分，建成后可在
          「数据源管理」启用更多），也可以现场自建一个新源。本步可跳过。
        </p>
        <div class="wizard-section-title">
          <strong>共享源</strong>
          <span>{{ selectedWizardSourceIds.size }} 已选</span>
        </div>
        <div class="wizard-source-list">
          <label v-for="source in wizardSources.slice(0, 12)" :key="source.id" class="wizard-source-row">
            <input
              type="checkbox"
              :checked="isWizardSourceSelected(source.id)"
              @change="toggleWizardSource(source.id, ($event.target as HTMLInputElement).checked)"
            />
            <span>
              <strong>{{ source.name }}</strong>
              <small>{{ source.source_type }} · {{ source.domain_code }}</small>
            </span>
          </label>
          <p v-if="loadingWizardSources" class="empty-state">加载中</p>
          <p v-else-if="wizardSources.length === 0" class="empty-state">共享池暂无信息源，可在下方先自建一个 RSS 源。</p>
        </div>

        <div class="wizard-section-title">
          <strong>自建源</strong>
          <span>可选</span>
        </div>
        <div class="config-grid">
          <label>
            <span>名称</span>
            <input v-model="workspaceForm.custom_source_name" placeholder="例如 硬件新闻 RSS" />
          </label>
          <label>
            <span>类型</span>
            <select v-model="workspaceForm.custom_source_type">
              <option value="rss">RSS</option>
              <option value="paper_rss">论文 RSS</option>
              <option value="page_manual">页面手工</option>
              <option value="page_monitor">页面监控</option>
            </select>
          </label>
          <label class="config-grid-wide">
            <span>URL</span>
            <input v-model="workspaceForm.custom_source_url" placeholder="https://example.com/feed.xml" />
          </label>
        </div>
      </section>

      <section v-else class="wizard-page">
        <p class="workspace-form-hint">
          标签策略决定这个工作台成品新闻的一级分类口径（影响日报分组与导出）。
          可先复制一套预设，建成后随时在「数据源管理」右侧策略面板调整。
        </p>
        <div class="wizard-policy-options">
          <label>
            <input v-model="workspaceForm.policy_preset" type="radio" value="ai_sql" />
            <span>复制 AI 十分类</span>
          </label>
          <label>
            <input v-model="workspaceForm.policy_preset" type="radio" value="ai_tools" />
            <span>复制 AI 工具策略</span>
          </label>
          <label>
            <input v-model="workspaceForm.policy_preset" type="radio" value="blank" />
            <span>空白自定义</span>
          </label>
        </div>
        <label v-if="workspaceForm.policy_preset === 'blank'" class="wizard-textarea-label">
          <span>一级标签</span>
          <textarea v-model="workspaceForm.custom_categories" rows="6"></textarea>
        </label>
      </section>

      <p v-if="workspaceFormError" class="form-error">{{ workspaceFormError }}</p>

      <div class="wizard-actions">
        <button type="button" class="icon-button secondary" :disabled="wizardStep === 1 || creatingWorkspace" @click="previousWizardStep">
          <ChevronLeft :size="16" />
          <span>上一步</span>
        </button>
        <button v-if="wizardStep < 3" type="button" class="icon-button" @click="nextWizardStep">
          <ChevronRight :size="16" />
          <span>下一步</span>
        </button>
        <button v-else type="button" class="icon-button" :disabled="creatingWorkspace" @click="submitWorkspaceForm">
          <Plus :size="16" />
          <span>{{ creatingWorkspace ? "创建中" : "创建工作台" }}</span>
        </button>
      </div>
    </div>

    <div v-else class="workspace-wizard-done">
      <CheckCircle2 :size="28" />
      <strong>{{ workspace.current?.name }}</strong>
      <span>{{ workspace.currentCode }}</span>
      <div class="wizard-actions">
        <button type="button" class="icon-button secondary" @click="closeWorkspaceForm">完成</button>
        <button type="button" class="icon-button" @click="router.push('/sources'); closeWorkspaceForm()">
          <Radio :size="16" />
          <span>数据源</span>
        </button>
      </div>
    </div>
  </aside>
</template>
