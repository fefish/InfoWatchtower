<script setup lang="ts">
import { Activity, CalendarDays, Database, FileText, Layers, LogOut, Radio, ShieldCheck, SquareStack, Users } from "lucide-vue-next";
import { computed } from "vue";
import { useRouter } from "vue-router";

import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const router = useRouter();
const session = useSessionStore();
const workspace = useWorkspaceStore();

const coreNavItems = [
  { label: "工作台", icon: Activity, path: "/dashboard" },
  { label: "数据源", icon: Radio, path: "/sources" },
  { label: "候选池", icon: Layers, path: "/news" },
  { label: "日报", icon: FileText, path: "/daily-reports" },
  { label: "周报", icon: CalendarDays, path: "/weekly-reports" },
  { label: "热点专题", icon: SquareStack, path: "/topics" },
  { label: "SQL导出", icon: Database, path: "/exports" },
  { label: "用户权限", icon: Users, path: "/users" },
  { label: "审计", icon: ShieldCheck, path: "/audit-logs" }
];

const toolNavItems = [
  { label: "工具目录", icon: SquareStack, path: "/tools" },
  { label: "工具任务", icon: Layers, path: "/tool-runs" }
];

const navItems = computed(() => {
  const extraItems = (workspace.current?.extraModules ?? []).includes("tools") ? toolNavItems : [];
  return [...coreNavItems, ...extraItems];
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
        <RouterLink v-for="item in navItems" :key="item.label" class="nav-item" :to="item.path">
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
          <h1>{{ workspace.current?.name }}</h1>
          <p class="topbar-subtitle">{{ workspace.current?.description }}</p>
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
