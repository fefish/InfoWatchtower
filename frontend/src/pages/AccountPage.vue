<script setup lang="ts">
import { KeyRound, Save } from "lucide-vue-next";
import { reactive, ref } from "vue";
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

async function submitPassword() {
  error.value = "";
  message.value = "";
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
</script>

<template>
  <section class="toolbar-band">
    <div>
      <p class="eyebrow">Account</p>
      <h2>账号</h2>
      <p>{{ session.user?.display_name }} · {{ session.user?.username }}</p>
    </div>
    <KeyRound :size="22" />
  </section>

  <section class="data-table-wrap">
    <form class="form-grid-two" @submit.prevent="submitPassword">
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
      <p v-if="message" class="empty-state">{{ message }}</p>
      <button type="submit" class="icon-button" :disabled="session.loading">
        <Save :size="16" />
        <span>{{ session.loading ? "保存中" : "保存" }}</span>
      </button>
    </form>
  </section>
</template>
