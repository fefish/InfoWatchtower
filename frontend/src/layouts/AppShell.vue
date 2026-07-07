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
  Settings,
  ShieldCheck,
  SquareStack,
  GitCompareArrows,
  KeyRound,
  ListChecks,
  Users
} from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchUnreadNotificationCount } from "../api/notifications";
import { searchWorkspace, type SearchResultRecord } from "../api/search";
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
import AppModal from "../components/AppModal.vue";
import WorkspaceDiscovery from "../components/WorkspaceDiscovery.vue";
import { useRuntimeStore } from "../stores/runtime";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const router = useRouter();
const session = useSessionStore();
const workspace = useWorkspaceStore();
const runtime = useRuntimeStore();

const metaErrorMessage = computed(() => {
  if (runtime.metaErrorKind === "stale-backend") {
    return "后端版本过旧（缺少 /api/meta/runtime）：前端代码已更新但后端进程/镜像未更新，请重启或重建后端后重试。";
  }
  if (runtime.metaErrorKind === "unreachable") {
    return "后端不可达：请确认后端服务已启动，再点重试。";
  }
  return `运行时信息加载失败${runtime.metaErrorStatus ? `（HTTP ${runtime.metaErrorStatus}）` : ""}，功能已保守禁用。`;
});

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
const notificationUnreadCount = ref(0);
const searchQuery = ref("");
const searchResults = ref<SearchResultRecord[]>([]);
const recentSearchResults = ref<SearchResultRecord[]>([]);
const searchLoading = ref(false);
const searchError = ref("");
const searchPanelOpen = ref(false);
const activeSearchResultIndex = ref(-1);
let searchRequestId = 0;
const recentSearchLimit = 6;
const recentSearchStoragePrefix = "infowatchtower:search:recent";
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

// 建台向导脏状态（frontend-product-design §10.1）：与打开时的快照比对，
// 有未保存输入时遮罩/Esc/关闭按钮先弹 sm 确认层，不允许静默丢输入。
const wizardBaseline = ref("");

function wizardSnapshot() {
  return JSON.stringify({
    form: { ...workspaceForm },
    selected: Array.from(selectedWizardSourceIds.value).sort()
  });
}

const workspaceWizardDirty = computed(
  () => showWorkspaceForm.value && !wizardFinished.value && wizardSnapshot() !== wizardBaseline.value
);

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
  wizardBaseline.value = wizardSnapshot();
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
  strategic_insights: GitBranch,
  requirements: ListChecks,
  topic_tasks: SquareStack,
  sync: GitCompareArrows,
  exports: Database,
  workspace_settings: Settings,
  users: Users,
  audit_logs: ShieldCheck
} as const;

const workspaceRoleRank: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3
};

// 当前工作台的有效角色：super_admin / editor_admin 全局角色视同 owner；
// 其余取 membership 角色，未知时按 viewer 保守处理。
const effectiveWorkspaceRole = computed(() => {
  const globalRoles = session.user?.roles ?? [];
  if (globalRoles.includes("super_admin") || globalRoles.includes("editor_admin")) {
    return "owner";
  }
  return workspace.currentRole ?? "viewer";
});

// 工作台配置中心入口（切换器旁齿轮）：admin/owner 可见，与
// workspace_settings 分区的 min_role=admin 口径一致。
const canOpenWorkspaceSettings = computed(
  () =>
    Boolean(workspace.currentCode) &&
    (workspaceRoleRank[effectiveWorkspaceRole.value] ?? 0) >= workspaceRoleRank.admin
);

