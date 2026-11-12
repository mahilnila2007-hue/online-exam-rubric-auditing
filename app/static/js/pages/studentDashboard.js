/**
 * Student Dashboard: KPI summary and filterable examination cards.
 */

import { api } from "../core/apiClient.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, formatDateTime, formatRelativeWindow, renderStudentNotifications, statusBadge } from "../core/ui.js";

let allExams = [];
let activeFilter = "all";
let searchQuery = "";

const container = document.getElementById("student-exams-container");
const searchInput = document.getElementById("student-exam-search");

function renderSummary(summary = {}) {
  document.getElementById("kpi-live").textContent = summary.live_count ?? 0;
  document.getElementById("kpi-upcoming").textContent = summary.upcoming_count ?? 0;
  document.getElementById("kpi-completed").textContent = summary.completed_count ?? 0;
  document.getElementById("kpi-total").textContent = summary.total_visible ?? 0;
}

function buildActionControl(exam) {
  if (exam.attempt_status === "submitted" || exam.attempt_status === "auto_submitted") {
    return `<a href="/student/submissions/${encodeURIComponent(exam.submission_id)}/confirmation" class="btn btn-secondary btn-sm">View Receipt</a>`;
  }
  if (exam.can_resume) {
    return `<a href="/student/exams/${encodeURIComponent(exam.exam_id)}/attempt" class="btn btn-success btn-sm">Resume Examination</a>`;
  }
  if (exam.can_start) {
    return `<a href="/student/exams/${encodeURIComponent(exam.exam_id)}/instructions" class="btn btn-primary btn-sm">Instructions &amp; Start</a>`;
  }
  if (exam.availability === "upcoming") {
    return `<a href="/student/exams/${encodeURIComponent(exam.exam_id)}/instructions" class="btn btn-secondary btn-sm">Preview Instructions</a>`;
  }
  return `<button type="button" class="btn btn-secondary btn-sm" disabled>Window Closed</button>`;
}

function renderExams() {
  const byTab = activeFilter === "all" ? allExams : allExams.filter((e) => e.availability === activeFilter);
  const list = searchQuery
    ? byTab.filter((e) =>
        [e.title, e.course_code, e.subject, e.description, e.created_by_name]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(searchQuery))
      )
    : byTab;

  if (!list.length) {
    container.innerHTML = `
      <div class="empty-state" style="grid-column:1 / -1;">
        <div class="empty-state-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </div>
        <h3>No Examinations Found</h3>
        <p class="text-sm">There are currently no examinations matching this filter.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = list
    .map((exam) => {
      const attemptChip =
        exam.attempt_status !== "not_started" ? statusBadge(exam.attempt_status) : "";
      const relHint =
        exam.availability === "live"
          ? formatRelativeWindow(exam.scheduled_end, "Closes in", "closed")
          : exam.availability === "upcoming"
            ? formatRelativeWindow(exam.scheduled_start, "Opens in", "opened")
            : "";
      return `
        <article class="card exam-card">
          <div>
            <div class="flex items-center justify-between gap-2 mb-2 flex-wrap">
              <span class="badge badge-brand mono">${escapeHtml(exam.course_code)}</span>
              <div class="flex items-center gap-1 flex-wrap">
                ${statusBadge(exam.availability)}
                ${attemptChip}
              </div>
            </div>

            <h3 style="font-size:1.05rem;margin-top:0.4rem;">${escapeHtml(exam.title)}</h3>
            <p class="text-sm text-secondary mt-1">${escapeHtml(exam.description || "Structured online examination.")}</p>

            <div class="exam-meta-pills">
              <span class="meta-pill">${exam.duration_minutes} mins</span>
              <span class="meta-pill">${exam.question_count} Questions (${exam.mcq_count} MCQ · ${exam.descriptive_count} Desc)</span>
              <span class="meta-pill">${exam.total_marks} Marks</span>
              ${exam.rubric_audit_enabled && exam.descriptive_count > 0 ? '<span class="meta-pill">Rubric Audited</span>' : ""}
            </div>
          </div>

          <div style="border-top:1px solid var(--border-default);padding-top:0.85rem;margin-top:0.5rem;">
            <div class="text-xs text-muted mb-3">
              <div><strong>Opens:</strong> ${escapeHtml(formatDateTime(exam.scheduled_start))}</div>
              <div><strong>Closes:</strong> ${escapeHtml(formatDateTime(exam.scheduled_end))}</div>
              ${relHint ? `<div class="mt-1 fw-semibold" style="color:${exam.availability === "live" ? "var(--success)" : "var(--brand-primary)"};">${escapeHtml(relHint)}</div>` : ""}
            </div>
            <div class="flex items-center justify-between gap-2">
              <span class="text-xs text-muted">By ${escapeHtml(exam.created_by_name)}</span>
              ${buildActionControl(exam)}
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadExams() {
  try {
    const res = await api.get("/api/student/exams");
    allExams = res.data?.exams || [];
    renderSummary(res.data?.summary || {});
    renderExams();
    renderStudentNotifications("student-notifications-banner");
  } catch (err) {
    showToast({ type: "error", title: "Could not load examinations", message: err.message });
    container.innerHTML = `<div class="alert alert-danger" style="grid-column:1 / -1;">${escapeHtml(err.message)}</div>`;
  }
}

document.querySelectorAll("#student-exam-tabs [data-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    activeFilter = btn.dataset.filter;
    document.querySelectorAll("#student-exam-tabs [data-filter]").forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
    renderExams();
  });
});

searchInput?.addEventListener("input", () => {
  searchQuery = searchInput.value.trim().toLowerCase();
  renderExams();
});

document.getElementById("refresh-exams-btn")?.addEventListener("click", loadExams);

loadExams();

