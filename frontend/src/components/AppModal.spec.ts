import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import AppModal from "./AppModal.vue";

// 居中 Modal 基座行为看护（frontend-product-design §10.1/§10.4）。

let wrapper: VueWrapper | null = null;
let trigger: HTMLButtonElement | null = null;

function mountModal(props: Record<string, unknown> = {}, slots: Record<string, string> = {}) {
  wrapper = mount(AppModal, {
    attachTo: document.body,
    props: {
      open: true,
      title: "测试弹窗",
      ...props
    },
    slots: {
      default: '<button id="inner-first" type="button">第一个</button><input id="inner-input" /><button id="inner-last" type="button">最后一个</button>',
      ...slots
    }
  });
  return wrapper;
}

function backdrop(): HTMLElement {
  const node = document.body.querySelector(".modal-backdrop");
  expect(node).not.toBeNull();
  return node as HTMLElement;
}

function modal(): HTMLElement {
  const node = document.body.querySelector(".modal");
  expect(node).not.toBeNull();
  return node as HTMLElement;
}

function pressKey(key: string, init: KeyboardEventInit = {}) {
  document.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
}

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  trigger?.remove();
  trigger = null;
  document.body.style.overflow = "";
  document.body.innerHTML = "";
});

describe("AppModal", () => {
  // 断言 1：居中基座结构 + role/aria + 尺寸档位
  it("renders a centered dialog with role/aria attributes and the declared size tier", async () => {
    mountModal({ size: "lg" });
    await nextTick();

    const dialog = modal();
    expect(dialog.getAttribute("role")).toBe("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.classList.contains("modal-lg")).toBe(true);
    // aria-labelledby 指向标题元素
    const labelledBy = dialog.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    const heading = document.getElementById(labelledBy as string);
    expect(heading?.textContent).toContain("测试弹窗");
    expect(backdrop().classList.contains("modal-backdrop")).toBe(true);
  });

  // 断言 2：sm/md 档位与默认档位
  it("defaults to the md tier and supports sm", async () => {
    mountModal();
    await nextTick();
    expect(modal().classList.contains("modal-md")).toBe(true);

    await wrapper!.setProps({ size: "sm" });
    expect(modal().classList.contains("modal-sm")).toBe(true);
  });

  // 断言 3：Esc 关闭
  it("closes on Escape when the form is clean", async () => {
    mountModal();
    await nextTick();

    pressKey("Escape");
    expect(wrapper!.emitted("close")).toHaveLength(1);
  });

  // 断言 4：遮罩点击关闭；点击 Modal 内部不关闭
  it("closes on backdrop click but not on clicks inside the modal", async () => {
    mountModal();
    await nextTick();

    modal().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(wrapper!.emitted("close")).toBeUndefined();

    backdrop().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    expect(wrapper!.emitted("close")).toHaveLength(1);
  });

  // 断言 5：右上角显式关闭按钮
  it("closes via the explicit close button", async () => {
    mountModal();
    await nextTick();

    const closeButton = document.body.querySelector('.modal-close[aria-label="关闭"]') as HTMLButtonElement;
    expect(closeButton).not.toBeNull();
    closeButton.click();
    await nextTick();
    expect(wrapper!.emitted("close")).toHaveLength(1);
  });

  // 断言 6：脏表单——遮罩/Esc 先弹 sm 确认层，不静默丢输入
  it("stacks an sm confirm layer instead of closing when dirty", async () => {
    mountModal({ dirty: true });
    await nextTick();

    pressKey("Escape");
    await nextTick();
    expect(wrapper!.emitted("close")).toBeUndefined();
    const confirm = document.body.querySelector(".modal-confirm") as HTMLElement;
    expect(confirm).not.toBeNull();
    expect(confirm.classList.contains("modal-sm")).toBe(true);
    expect(confirm.textContent).toContain("放弃未保存的修改？");

    // 继续编辑：确认层关闭、业务 Modal 保持打开
    (confirm.querySelectorAll("button")[0] as HTMLButtonElement).click();
    await nextTick();
    expect(document.body.querySelector(".modal-confirm")).toBeNull();
    expect(document.body.querySelector(".modal")).not.toBeNull();
    expect(wrapper!.emitted("close")).toBeUndefined();

    // 遮罩点击同样先确认，「放弃修改」才真正关闭
    backdrop().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await nextTick();
    const confirmAgain = document.body.querySelector(".modal-confirm") as HTMLElement;
    expect(confirmAgain).not.toBeNull();
    (confirmAgain.querySelectorAll("button")[1] as HTMLButtonElement).click();
    await nextTick();
    expect(wrapper!.emitted("close")).toHaveLength(1);
  });

  // 断言 7：打开时焦点移入 Modal（标题），Tab 焦点圈定在 Modal 内
  it("moves focus into the modal on open and traps Tab focus inside", async () => {
    mountModal();
    await nextTick();
    await nextTick();

    const heading = modal().querySelector("h3") as HTMLElement;
    expect(document.activeElement).toBe(heading);

    // Tab 到最后一个可聚焦元素后，再 Tab 回第一个（focus trap）
    const last = document.getElementById("inner-last") as HTMLButtonElement;
    last.focus();
    pressKey("Tab");
    const first = modal().querySelector("button, [href], input") as HTMLElement;
    expect(document.activeElement).toBe(first);

    // Shift+Tab 在第一个元素上回绕到最后一个
    pressKey("Tab", { shiftKey: true });
    expect(modal().contains(document.activeElement)).toBe(true);
  });

  // 断言 8：关闭后焦点归还触发控件
  it("returns focus to the trigger element after close", async () => {
    trigger = document.createElement("button");
    trigger.id = "modal-trigger";
    document.body.appendChild(trigger);
    trigger.focus();

    mountModal({ open: false });
    await wrapper!.setProps({ open: true });
    await nextTick();
    await nextTick();
    expect(document.activeElement).not.toBe(trigger);

    await wrapper!.setProps({ open: false });
    await nextTick();
    expect(document.activeElement).toBe(trigger);
  });

  // 断言 9：打开期间锁定 body 滚动，关闭后恢复
  it("locks body scroll while open and restores it on close", async () => {
    mountModal({ open: false });
    expect(document.body.style.overflow).toBe("");

    await wrapper!.setProps({ open: true });
    expect(document.body.style.overflow).toBe("hidden");

    await wrapper!.setProps({ open: false });
    expect(document.body.style.overflow).toBe("");
  });

  // 断言 10：≤640px 全屏化与档位宽度上限在 base.css 有唯一定义（CSS 层看护）
  it("keeps the ≤640px fullscreen rule and tier widths in base.css", () => {
    const baseCss = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..", "styles", "base.css"),
      "utf-8"
    );
    expect(baseCss).toContain(".modal.modal-sm");
    expect(baseCss).toContain("width: min(480px, calc(100vw - 48px))");
    expect(baseCss).toContain("width: min(720px, calc(100vw - 48px))");
    expect(baseCss).toContain("width: min(1120px, calc(100vw - 48px))");
    expect(baseCss).toContain("max-height: calc(100vh - 56px)");
    const fullscreen = baseCss.match(/@media \(max-width: 640px\) \{[\s\S]*?\.modal,[\s\S]*?border-radius: 0;/);
    expect(fullscreen).not.toBeNull();
  });
});
