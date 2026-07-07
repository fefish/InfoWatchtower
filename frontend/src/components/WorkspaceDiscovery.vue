<script setup lang="ts">
// 「发现工作台」居中 Modal（产品设计 §10.3 迁移清单 + §12，md 档）：
// - 列出 visibility=internal_public 的工作台，支持自助订阅/退订；
// - 顶部搜索框走 GET /api/workspaces/discover?q=（去抖，仍只返回 internal_public）；
// - 底部「凭码加入」调 POST /api/workspaces/join-by-code——失效码后端统一 400
//   「加入码无效或已失效」（防枚举），前端原样透传不改写、不区分原因。
// 游客会话隐藏订阅与凭码加入（后端中央写门禁同样 403 拦截）。
import { Compass, KeyRound, Search, UserPlus, UserMinus } from "lucide-vue-next";
import { onBeforeUnmount, ref } from "vue";

import {
  fetchDiscoverableWorkspaces,
  joinWorkspaceByCode,
  subscribeWorkspace,
  unsubscribeWorkspace,
  type DiscoverableWorkspaceRecord
} from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";
import AppModal from "./AppModal.vue";

const SEARCH_DEBOUNCE_MS = 300;

const session = useSessionStore();
const workspace = useWorkspaceStore();

const modalOpen = ref(false);
const loading = ref(false);
const errorMessage = ref("");
const items = ref<DiscoverableWorkspaceRecord[]>([]);
const pendingCode = ref("");
const searchQuery = ref("");
let searchTimer: ReturnType<typeof setTimeout> | null = null;

const joinCodeDraft = ref("");
const joiningByCode = ref(false);
const joinByCodeError = ref("");
const joinByCodeMessage = ref("");

async function openModal() {
  modalOpen.value = true;
  await loadDiscoverableWorkspaces();
}

function closeModal() {
  modalOpen.value = false;
}

async function loadDiscoverableWorkspaces() {
  loading.value = true;
  errorMessage.value = "";
  try {
    items.value = await fetchDiscoverableWorkspaces(searchQuery.value);
  } catch (exc) {
    errorMessage.value = exc instanceof Error ? exc.message : "加载可订阅工作台失败";
    items.value = [];
  } finally {
    loading.value = false;
  }
}

// 输入去抖后请求（产品设计 §12.1）；回车立即搜索。
function onSearchInput() {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
  searchTimer = setTimeout(() => {
    searchTimer = null;
    void loadDiscoverableWorkspaces();
  }, SEARCH_DEBOUNCE_MS);
}

function onSearchSubmit() {
  if (searchTimer) {
    clearTimeout(searchTimer);
    searchTimer = null;
  }
  void loadDiscoverableWorkspaces();
}

onBeforeUnmount(() => {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
});

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

async function submitJoinByCode() {
  const code = joinCodeDraft.value.trim();
  joinByCodeError.value = "";
  joinByCodeMessage.value = "";
  if (!code) {
    joinByCodeError.value = "请输入加入码";
    return;
  }
  joiningByCode.value = true;
  try {
    const result = await joinWorkspaceByCode(code);
    joinByCodeMessage.value = result.joined
      ? `已加入「${result.workspace_name}」（角色 ${result.workspace_role}）`
      : `你已是「${result.workspace_name}」成员（保持原角色 ${result.workspace_role}）`;
    joinCodeDraft.value = "";
    await workspace.loadWorkspaces();
    await loadDiscoverableWorkspaces();
  } catch (exc) {
    // 后端统一失效文案「加入码无效或已失效」/ 429 限流信息：原样展示，不区分原因
    joinByCodeError.value = exc instanceof Error ? exc.message : "凭码加入失败";
  } finally {
    joiningByCode.value = false;
  }
}
</script>

<template>
  <button
    type="button"
    class="workspace-discovery-button"
    title="发现可订阅的工作台"
    @click="openModal"
  >
    <Compass :size="14" />
    <span>发现工作台</span>
  </button>

  <AppModal :open="modalOpen" title="发现工作台" size="md" @close="closeModal">
    <template #header-meta>
      <p class="eyebrow">工作台订阅</p>
    </template>

    <p class="workspace-form-hint">
      这里列出组织内公开（internal_public）的工作台。订阅后你将以 viewer 身份加入，
      可以阅读其日报、周报等已发布内容；随时可退订。
    </p>
    <p v-if="session.isGuest" class="workspace-form-hint workspace-discovery-guest-hint">
      当前为游客身份：可直接浏览公开工作台的已发布内容，注册账号后才能订阅或凭码加入。
    </p>

    <div class="workspace-discovery-search">
      <Search :size="15" aria-hidden="true" />
      <input
        v-model="searchQuery"
        type="search"
        placeholder="按名称或描述搜索公开工作台"
        aria-label="搜索公开工作台"
        @input="onSearchInput"
        @keydown.enter.prevent="onSearchSubmit"
      />
    </div>

    <p v-if="errorMessage" class="form-error">{{ errorMessage }}</p>
    <p v-if="loading" class="empty-state">加载中</p>
    <p v-else-if="items.length === 0 && !errorMessage && searchQuery.trim()" class="empty-state">
      没有匹配的公开工作台，若你有工作台加入码可在下方凭码加入。
    </p>
    <p v-else-if="items.length === 0 && !errorMessage" class="empty-state">暂时没有可订阅的公开工作台。</p>

    <ul v-else-if="items.length > 0" class="workspace-discovery-list">
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

    <!-- 凭码加入（产品设计 §12.2）：private 工作台不出现在上方列表，
         已注册用户凭管理员发的加入码在这里自助入台。 -->
    <section
      v-if="!session.isGuest"
      class="workspace-discovery-joincode"
      aria-label="凭码加入"
    >
      <div class="label-section-title">
        <span><KeyRound :size="14" aria-hidden="true" /> 凭码加入</span>
        <small>拿到工作台加入码（8 位大写字母+数字）后在此输入，私有工作台也可加入</small>
      </div>
      <div class="workspace-discovery-joincode-line">
        <input
          v-model="joinCodeDraft"
          maxlength="16"
          placeholder="例如 7F2KQ9XN"
          aria-label="工作台加入码"
          @keydown.enter.prevent="submitJoinByCode"
        />
        <button
          type="button"
          class="icon-button"
          :disabled="joiningByCode"
          @click="submitJoinByCode"
        >
          {{ joiningByCode ? "加入中" : "凭码加入" }}
        </button>
      </div>
      <p v-if="joinByCodeError" class="form-error">{{ joinByCodeError }}</p>
      <p v-else-if="joinByCodeMessage" class="form-success">{{ joinByCodeMessage }}</p>
    </section>
  </AppModal>
</template>

<style scoped>
/* 发现工作台 Modal 内部排布（表面材质由 AppModal + base.css 承担） */
.workspace-discovery-search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 12px;
}

.workspace-discovery-search input {
  flex: 1;
  min-width: 0;
}

.workspace-discovery-joincode {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid rgba(100, 116, 139, 0.18);
}

.workspace-discovery-joincode-line {
  display: flex;
  gap: 8px;
  align-items: center;
}

.workspace-discovery-joincode-line input {
  flex: 1;
  min-width: 0;
  text-transform: uppercase;
  letter-spacing: 0.12em;
}
</style>
