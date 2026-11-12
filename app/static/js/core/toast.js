/**
 * Non-blocking toast notification stack.
 */

import { escapeHtml } from "./ui.js";

function ensureToastStack() {
  let stack = document.getElementById("toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toast-stack";
    stack.className = "toast-stack";
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  return stack;
}

export function showToast({ type = "info", title = "", message = "", duration = 4200 } = {}) {
  const stack = ensureToastStack();
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.innerHTML = `
    <div style="flex:1;min-width:0;">
      ${title ? `<div class="fw-semibold" style="margin-bottom:2px;">${escapeHtml(title)}</div>` : ""}
      <div class="text-sm text-secondary">${escapeHtml(message)}</div>
    </div>
    <button type="button" class="btn btn-ghost btn-sm" aria-label="Dismiss notification" style="padding:2px 6px;">&times;</button>
  `;

  const remove = () => {
    if (el.parentNode) el.parentNode.removeChild(el);
  };
  el.querySelector("button").addEventListener("click", remove);
  stack.appendChild(el);

  if (duration > 0) {
    window.setTimeout(remove, duration);
  }
}

