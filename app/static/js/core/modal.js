/**
 * Accessible modal dialog manager and confirmation prompt.
 */

import { escapeHtml } from "./ui.js";

let activeBackdrop = null;

export function closeModal() {
  if (activeBackdrop && activeBackdrop.parentNode) {
    activeBackdrop.parentNode.removeChild(activeBackdrop);
  }
  activeBackdrop = null;
  document.body.style.overflow = "";
}

export function openModal({ title = "", bodyHtml = "", footerHtml = "", size = "md", onMount = null } = {}) {
  closeModal();

  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.setAttribute("role", "dialog");
  backdrop.setAttribute("aria-modal", "true");

  const dialogClass = size === "lg" ? "modal-dialog modal-lg" : "modal-dialog";
  backdrop.innerHTML = `
    <div class="${dialogClass}">
      <div class="modal-header">
        <h3 class="modal-title">${escapeHtml(title)}</h3>
        <button type="button" class="btn btn-ghost btn-sm" data-modal-close aria-label="Close modal">&times;</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ""}
    </div>
  `;

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop || e.target.closest("[data-modal-close]")) {
      closeModal();
    }
  });

  const escHandler = (e) => {
    if (e.key === "Escape") {
      document.removeEventListener("keydown", escHandler);
      closeModal();
    }
  };
  document.addEventListener("keydown", escHandler);

  document.body.appendChild(backdrop);
  document.body.style.overflow = "hidden";
  activeBackdrop = backdrop;

  if (typeof onMount === "function") {
    onMount(backdrop);
  }
  return backdrop;
}

export function confirmDialog({
  title = "Confirm Action",
  message = "Are you sure you want to proceed?",
  confirmLabel = "Confirm",
  confirmVariant = "primary",
} = {}) {
  return new Promise((resolve) => {
    const backdrop = openModal({
      title,
      bodyHtml: `<p class="text-secondary">${escapeHtml(message)}</p>`,
      footerHtml: `
        <button type="button" class="btn btn-secondary" data-confirm-cancel>Cancel</button>
        <button type="button" class="btn btn-${confirmVariant}" data-confirm-ok>${escapeHtml(confirmLabel)}</button>
      `,
    });

    const finish = (result) => {
      closeModal();
      resolve(result);
    };

    backdrop.querySelector("[data-confirm-cancel]").addEventListener("click", () => finish(false));
    backdrop.querySelector("[data-confirm-ok]").addEventListener("click", () => finish(true));
  });
}

