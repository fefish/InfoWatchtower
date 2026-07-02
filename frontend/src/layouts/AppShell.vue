<script setup lang="ts">
import {
  Activity,
  Archive,
  BarChart3,
  Bell,
  CalendarDays,
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
  ListChecks,
  Users,
  X
} from "lucide-vue-next";
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const router = useRouter();
const session = useSessionStore();
const workspace = useWorkspaceStore();

const isSuperAdmin = computed(() => session.user?.roles.includes("super_admin") ?? false);
const showWorkspaceForm = ref(false);
const creatingWorkspace = ref(false);
const workspaceFormError = ref("");
const workspaceForm = reactive({
  code: "",
  name: "",
  description: "",
  default_domain_code: "ai"
});

function openWorkspaceForm() {
  workspaceFormError.value = "";
  workspaceForm.code = "";
  workspaceForm.name = "";
  workspaceForm.description = "";
  workspaceForm.default_domain_code = "ai";
  showWorkspaceForm.value = true;
}

function closeWorkspaceForm() {
  showWorkspaceForm.value = false;
}

async function submitWorkspaceForm() {
  const code = workspaceForm.code.trim();
  const name = workspaceForm.name.trim();
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(code)) {
    workspaceFormError.value = "标识需以小写字母开头，只含小写字母、数字和下划线";
    return;
  }
  if (!name) {
    workspaceFormError.value = "请填写工作台名称";
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
    showWorkspaceForm.value = false;
    router.push("/sources");
  } catch (exc) {
    workspaceFormError.value = exc instanceof Error ? exc.message : "创建工作台失败";
  } finally {
    creatingWorkspace.value = false;
  }
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
          v-if="isSuperAdmin"
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
        <h3>新建工作台</h3>
      </div>
      <button type="button" class="panel-close" @click="closeWorkspaceForm" title="关闭">
        <X :size="18" />
      </button>
    </header>

    <p class="workspace-form-hint">
      新工作台自动获得数据源管理、候选池、日报周报、归档和导出等核心页面，可在数据源管理页启用共享源或自建信息源。
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

    <p v-if="workspaceFormError" class="form-error">{{ workspaceFormError }}</p>

    <button type="button" class="config-save" :disabled="creatingWorkspace" @click="submitWorkspaceForm">
      {{ creatingWorkspace ? "创建中" : "创建工作台" }}
    </button>
  </aside>
</template>
