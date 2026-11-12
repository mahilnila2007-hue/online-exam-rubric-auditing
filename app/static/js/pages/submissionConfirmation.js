/**
 * Submission Confirmation Receipt page.
 */

import { api } from "../core/apiClient.js";
import { escapeHtml, formatDateTime, formatDurationSeconds, statusBadge } from "../core/ui.js";

const state = JSON.parse(document.getElementById("confirmation-page-state").textContent || "{}");
const container = document.getElementById("confirmation-container");

async function loadConfirmation() {
  try {
    const res = await api.get(`/api/student/submissions/${encodeURIComponent(state.submissionId)}`);
    const sub = res.data.submission;
    const g = sub.grading || {};
    const audit = sub.rubric_audit || {};
    const descReleased = g.descriptive_max_score > 0 && sub.publication_status === "published";
    const descLabel =
      g.descriptive_max_score > 0
        ? descReleased
          ? `${g.descriptive_score ?? 0} / ${g.descriptive_max_score} Marks`
          : `${g.descriptive_max_score} Marks Pending`
        : "None";

    container.innerHTML = `
      <div class="card">
        <div class="receipt-banner">
          <div style="width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,0.2);display:grid;place-items:center;margin:0 auto 0.9rem;">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <h1 style="color:#fff;font-size:1.55rem;">Examination Submitted Successfully</h1>
          <p style="color:rgba(255,255,255,0.9);margin-top:0.35rem;">Your responses have been securely stored and verified.</p>
        </div>

        <div class="card-body">
          <div class="flex items-center justify-between flex-wrap gap-2 pb-4 mb-4" style="border-bottom:1px solid var(--border-default);padding-bottom:1rem;">
            <div>
              <span class="badge badge-brand mono mb-1">${escapeHtml(sub.course_code)}</span>
              <h2 style="font-size:1.2rem;">${escapeHtml(sub.exam_title)}</h2>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              ${statusBadge(sub.status)}
              ${statusBadge(g.evaluation_status)}
            </div>
          </div>

          <div class="kpi-grid mb-6">
            <div class="kpi-card">
              <div>
                <div class="kpi-label">Instant MCQ Score</div>
                <div class="kpi-value" style="font-size:1.45rem;">${g.mcq_score ?? 0} / ${g.mcq_max_score ?? 0}</div>
                <div class="kpi-meta">Auto-graded on server</div>
              </div>
            </div>
            <div class="kpi-card">
              <div>
                <div class="kpi-label">Questions Answered</div>
                <div class="kpi-value" style="font-size:1.45rem;">${sub.answered_count} / ${sub.total_questions}</div>
                <div class="kpi-meta">Time used: ${formatDurationSeconds(sub.duration_seconds_used)}</div>
              </div>
            </div>
            <div class="kpi-card">
              <div>
                <div class="kpi-label">Descriptive Evaluation</div>
                <div class="kpi-value" style="font-size:1.25rem;">${descLabel}</div>
                <div class="kpi-meta">${statusBadge(audit.audit_status || "not_applicable")}</div>
              </div>
            </div>
          </div>

          <div class="card" style="background:var(--bg-subtle);border-radius:var(--radius-md);padding:1rem 1.2rem;margin-bottom:1.5rem;">
            <div class="form-grid text-sm">
              <div><span class="text-muted">Submission Receipt ID:</span><div class="mono fw-semibold">${escapeHtml(sub.submission_id)}</div></div>
              <div><span class="text-muted">Submitted At:</span><div class="fw-semibold">${escapeHtml(formatDateTime(sub.submitted_at))}</div></div>
              <div><span class="text-muted">Candidate:</span><div class="fw-semibold">${escapeHtml(sub.student_name)} (${escapeHtml(sub.institution_id)})</div></div>
              <div><span class="text-muted">Total Examination Marks:</span><div class="fw-semibold">${g.total_max_score ?? 0} Marks</div></div>
            </div>
          </div>

          <div class="flex items-center justify-between gap-3 flex-wrap">
            <a href="/student/dashboard" class="btn btn-secondary">Return to Dashboard</a>
            <div class="flex items-center gap-2">
              ${sub.publication_status === "published" && sub.result_id ? `<a href="/student/results/${encodeURIComponent(sub.result_id)}" class="btn btn-success">View Published Result</a>` : ""}
              <a href="/student/history" class="btn btn-primary">View Full Exam History</a>
            </div>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `
      <div class="card card-body">
        <div class="alert alert-danger mb-4">${escapeHtml(err.message)}</div>
        <a href="/student/dashboard" class="btn btn-secondary">Return to Dashboard</a>
      </div>
    `;
  }
}

loadConfirmation();

