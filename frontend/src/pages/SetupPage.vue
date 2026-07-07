<script setup lang="ts">
import { CheckCircle2, Database, KeyRound, UserPlus } from "lucide-vue-next";
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { importLegacySources, importTechInsightLoopSources } from "../api/sources";
import { createSetupAdmin } from "../api/setup";
import { useSessionStore } from "../stores/session";
import { useSetupStore } from "../stores/setup";

const router = useRouter();
const session = useSessionStore();
const setup = useSetupStore();
const loading = ref(false);
const importing = ref(false);
const error = ref("");
const notice = ref("");
const form = reactive({
  username: "admin",
  display_name: "系统管理员",
  password: "",
  confirmPassword: "",
  importLegacy: false,
  importTechLoop: false
});

async function submitSetup() {
  error.value = "";
  notice.value = "";
  if (form.password.length < 10) {
    error.value = "密码至少 10 位";
    return;
  }
  if (form.password !== form.confirmPassword) {
    error.value = "两次输入的密码不一致";
    return;
  }

  loading.value = true;
  try {
    const response = await createSetupAdmin({
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password
    });
    session.user = response.user;
    session.checked = true;
    setup.markComplete();
    notice.value = "管理员已创建";
    await runOptionalImports();
    router.replace("/dashboard");
  } catch (exc) {
    error.value = setupErrorMessage(exc);
  } finally {
    loading.value = false;
  }
}

async function runOptionalImports() {
  const jobs = [];
  if (form.importLegacy) {
    jobs.push(importLegacySources());
  }
  if (form.importTechLoop) {
    jobs.push(importTechInsightLoopSources());
  }
  if (!jobs.length) {
    return;
  }
  importing.value = true;
  try {
    await Promise.all(jobs);
    notice.value = "管理员已创建，种子源已导入";
  } finally {
    importing.value = false;
  }
}

function setupErrorMessage(exc: unknown) {
  if (!(exc instanceof Error)) {
    return "初始化失败";
  }
  if (exc.message.includes("Setup already completed") || exc.message.includes("410")) {
    return "首次设置已完成，请返回登录页。";
  }
  return exc.message;
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel setup-panel">
      <div>
        <p class="eyebrow">InfoWatchtower</p>
        <h1>首次运行设置</h1>
      </div>

      <p v-if="error" class="form-error">{{ error }}</p>
      <p v-if="notice" class="empty-state">{{ notice }}</p>

      <form class="login-form" @submit.prevent="submitSetup">
        <label>
          <span>管理员账号</span>
          <input v-model="form.username" autocomplete="username" />
        </label>
        <label>
          <span>显示名称</span>
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

        <label class="setup-option">
          <input v-model="form.importLegacy" type="checkbox" />
          <Database :size="16" />
          <span>导入内置 legacy 种子源</span>
        </label>
        <label class="setup-option">
          <input v-model="form.importTechLoop" type="checkbox" />
          <CheckCircle2 :size="16" />
          <span>导入 Tech Insight Loop 源治理记录</span>
        </label>

        <button type="submit" :disabled="loading || importing">
          <UserPlus :size="18" />
          <span>{{ loading || importing ? "初始化中" : "创建管理员" }}</span>
        </button>
        <div class="setup-note">
          <KeyRound :size="16" />
          <span>创建后可在用户页邀请同事，并在数据源页配置源和标签策略。</span>
        </div>
      </form>
    </section>
  </main>
</template>
