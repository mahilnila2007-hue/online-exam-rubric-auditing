/**
 * Pre-examination instructions and honor code confirmation page.
 */

import { api } from "../core/apiClient.js";
import { escapeHtml, formatDateTime, statusBadge } from "../core/ui.js";

const state = JSON.parse(document.getElementById("instructions-page-state").textContent || "{}");
const container = document.getElementById("instructions-container");

async function loadInstructions() {
  try {
    const res = await api.get(`/api/student/exams/${encodeURIComponent(state.examId)}/instructions`);
    const exam = res.data.exam;

    const alreadySubmitted = ["submitted", "auto_submitted"].includes(exam.attempt_status);
    let primaryActionHtml = "";

    if (alreadySubmitted && exam.submission_id) {
      primaryActionHtml = `
        <a href="/student/submissions/${encodeURIComponent(exam.submission_id)}/confirmation" class="btn btn-primary btn-lg">
          View Submission Receipt
        </a>
      `;
    } else if (exam.can_start || exam.can_resume) {
      const label = exam.can_resume ? "Resume Examination" : "Start Examination";
      primaryActionHtml = `
        <button type="button" id="launch-exam-btn" class="btn btn-primary btn-lg" disabled>
          ${label}
        </button>
      `;
    } else if (exam.availability === "upcoming") {
      primaryActionHtml = `<button type="button" class="btn btn-secondary btn-lg" disabled>Opens ${escapeHtml(formatDateTime(exam.scheduled_start))}</button>`;
    } else {
      primaryActionHtml = `<button type="button" class="btn btn-secondary btn-lg" disabled>Examination Window Closed</button>`;
    }

    container.innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <div class="flex items-center gap-2 mb-2 flex-wrap">
              <span class="badge badge-brand mono">${escapeHtml(exam.course_code)}</span>
              ${statusBadge(exam.availability)}
              ${exam.attempt_status !== "not_started" ? statusBadge(exam.attempt_status) : ""}
            </div>
            <h1 style="font-size:1.5rem;">${escapeHtml(exam.title)}</h1>
            <p class="text-secondary mt-1">${escapeHtml(exam.description || "Please review all assessment instructions carefully before beginning.")}</p>
          </div>
        </div>

        <div class="card-body">
          <div class="kpi-grid mb-6">
            <div class="kpi-card">
              <div>
                <div class="kpi-label">Duration</div>
                <div class="kpi-value" style="font-size:1.45rem;">${exam.duration_minutes} min</div>
                <div class="kpi-meta">Continuous countdown</div>
              </div>
            </div>
            <div class="kpi-card">
              <div>
                <div class="kpi-label">Questions</div>
                <div class="kpi-value" style="font-size:1.45rem;">${exam.question_count}</div>
                <div class="kpi-meta">${exam.mcq_count} MCQ · ${exam.descriptive_count} Descriptive</div>
              </div>
            </div>
            <div class="kpi-card">
              <div>
                <div class="kpi-label">Total Marks</div>
                <div class="kpi-value" style="font-size:1.45rem;">${exam.total_marks}</div>
                <div class="kpi-meta">Passing threshold: ${exam.passing_marks}</div>
              </div>
            </div>
          </div>

          <div class="alert alert-info mb-4">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            <div class="text-sm">
              <strong>Availability Window:</strong>
              ${escapeHtml(formatDateTime(exam.scheduled_start))} to ${escapeHtml(formatDateTime(exam.scheduled_end))}
              ${exam.rubric_audit_enabled && exam.descriptive_count > 0 ? " · Descriptive answers are evaluated against structured rubrics with Phase 3 auditing support." : ""}
            </div>
          </div>

          <h2 style="font-size:1.05rem;margin-bottom:0.75rem;">Examination Rules &amp; Integrity Guidelines</h2>
          <ul style="padding-left:1.3rem;display:grid;gap:0.55rem;color:var(--text-secondary);margin-bottom:1.5rem;">
            ${(exam.instructions || []).map((rule) => `<li>${escapeHtml(rule)}</li>`).join("")}
          </ul>

          ${
            exam.can_start || exam.can_resume
              ? `
                <label class="checkbox-row mb-6">
                  <input type="checkbox" id="acknowledge-rules-cb">
                  <div>
                    <div class="fw-semibold text-sm">Academic Integrity Declaration</div>
                    <div class="text-xs text-secondary">I confirm I have read the examination instructions and understand the timer begins immediately upon starting.</div>
                  </div>
                </label>
              `
              : ""
          }

          <div class="flex items-center justify-between gap-3 flex-wrap">
            <a href="/student/dashboard" class="btn btn-secondary">Back to Dashboard</a>
            ${primaryActionHtml}
          </div>
        </div>
      </div>
    `;

    const checkbox = document.getElementById("acknowledge-rules-cb");
    const launchBtn = document.getElementById("launch-exam-btn");
    if (checkbox && launchBtn) {
      checkbox.addEventListener("change", () => {
        launchBtn.disabled = !checkbox.checked;
      });
      launchBtn.addEventListener("click", () => {
        window.location.href = `/student/exams/${encodeURIComponent(state.examId)}/attempt`;
      });
    }
  } catch (err) {
    container.innerHTML = `
      <div class="card card-body">
        <div class="alert alert-danger mb-4">${escapeHtml(err.message)}</div>
        <a href="/student/dashboard" class="btn btn-secondary">Return to Dashboard</a>
      </div>
    `;
  }
}

loadInstructions();

