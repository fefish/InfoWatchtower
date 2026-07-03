<script setup lang="ts">
import { Ban, Copy, KeyRound, Plus, RefreshCw, Save, Trash2, UserPlus } from "lucide-vue-next";
import { computed, onMounted, reactive, ref, watch } from "vue";

import type { InviteRecord, SessionUser, UserRole } from "../api/auth";
import {
  createInvite,
  fetchInvites,
  fetchRoles,
  fetchUsers,
  patchUser,
  resetUserPassword,
  revokeInvite,
  updateUserRoles,
  type RoleRecord
} from "../api/identity";
import {
  fetchWorkspaceMembers,
  removeWorkspaceMember,
  upsertWorkspaceMember,
  type WorkspaceMemberRecord
} from "../api/workspaces";
import { useSessionStore } from "../stores/session";
import { useWorkspaceStore } from "../stores/workspace";

const session = useSessionStore();
const workspace = useWorkspaceStore();
const users = ref<SessionUser[]>([]);
const roles = ref<RoleRecord[]>([]);
const invites = ref<InviteRecord[]>([]);
const members = ref<WorkspaceMemberRecord[]>([]);
const selectedRoles = reactive<Record<string, Set<UserRole>>>({});
const activeTab = ref<"users" | "invites" | "members">("users");
const loading = ref(false);
const savingUserId = ref("");
const error = ref("");
const notice = ref("");
const temporaryPassword = ref("");
const savingMember = ref(false);
const inviteForm = reactive({
  email: "",
  role_code: "viewer" as UserRole,
  workspace_code: "",
  workspace_role: "member",
  expires_in_days: 7
});
const memberForm = reactive({
  user_id: "",
  workspace_role: "member"
});
const isSuperAdmin = computed(() => session.user?.roles.includes("super_admin") ?? false);
const memberUserOptions = computed(() =>
  users.value.filter((user) => !members.value.some((member) => member.user.id === user.id))
);

