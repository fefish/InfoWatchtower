<script setup lang="ts">
import { LogIn } from "lucide-vue-next";
import { useRouter } from "vue-router";

import { useSessionStore } from "../stores/session";

const router = useRouter();
const session = useSessionStore();

function login() {
  session.setDemoUser();
  router.push("/dashboard");
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div>
        <p class="eyebrow">InfoWatchtower</p>
        <h1>登录工作台</h1>
      </div>

      <form class="login-form" @submit.prevent="login">
        <label>
          <span>账号</span>
          <input autocomplete="username" value="admin" />
        </label>
        <label>
          <span>密码</span>
          <input autocomplete="current-password" type="password" value="password" />
        </label>
        <button type="submit">
          <LogIn :size="18" />
          <span>进入</span>
        </button>
      </form>
    </section>
  </main>
</template>
