<script setup lang="ts">
import { Save } from "lucide-vue-next";
import { computed, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { useSessionStore } from "../stores/session";

const router = useRouter();
const session = useSessionStore();
const form = reactive({
  currentPassword: "",
  newPassword: "",
  confirmPassword: ""
});
const message = ref("");
const error = ref("");
const canChangeLocalPassword = computed(() => session.user?.external_provider === "local");
const providerLabel = computed(() => {
  const provider = session.user?.external_provider || "";
  if (provider === "local") {
    return "本地账号";
  }
  if (provider === "intranet_header") {
    return "内网门户身份";
  }
  if (provider.includes("oidc")) {
    return "单点登录账号";
  }
  return provider || "外部身份";
});

async function submitPassword() {
  error.value = "";
  message.value = "";
  if (!canChangeLocalPassword.value) {
    error.value = "当前账号由外部身份系统管理，不能在本系统修改密码。";
    return;
  }
  if (form.newPassword.length < 8) {
    error.value = "新密码至少 8 位";
    return;
  }
  if (form.newPassword !== form.confirmPassword) {
    error.value = "两次输入的新密码不一致";
    return;
  }
  try {
    await session.changePassword(form.currentPassword, form.newPassword);
    form.currentPassword = "";
    form.newPassword = "";
    form.confirmPassword = "";
    message.value = "密码已更新";
    if (session.user?.status === "active") {
      router.replace("/dashboard");
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "修改密码失败";
  }
}

async function signOut() {
  await session.logout();
  router.replace("/login");
}
</script>

<template>
  <section class="toolbar-band">
    <div>
      <p class="eyebrow">Account</p>
      <h2>账号</h2>
      <p>{{ session.user?.display_name }} · {{ session.user?.username }} · {{ providerLabel }}</p>
    </div>
    <button class="ghost-button" type="button" @click="signOut">退出登录</button>
  </section>

  <section class="data-table-wrap account-profile-card">
    <div class="profile-summary-grid">
      <article>
        <span>姓名</span>
        <strong>{{ session.user?.display_name || "未命名用户" }}</strong>
      </article>
      <article>
        <span>账号</span>
        <strong>{{ session.user?.username || session.user?.external_id }}</strong>
      </article>
      <article>
        <span>部门</span>
        <strong>{{ session.user?.department || "未设置" }}</strong>
      </article>
      <article>
        <span>角色</span>
        <strong>{{ session.user?.roles.join(", ") || "无角色" }}</strong>
      </article>
    </div>
    <p v-if="!canChangeLocalPassword" class="form-info">
      当前账号来自 {{ providerLabel }}，密码、MFA 和会话策略由外部身份系统管理；本系统只使用映射后的用户、角色和工作台权限。
    </p>
  </section>

  <section v-if="canChangeLocalPassword" class="data-table-wrap">
    <form class="form-grid-two ops-form account-password-form" @submit.prevent="submitPassword">
      <label>
        <span>当前密码</span>
        <input v-model="form.currentPassword" type="password" autocomplete="current-password" />
      </label>
      <label>
        <span>新密码</span>
        <input v-model="form.newPassword" type="password" autocomplete="new-password" />
      </label>
      <label>
        <span>确认新密码</span>
        <input v-model="form.confirmPassword" type="password" autocomplete="new-password" />
      </label>
      <p v-if="error" class="form-error">{{ error }}</p>
      <p v-if="message" class="form-success">{{ message }}</p>
      <button type="submit" class="icon-button" :disabled="session.loading">
        <Save :size="16" />
        <span>{{ session.loading ? "保存中" : "保存" }}</span>
      </button>
    </form>
  </section>
</template>
