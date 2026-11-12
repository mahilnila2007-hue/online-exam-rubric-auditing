/**
 * Student Examination Interface: timer, question palette, MCQ & descriptive entry, autosave, and submission.
 */

import { api } from "../core/apiClient.js";
import { closeModal, openModal } from "../core/modal.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, formatDurationSeconds, setButtonLoading } from "../core/ui.js";

const state = JSON.parse(document.getElementById("attempt-page-state").textContent || "{}");

let examMeta = null;
let questions = [];
let answers = {}; // { [qid]: { selected_option_id, text_answer, flagged_for_review } }
let currentIndex = 0;
let remainingSeconds = 0;
let timerInterval = null;
let autosaveInterval = null;
let isDirty = false;
let isSubmitting = false;
let paletteFilter = "all";

const stageEl = document.getElementById("question-stage-card");
const paletteEl = document.getElementById("question-palette");
const progressTextEl = document.getElementById("palette-progress-text");
const progressFillEl = document.getElementById("attempt-progress-fill");
const autosaveEl = document.getElementById("autosave-indicator");
const timerPillEl = document.getElementById("exam-timer-pill");
const timerValEl = document.getElementById("exam-timer-value");

function getAnswerState(qid) {
  if (!answers[qid]) {
    answers[qid] = { selected_option_id: null, text_answer: null, flagged_for_review: false };
  }
  return answers[qid];
}

function isQuestionAnswered(qid) {
  const a = answers[qid];
  return Boolean(a && (a.selected_option_id || (a.text_answer && a.text_answer.trim().length > 0)));
}

function setAutosaveStatus(label, variant = "neutral") {
  if (!autosaveEl) return;
  autosaveEl.className = `badge badge-${variant}`;
  autosaveEl.textContent = label;
}

function updateTimerDisplay() {
  if (!timerValEl || !timerPillEl) return;
  timerValEl.textContent = formatDurationSeconds(remainingSeconds);
  timerPillEl.classList.remove("is-warning", "is-critical");
  if (remainingSeconds <= 60) {
    timerPillEl.classList.add("is-critical");
  } else if (remainingSeconds <= 300) {
    timerPillEl.classList.add("is-warning");
  }
}

function renderPalette() {
  if (!paletteEl) return;
  let answeredCount = 0;
  const visibleButtons = [];

  questions.forEach((q, idx) => {
    const answered = isQuestionAnswered(q.question_id);
    if (answered) answeredCount += 1;
    const flagged = Boolean(answers[q.question_id]?.flagged_for_review);

    if (paletteFilter === "unanswered" && answered) return;
    if (paletteFilter === "flagged" && !flagged) return;

    const classes = [
      "palette-btn",
      answered ? "is-answered" : "",
      flagged ? "is-flagged" : "",
      idx === currentIndex ? "is-current" : "",
    ]
      .filter(Boolean)
      .join(" ");
    visibleButtons.push(`<button type="button" class="${classes}" data-nav-idx="${idx}" aria-label="Question ${idx + 1}">${idx + 1}</button>`);
  });

  paletteEl.innerHTML = visibleButtons.length
    ? visibleButtons.join("")
    : `<div class="text-xs text-muted" style="grid-column:1 / -1;text-align:center;padding:0.5rem 0;">${
        paletteFilter === "flagged" ? "No flagged questions." : "All questions answered."
      }</div>`;

  progressTextEl.textContent = `${answeredCount} of ${questions.length} answered`;
  if (progressFillEl) {
    const pct = questions.length ? Math.round((answeredCount / questions.length) * 100) : 0;
    progressFillEl.style.width = `${pct}%`;
  }

  paletteEl.querySelectorAll("[data-nav-idx]").forEach((btn) => {
    btn.addEventListener("click", () => {
      goToQuestion(Number(btn.dataset.navIdx));
    });
  });
}

