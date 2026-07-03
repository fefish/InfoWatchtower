<script setup lang="ts">
import { KeyRound, LogIn } from "lucide-vue-next";
import { ref } from "vue";
import { useRouter } from "vue-router";

import { forgotPassword } from "../api/auth";
import { useSessionStore } from "../stores/session";

const router = useRouter();
const session = useSessionStore();
const username = ref("admin");
const password = ref("password");
const error = ref("");
const notice = ref("");

async function submitLogin() {
  error.value = "";
  notice.value = "";
  try {
    await session.login(username.value, password.value);
    router.push("/dashboard");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登录失败";
  }
}

async function submitForgot() {
  error.value = "";
  notice.value = "";
  try {
    await forgotPassword(username.value || "unknown");
    notice.value = "已提交";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "提交失败";
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div>
        <p class="eyebrow">InfoWatchtower</p>
        <h1>登录工作台</h1>
      </div>

      <form class="login-form" @submit.prevent="submitLogin">
        <label>
          <span>账号</span>
          <input v-model="username" autocomplete="username" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" autocomplete="current-password" type="password" />
        </label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <p v-if="notice" class="empty-state">{{ notice }}</p>
        <button type="submit" :disabled="session.loading">
          <LogIn :size="18" />
          <span>{{ session.loading ? "登录中" : "进入" }}</span>
        </button>
        <button type="button" class="icon-button secondary" @click="submitForgot">
          <KeyRound :size="16" />
          <span>忘记密码</span>
        </button>
      </form>
    </section>
  </main>
</template>
