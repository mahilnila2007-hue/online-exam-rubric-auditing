/**
 * Shared Rubric Version History modal renderer across Question Bank and Phase 3 Rubric Audit.
 */

import { api } from "./apiClient.js";
import { openModal } from "./modal.js";
import { showToast } from "./toast.js";
import { escapeHtml, formatDateTime } from "./ui.js";

function renderCriteriaBlock(criteria = []) {
  return criteria
    .map(
      (c) =>
        `<div class="text-xs" style="background:var(--bg-subtle);padding:0.55rem;border-radius:var(--radius-sm);">
          <strong>${escapeHtml(c.title)} (${c.max_marks}m):</strong>
          Keywords: ${escapeHtml((c.key_concepts || []).join(", ") || "—")}
          · Alternatives: <span class="fw-semibold" style="color:var(--brand-primary);">${escapeHtml((c.alternative_phrases || []).join(", ") || "—")}</span>
        </div>`
    )
    .join("");
}

export async function openRubricVersionsModal(rubricId, title = "Evaluation Rubric") {
  if (!rubricId) return;
  try {
    const res = await api.get(`/api/examiner/rubrics/${encodeURIComponent(rubricId)}/versions`);
    const versions = res.data?.versions || [];
    const current = res.data?.current_rubric || null;

    const currentHtml = current
      ? `
        <div class="card card-body mb-4" style="padding:1rem;border-color:var(--brand-border);background:var(--brand-soft);">
          <div class="flex items-center justify-between gap-2 mb-2 flex-wrap">
            <span class="badge badge-success mono">Active Version v${current.version || 1}</span>
            <span class="text-xs text-muted">Current scoring rubric (${current.max_marks} marks)</span>
          </div>
          <div style="display:grid;gap:0.4rem;">${renderCriteriaBlock(current.criteria || [])}</div>
        </div>
      `
      : "";

    const archivedHtml = versions.length
      ? versions
          .map(
            (v) => `
            <div class="card card-body mb-3" style="padding:1rem;">
              <div class="flex items-center justify-between gap-2 mb-2 flex-wrap">
                <span class="badge badge-brand mono">Archived Snapshot v${v.version_number}</span>
                <span class="text-xs text-muted">${escapeHtml(formatDateTime(v.created_at))}</span>
              </div>
              <div class="text-xs text-secondary mb-2">${escapeHtml(v.changed_reason || "Archived snapshot")} · By ${escapeHtml(v.changed_by_name || "Examiner")}</div>
              <div style="display:grid;gap:0.4rem;">${renderCriteriaBlock(v.rubric_data?.criteria || [])}</div>
            </div>
          `
          )
          .join("")
      : `<div class="empty-state" style="padding:1.5rem 1rem;"><h3>No Archived Revisions Yet</h3><p class="text-sm">Prior snapshots are preserved automatically whenever rubric audit suggestions are approved.</p></div>`;

    openModal({
      title: `Rubric Version Timeline · ${title}`,
      size: "lg",
      bodyHtml: `${currentHtml}${archivedHtml}`,
      footerHtml: `<button type="button" class="btn btn-primary" data-modal-close>Close</button>`,
    });
  } catch (err) {
    showToast({ type: "error", title: "Could not load rubric versions", message: err.message });
  }
}

