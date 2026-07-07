<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";

// 居中 Modal 基座（frontend-product-design §10.1，2026-07 定稿，全站唯一弹窗基座）：
// - 结构：.modal-backdrop（fixed inset 0 遮罩 + grid 居中）+ .modal（role=dialog aria-modal）
// - 尺寸档位 sm 480 / md 720 / lg 1120（min(档位, calc(100vw - 48px))；≤640px 全屏化在 CSS 层）
// - 遮罩点击、Esc、右上显式关闭按钮三者同时可用
// - dirty（含未保存输入）时遮罩/Esc/关闭先叠一层 sm 确认 Modal，不允许静默丢输入
// - 打开时焦点移入（标题），Tab 焦点圈定在 Modal 内，关闭后焦点归还触发控件
// - 打开期间锁定 body 滚动；业务 Modal 之上最多叠一层确认 Modal（sm）
// 迁移清单与上下文面板判定见产品设计 §10.2/§10.3（8 项弹层迁移由 Wave2 逐项收编）。
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    size?: "sm" | "md" | "lg";
    dirty?: boolean;
    bodyClass?: string;
    confirmText?: string;
  }>(),
  {
    size: "md",
    dirty: false,
    bodyClass: "",
    confirmText: "放弃未保存的修改？"
  }
);

const emit = defineEmits<{ (event: "close"): void }>();

const titleId = `app-modal-title-${useId()}`;
const confirmTitleId = `${titleId}-confirm`;
const modalEl = ref<HTMLElement | null>(null);
const confirmEl = ref<HTMLElement | null>(null);
const titleEl = ref<HTMLElement | null>(null);
const confirmOpen = ref(false);

let triggerEl: HTMLElement | null = null;
let previousBodyOverflow = "";
let active = false;

const sizeClass = computed(() => `modal-${props.size}`);

function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  );
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.stopPropagation();
    if (confirmOpen.value) {
      confirmOpen.value = false;
      return;
    }
    requestClose();
    return;
  }
  if (event.key !== "Tab") {
    return;
  }
  // Tab 焦点圈定：确认层打开时圈定在确认 Modal 内，否则圈定在业务 Modal 内
  const scope = confirmOpen.value ? confirmEl.value : modalEl.value;
  if (!scope) {
    return;
  }
  const nodes = focusables(scope);
  if (!nodes.length) {
    event.preventDefault();
    return;
  }
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  const current = document.activeElement as HTMLElement | null;
  if (!current || !scope.contains(current)) {
    event.preventDefault();
    first.focus();
    return;
  }
  if (event.shiftKey && current === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && current === last) {
    event.preventDefault();
    first.focus();
  }
}

function requestClose() {
  if (props.dirty) {
    confirmOpen.value = true;
    void nextTick(() => {
      if (confirmEl.value) {
        focusables(confirmEl.value)[0]?.focus();
      }
    });
    return;
  }
  emit("close");
}

function keepEditing() {
  confirmOpen.value = false;
}

function discardAndClose() {
  confirmOpen.value = false;
  emit("close");
}

function activate() {
  if (active) {
    return;
  }
  active = true;
  triggerEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  previousBodyOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onKeydown, true);
  void nextTick(() => {
    titleEl.value?.focus();
  });
}

function deactivate() {
  if (!active) {
    return;
  }
  active = false;
  confirmOpen.value = false;
  document.removeEventListener("keydown", onKeydown, true);
  document.body.style.overflow = previousBodyOverflow;
  triggerEl?.focus();
  triggerEl = null;
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      activate();
    } else {
      deactivate();
    }
  }
);

onMounted(() => {
  if (props.open) {
    activate();
  }
});

onBeforeUnmount(() => {
  deactivate();
});
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="requestClose">
      <section
        ref="modalEl"
        class="modal"
        :class="sizeClass"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
      >
        <header class="modal-head">
          <div class="modal-head-body">
            <slot name="header-meta" />
            <h3 :id="titleId" ref="titleEl" tabindex="-1">{{ title }}</h3>
          </div>
          <button type="button" class="modal-close" aria-label="关闭" @click="requestClose">
            <X :size="18" />
          </button>
        </header>
        <div class="modal-body" :class="bodyClass">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="modal-foot">
          <slot name="footer" />
        </footer>
      </section>

      <!-- 脏表单确认层：业务 Modal 之上唯一允许叠加的 sm 确认 Modal（§10.1 层叠规则） -->
      <div
        v-if="confirmOpen"
        class="modal-backdrop modal-confirm-backdrop"
        @click.self="keepEditing"
      >
        <section
          ref="confirmEl"
          class="modal modal-sm modal-confirm"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="confirmTitleId"
        >
          <header class="modal-head">
            <div class="modal-head-body">
              <h3 :id="confirmTitleId" tabindex="-1">{{ confirmText }}</h3>
            </div>
          </header>
          <div class="modal-body">
            <p class="modal-confirm-text">关闭后当前输入不会保存。</p>
          </div>
          <footer class="modal-foot">
            <button type="button" class="icon-button secondary" @click="keepEditing">继续编辑</button>
            <button type="button" class="icon-button" @click="discardAndClose">放弃修改</button>
          </footer>
        </section>
      </div>
    </div>
  </Teleport>
</template>