async function loadData() {
  loading.value = true;
  error.value = "";
  try {
    await workspace.loadWorkspaces();
    if (!isSuperAdmin.value && activeTab.value !== "members") {
      activeTab.value = "members";
    }
    const [nextUsers, nextRoles, nextInvites, nextMembers] = await Promise.all([
      fetchUsers(isSuperAdmin.value ? undefined : workspace.currentCode),
      isSuperAdmin.value ? fetchRoles() : Promise.resolve([]),
      isSuperAdmin.value ? fetchInvites() : Promise.resolve([]),
      fetchWorkspaceMembers(workspace.currentCode)
    ]);
    users.value = nextUsers;
    roles.value = nextRoles;
    invites.value = nextInvites;
    members.value = nextMembers;
    for (const user of nextUsers) {
      selectedRoles[user.id] = new Set(user.roles);
    }
    if (!memberUserOptions.value.some((user) => user.id === memberForm.user_id)) {
      memberForm.user_id = memberUserOptions.value[0]?.id ?? "";
    }
    if (!workspace.options.some((item) => item.code === inviteForm.workspace_code)) {
      inviteForm.workspace_code = workspace.currentCode;
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载用户权限失败";
  } finally {
    loading.value = false;
  }
}

async function loadWorkspaceMembers() {
  if (!workspace.currentCode) {
    members.value = [];
    return;
  }
  const [nextUsers, nextMembers] = await Promise.all([
    fetchUsers(isSuperAdmin.value ? undefined : workspace.currentCode),
    fetchWorkspaceMembers(workspace.currentCode)
  ]);
  users.value = nextUsers;
  members.value = nextMembers;
  if (!memberUserOptions.value.some((user) => user.id === memberForm.user_id)) {
    memberForm.user_id = memberUserOptions.value[0]?.id ?? "";
  }
}

function toggleRole(userId: string, role: UserRole, checked: boolean) {
  const current = selectedRoles[userId] ?? new Set<UserRole>();
  if (checked) {
    current.add(role);
  } else {
    current.delete(role);
  }
  selectedRoles[userId] = current;
}

async function saveUser(user: SessionUser) {
  savingUserId.value = user.id;
  error.value = "";
  try {
    const updated = await updateUserRoles(user.id, Array.from(selectedRoles[user.id] ?? []));
    users.value = users.value.map((item) => (item.id === updated.id ? updated : item));
    selectedRoles[updated.id] = new Set(updated.roles);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存角色失败";
  } finally {
    savingUserId.value = "";
  }
}

async function submitInvite() {
  error.value = "";
  notice.value = "";
  if (!inviteForm.workspace_code) {
    error.value = "请选择工作台";
    return;
  }
  try {
    const invite = await createInvite({
      email: inviteForm.email.trim() || undefined,
      role_code: inviteForm.role_code,
      workspaces: [{ code: inviteForm.workspace_code, workspace_role: inviteForm.workspace_role }],
      expires_in_days: Number(inviteForm.expires_in_days)
    });
    invites.value = [invite, ...invites.value];
    notice.value = invite.invite_url;
    await copyText(invite.invite_url);
    inviteForm.email = "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建邀请失败";
  }
}

async function revokeInviteRow(invite: InviteRecord) {
  error.value = "";
  try {
    const updated = await revokeInvite(invite.code);
    invites.value = invites.value.map((item) => (item.id === updated.id ? updated : item));
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "撤销邀请失败";
  }
}

async function resetPassword(user: SessionUser) {
  error.value = "";
  temporaryPassword.value = "";
  try {
    const result = await resetUserPassword(user.id);
    temporaryPassword.value = result.temporary_password;
    users.value = users.value.map((item) =>
      item.id === user.id ? { ...item, status: "must_change_password" } : item
    );
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "重置密码失败";
  }
}

async function toggleActive(user: SessionUser) {
  error.value = "";
  try {
    const updated = await patchUser(user.id, { is_active: !user.is_active });
    users.value = users.value.map((item) => (item.id === updated.id ? updated : item));
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "更新用户失败";
  }
}

async function submitMember() {
  if (!workspace.currentCode || !memberForm.user_id) {
    return;
  }
  savingMember.value = true;
  error.value = "";
  try {
    await upsertWorkspaceMember(workspace.currentCode, {
      user_id: memberForm.user_id,
      workspace_role: memberForm.workspace_role
    });
    await loadWorkspaceMembers();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "保存成员失败";
  } finally {
    savingMember.value = false;
  }
}

async function removeMember(member: WorkspaceMemberRecord) {
  if (!workspace.currentCode) {
    return;
  }
  savingMember.value = true;
  error.value = "";
  try {
    await removeWorkspaceMember(workspace.currentCode, member.user.id);
    await loadWorkspaceMembers();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "移除成员失败";
  } finally {
    savingMember.value = false;
  }
}

async function copyText(value: string) {
  try {
    await navigator.clipboard?.writeText(value);
  } catch {
    // Clipboard is optional in non-secure local contexts.
  }
}

watch(
  () => workspace.currentCode,
  () => {
    if (activeTab.value === "members") {
      void loadData();
    }
  }
);

onMounted(loadData);
</script>

<template>
  <section class="toolbar-band">
    <div>
      <p class="eyebrow">Identity</p>
      <h2>用户权限</h2>
      <p>公网账号和内网身份最终都落到本地用户，再由这里的角色决定权限。</p>
    </div>
    <div class="topbar-tools">
      <button type="button" class="icon-button" :disabled="loading" @click="loadData" title="刷新">
        <RefreshCw :size="18" />
        <span>刷新</span>
      </button>
    </div>
  </section>

  <div class="policy-tabs">
    <button v-if="isSuperAdmin" type="button" :class="{ active: activeTab === 'users' }" @click="activeTab = 'users'">用户</button>
    <button v-if="isSuperAdmin" type="button" :class="{ active: activeTab === 'invites' }" @click="activeTab = 'invites'">邀请</button>
    <button type="button" :class="{ active: activeTab === 'members' }" @click="activeTab = 'members'">工作台成员</button>
  </div>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="temporaryPassword" class="empty-state">临时密码：{{ temporaryPassword }}</p>
  <p v-if="notice" class="empty-state">邀请链接：{{ notice }}</p>

  <section v-if="activeTab === 'users'" class="data-table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th>用户</th>
          <th>身份来源</th>
          <th>部门</th>
          <th>状态</th>
          <th>角色</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="user in users" :key="user.id">
          <td>
            <strong>{{ user.display_name }}</strong>
            <span>{{ user.username }}</span>
          </td>
          <td>
            <strong>{{ user.external_provider }}</strong>
            <span>{{ user.employee_no || user.external_id }}</span>
          </td>
          <td>{{ user.department || "-" }}</td>
          <td>{{ user.status }}</td>
          <td>
            <div class="role-checks">
              <label v-for="role in roles" :key="role.code">
                <input
                  type="checkbox"
                  :checked="selectedRoles[user.id]?.has(role.code)"
                  @change="toggleRole(user.id, role.code, ($event.target as HTMLInputElement).checked)"
                />
                <span>{{ role.name }}</span>
              </label>
            </div>
          </td>
          <td>
            <button
              type="button"
              class="icon-button"
              :disabled="savingUserId === user.id"
              @click="saveUser(user)"
              title="保存角色"
            >
              <Save :size="16" />
              <span>{{ savingUserId === user.id ? "保存中" : "保存" }}</span>
            </button>
            <button type="button" class="icon-button secondary" @click="resetPassword(user)" title="重置密码">
              <KeyRound :size="16" />
              <span>重置</span>
            </button>
            <button type="button" class="icon-button secondary" @click="toggleActive(user)" title="启停用户">
              <Ban :size="16" />
              <span>{{ user.is_active ? "停用" : "启用" }}</span>
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && users.length === 0" class="empty-state">暂无用户，可通过邀请链接创建第一个协作者账号。</p>
  </section>

  <section v-else-if="activeTab === 'invites'" class="data-table-wrap">
    <form class="form-grid-two" @submit.prevent="submitInvite">
      <label>
        <span>邮箱</span>
        <input v-model="inviteForm.email" type="email" />
      </label>
      <label>
        <span>全局角色</span>
        <select v-model="inviteForm.role_code">
          <option v-for="role in roles" :key="role.code" :value="role.code">{{ role.name }}</option>
        </select>
      </label>
      <label>
        <span>工作台</span>
        <select v-model="inviteForm.workspace_code">
          <option v-for="item in workspace.options" :key="item.code" :value="item.code">{{ item.name }}</option>
        </select>
      </label>
      <label>
        <span>工作台角色</span>
        <select v-model="inviteForm.workspace_role">
          <option value="viewer">viewer</option>
          <option value="member">member</option>
          <option value="admin">admin</option>
          <option value="owner">owner</option>
        </select>
      </label>
      <label>
        <span>有效天数</span>
        <input v-model.number="inviteForm.expires_in_days" type="number" min="1" max="30" />
      </label>
      <button type="submit" class="icon-button">
        <Plus :size="16" />
        <span>创建邀请</span>
      </button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>邀请</th>
          <th>角色</th>
          <th>工作台</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="invite in invites" :key="invite.id">
          <td>
            <strong>{{ invite.email || invite.code }}</strong>
            <span>{{ invite.invite_url }}</span>
          </td>
          <td>{{ invite.role_code }}</td>
          <td>
            <span v-for="target in invite.workspaces" :key="target.code">
              {{ target.code }} · {{ target.workspace_role }}
            </span>
          </td>
          <td>{{ invite.status }}</td>
          <td>
            <button type="button" class="icon-button secondary" @click="copyText(invite.invite_url)" title="复制链接">
              <Copy :size="16" />
              <span>复制</span>
            </button>
            <button
              type="button"
              class="icon-button secondary"
              :disabled="invite.status !== 'pending'"
              @click="revokeInviteRow(invite)"
              title="撤销邀请"
            >
              <Ban :size="16" />
              <span>撤销</span>
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && invites.length === 0" class="empty-state">暂无邀请，选择角色和工作台后生成邀请链接。</p>
  </section>

  <section v-else class="data-table-wrap">
    <form class="form-grid-two" @submit.prevent="submitMember">
      <label>
        <span>工作台</span>
        <input :value="workspace.current?.name || workspace.currentCode" disabled />
      </label>
      <label>
        <span>用户</span>
        <select v-model="memberForm.user_id">
          <option v-for="user in memberUserOptions" :key="user.id" :value="user.id">
            {{ user.display_name }} · {{ user.username }}
          </option>
        </select>
      </label>
      <label>
        <span>工作台角色</span>
        <select v-model="memberForm.workspace_role">
          <option value="viewer">viewer</option>
          <option value="member">member</option>
          <option value="admin">admin</option>
          <option value="owner">owner</option>
        </select>
      </label>
      <button type="submit" class="icon-button" :disabled="savingMember || !memberForm.user_id">
        <UserPlus :size="16" />
        <span>加入工作台</span>
      </button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>成员</th>
          <th>全局角色</th>
          <th>工作台角色</th>
          <th>状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="member in members" :key="member.user.id">
          <td>
            <strong>{{ member.user.display_name }}</strong>
            <span>{{ member.user.username }}</span>
          </td>
          <td>{{ member.user.roles.join(", ") || "-" }}</td>
          <td>{{ member.workspace_role }}</td>
          <td>{{ member.user.status }}</td>
          <td>
            <button type="button" class="icon-button secondary" :disabled="savingMember" @click="removeMember(member)" title="移出工作台">
              <Trash2 :size="16" />
              <span>移出</span>
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && members.length === 0" class="empty-state">暂无成员，从上方选择用户并加入当前工作台。</p>
  </section>
</template>