function renderCurrentQuestion() {
  const q = questions[currentIndex];
  if (!q) return;

  const ans = getAnswerState(q.question_id);
  const flagged = Boolean(ans.flagged_for_review);

  let answerInputHtml = "";
  if (q.type === "mcq") {
    answerInputHtml = `
      <div class="option-list" role="radiogroup" aria-label="Answer options">
        ${(q.options || [])
          .map((opt, idx) => {
            const selected = ans.selected_option_id === opt.id;
            const letter = String.fromCharCode(65 + idx);
            return `
              <label class="option-card ${selected ? "is-selected" : ""}">
                <input type="radio" name="mcq-option" value="${escapeHtml(opt.id)}" ${selected ? "checked" : ""}>
                <div>
                  <span class="fw-semibold mono" style="margin-right:6px;">${letter}.</span>
                  <span>${escapeHtml(opt.text)}</span>
                </div>
              </label>
            `;
          })
          .join("")}
      </div>
      <div class="mt-3">
        <button type="button" id="clear-mcq-btn" class="btn btn-ghost btn-sm">Clear Selected Option</button>
      </div>
    `;
  } else {
    const textVal = ans.text_answer || "";
    const wordCount = textVal.trim() ? textVal.trim().split(/\s+/).length : 0;
    const rubricCriteriaHtml = q.rubric_overview
      ? `
        <div class="alert alert-info mt-4" style="display:block;">
          <div class="fw-semibold text-sm mb-2">Evaluation Rubric Overview (${escapeHtml(q.rubric_overview.title)} · ${q.rubric_overview.max_marks} Marks)</div>
          <ul style="padding-left:1.2rem;margin:0;display:grid;gap:0.3rem;" class="text-xs">
            ${(q.rubric_overview.criteria || [])
              .map((c) => `<li><strong>${escapeHtml(c.title)} (${c.max_marks}m):</strong> ${escapeHtml(c.description || "Evaluated for accuracy & clarity.")}</li>`)
              .join("")}
          </ul>
        </div>
      `
      : "";

    answerInputHtml = `
      <div class="form-group mt-4">
        <label class="form-label" for="descriptive-answer-input">
          <span>Your Descriptive Response</span>
          <span id="word-count-label" class="text-xs text-muted">${wordCount} words · ${textVal.length} chars</span>
        </label>
        <textarea id="descriptive-answer-input" class="form-textarea" rows="10" placeholder="Structure your analytical explanation clearly addressing all rubric criteria...">${escapeHtml(textVal)}</textarea>
      </div>
      ${rubricCriteriaHtml}
    `;
  }

  stageEl.innerHTML = `
    <div class="flex items-center justify-between gap-2 flex-wrap mb-4" style="border-bottom:1px solid var(--border-default);padding-bottom:0.9rem;">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="badge badge-brand">Question ${currentIndex + 1} of ${questions.length}</span>
        <span class="badge badge-${q.type}">${q.type === "mcq" ? "Multiple Choice" : "Descriptive"}</span>
        <span class="badge badge-neutral">${q.marks} Marks</span>
      </div>
      <button type="button" id="flag-question-btn" class="btn ${flagged ? "btn-primary" : "btn-secondary"} btn-sm">
        ${flagged ? "Flagged for Review" : "Flag for Review"}
      </button>
    </div>

    <div class="text-xs text-muted mb-2">${escapeHtml(q.subject)}${q.topic ? ` · ${escapeHtml(q.topic)}` : ""}</div>
    <h2 style="font-size:1.15rem;line-height:1.5;font-weight:600;white-space:pre-wrap;">${escapeHtml(q.prompt)}</h2>

    ${answerInputHtml}

    <div class="flex items-center justify-between gap-3 flex-wrap mt-6" style="border-top:1px solid var(--border-default);padding-top:1rem;">
      <button type="button" id="prev-q-btn" class="btn btn-secondary" ${currentIndex === 0 ? "disabled" : ""}>&larr; Previous</button>
      <div class="flex items-center gap-2">
        ${
          currentIndex < questions.length - 1
            ? `<button type="button" id="next-q-btn" class="btn btn-primary">Save &amp; Next &rarr;</button>`
            : `<button type="button" id="stage-submit-btn" class="btn btn-success">Review &amp; Submit Exam</button>`
        }
      </div>
    </div>
  `;

  // Bind question interactions
  if (q.type === "mcq") {
    stageEl.querySelectorAll('input[name="mcq-option"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        ans.selected_option_id = radio.value;
        isDirty = true;
        setAutosaveStatus("Unsaved changes", "warning");
        renderCurrentQuestion();
        renderPalette();
      });
    });
    document.getElementById("clear-mcq-btn")?.addEventListener("click", () => {
      ans.selected_option_id = null;
      isDirty = true;
      setAutosaveStatus("Unsaved changes", "warning");
      renderCurrentQuestion();
      renderPalette();
    });
  } else {
    const textarea = document.getElementById("descriptive-answer-input");
    const wcLabel = document.getElementById("word-count-label");
    textarea?.addEventListener("input", () => {
      ans.text_answer = textarea.value;
      isDirty = true;
      setAutosaveStatus("Unsaved changes", "warning");
      const trimmed = textarea.value.trim();
      const words = trimmed ? trimmed.split(/\s+/).length : 0;
      wcLabel.textContent = `${words} words · ${textarea.value.length} chars`;
      renderPalette();
    });
  }

  document.getElementById("flag-question-btn")?.addEventListener("click", () => {
    ans.flagged_for_review = !ans.flagged_for_review;
    isDirty = true;
    renderCurrentQuestion();
    renderPalette();
  });

  document.getElementById("prev-q-btn")?.addEventListener("click", () => goToQuestion(currentIndex - 1));
  document.getElementById("next-q-btn")?.addEventListener("click", () => goToQuestion(currentIndex + 1));
  document.getElementById("stage-submit-btn")?.addEventListener("click", openSubmitReviewModal);
}

