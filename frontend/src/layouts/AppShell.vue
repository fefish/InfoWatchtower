<script setup lang="ts">
import {
  Activity,
  Database,
  FileText,
  Layers,
  LogOut,
  Radio,
  ShieldCheck,
  Users
} from "lucide-vue-next";
import { useRouter } from "vue-router";

import { useSessionStore } from "../stores/session";

const router = useRouter();
const session = useSessionStore();

if (!session.user) {
  session.setDemoUser();
}

const navItems = [
  { label: "工作台", icon: Activity, path: "/dashboard" },
  { label: "数据源", icon: Radio, path: "/sources" },
  { label: "候选新闻", icon: Layers, path: "/news" },
  { label: "日报", icon: FileText, path: "/daily-reports" },
  { label: "SQL导出", icon: Database, path: "/exports" },
  { label: "用户权限", icon: Users, path: "/users" },
  { label: "审计", icon: ShieldCheck, path: "/audit-logs" }
];

function logout() {
  session.clear();
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
          <h1>规划部情报工作台</h1>
        </div>
        <div class="user-chip">
          <span>{{ session.user?.displayName }}</span>
          <strong>{{ session.user?.roles[0] }}</strong>
        </div>
      </header>

      <router-view />
    </main>
  </div>
</template>
