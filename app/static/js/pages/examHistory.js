/**
 * Student Examination History table and detailed question breakdown modal.
 */

import { api } from "../core/apiClient.js";
import { openModal } from "../core/modal.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, formatDateTime, formatDurationSeconds, statusBadge } from "../core/ui.js";

let historyItems = [];
const tbody = document.getElementById("history-tbody");
const filterSelect = document.getElementById("history-status-filter");

function renderTable() {
  const filter = filterSelect.value;
  const rows = filter ? historyItems.filter((i) => i.evaluation_status === filter || i.status === filter) : historyItems;

  if (!rows.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="empty-state">
            <h3>No Examination History Yet</h3>
            <p class="text-sm">Your attempted and submitted examinations will appear here.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = rows
    .map((item) => {
      const resultBtn =
        item.publication_status === "published" && item.result_id
          ? `<a href="/student/results/${encodeURIComponent(item.result_id)}" class="btn btn-primary btn-sm">View Result</a>`
          : "";

      const actionBtn =
        item.status === "in_progress"
          ? `<a href="/student/exams/${encodeURIComponent(item.exam_id)}/attempt" class="btn btn-success btn-sm">Resume</a>`
          : `<div class="flex items-center justify-end gap-2">${resultBtn}<button type="button" class="btn btn-secondary btn-sm" data-view-sub="${escapeHtml(item.submission_id)}">Breakdown</button></div>`;

      return `
        <tr>
          <td>
            <div class="fw-semibold">${escapeHtml(item.exam_title)}</div>
            <div class="text-xs text-muted mono">${escapeHtml(item.course_code)}</div>
          </td>
          <td class="text-sm">${escapeHtml(formatDateTime(item.submitted_at || item.started_at))}</td>
          <td class="text-sm">${item.answered_count} / ${item.total_questions}</td>
          <td class="fw-semibold tabular-nums">${item.mcq_score} / ${item.mcq_max_score}</td>
          <td>${statusBadge(item.evaluation_status)}</td>
          <td>${statusBadge(item.audit_status)}</td>
          <td style="text-align:right;">${actionBtn}</td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll("[data-view-sub]").forEach((btn) => {
    btn.addEventListener("click", () => openBreakdownModal(btn.dataset.viewSub));
  });
}

async function openBreakdownModal(submissionId) {
  try {
    const res = await api.get(`/api/student/submissions/${encodeURIComponent(submissionId)}`);
    const sub = res.data.submission;
    const g = sub.grading || {};

    const questionsHtml = (sub.questions || [])
      .map((q) => {
        if (q.type === "mcq") {
          const selectedOpt = (q.options || []).find((o) => o.id === q.student_answer?.selected_option_id);
          const correctOpt = (q.options || []).find((o) => o.id === q.correct_option_id);
          return `
            <div class="card card-body mb-3" style="padding:1rem;">
              <div class="flex items-center justify-between gap-2 mb-2">
                <span class="badge badge-mcq">Q${q.index} · MCQ</span>
                <span class="fw-semibold text-sm">${q.awarded_marks ?? 0} / ${q.marks} Marks</span>
              </div>
              <div class="fw-semibold mb-2">${escapeHtml(q.prompt)}</div>
              <div class="text-sm"><strong>Your Answer:</strong> ${escapeHtml(selectedOpt ? selectedOpt.text : "Not answered")}</div>
              ${correctOpt ? `<div class="text-sm text-secondary mt-1"><strong>Correct Answer:</strong> ${escapeHtml(correctOpt.text)}</div>` : ""}
              ${q.explanation ? `<div class="text-xs text-muted mt-1"><strong>Rationale:</strong> ${escapeHtml(q.explanation)}</div>` : ""}
            </div>
          `;
        }
        const reval = q.rubric_evaluation;
        const criteriaRows = (reval?.criteria_scores || [])
          .map(
            (cs) => `
            <tr>
              <td class="text-xs fw-semibold">${escapeHtml(cs.title)}</td>
              <td class="text-xs tabular-nums">${cs.awarded_marks ?? 0} / ${cs.max_marks}</td>
              <td class="text-xs text-secondary">${escapeHtml(cs.feedback || "—")}</td>
            </tr>
          `
          )
          .join("");
        return `
          <div class="card card-body mb-3" style="padding:1rem;">
            <div class="flex items-center justify-between gap-2 mb-2">
              <span class="badge badge-descriptive">Q${q.index} · Descriptive</span>
              ${
                reval
                  ? `<span class="badge badge-success tabular-nums">${reval.awarded_marks ?? 0} / ${q.marks} Marks</span>`
                  : `<span class="badge badge-warning">Pending Rubric Evaluation (${q.marks}m)</span>`
              }
            </div>
            <div class="fw-semibold mb-2">${escapeHtml(q.prompt)}</div>
            <div class="text-sm" style="background:var(--bg-subtle);padding:0.75rem;border-radius:var(--radius-sm);white-space:pre-wrap;">${escapeHtml(q.student_answer?.text_answer || "No response provided.")}</div>
            ${
              criteriaRows
                ? `<div class="table-wrap mt-3"><table class="data-table"><thead><tr><th>Criterion</th><th>Awarded</th><th>Feedback</th></tr></thead><tbody>${criteriaRows}</tbody></table></div>`
                : ""
            }
            ${reval?.feedback ? `<div class="text-xs text-secondary mt-2"><strong>Examiner Note:</strong> ${escapeHtml(reval.feedback)}</div>` : ""}
          </div>
        `;
      })
      .join("");

    openModal({
      title: `${sub.course_code} · Submission Breakdown`,
      size: "lg",
      bodyHtml: `
        <div class="flex items-center justify-between flex-wrap gap-2 mb-4">
          <div class="text-sm text-secondary">
            Submitted ${escapeHtml(formatDateTime(sub.submitted_at))} · Time used: ${formatDurationSeconds(sub.duration_seconds_used)}
          </div>
          <div class="fw-semibold tabular-nums">
            MCQ: ${g.mcq_score ?? 0} / ${g.mcq_max_score ?? 0}${
              g.descriptive_max_score > 0
                ? sub.publication_status === "published"
                  ? ` · Descriptive: ${g.descriptive_score ?? 0} / ${g.descriptive_max_score}`
                  : ` · Descriptive: Pending`
                : ""
            }
          </div>
        </div>
        ${questionsHtml}
      `,
      footerHtml: `<button type="button" class="btn btn-primary" data-modal-close>Close</button>`,
    });
  } catch (err) {
    showToast({ type: "error", title: "Unable to load breakdown", message: err.message });
  }
}

async function loadHistory() {
  try {
    const res = await api.get("/api/student/history");
    historyItems = res.data?.submissions || [];
    renderTable();
  } catch (err) {
    showToast({ type: "error", title: "Failed to load history", message: err.message });
  }
}

filterSelect?.addEventListener("change", renderTable);
loadHistory();