async function syncProgress(force = false) {
  if (isSubmitting || (!isDirty && !force) || !questions.length) return;
  setAutosaveStatus("Saving...", "upcoming");
  try {
    const res = await api.put(`/api/student/exams/${encodeURIComponent(state.examId)}/answers`, {
      answers,
    });
    isDirty = false;
    if (typeof res.data?.remaining_seconds === "number") {
      remainingSeconds = res.data.remaining_seconds;
      updateTimerDisplay();
    }
    setAutosaveStatus("All changes saved", "success");
  } catch (err) {
    if (err.code === "EXAM_TIME_EXPIRED" || err.code === "EXAM_ALREADY_SUBMITTED") {
      handleSubmissionRedirect(err.details?.submission_id);
      return;
    }
    setAutosaveStatus("Save failed — retrying", "danger");
  }
}

async function goToQuestion(newIdx) {
  if (newIdx < 0 || newIdx >= questions.length) return;
  if (isDirty) {
    await syncProgress(true);
  }
  currentIndex = newIdx;
  renderCurrentQuestion();
  renderPalette();
}

function handleSubmissionRedirect(submissionId) {
  clearInterval(timerInterval);
  clearInterval(autosaveInterval);
  isSubmitting = true;
  if (submissionId) {
    window.location.href = `/student/submissions/${encodeURIComponent(submissionId)}/confirmation`;
  } else {
    window.location.href = "/student/history";
  }
}

async function executeSubmit(autoSubmit = false) {
  if (isSubmitting) return;
  isSubmitting = true;
  clearInterval(timerInterval);
  clearInterval(autosaveInterval);

  try {
    const res = await api.post(`/api/student/exams/${encodeURIComponent(state.examId)}/submit`, {
      answers,
      auto_submit: autoSubmit,
    });
    const subId = res.data?.submission?.submission_id;
    handleSubmissionRedirect(subId);
  } catch (err) {
    isSubmitting = false;
    showToast({ type: "error", title: "Submission failed", message: err.message });
  }
}

