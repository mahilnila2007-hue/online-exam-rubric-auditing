/**
 * Examiner Exam Results Console: preliminary batch evaluation, result listing, and publication.
 */

import { api } from "../core/apiClient.js";
import { confirmDialog } from "../core/modal.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, setButtonLoading, statusBadge } from "../core/ui.js";

const state = JSON.parse(document.getElementById("exam-results-state").textContent || "{}");
const tbody = document.getElementById("er-tbody");
const searchInput = document.getElementById("er-search");
const filterSelect = document.getElementById("er-filter-status");
const distCard = document.getElementById("er-distribution-card");
const distGrid = document.getElementById("er-distribution-grid");

let allRows = [];

function renderDistribution(summary = {}) {
  if (!distCard || !distGrid) return;
  const dist = summary.grade_distribution || {};
  const entries = Object.entries(dist);
  if (!entries.length) {
    distCard.classList.add("hidden");
    return;
  }
  distCard.classList.remove("hidden");
  const evalCount = summary.evaluated_count || 0;
  const passCount = summary.passed_count || 0;
  const failCount = Math.max(0, evalCount - passCount);
  document.getElementById("er-dist-meta").textContent = `${passCount} Passed · ${failCount} Failed (${evalCount} Evaluated)`;
  distGrid.innerHTML = [
    `<div class="dist-pill" style="background:var(--success-soft);border-color:var(--success-border);"><div class="dist-pill-label" style="color:var(--success);">Passed</div><div class="dist-pill-val" style="color:var(--success);">${passCount}</div></div>`,
    `<div class="dist-pill" style="background:${failCount ? "var(--danger-soft)" : "var(--bg-subtle)"};border-color:${failCount ? "var(--danger-border)" : "var(--border-default)"};"><div class="dist-pill-label" style="color:${failCount ? "var(--danger)" : "var(--text-muted)"};">Failed</div><div class="dist-pill-val" style="color:${failCount ? "var(--danger)" : "var(--text-primary)"};">${failCount}</div></div>`,
    ...entries.map(
      ([grade, count]) =>
        `<div class="dist-pill"><div class="dist-pill-label">Grade ${escapeHtml(grade)}</div><div class="dist-pill-val">${count}</div></div>`
    ),
  ].join("");
}

function getFilteredRows() {
  const term = (searchInput?.value || "").trim().toLowerCase();
  const statusVal = filterSelect?.value || "";
  return allRows.filter((r) => {
    if (term) {
      const hay = `${r.student_name} ${r.institution_id} ${r.student_email}`.toLowerCase();
      if (!hay.includes(term)) return false;
    }
    if (statusVal === "published") return r.publication_status === "published";
    if (statusVal === "evaluated") return ["evaluated", "completed"].includes(r.evaluation_status);
    if (statusVal) return r.evaluation_status === statusVal;
    return true;
  });
}

async function loadResults() {
  try {
    const res = await api.get(`/api/examiner/exams/${encodeURIComponent(state.examId)}/results`);
    const { exam, summary, rows } = res.data;
    allRows = rows || [];

    document.getElementById("er-course-code").textContent = exam.course_code;
    document.getElementById("er-exam-title").textContent = `${exam.title} · Results`;
    document.getElementById("er-passing-meta").textContent =
      `Total: ${exam.total_marks}m · Passing: ${exam.passing_marks}m${exam.negative_marking_enabled ? ` · Negative Marking: -${exam.negative_mark_fraction}x` : ""}`;

    document.getElementById("er-kpi-total").textContent = summary.total_submissions;
    document.getElementById("er-kpi-pending").textContent = `${summary.pending_count} awaiting review`;
    document.getElementById("er-kpi-evaluated").textContent = summary.evaluated_count;
    document.getElementById("er-kpi-published").textContent = summary.published_count;
    document.getElementById("er-kpi-avg").textContent = `${summary.average_percentage}%`;
    document.getElementById("er-kpi-pass-rate").textContent = `Pass rate: ${summary.pass_rate}%`;

    renderDistribution(summary);
    renderRows(getFilteredRows());
  } catch (err) {
    showToast({ type: "error", title: "Could not load exam results", message: err.message });
    tbody.innerHTML = `<tr><td colspan="8"><div class="alert alert-danger">${escapeHtml(err.message)}</div></td></tr>`;
  }
}

