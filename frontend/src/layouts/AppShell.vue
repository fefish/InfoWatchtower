<script setup lang="ts">
import { Activity, CalendarDays, Database, FileText, Layers, LogOut, Radio, ShieldCheck, SquareStack, Users } from "lucide-vue-next";
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

      <nav class="nav-list" aria-label="主导航">
        <RouterLink v-for="item in navItems" :key="item.key" class="nav-item" :to="item.path">
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <button class="sidebar-action" type="button" @click="logout" aria-label="退出登录">
        <LogOut :size="18" />
      </button>
    </aside>

    <main class="main-panel">
      <header class="topbar">
        <div>
          <p class="eyebrow">产业情报操作系统</p>
          <h1>{{ workspace.current?.name || "工作台" }}</h1>
          <p class="topbar-subtitle">{{ workspace.error || workspace.current?.description || "正在加载工作台配置" }}</p>
        </div>
        <div class="user-chip">
          <span>{{ session.user?.display_name }}</span>
          <strong>{{ session.user?.roles[0] }}</strong>
        </div>
      </header>

      <router-view />
    </main>
  </div>
</template>
