<script setup lang="ts">
import { Eye, KeyRound, LogIn, ShieldCheck } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { forgotPassword, startOidcLogin } from "../api/auth";
import { useRuntimeStore } from "../stores/runtime";
import { useSessionStore } from "../stores/session";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const runtime = useRuntimeStore();
const username = ref("admin");
const password = ref("password");
const error = ref("");
const notice = ref("");
const authErrorMessages: Record<string, string> = {
  identity_resolution_failed: "单点登录身份信息不完整，请联系管理员检查 SSO claims 映射。",
  membership_mapping_failed: "单点登录已返回身份，但工作台权限映射失败，请联系管理员。",
  oidc_not_configured: "单点登录服务尚未配置完成，请联系管理员检查 OIDC 设置。",
  provider_error: "单点登录服务返回错误，请重试或联系管理员。",
  state_mismatch: "单点登录状态已失效，请重新发起登录。",
  state_missing: "单点登录状态缺失，请重新发起登录。",
  token_exchange_failed: "单点登录凭证交换失败，请重试或联系管理员。"
};
const passwordLoginEnabled = computed(() => ["local", "public_password", ""].includes(runtime.authMode));
// 游客登录（AUTH_GUEST_ENABLED，仅 standalone/cloud 形态可开）：共享只读会话。
const guestLoginEnabled = computed(() => runtime.authGuestEnabled);
const oidcLoginEnabled = computed(() => runtime.authMode === "oidc");
const intranetHeaderEnabled = computed(() => runtime.authMode === "intranet_header");
const unsupportedAuthMode = computed(
  () => !passwordLoginEnabled.value && !oidcLoginEnabled.value && !intranetHeaderEnabled.value
);
const authErrorMessage = computed(() => {
  const raw = route.query.auth_error;
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (!value || typeof value !== "string") {
    return "";
  }
  return authErrorMessages[value] ?? "登录过程出现异常，请重试或联系管理员。";
});

onMounted(() => {
  void runtime.load();
});

async function submitLogin() {
  if (!passwordLoginEnabled.value) {
    return;
  }
  error.value = "";
  notice.value = "";
  try {
    await session.login(username.value, password.value);
    router.push(postLoginTarget());
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "登录失败";
  }
}

function submitOidcLogin() {
  error.value = "";
  notice.value = "";
  startOidcLogin(redirectTarget());
}

async function submitGuestLogin() {
  if (!guestLoginEnabled.value) {
    return;
  }
  error.value = "";
  notice.value = "";
  try {
    await session.guestLogin();
    router.push(postLoginTarget());
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "游客登录失败";
  }
}

function postLoginTarget() {
  if (session.user?.status === "must_change_password") {
    return "/account";
  }
  return redirectTarget();
}

function redirectTarget() {
  const raw = route.query.redirect;
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value === "string" && value.startsWith("/") && !value.startsWith("//")) {
    return value;
  }
  return "/dashboard";
}

async function submitForgot() {
  if (!passwordLoginEnabled.value) {
    return;
  }
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
      <p v-if="authErrorMessage" class="form-error">{{ authErrorMessage }}</p>

      <form v-if="passwordLoginEnabled" class="login-form" @submit.prevent="submitLogin">
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

      <div v-else-if="oidcLoginEnabled" class="login-action-stack">
        <button type="button" class="icon-button" :disabled="runtime.loading" @click="submitOidcLogin">
          <ShieldCheck :size="18" />
          <span>{{ runtime.loading ? "准备登录" : "使用单点登录" }}</span>
        </button>
        <p class="form-info">当前部署使用 OIDC/SSO 认证，工作台权限仍由本地 RBAC 管理。</p>
      </div>

      <div v-else-if="intranetHeaderEnabled" class="login-action-stack">
        <p class="form-info">当前内网部署由门户登录态接入。请从内部门户进入，或刷新后由网关注入身份。</p>
      </div>

      <div v-else-if="unsupportedAuthMode" class="login-action-stack">
        <p class="form-warning">当前认证模式暂未接入登录页：{{ runtime.authMode }}</p>
      </div>

      <div v-if="guestLoginEnabled" class="login-action-stack login-guest-entry">
        <button
          type="button"
          class="icon-button secondary"
          :disabled="session.loading"
          @click="submitGuestLogin"
        >
          <Eye :size="16" />
          <span>{{ session.loading ? "进入中" : "以游客身份浏览" }}</span>
        </button>
        <p v-if="error && !passwordLoginEnabled" class="form-error">{{ error }}</p>
        <p class="form-info">游客可浏览公开工作台的已发布内容；评论、点赞与订阅工作台需注册账号。</p>
      </div>
    </section>
  </main>
</template>
