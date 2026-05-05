<script setup lang="ts">
import { LogIn } from "lucide-vue-next";
import { ref } from "vue";
import { useRouter } from "vue-router";

import { useSessionStore } from "../stores/session";

const router = useRouter();
const session = useSessionStore();
const username = ref("admin");
const password = ref("password");
const error = ref("");

async function submitLogin() {
  error.value = "";
  try {
    await session.login(username.value, password.value);
    router.push("/dashboard");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登录失败";
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
        <button type="submit" :disabled="session.loading">
          <LogIn :size="18" />
          <span>{{ session.loading ? "登录中" : "进入" }}</span>
        </button>
      </form>
    </section>
  </main>
</template>
