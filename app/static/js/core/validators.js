/**
 * Shared client-side validation & inline field error rendering helpers.
 */

export function clearFormErrors(form) {
  if (!form) return;
  form.querySelectorAll(".is-invalid").forEach((el) => el.classList.remove("is-invalid"));
  form.querySelectorAll("[data-error-for]").forEach((el) => {
    el.textContent = "";
  });
}

export function applyFieldErrors(form, fieldErrors = {}) {
  if (!form || !fieldErrors) return;
  Object.entries(fieldErrors).forEach(([field, message]) => {
    const input = form.querySelector(`[name="${field}"]`);
    if (input) input.classList.add("is-invalid");
    const errEl = form.querySelector(`[data-error-for="${field}"]`);
    if (errEl) errEl.textContent = String(message);
  });
}

export function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(email || "").trim());
}