const navItems = computed(() =>
  workspace.sections
    // 采集能力关闭（如 intranet 形态）时隐藏「抓取与覆盖」入口。
    .filter((section) => runtime.canIngest || section.section_key !== "ingestion_coverage")
    // 数据驱动的角色过滤：viewer（游客）只看到 min_role=viewer 的阅读分区
    // （日报/周报/历史报告/实体大事记），管理分区整组隐藏。
    .filter(
      (section) =>
        (workspaceRoleRank[effectiveWorkspaceRole.value] ?? 0) >=
        (workspaceRoleRank[section.min_role ?? "member"] ?? 1)
    )
    .map((section) => ({
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

const objectTypeLabels: Record<string, string> = {
  daily_report: "日报",
  daily_report_item: "日报条目",
  weekly_report: "周报",
  weekly_report_item: "周报条目",
  news_item: "候选新闻",
  generated_news: "成品新闻",
  data_source: "数据源",
  tracked_entity: "实体",
  entity_milestone: "大事记",
  historical_report: "历史报告",
  requirement: "需求",
  topic_task: "任务",
  comment: "评论",
  export_job: "导出任务",
  export_job_item: "导出 trace",
  sync_run: "同步运行",
  sync_conflict: "同步冲突"
};

const trimmedSearchQuery = computed(() => searchQuery.value.trim());
const searchReady = computed(() => runtime.capabilities.search && Boolean(workspace.currentCode));
const hasSearchTerm = computed(() => trimmedSearchQuery.value.length >= 2);
const displayedSearchResults = computed(() =>
  hasSearchTerm.value ? searchResults.value : recentSearchResults.value
);
const groupedSearchResults = computed(() => {
  const groups = new Map<string, { objectType: string; label: string; items: { result: SearchResultRecord; index: number }[] }>();
  displayedSearchResults.value.forEach((result, index) => {
    const existing = groups.get(result.object_type);
    if (existing) {
      existing.items.push({ result, index });
      return;
    }
    groups.set(result.object_type, {
      objectType: result.object_type,
      label: searchResultTypeLabel(result.object_type),
      items: [{ result, index }]
    });
  });
  return Array.from(groups.values());
});
const recentSearchStorageKey = computed(() => {
  const userId = session.user?.id || "anonymous";
  const workspaceCode = workspace.currentCode || "none";
  return `${recentSearchStoragePrefix}:${userId}:${workspaceCode}`;
});
const showRecentSearchResults = computed(
  () => !hasSearchTerm.value && recentSearchResults.value.length > 0
);

watch(
  () => [trimmedSearchQuery.value, workspace.currentCode, runtime.capabilities.search] as const,
  () => {
    void runGlobalSearch();
  }
);

watch(
  () => [workspace.currentCode, session.user?.id] as const,
  () => {
    loadRecentSearchResults();
    if (!hasSearchTerm.value) {
      activeSearchResultIndex.value = recentSearchResults.value.length > 0 ? 0 : -1;
    }
  },
  { immediate: true }
);

async function runGlobalSearch() {
  const query = trimmedSearchQuery.value;
  const currentWorkspace = workspace.currentCode;
  const requestId = ++searchRequestId;
  if (!searchReady.value || query.length < 2) {
    searchResults.value = [];
    searchError.value = "";
    searchLoading.value = false;
    if (recentSearchResults.value.length === 0) {
      searchPanelOpen.value = false;
    }
    activeSearchResultIndex.value = recentSearchResults.value.length > 0 ? 0 : -1;
    return;
  }
  searchLoading.value = true;
  searchError.value = "";
  searchPanelOpen.value = true;
  try {
    const payload = await searchWorkspace(currentWorkspace, query, undefined, 10);
    if (requestId !== searchRequestId) {
      return;
    }
    searchResults.value = payload.results;
    activeSearchResultIndex.value = payload.results.length > 0 ? 0 : -1;
  } catch (exc) {
    if (requestId !== searchRequestId) {
      return;
    }
    searchResults.value = [];
    activeSearchResultIndex.value = -1;
    searchError.value = exc instanceof Error ? exc.message : "搜索失败";
  } finally {
    if (requestId === searchRequestId) {
      searchLoading.value = false;
    }
  }
}

function openSearchPanel() {
  if (hasSearchTerm.value || showRecentSearchResults.value) {
    searchPanelOpen.value = true;
    if (displayedSearchResults.value.length > 0 && activeSearchResultIndex.value < 0) {
      activeSearchResultIndex.value = 0;
    }
  }
}

function closeSearchPanel() {
  searchPanelOpen.value = false;
}

function submitSearch() {
  openActiveSearchResult();
}

function moveSearchSelection(delta: number) {
  if (!searchPanelOpen.value && (hasSearchTerm.value || showRecentSearchResults.value)) {
    searchPanelOpen.value = true;
  }
  const count = displayedSearchResults.value.length;
  if (count === 0) {
    activeSearchResultIndex.value = -1;
    return;
  }
  const current = activeSearchResultIndex.value;
  activeSearchResultIndex.value = current < 0 ? (delta > 0 ? 0 : count - 1) : (current + delta + count) % count;
}

function openActiveSearchResult() {
  const result = displayedSearchResults.value[activeSearchResultIndex.value] ?? displayedSearchResults.value[0];
  if (result) {
    void openSearchResult(result);
  }
}

async function openSearchResult(result: SearchResultRecord) {
  searchPanelOpen.value = false;
  rememberSearchResult(result);
  await router.push(result.route);
}

function searchResultTypeLabel(type: string) {
  return objectTypeLabels[type] ?? type;
}

function searchResultDomId(index: number) {
  return `global-search-result-${index}`;
}

function loadRecentSearchResults() {
  if (typeof window === "undefined") {
    recentSearchResults.value = [];
    return;
  }
  try {
    const raw = window.localStorage.getItem(recentSearchStorageKey.value);
    const parsed = raw ? JSON.parse(raw) : [];
    recentSearchResults.value = Array.isArray(parsed) ? parsed.filter(isSearchResultRecord).slice(0, recentSearchLimit) : [];
  } catch {
    recentSearchResults.value = [];
  }
}

function rememberSearchResult(result: SearchResultRecord) {
  if (typeof window === "undefined" || !workspace.currentCode) {
    return;
  }
  const next = [
    result,
    ...recentSearchResults.value.filter(
      (item) => item.object_type !== result.object_type || item.object_id !== result.object_id
    )
  ].slice(0, recentSearchLimit);
  recentSearchResults.value = next;
  try {
    window.localStorage.setItem(recentSearchStorageKey.value, JSON.stringify(next));
  } catch {
    // localStorage can be unavailable in restricted browser contexts; search still works without recents.
  }
}

function isSearchResultRecord(value: unknown): value is SearchResultRecord {
  if (!value || typeof value !== "object") {
    return false;
  }
  const item = value as Record<string, unknown>;
  return (
    typeof item.object_type === "string" &&
    typeof item.object_id === "string" &&
    typeof item.title === "string" &&
    typeof item.summary === "string" &&
    typeof item.highlight === "string" &&
    typeof item.route === "string" &&
    typeof item.score === "number" &&
    (typeof item.updated_at === "string" || item.updated_at === null) &&
    Array.isArray(item.matched_fields)
  );
}

async function loadNotificationUnreadCount() {
  try {
    const result = await fetchUnreadNotificationCount();
    notificationUnreadCount.value = result.unread_count;
  } catch {
    notificationUnreadCount.value = 0;
  }
}

function onNotificationUpdate() {
  void loadNotificationUnreadCount();
}

onMounted(() => {
  void workspace.loadWorkspaces();
  void loadNotificationUnreadCount();
  window.addEventListener("infowatchtower:notifications-updated", onNotificationUpdate);
});

onBeforeUnmount(() => {
  window.removeEventListener("infowatchtower:notifications-updated", onNotificationUpdate);
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
        <div class="workspace-switcher-row">
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
          <RouterLink
            v-if="canOpenWorkspaceSettings"
            class="workspace-settings-link"
            to="/workspace-settings"
            aria-label="工作台配置"
            title="工作台配置"
          >
            <Settings :size="16" />
          </RouterLink>
        </div>
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
        <WorkspaceDiscovery />

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
          <span v-if="runtime.deployModeBadge" class="deploy-badge">{{ runtime.deployModeBadge }}</span>
          <p class="topbar-subtitle">{{ workspace.error || workspace.current?.description || "" }}</p>
        </div>

        <div class="topbar-tools">
          <form
            v-if="runtime.capabilities.search"
            class="global-search"
            role="search"
            @submit.prevent="submitSearch"
          >
            <label class="global-search-input">
              <Search :size="16" />
              <input
                v-model="searchQuery"
                type="search"
                placeholder="搜索情报对象"
                aria-label="搜索情报对象"
                aria-controls="global-search-panel"
                :aria-activedescendant="
                  activeSearchResultIndex >= 0 ? searchResultDomId(activeSearchResultIndex) : undefined
                "
                autocomplete="off"
                @focus="openSearchPanel"
                @keydown.down.prevent="moveSearchSelection(1)"
                @keydown.up.prevent="moveSearchSelection(-1)"
                @keydown.enter.prevent="openActiveSearchResult"
                @keydown.esc.prevent="closeSearchPanel"
              />
            </label>
            <div v-if="searchPanelOpen" id="global-search-panel" class="global-search-panel" role="listbox">
              <p v-if="searchLoading" class="global-search-state">搜索中</p>
              <p v-else-if="searchError" class="global-search-state error">{{ searchError }}</p>
              <p v-else-if="hasSearchTerm && searchResults.length === 0" class="global-search-state">
                没有匹配的情报对象
              </p>
              <template v-else>
                <p v-if="showRecentSearchResults" class="global-search-recent-title">最近打开</p>
                <section v-for="group in groupedSearchResults" :key="group.objectType" class="global-search-group">
                  <p class="global-search-group-title">
                    <span>{{ group.label }}</span>
                    <small>{{ group.items.length }}</small>
                  </p>
                  <button
                    v-for="{ result, index } in group.items"
                    :id="searchResultDomId(index)"
                    :key="`${result.object_type}-${result.object_id}`"
                    type="button"
                    role="option"
                    class="global-search-result"
                    :class="{ active: activeSearchResultIndex === index }"
                    :aria-selected="activeSearchResultIndex === index ? 'true' : 'false'"
                    @mouseenter="activeSearchResultIndex = index"
                    @click="openSearchResult(result)"
                  >
                    <span>{{ searchResultTypeLabel(result.object_type) }}</span>
                    <strong>{{ result.title }}</strong>
                    <small>{{ result.highlight || result.summary }}</small>
                  </button>
                </section>
              </template>
            </div>
          </form>
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
          <RouterLink
            class="notification-button"
            to="/notifications"
            aria-label="消息通知"
            title="消息通知"
          >
            <Bell :size="18" />
            <span v-if="notificationUnreadCount > 0" class="notification-badge">
              {{ notificationUnreadCount > 99 ? "99+" : notificationUnreadCount }}
            </span>
          </RouterLink>
          <RouterLink
            class="user-pill"
            to="/account"
            aria-label="账号设置"
            :title="`${session.user?.display_name} · ${session.user?.roles[0]}`"
          >
            <span class="user-pill-avatar">{{ session.user?.display_name?.slice(0, 1) || "U" }}</span>
            <span class="user-pill-name">{{ session.user?.display_name }}</span>
          </RouterLink>
        </div>
      </header>

      <div v-if="runtime.metaError" class="form-error runtime-meta-error" role="alert">
        <span>{{ metaErrorMessage }}</span>
        <button type="button" class="ghost-button" :disabled="runtime.loading" @click="runtime.reload()">
          {{ runtime.loading ? "重试中" : "重试" }}
        </button>
      </div>

      <router-view />
    </main>
  </div>

  <!-- 新建工作台向导：居中 Modal md 档（frontend-product-design §10.3 迁移清单第 1 项）。
       创建类操作不满足上下文面板判定（§10.2 条件 1/3），原右上 config-panel 浮层收编到
       AppModal 基座；脏表单遮罩/Esc 先确认由 dirty 快照驱动。 -->
  <AppModal
    :open="showWorkspaceForm"
    :title="wizardFinished ? '工作台已创建' : '新建工作台'"
    size="md"
    :dirty="workspaceWizardDirty"
    @close="closeWorkspaceForm"
  >
    <template #header-meta>
      <p class="eyebrow">工作台扩展</p>
    </template>

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
  </AppModal>
</template>
