<script setup lang="ts">
import {
  Activity,
  Archive,
  Bell,
  CalendarDays,
  ClipboardCheck,
  Database,
  FileText,
  GitBranch,
  Layers,
  LogOut,
  Radio,
  Search,
  ShieldCheck,
  SquareStack,
  GitCompareArrows,
  ListChecks,
  Users
} from "lucide-vue-next";
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";

import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const router = useRouter();
const session = useSessionStore();
const workspace = useWorkspaceStore();

const sectionIcons = {
  dashboard: Activity,
  source_management: Radio,
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
    path: section.route_path
  }))
);

const primaryNavKeys = new Set([
  "dashboard",
  "source_management",
  "candidate_pool",
  "daily_reports",
  "weekly_reports",
  "historical_reports",
  "entity_milestones",
  "quality_archive",
  "requirements",
  "topic_tasks"
]);

const primaryNavItems = computed(() => navItems.value.filter((item) => primaryNavKeys.has(item.key)));
const systemNavItems = computed(() => navItems.value.filter((item) => !primaryNavKeys.has(item.key)));

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

        <div class="nav-group">
          <p class="nav-group-title">Menu</p>
          <RouterLink v-for="item in primaryNavItems" :key="item.key" class="nav-item" :to="item.path">
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </div>

        <div class="nav-group">
          <p class="nav-group-title">System</p>
          <RouterLink v-for="item in systemNavItems" :key="item.key" class="nav-item" :to="item.path">
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
        <div>
          <p class="eyebrow">产业情报操作系统</p>
          <h1>{{ workspace.current?.name || "工作台" }}</h1>
          <p class="topbar-subtitle">{{ workspace.error || workspace.current?.description || "正在加载工作台配置" }}</p>
        </div>

        <div class="topbar-tools">
          <label class="global-search" aria-label="搜索资源">
            <Search :size="16" />
            <input type="search" placeholder="搜索资源..." />
          </label>
          <button class="notification-button" type="button" title="通知">
            <Bell :size="19" />
            <span aria-hidden="true"></span>
          </button>
          <div class="user-chip">
            <span>{{ session.user?.display_name }}</span>
            <strong>{{ session.user?.roles[0] }}</strong>
          </div>
        </div>
      </header>

      <router-view />
    </main>
  </div>
</template>
