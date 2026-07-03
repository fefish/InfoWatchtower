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

async function loadInvite() {
  loading.value = true;
  error.value = "";
  try {
    invite.value = await fetchInvite(String(route.params.code));
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "邀请无效";
  } finally {
    loading.value = false;
  }
}

async function submitInvite() {
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
    error.value = exc instanceof Error ? exc.message : "接受邀请失败";
  } finally {
    loading.value = false;
  }
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
      <p v-if="invite && invite.status !== 'pending'" class="form-error">邀请状态：{{ invite.status }}</p>

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
