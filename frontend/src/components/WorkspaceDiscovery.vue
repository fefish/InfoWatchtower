<script setup lang="ts">
// 「发现工作台」抽屉：列出 visibility=internal_public 的工作台，支持自助订阅/退订。
// 独立组件由 AppShell 挂一行（工作台切换器底部入口），把与建台向导等 AppShell
// 其余区块的改动冲突面压到最小。游客会话隐藏订阅按钮（后端也会 403 拦截）。
import { Compass, UserPlus, UserMinus, X } from "lucide-vue-next";
import { ref } from "vue";

import {
  fetchDiscoverableWorkspaces,
  subscribeWorkspace,
  unsubscribeWorkspace,
  type DiscoverableWorkspaceRecord
} from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const session = useSessionStore();
const workspace = useWorkspaceStore();

const drawerOpen = ref(false);
const loading = ref(false);
const errorMessage = ref("");
const items = ref<DiscoverableWorkspaceRecord[]>([]);
const pendingCode = ref("");

async function openDrawer() {
  drawerOpen.value = true;
  await loadDiscoverableWorkspaces();
}

function closeDrawer() {
  drawerOpen.value = false;
}

async function loadDiscoverableWorkspaces() {
  loading.value = true;
  errorMessage.value = "";
  try {
    items.value = await fetchDiscoverableWorkspaces();
  } catch (exc) {
    errorMessage.value = exc instanceof Error ? exc.message : "加载可订阅工作台失败";
    items.value = [];
  } finally {
    loading.value = false;
  }
}

function canUnsubscribe(item: DiscoverableWorkspaceRecord) {
  // 只有 viewer membership 可自助退订；更高角色由管理员在成员管理里维护。
  return item.joined && item.workspace_role === "viewer";
}

async function subscribe(item: DiscoverableWorkspaceRecord) {
  pendingCode.value = item.code;
  errorMessage.value = "";
  try {
    await subscribeWorkspace(item.code);
    await workspace.loadWorkspaces();
    await loadDiscoverableWorkspaces();
  } catch (exc) {
    errorMessage.value = exc instanceof Error ? exc.message : "订阅失败";
  } finally {
    pendingCode.value = "";
  }
}

async function unsubscribe(item: DiscoverableWorkspaceRecord) {
  pendingCode.value = item.code;
  errorMessage.value = "";
  try {
    await unsubscribeWorkspace(item.code);
    await workspace.loadWorkspaces();
    await loadDiscoverableWorkspaces();
  } catch (exc) {
    errorMessage.value = exc instanceof Error ? exc.message : "退订失败";
  } finally {
    pendingCode.value = "";
  }
}
</script>

<template>
  <button
    type="button"
    class="workspace-discovery-button"
    title="发现可订阅的工作台"
    @click="openDrawer"
  >
    <Compass :size="14" />
    <span>发现工作台</span>
  </button>

  <div v-if="drawerOpen" class="config-backdrop" @click="closeDrawer"></div>
  <aside v-if="drawerOpen" class="config-panel workspace-discovery-panel" aria-label="发现工作台">
    <header>
      <div>
        <p class="eyebrow">工作台订阅</p>
        <h3>发现工作台</h3>
      </div>
      <button type="button" class="panel-close" @click="closeDrawer" title="关闭">
        <X :size="18" />
      </button>
    </header>

    <p class="workspace-form-hint">
      这里列出组织内公开（internal_public）的工作台。订阅后你将以 viewer 身份加入，
      可以阅读其日报、周报等已发布内容；随时可退订。
    </p>
    <p v-if="session.isGuest" class="workspace-form-hint workspace-discovery-guest-hint">
      当前为游客身份：可直接浏览公开工作台的已发布内容，注册账号后才能订阅。
    </p>

    <p v-if="errorMessage" class="form-error">{{ errorMessage }}</p>
    <p v-if="loading" class="empty-state">加载中</p>
    <p v-else-if="items.length === 0 && !errorMessage" class="empty-state">暂时没有可订阅的公开工作台。</p>

    <ul v-else class="workspace-discovery-list">
      <li v-for="item in items" :key="item.code" class="workspace-discovery-row">
        <div class="workspace-discovery-meta">
          <strong>{{ item.name }}</strong>
          <small>{{ item.description || item.code }}</small>
          <small>{{ item.member_count }} 名成员</small>
        </div>
        <span v-if="item.joined" class="workspace-discovery-joined">已加入</span>
        <template v-if="!session.isGuest">
          <button
            v-if="!item.joined"
            type="button"
            class="icon-button"
            :disabled="pendingCode === item.code"
            @click="subscribe(item)"
          >
            <UserPlus :size="14" />
            <span>{{ pendingCode === item.code ? "订阅中" : "订阅" }}</span>
          </button>
          <button
            v-else-if="canUnsubscribe(item)"
            type="button"
            class="icon-button secondary"
            :disabled="pendingCode === item.code"
            @click="unsubscribe(item)"
          >
            <UserMinus :size="14" />
            <span>{{ pendingCode === item.code ? "退订中" : "退订" }}</span>
          </button>
          <small v-else class="workspace-discovery-managed">{{ item.workspace_role }} · 由管理员管理</small>
        </template>
      </li>
    </ul>
  </aside>
</template>