function renderRows(rows) {
  if (!rows.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8">
          <div class="empty-state">
            <h3>No Submitted Attempts Yet</h3>
            <p class="text-sm">Student submissions will appear here once candidates submit this examination.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = rows
    .map((r) => {
      const descText =
        r.descriptive_max_score > 0
          ? `${r.descriptive_score ?? "—"} / ${r.descriptive_max_score}`
          : "N/A";
      const totalText =
        r.obtained_marks !== null && r.obtained_marks !== undefined
          ? `${r.obtained_marks} / ${r.total_marks} (${r.percentage ?? 0}%)`
          : "Pending";
      const gradeHtml = r.grade
        ? `<span class="badge badge-brand mono">${escapeHtml(r.grade)}</span> ${statusBadge(r.pass_status)}`
        : `<span class="text-xs text-muted">—</span>`;
      const canPublish =
        ["evaluated", "completed"].includes(r.evaluation_status) && r.publication_status !== "published";

      return `
        <tr>
          <td>
            <div class="fw-semibold">${escapeHtml(r.student_name)}</div>
            <div class="text-xs text-muted">${escapeHtml(r.institution_id || r.student_email)}</div>
          </td>
          <td class="tabular-nums text-sm">${r.mcq_score} / ${r.mcq_max_score}</td>
          <td class="tabular-nums text-sm">${descText}</td>
          <td class="fw-semibold tabular-nums text-sm">${totalText}</td>
          <td><div class="flex items-center gap-1 flex-wrap">${gradeHtml}</div></td>
          <td>${statusBadge(r.evaluation_status)}</td>
          <td>${statusBadge(r.publication_status)}</td>
          <td style="text-align:right;">
            <div class="flex items-center justify-end gap-2">
              <a href="/examiner/evaluations/${encodeURIComponent(r.submission_id)}" class="btn btn-primary btn-sm">Evaluate / Review</a>
              ${
                canPublish
                  ? `<button type="button" class="btn btn-success btn-sm" data-publish-sub="${escapeHtml(r.submission_id)}">Publish</button>`
                  : ""
              }
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll("[data-publish-sub]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const subId = btn.dataset.publishSub;
      setButtonLoading(btn, true, "Publishing...");
      try {
        await api.post(`/api/examiner/submissions/${encodeURIComponent(subId)}/publish-result`, {});
        showToast({ type: "success", title: "Result published", message: "Student can now view their report." });
        loadResults();
      } catch (err) {
        setButtonLoading(btn, false);
        showToast({ type: "error", title: "Publication failed", message: err.message });
      }
    });
  });
}

document.getElementById("batch-eval-btn")?.addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  setButtonLoading(btn, true, "Processing...");
  try {
    const res = await api.post(`/api/examiner/exams/${encodeURIComponent(state.examId)}/process-evaluations`, {});
    const d = res.data || {};
    showToast({
      type: "success",
      title: "Preliminary Rubric Check Complete",
      message: `Processed ${d.processed_count || 0} pending submission(s); skipped ${d.skipped_count || 0}.`,
    });
    loadResults();
  } catch (err) {
    showToast({ type: "error", title: "Batch evaluation failed", message: err.message });
  } finally {
    setButtonLoading(btn, false);
  }
});

document.getElementById("publish-all-btn")?.addEventListener("click", async (ev) => {
  const ok = await confirmDialog({
    title: "Publish All Evaluated Results?",
    message: "All finalized submissions will become visible in students' Published Results portals.",
    confirmLabel: "Publish Results",
    confirmVariant: "success",
  });
  if (!ok) return;

  const btn = ev.currentTarget;
  setButtonLoading(btn, true, "Publishing...");
  try {
    const res = await api.post(`/api/examiner/exams/${encodeURIComponent(state.examId)}/publish-results`, {});
    const d = res.data || {};
    showToast({
      type: "success",
      title: "Results Published",
      message: `Published ${d.published_count || 0} result(s). ${d.skipped_pending_count ? `${d.skipped_pending_count} pending descriptive review skipped.` : ""}`,
    });
    loadResults();
  } catch (err) {
    showToast({ type: "error", title: "Publication failed", message: err.message });
  } finally {
    setButtonLoading(btn, false);
  }
});

searchInput?.addEventListener("input", () => renderRows(getFilteredRows()));
filterSelect?.addEventListener("change", () => renderRows(getFilteredRows()));
document.getElementById("er-refresh-btn")?.addEventListener("click", loadResults);
loadResults();

