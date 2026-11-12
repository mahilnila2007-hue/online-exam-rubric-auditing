/**
 * Examiner Dashboard: KPI overview, exam management, status toggling, and submission inspector.
 */

import { api } from "../core/apiClient.js";
import { confirmDialog, openModal } from "../core/modal.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, formatDateTime, formatDurationSeconds, setButtonLoading, statusBadge } from "../core/ui.js";

const tbody = document.getElementById("examiner-exams-tbody");
const statusFilter = document.getElementById("examiner-status-filter");
const searchInput = document.getElementById("examiner-exam-search");

async function loadDashboard() {
  try {
    const params = new URLSearchParams();
    if (statusFilter.value) params.set("status", statusFilter.value);
    if (searchInput?.value?.trim()) params.set("search", searchInput.value.trim());
    const queryStr = params.toString() ? `?${params.toString()}` : "";

    const [examsRes, questionsRes, rubricsRes] = await Promise.all([
      api.get(`/api/examiner/exams${queryStr}`),
      api.get("/api/examiner/questions"),
      api.get("/api/examiner/rubrics"),
    ]);

    const exams = examsRes.data?.exams || [];
    const questions = questionsRes.data?.questions || [];
    const rubrics = rubricsRes.data?.rubrics || [];

    const totalSubs = exams.reduce((acc, e) => acc + (e.submission_count || 0), 0);
    const liveCount = exams.filter((e) => e.status === "published" || e.status === "scheduled").length;

    document.getElementById("ex-kpi-exams").textContent = exams.length;
    document.getElementById("ex-kpi-live").textContent = liveCount;
    document.getElementById("ex-kpi-questions").textContent = questions.length;
    document.getElementById("ex-kpi-rubrics").textContent = `${rubrics.length} rubric templates`;
    document.getElementById("ex-kpi-submissions").textContent = totalSubs;

    renderExamsTable(exams);
  } catch (err) {
    showToast({ type: "error", title: "Failed to load dashboard", message: err.message });
  }
}