function openSubmitReviewModal() {
  const answeredCount = questions.filter((q) => isQuestionAnswered(q.question_id)).length;
  const unansweredCount = questions.length - answeredCount;
  const flaggedCount = questions.filter((q) => Boolean(answers[q.question_id]?.flagged_for_review)).length;

  const modal = openModal({
    title: "Submit Examination?",
    bodyHtml: `
      <div class="kpi-grid mb-4" style="grid-template-columns:repeat(3,1fr);">
        <div class="kpi-card"><div><div class="kpi-label">Answered</div><div class="kpi-value" style="font-size:1.35rem;color:var(--success);">${answeredCount}</div></div></div>
        <div class="kpi-card"><div><div class="kpi-label">Unanswered</div><div class="kpi-value" style="font-size:1.35rem;color:${unansweredCount ? "var(--danger)" : "var(--text-primary)"};">${unansweredCount}</div></div></div>
        <div class="kpi-card"><div><div class="kpi-label">Flagged</div><div class="kpi-value" style="font-size:1.35rem;color:var(--warning);">${flaggedCount}</div></div></div>
      </div>
      <p class="text-sm text-secondary">
        Once submitted, you cannot modify your answers. MCQ questions are graded immediately, and descriptive answers are queued for rubric evaluation.
      </p>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Return to Exam</button>
      <button type="button" id="confirm-final-submit-btn" class="btn btn-success">Confirm Final Submission</button>
    `,
  });

  modal.querySelector("#confirm-final-submit-btn").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    setButtonLoading(btn, true, "Submitting...");
    await executeSubmit(false);
    closeModal();
  });
}

async function initExamAttempt() {
  try {
    const res = await api.post(`/api/student/exams/${encodeURIComponent(state.examId)}/start`, {});
    const data = res.data;
    examMeta = data.exam;
    questions = data.questions || [];
    answers = data.answers || {};
    remainingSeconds = data.remaining_seconds ?? 0;

    document.getElementById("attempt-exam-title").textContent = `${examMeta.course_code} · ${examMeta.title}`;
    setAutosaveStatus("Session synchronized", "success");
    updateTimerDisplay();
    renderCurrentQuestion();
    renderPalette();

    timerInterval = window.setInterval(() => {
      remainingSeconds = Math.max(0, remainingSeconds - 1);
      updateTimerDisplay();
      if (remainingSeconds <= 0) {
        clearInterval(timerInterval);
        showToast({ type: "warning", title: "Time Expired", message: "Submitting your examination automatically..." });
        executeSubmit(true);
      }
    }, 1000);

    autosaveInterval = window.setInterval(() => {
      syncProgress(false);
    }, 15000);
  } catch (err) {
    if (err.code === "EXAM_ALREADY_SUBMITTED" || err.code === "EXAM_TIME_EXPIRED") {
      showToast({ type: "info", title: "Examination Finalized", message: err.message });
      window.setTimeout(() => handleSubmissionRedirect(err.details?.submission_id), 900);
      return;
    }
    stageEl.innerHTML = `
      <div class="alert alert-danger mb-4">${escapeHtml(err.message)}</div>
      <a href="/student/dashboard" class="btn btn-secondary">Back to Dashboard</a>
    `;
    setAutosaveStatus("Unavailable", "danger");
  }
}

document.querySelectorAll("#palette-filter-tabs [data-palette-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    paletteFilter = btn.dataset.paletteFilter || "all";
    document.querySelectorAll("#palette-filter-tabs [data-palette-filter]").forEach((b) =>
      b.classList.toggle("active", b === btn)
    );
    renderPalette();
  });
});

document.addEventListener("keydown", (e) => {
  if (!e.altKey || e.ctrlKey || e.metaKey || isSubmitting) return;
  if (document.querySelector(".modal-backdrop")) return;
  const key = e.key.toLowerCase();
  if (key === "n" && currentIndex < questions.length - 1) {
    e.preventDefault();
    goToQuestion(currentIndex + 1);
  } else if (key === "p" && currentIndex > 0) {
    e.preventDefault();
    goToQuestion(currentIndex - 1);
  }
});

document.getElementById("header-submit-btn")?.addEventListener("click", openSubmitReviewModal);
document.getElementById("sidebar-save-btn")?.addEventListener("click", () => syncProgress(true));

window.addEventListener("beforeunload", (e) => {
  if (isDirty && !isSubmitting) {
    e.preventDefault();
    e.returnValue = "";
  }
});

initExamAttempt();

