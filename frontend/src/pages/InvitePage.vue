<script setup lang="ts">
import { LogIn, UserPlus } from "lucide-vue-next";
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { acceptInvite, fetchInvite, type InvitePublicRecord } from "../api/auth";
import { useSessionStore } from "../stores/session";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const invite = ref<InvitePublicRecord | null>(null);
const loading = ref(false);
const error = ref("");
const form = reactive({
  username: "",
  display_name: "",
  password: "",
  confirmPassword: ""
});
const statusLabels: Record<string, string> = {
  pending: "待接受",
  accepted: "已接受",
  revoked: "已撤销",
  expired: "已过期"
};
const statusHints: Record<string, string> = {
  accepted: "这条邀请已经被使用。请直接登录，或联系管理员重新发放邀请。",
  revoked: "管理员已经撤销这条邀请。请联系管理员确认是否需要重新邀请。",
  expired: "这条邀请已经超过有效期。请联系管理员重新生成邀请链接。"
};

async function loadInvite() {
  loading.value = true;
  error.value = "";
  try {
    invite.value = await fetchInvite(String(route.params.code));
  } catch (exc) {
    invite.value = null;
    error.value = friendlyInviteError(exc);
  } finally {
    loading.value = false;
  }
}

async function submitInvite() {
  if (!form.username.trim()) {
    error.value = "请填写账号";
    return;
  }
  if (!form.display_name.trim()) {
    error.value = "请填写姓名";
    return;
  }
  if (form.password.length < 8) {
    error.value = "密码至少 8 位";
    return;
  }
  if (form.password !== form.confirmPassword) {
    error.value = "两次输入的密码不一致";
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const response = await acceptInvite(String(route.params.code), {
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password
    });
    session.user = response.user;
    session.checked = true;
    router.replace("/dashboard");
  } catch (exc) {
    error.value = friendlyInviteError(exc);
  } finally {
    loading.value = false;
  }
}

function inviteStatusLabel(status: string) {
  return statusLabels[status] ?? status;
}

function inviteStatusHint(status: string) {
  return statusHints[status] ?? "这条邀请当前不可接受，请联系管理员确认状态。";
}

function friendlyInviteError(exc: unknown) {
  const detail = exc instanceof Error ? exc.message : "";
  if (detail.includes("Invite not found")) {
    return "邀请不存在或链接已失效";
  }
  if (detail.includes("Invite is revoked")) {
    return inviteStatusHint("revoked");
  }
  if (detail.includes("Invite is expired")) {
    return inviteStatusHint("expired");
  }
  if (detail.includes("Invite is accepted")) {
    return inviteStatusHint("accepted");
  }
  if (detail.includes("Username already exists")) {
    return "账号已存在，请换一个账号或联系管理员。";
  }
  if (detail.includes("HTTP 422")) {
    return "请检查账号、姓名和密码是否符合要求。";
  }
  return detail || "接受邀请失败";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

onMounted(loadInvite);
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div>
        <p class="eyebrow">InfoWatchtower</p>
        <h1>接受邀请</h1>
      </div>

      <p v-if="error" class="form-error">{{ error }}</p>
      <p v-if="loading && !invite" class="empty-state compact">正在读取邀请...</p>

      <section v-if="invite" class="invite-summary">
        <span class="metric-pill">{{ inviteStatusLabel(invite.status) }}</span>
        <p v-if="invite.email_hint">邀请邮箱：{{ invite.email_hint }}</p>
        <p>全局角色：{{ invite.role_code }}</p>
        <p>有效期至：{{ formatDate(invite.expires_at) }}</p>
        <div v-if="invite.workspaces.length" class="invite-targets">
          <span v-for="target in invite.workspaces" :key="`${target.code}-${target.workspace_role}`">
            {{ target.code }} · {{ target.workspace_role }}
          </span>
        </div>
      </section>

      <p v-if="invite && invite.status !== 'pending'" class="form-info">
        {{ inviteStatusHint(invite.status) }}
      </p>

      <form v-if="invite?.status === 'pending'" class="login-form" @submit.prevent="submitInvite">
        <label>
          <span>账号</span>
          <input v-model="form.username" autocomplete="username" />
        </label>
        <label>
          <span>姓名</span>
          <input v-model="form.display_name" autocomplete="name" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="form.password" autocomplete="new-password" type="password" />
        </label>
        <label>
          <span>确认密码</span>
          <input v-model="form.confirmPassword" autocomplete="new-password" type="password" />
        </label>
        <button type="submit" :disabled="loading">
          <UserPlus :size="18" />
          <span>{{ loading ? "提交中" : "创建账号" }}</span>
        </button>
      </form>

      <RouterLink class="icon-button secondary" to="/login">
        <LogIn :size="16" />
        <span>登录</span>
      </RouterLink>
    </section>
  </main>
</template>