function renderExamsTable(exams) {
  if (!exams.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6">
          <div class="empty-state">
            <h3>No Examinations Created Yet</h3>
            <p class="text-sm mb-3">Build your question bank and create your first scheduled examination.</p>
            <a href="/examiner/exams/new" class="btn btn-primary btn-sm">Create Examination</a>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = exams
    .map((exam) => {
      const canPublish = exam.status === "draft" || exam.status === "scheduled";
      const toggleBtn =
        exam.status !== "archived"
          ? canPublish
            ? `<button type="button" class="btn btn-success btn-sm" data-status-exam="${escapeHtml(exam.exam_id)}" data-next-status="published">Publish</button>`
            : `<button type="button" class="btn btn-secondary btn-sm" data-status-exam="${escapeHtml(exam.exam_id)}" data-next-status="archived">Archive</button>`
          : `<button type="button" class="btn btn-secondary btn-sm" data-status-exam="${escapeHtml(exam.exam_id)}" data-next-status="draft">Restore Draft</button>`;

      return `
        <tr>
          <td>
            <div class="flex items-center gap-2">
              <span class="badge badge-brand mono">${escapeHtml(exam.course_code)}</span>
              <span class="fw-semibold">${escapeHtml(exam.title)}</span>
            </div>
            <div class="text-xs text-muted mt-1">${exam.duration_minutes} min · Passing ${exam.passing_marks} / ${exam.total_marks} marks</div>
          </td>
          <td class="text-xs">
            <div><strong>Start:</strong> ${escapeHtml(formatDateTime(exam.scheduled_start))}</div>
            <div><strong>End:</strong> ${escapeHtml(formatDateTime(exam.scheduled_end))}</div>
          </td>
          <td class="text-sm">
            <div>${exam.question_count} Questions</div>
            <div class="text-xs text-muted">${exam.mcq_count} MCQ · ${exam.descriptive_count} Desc</div>
          </td>
          <td>
            <div class="flex flex-wrap gap-1">
              ${statusBadge(exam.status)}
              ${exam.status === "published" ? statusBadge(exam.availability) : ""}
            </div>
          </td>
          <td class="text-sm">
            <span class="fw-semibold">${exam.submission_count || 0}</span> submitted
            ${exam.active_attempt_count ? `<div class="text-xs text-muted">${exam.active_attempt_count} active</div>` : ""}
          </td>
          <td style="text-align:right;">
            <div class="flex items-center justify-end gap-2 flex-wrap">
              <a href="/examiner/exams/${encodeURIComponent(exam.exam_id)}/results" class="btn btn-primary btn-sm">Evaluate &amp; Results</a>
              ${exam.descriptive_count > 0 ? `<a href="/examiner/audit?exam_id=${encodeURIComponent(exam.exam_id)}" class="btn btn-secondary btn-sm">Rubric Audit</a>` : ""}
              <button type="button" class="btn btn-secondary btn-sm" data-view-subs="${escapeHtml(exam.exam_id)}" data-exam-title="${escapeHtml(exam.title)}">Submissions</button>
              <a href="/examiner/exams/${encodeURIComponent(exam.exam_id)}/edit" class="btn btn-secondary btn-sm">Edit</a>
              <button type="button" class="btn btn-secondary btn-sm" data-clone-exam="${escapeHtml(exam.exam_id)}" data-clone-title="${escapeHtml(exam.title)}">Clone Draft</button>
              ${toggleBtn}
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll("[data-status-exam]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const examId = btn.dataset.statusExam;
      const nextStatus = btn.dataset.nextStatus;
      const ok = await confirmDialog({
        title: `Change Status to "${nextStatus}"?`,
        message:
          nextStatus === "published"
            ? "Students will be able to view this examination and attend it during the scheduled window."
            : `Update examination status to ${nextStatus}?`,
        confirmLabel: "Confirm",
      });
      if (!ok) return;
      try {
        await api.patch(`/api/examiner/exams/${encodeURIComponent(examId)}/status`, { status: nextStatus });
        showToast({ type: "success", title: "Status updated", message: `Examination is now ${nextStatus}.` });
        loadDashboard();
      } catch (err) {
        showToast({ type: "error", title: "Update failed", message: err.message });
      }
    });
  });

  tbody.querySelectorAll("[data-view-subs]").forEach((btn) => {
    btn.addEventListener("click", () => openExamSubmissionsModal(btn.dataset.viewSubs, btn.dataset.examTitle));
  });

  tbody.querySelectorAll("[data-clone-exam]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ok = await confirmDialog({
        title: "Clone Examination as Draft?",
        message: `Create a fresh draft copy of "${btn.dataset.cloneTitle || "this examination"}" with the same structure and question list?`,
        confirmLabel: "Clone Draft",
      });
      if (!ok) return;
      setButtonLoading(btn, true, "Cloning...");
      try {
        const res = await api.post(`/api/examiner/exams/${encodeURIComponent(btn.dataset.cloneExam)}/duplicate`, {});
        const cloned = res.data?.exam;
        showToast({
          type: "success",
          title: "Examination cloned",
          message: `Created draft "${cloned?.title || "Copy"}".`,
        });
        loadDashboard();
      } catch (err) {
        setButtonLoading(btn, false);
        showToast({ type: "error", title: "Clone failed", message: err.message });
      }
    });
  });
}

async function openExamSubmissionsModal(examId, examTitle) {
  try {
    const res = await api.get(`/api/examiner/exams/${encodeURIComponent(examId)}/submissions`);
    const subs = res.data?.submissions || [];

    const bodyHtml = subs.length
      ? `
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Student</th>
                <th>Status</th>
                <th>MCQ Score</th>
                <th>Descriptive</th>
                <th>Submitted</th>
                <th style="text-align:right;">Inspect</th>
              </tr>
            </thead>
            <tbody>
              ${subs
                .map(
                  (s) => `
                  <tr>
                    <td>
                      <div class="fw-semibold">${escapeHtml(s.student_name)}</div>
                      <div class="text-xs text-muted">${escapeHtml(s.institution_id || s.student_email)}</div>
                    </td>
                    <td>${statusBadge(s.status)}</td>
                    <td class="fw-semibold">${s.grading?.mcq_score ?? 0} / ${s.grading?.mcq_max_score ?? 0}</td>
                    <td>${statusBadge(s.grading?.evaluation_status || "in_progress")}</td>
                    <td class="text-xs">${escapeHtml(formatDateTime(s.submitted_at || s.started_at))}</td>
                    <td style="text-align:right;">
                      <div class="flex items-center justify-end gap-2">
                        <a href="/examiner/evaluations/${encodeURIComponent(s.submission_id)}" class="btn btn-primary btn-sm">Evaluate</a>
                        <button type="button" class="btn btn-secondary btn-sm" data-inspect-sub="${escapeHtml(s.submission_id)}">Inspect</button>
                      </div>
                    </td>
                  </tr>
                `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      `
      : `<div class="empty-state"><h3>No Submissions Yet</h3><p class="text-sm">Student attempts will appear here once started or submitted.</p></div>`;

    const modal = openModal({
      title: `Submissions · ${examTitle}`,
      size: "lg",
      bodyHtml,
      footerHtml: `<button type="button" class="btn btn-primary" data-modal-close>Close</button>`,
    });

    modal.querySelectorAll("[data-inspect-sub]").forEach((btn) => {
      btn.addEventListener("click", () => openSubmissionInspector(btn.dataset.inspectSub));
    });
  } catch (err) {
    showToast({ type: "error", title: "Could not load submissions", message: err.message });
  }
}

async function openSubmissionInspector(submissionId) {
  try {
    const res = await api.get(`/api/examiner/submissions/${encodeURIComponent(submissionId)}`);
    const sub = res.data.submission;
    const g = sub.grading || {};

    const itemsHtml = (sub.questions || [])
      .map((q) => {
        if (q.type === "mcq") {
          const selected = (q.options || []).find((o) => o.id === q.student_answer?.selected_option_id);
          return `
            <div class="card card-body mb-3" style="padding:1rem;">
              <div class="flex items-center justify-between mb-2">
                <span class="badge badge-mcq">Q${q.index} · MCQ</span>
                <span class="fw-semibold text-sm">${q.awarded_marks ?? 0} / ${q.marks} Marks</span>
              </div>
              <div class="fw-semibold mb-1">${escapeHtml(q.prompt)}</div>
              <div class="text-sm"><strong>Selected:</strong> ${escapeHtml(selected ? selected.text : "No selection")}</div>
            </div>
          `;
        }
        const rubricCriteria = (q.rubric_snapshot?.criteria || [])
          .map(
            (c) =>
              `<div class="text-xs text-secondary">&bull; <strong>${escapeHtml(c.title)} (${c.max_marks}m):</strong> ${escapeHtml(c.description || "Rubric criterion")}</div>`
          )
          .join("");
        return `
          <div class="card card-body mb-3" style="padding:1rem;">
            <div class="flex items-center justify-between mb-2">
              <span class="badge badge-descriptive">Q${q.index} · Descriptive (${q.marks}m)</span>
              <span class="badge badge-warning">Ready for Phase 2/3 Rubric Scoring</span>
            </div>
            <div class="fw-semibold mb-2">${escapeHtml(q.prompt)}</div>
            <div class="text-sm mb-3" style="background:var(--bg-subtle);padding:0.75rem;border-radius:var(--radius-sm);white-space:pre-wrap;">${escapeHtml(q.student_answer?.text_answer || "No answer provided.")}</div>
            ${rubricCriteria ? `<div style="border-top:1px solid var(--border-default);padding-top:0.65rem;"><div class="text-xs fw-semibold mb-1">Attached Rubric Criteria (${escapeHtml(q.rubric_snapshot?.title || "")}):</div>${rubricCriteria}</div>` : ""}
          </div>
        `;
      })
      .join("");

    openModal({
      title: `Submission Inspection · ${sub.student_name}`,
      size: "lg",
      bodyHtml: `
        <div class="flex items-center justify-between flex-wrap gap-2 mb-4">
          <div class="text-sm text-secondary">ID: ${escapeHtml(sub.institution_id || sub.student_email)} · Time used: ${formatDurationSeconds(sub.duration_seconds_used)}</div>
          <div class="fw-semibold">MCQ: ${g.mcq_score} / ${g.mcq_max_score} · Desc Max: ${g.descriptive_max_score}</div>
        </div>
        ${itemsHtml}
      `,
      footerHtml: `<button type="button" class="btn btn-primary" data-modal-close>Done</button>`,
    });
  } catch (err) {
    showToast({ type: "error", title: "Unable to inspect submission", message: err.message });
  }
}

statusFilter?.addEventListener("change", loadDashboard);
searchInput?.addEventListener("input", loadDashboard);
document.getElementById("examiner-refresh-btn")?.addEventListener("click", loadDashboard);

loadDashboard();

