<script setup lang="ts">
import { Save } from "lucide-vue-next";
import { computed, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { updateProfile } from "../api/auth";
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

// ---------- 资料卡（identity-access-design §4.4 / page-specs §25.1，WP3-F） ----------
// 本地账号可编辑三字段；外部身份只读说明；游客不渲染；must_change_password 改密前禁用。
const isLocalAccount = computed(() => session.user?.external_provider === "local");
const isGuest = computed(() => session.isGuest);
const mustChangePassword = computed(() => session.user?.status === "must_change_password");
const profileForm = reactive({
  displayName: "",
  department: "",
  email: ""
});
const profileError = ref("");
const profileMessage = ref("");
const savingProfile = ref(false);

function fillProfileForm() {
  profileForm.displayName = session.user?.display_name ?? "";
  profileForm.department = session.user?.department ?? "";
  profileForm.email = session.user?.email ?? "";
}

watch(() => session.user, fillProfileForm, { immediate: true });

async function submitProfile() {
  profileError.value = "";
  profileMessage.value = "";
  // 改密完成前后端会 403：前端同样不发请求（identity-access-design §4.4）
  if (mustChangePassword.value) {
    profileError.value = "请先完成改密，再编辑资料。";
    return;
  }
  const displayName = profileForm.displayName.trim();
  // display_name 为空不发请求（page-specs §25.4）
  if (!displayName) {
    profileError.value = "姓名不能为空";
    return;
  }
  savingProfile.value = true;
  try {
    const response = await updateProfile({
      display_name: displayName,
      department: profileForm.department.trim(),
      email: profileForm.email.trim()
    });
    // 刷新 session store：顶部用户胶囊与评论署名立即显示新姓名（产品设计 §11）
    session.user = response.user;
    fillProfileForm();
    profileMessage.value = "资料已保存";
  } catch (exc) {
    // 保存失败展示后端错误，不显示假成功
    profileError.value = exc instanceof Error ? exc.message : "保存资料失败";
  } finally {
    savingProfile.value = false;
  }
}

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
  <!-- settings 模板容器（frontend-product-design §9.3：内容窄列 860px 居中）
       设置卡顺序（§25.1）：资料 → 密码 → 身份来源说明 -->
  <div class="layout-settings">
    <section class="toolbar-band">
      <div>
        <p class="eyebrow">Account</p>
        <h2>账号</h2>
        <p>{{ session.user?.display_name }} · {{ session.user?.username }} · {{ providerLabel }}</p>
      </div>
      <button class="ghost-button" type="button" @click="signOut">退出登录</button>
    </section>

    <!-- 资料卡：游客会话不渲染（中央 guest 门拒绝一切写操作） -->
    <section v-if="!isGuest" class="data-table-wrap account-profile-card" aria-label="资料">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Profile</p>
          <h3>资料</h3>
        </div>
      </div>

      <!-- 本地账号：三字段可编辑 -->
      <form
        v-if="isLocalAccount"
        class="form-grid-two ops-form account-profile-form"
        @submit.prevent="submitProfile"
      >
        <label>
          <span>登录账号</span>
          <input :value="session.user?.username" disabled aria-label="登录账号" />
          <small>登录账号不可修改</small>
        </label>
        <label>
          <span>姓名（必填）</span>
          <input
            v-model="profileForm.displayName"
            :disabled="mustChangePassword"
            maxlength="128"
            aria-label="姓名"
          />
        </label>
        <label>
          <span>部门</span>
          <input
            v-model="profileForm.department"
            :disabled="mustChangePassword"
            maxlength="128"
            aria-label="部门"
          />
        </label>
        <label>
          <span>邮箱</span>
          <input
            v-model="profileForm.email"
            :disabled="mustChangePassword"
            type="email"
            maxlength="255"
            aria-label="邮箱"
          />
        </label>
        <p v-if="mustChangePassword" class="form-info">
          管理员已重置你的密码：请先在下方完成改密，再编辑资料。
        </p>
        <p v-if="profileError" class="form-error">{{ profileError }}</p>
        <p v-if="profileMessage" class="form-success">{{ profileMessage }}</p>
        <button type="submit" class="icon-button" :disabled="savingProfile || mustChangePassword">
          <Save :size="16" />
          <span>{{ savingProfile ? "保存中" : "保存资料" }}</span>
        </button>
      </form>

      <!-- 外部身份：同一卡片只读展示，不渲染必然失败的编辑表单 -->
      <template v-else>
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
            <span>邮箱</span>
            <strong>{{ session.user?.email || "未设置" }}</strong>
          </article>
        </div>
        <p class="form-info">资料由外部身份系统管理，登录时自动同步；如需修改请在身份系统侧更新。</p>
      </template>

      <p class="workspace-form-hint">
        角色：{{ session.user?.roles.join(", ") || "无角色" }}（角色与权限不在本页调整）
      </p>
    </section>

    <section v-if="canChangeLocalPassword" class="data-table-wrap" aria-label="密码">
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

    <!-- 身份来源说明（外部身份/游客） -->
    <section v-if="!canChangeLocalPassword" class="data-table-wrap" aria-label="身份来源">
      <p class="form-info">
        当前账号来自 {{ providerLabel }}，密码、MFA 和会话策略由外部身份系统管理；本系统只使用映射后的用户、角色和工作台权限。
      </p>
    </section>
  </div>
</template>

<style scoped>
.account-profile-form label small {
  color: var(--text-muted, rgba(71, 85, 105, 0.9));
  font-size: 12px;
}
</style>
