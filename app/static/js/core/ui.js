/**
 * Common DOM, formatting, escaping, and shell navigation helpers.
 */

import { api } from "./apiClient.js";
import { showToast } from "./toast.js";

const HTML_ESCAPE_MAP = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => HTML_ESCAPE_MAP[ch]);
}

export function formatDateTime(isoString) {
  if (!isoString) return "—";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return String(isoString);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function toDatetimeLocalValue(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function formatDurationSeconds(totalSeconds) {
  const sec = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hrs = Math.floor(sec / 3600);
  const mins = Math.floor((sec % 3600) / 60);
  const rem = sec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hrs > 0 ? `${pad(hrs)}:${pad(mins)}:${pad(rem)}` : `${pad(mins)}:${pad(rem)}`;
}

export function formatRelativeWindow(isoString, prefixFuture = "in", suffixPast = "ago") {
  if (!isoString) return "";
  const target = new Date(isoString).getTime();
  if (Number.isNaN(target)) return "";
  const diffSec = Math.round((target - Date.now()) / 1000);
  const absSec = Math.abs(diffSec);
  const days = Math.floor(absSec / 86400);
  const hours = Math.floor((absSec % 86400) / 3600);
  const mins = Math.max(1, Math.floor((absSec % 3600) / 60));

  let span = `${mins}m`;
  if (days > 0) span = `${days}d ${hours}h`;
  else if (hours > 0) span = `${hours}h ${mins}m`;

  return diffSec >= 0 ? `${prefixFuture} ${span}`.trim() : `${span} ${suffixPast}`.trim();
}

export function formatMetadataChips(meta = {}, { maxItems = 5 } = {}) {
  if (!meta || typeof meta !== "object") {
    return `<span class="text-xs text-muted">—</span>`;
  }
  const entries = Object.entries(meta).filter(([, val]) => val !== null && val !== undefined && val !== "");
  if (!entries.length) {
    return `<span class="text-xs text-muted">—</span>`;
  }
  const visible = entries.slice(0, maxItems);
  const chips = visible
    .map(([key, val]) => {
      const label = String(key).replace(/_/g, " ");
      const formattedVal = Array.isArray(val)
        ? `${val.length} item(s)`
        : typeof val === "object"
          ? `${Object.keys(val).length} field(s)`
          : String(val);
      return `<span class="meta-kv-chip" title="${escapeHtml(`${label}: ${formattedVal}`)}"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(formattedVal)}</span>`;
    })
    .join("");
  const extra = entries.length > maxItems ? `<span class="meta-kv-chip">+${entries.length - maxItems} more</span>` : "";
  return `<div class="meta-kv-list">${chips}${extra}</div>`;
}

export function statusBadge(status, labelOverride = null) {
  const raw = String(status || "neutral").toLowerCase();
  const labelMap = {
    live: "Live Now",
    upcoming: "Scheduled",
    ended: "Closed",
    published: "Published",
    scheduled: "Scheduled",
    draft: "Draft",
    archived: "Archived",
    submitted: "Submitted",
    auto_submitted: "Auto-Submitted",
    in_progress: "In Progress",
    not_started: "Not Started",
    completed: "Graded",
    evaluated: "Evaluated",
    preliminary_evaluated: "Preliminary Checked",
    pending_descriptive: "Pending Rubric Grading",
    pending_audit: "Pending Phase 3 Audit",
    pending: "Pending Review",
    approved: "Approved",
    rejected: "Rejected",
    flagged: "Flagged Gap",
    audited: "Audited",
    unpublished: "Unpublished",
    pass: "PASS",
    fail: "FAIL",
    not_applicable: "MCQ Only",
    active: "Active",
    suspended: "Suspended",
    pending_approval: "Pending Admin Approval",
    mcq: "MCQ",
    descriptive: "Descriptive",
  };
  const label = labelOverride || labelMap[raw] || raw.replace(/_/g, " ");
  let variant = "neutral";
  if (["live", "active", "completed", "evaluated", "submitted", "pass", "approved", "audited"].includes(raw)) variant = "success";
  else if (["upcoming", "published", "scheduled", "mcq"].includes(raw)) variant = "upcoming";
  else if (["pending_descriptive", "preliminary_evaluated", "pending_audit", "pending", "pending_approval", "flagged", "in_progress", "auto_submitted", "unpublished"].includes(raw)) variant = "warning";
  else if (["suspended", "hard", "fail", "rejected"].includes(raw)) variant = "danger";
  else if (["descriptive"].includes(raw)) variant = "violet";

  return `<span class="badge badge-${variant}"><span class="badge-dot"></span>${escapeHtml(label)}</span>`;
}

export function setButtonLoading(button, isLoading, loadingText = "Working...") {
  if (!button) return;
  if (isLoading) {
    if (!button.dataset.originalHtml) {
      button.dataset.originalHtml = button.innerHTML;
    }
    button.disabled = true;
    button.classList.add("is-loading");
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${escapeHtml(loadingText)}</span>`;
  } else {
    button.disabled = false;
    button.classList.remove("is-loading");
    if (button.dataset.originalHtml) {
      button.innerHTML = button.dataset.originalHtml;
      delete button.dataset.originalHtml;
    }
  }
}

export function initAppShell() {
  const sidebar = document.getElementById("app-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  const toggleBtn = document.getElementById("mobile-menu-btn");

  const closeSidebar = () => {
    sidebar?.classList.remove("is-open");
    backdrop?.classList.remove("is-open");
  };

  toggleBtn?.addEventListener("click", () => {
    sidebar?.classList.toggle("is-open");
    backdrop?.classList.toggle("is-open");
  });
  backdrop?.addEventListener("click", closeSidebar);

  document.querySelectorAll("[data-logout-btn]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      setButtonLoading(btn, true, "Signing out...");
      try {
        const res = await api.post("/api/auth/logout", {});
        window.location.href = res.data?.redirect_url || "/login";
      } catch (err) {
        setButtonLoading(btn, false);
        showToast({ type: "error", title: "Logout failed", message: err.message });
      }
    });
  });
}

export async function renderStudentNotifications(containerId = "student-notifications-banner") {
  const banner = document.getElementById(containerId);
  if (!banner) return;
  try {
    const res = await api.get("/api/student/notifications");
    const unread = (res.data?.notifications || []).filter((n) => !n.is_read);
    if (!unread.length) {
      banner.innerHTML = "";
      return;
    }
    banner.innerHTML = unread
      .slice(0, 3)
      .map(
        (n) => `
        <div class="alert alert-info mb-2 justify-between items-center flex-wrap gap-2">
          <div>
            <strong>${escapeHtml(n.title)}</strong>
            <div class="text-xs mt-1">${escapeHtml(n.message)}</div>
          </div>
          <div class="flex items-center gap-2">
            ${n.result_id ? `<a href="/student/results/${encodeURIComponent(n.result_id)}" class="btn btn-primary btn-sm">View Updated Result</a>` : ""}
            <button type="button" class="btn btn-secondary btn-sm" data-read-notif="${escapeHtml(n.notification_id)}">Dismiss</button>
          </div>
        </div>
      `
      )
      .join("");

    banner.querySelectorAll("[data-read-notif]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api.post(`/api/student/notifications/${encodeURIComponent(btn.dataset.readNotif)}/read`, {});
        renderStudentNotifications(containerId);
      });
    });
  } catch {
    // Non-blocking notification check
  }
}

