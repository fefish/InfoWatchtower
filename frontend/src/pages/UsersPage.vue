<script setup lang="ts">
import { RefreshCw, Save } from "lucide-vue-next";
import { onMounted, reactive, ref } from "vue";

import { fetchRoles, fetchUsers, updateUserRoles, type RoleRecord } from "../api/identity";
import type { SessionUser, UserRole } from "../api/auth";

const users = ref<SessionUser[]>([]);
const roles = ref<RoleRecord[]>([]);
const selectedRoles = reactive<Record<string, Set<UserRole>>>({});
const loading = ref(false);
const savingUserId = ref("");
const error = ref("");

async function loadData() {
  loading.value = true;
  error.value = "";
  try {
    const [nextUsers, nextRoles] = await Promise.all([fetchUsers(), fetchRoles()]);
    users.value = nextUsers;
    roles.value = nextRoles;
    for (const user of nextUsers) {
      selectedRoles[user.id] = new Set(user.roles);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载用户权限失败";
  } finally {
    loading.value = false;
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

onMounted(loadData);
</script>

<template>
  <section class="toolbar-band">
    <div>
      <p class="eyebrow">阶段 2</p>
      <h2>用户权限</h2>
      <p>公网账号和内网身份最终都落到本地用户，再由这里的角色决定权限。</p>
    </div>
    <button type="button" class="icon-button" :disabled="loading" @click="loadData" title="刷新">
      <RefreshCw :size="18" />
      <span>刷新</span>
    </button>
  </section>

  <p v-if="error" class="form-error">{{ error }}</p>

  <section class="data-table-wrap">
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
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="!loading && users.length === 0" class="empty-state">暂无用户</p>
  </section>
</template>
