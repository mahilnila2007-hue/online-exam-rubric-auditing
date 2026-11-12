/**
 * Examination Creation & Editing page with Question Bank Picker and live mark calculation.
 */

import { api } from "../core/apiClient.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, setButtonLoading, statusBadge, toDatetimeLocalValue } from "../core/ui.js";
import { applyFieldErrors, clearFormErrors } from "../core/validators.js";

const state = JSON.parse(document.getElementById("exam-editor-state").textContent || "{}");
const form = document.getElementById("exam-editor-form");
const pickerList = document.getElementById("question-picker-list");
const searchInput = document.getElementById("picker-search");
const setFilter = document.getElementById("picker-set-filter");
const marksFilter = document.getElementById("picker-marks-filter");
const typeFilter = document.getElementById("picker-type-filter");
const selectVisibleBtn = document.getElementById("picker-select-visible-btn");
const marksBadge = document.getElementById("exam-live-marks-badge");
const negMarkingCb = document.getElementById("exam-neg-marking");
const negFractionSel = document.getElementById("exam-neg-fraction");
const gradeRulesContainer = document.getElementById("grade-rules-container");

const DEFAULT_GRADE_RULES = [
  { grade: "A+", min_percentage: 90 },
  { grade: "A", min_percentage: 80 },
  { grade: "B", min_percentage: 70 },
  { grade: "C", min_percentage: 60 },
  { grade: "D", min_percentage: 50 },
  { grade: "F", min_percentage: 0 },
];

let allQuestions = [];
let selectedQuestionIds = new Set();

function renderGradeRules(rules = DEFAULT_GRADE_RULES) {
  gradeRulesContainer.innerHTML = rules
    .map(
      (r) => `
      <div class="criterion-card" data-grade-row style="padding:0.55rem 0.65rem;gap:0.4rem;">
        <div class="flex items-center justify-between gap-1">
          <input type="text" class="form-input mono fw-semibold" data-grade-label value="${escapeHtml(r.grade)}" placeholder="Grade" style="padding:0.35rem 0.5rem;width:68px;">
          <input type="number" min="0" max="100" step="0.5" class="form-input" data-grade-min value="${r.min_percentage}" placeholder="%" style="padding:0.35rem 0.5rem;width:72px;">
          <button type="button" class="btn btn-ghost btn-sm" data-remove-grade style="padding:2px 6px;color:var(--danger);">&times;</button>
        </div>
      </div>
    `
    )
    .join("");

  gradeRulesContainer.querySelectorAll("[data-remove-grade]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (gradeRulesContainer.querySelectorAll("[data-grade-row]").length <= 1) return;
      btn.closest("[data-grade-row]").remove();
    });
  });
}

function collectGradeRules() {
  return Array.from(gradeRulesContainer.querySelectorAll("[data-grade-row]")).map((row) => ({
    grade: row.querySelector("[data-grade-label]").value.trim().toUpperCase(),
    min_percentage: Number(row.querySelector("[data-grade-min]").value || 0),
  }));
}

negMarkingCb?.addEventListener("change", () => {
  if (negFractionSel) negFractionSel.disabled = !negMarkingCb.checked;
});

document.getElementById("add-grade-rule-btn")?.addEventListener("click", () => {
  const current = collectGradeRules();
  current.push({ grade: "", min_percentage: 0 });
  renderGradeRules(current);
});

function updateMarksBadge() {
  let totalMarks = 0;
  let count = 0;
  allQuestions.forEach((q) => {
    if (selectedQuestionIds.has(q.question_id)) {
      totalMarks += Number(q.marks || 0);
      count += 1;
    }
  });
  marksBadge.textContent = `${totalMarks} Marks · ${count} Questions`;
}

function populatePickerSetFilter() {
  if (!setFilter) return;
  const sets = Array.from(
    new Set(allQuestions.map((q) => (q.question_set || "").trim()).filter(Boolean))
  ).sort((a, b) => a.localeCompare(b));
  const current = setFilter.value;
  setFilter.innerHTML = `<option value="">All Sets</option>${sets
    .map((s) => `<option value="${escapeHtml(s)}" ${s === current ? "selected" : ""}>${escapeHtml(s)}</option>`)
    .join("")}`;
}

function getFilteredPickerQuestions() {
  const needle = (searchInput.value || "").trim().toLowerCase();
  const setVal = (setFilter?.value || "").trim().toLowerCase();
  const marksVal = marksFilter?.value ? Number(marksFilter.value) : null;
  const typeVal = typeFilter.value;

  return allQuestions.filter((q) => {
    if (typeVal && q.type !== typeVal) return false;
    if (setVal && (q.question_set || "").trim().toLowerCase() !== setVal) return false;
    if (marksVal !== null && Math.abs(Number(q.marks || 0) - marksVal) > 0.01) return false;
    if (needle) {
      const hay = `${q.prompt} ${q.subject} ${q.topic} ${q.question_set || ""}`.toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });
}

function renderQuestionPicker() {
  const filtered = getFilteredPickerQuestions();

  if (!filtered.length) {
    pickerList.innerHTML = `
      <div class="empty-state" style="padding:2rem 1rem;">
        <h3>No Matching Questions</h3>
        <p class="text-xs mb-3">Create MCQ or rubric-backed descriptive questions (or upload an Excel Set) in the Question Bank first.</p>
        <a href="/examiner/questions" class="btn btn-primary btn-sm">Open Question Bank</a>
      </div>
    `;
    return;
  }

  pickerList.innerHTML = filtered
    .map((q) => {
      const checked = selectedQuestionIds.has(q.question_id);
      const setChip = q.question_set
        ? `<span class="badge badge-brand">${escapeHtml(q.question_set)}</span>`
        : "";
      return `
        <label class="picker-item ${checked ? "is-selected" : ""}" style="cursor:pointer;">
          <div class="flex items-start gap-2" style="min-width:0;flex:1;">
            <input type="checkbox" data-pick-qid="${escapeHtml(q.question_id)}" ${checked ? "checked" : ""} style="margin-top:4px;accent-color:var(--brand-accent);">
            <div style="min-width:0;">
              <div class="flex items-center gap-1 flex-wrap mb-1">
                ${statusBadge(q.type)}
                ${setChip}
                <span class="badge badge-neutral">${escapeHtml(q.subject)}</span>
                <span class="badge badge-neutral">${q.marks}m</span>
              </div>
              <div class="text-sm fw-semibold">${escapeHtml(q.prompt.slice(0, 140))}${q.prompt.length > 140 ? "..." : ""}</div>
            </div>
          </div>
        </label>
      `;
    })
    .join("");

  pickerList.querySelectorAll("[data-pick-qid]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const qid = cb.dataset.pickQid;
      if (cb.checked) selectedQuestionIds.add(qid);
      else selectedQuestionIds.delete(qid);
      cb.closest(".picker-item").classList.toggle("is-selected", cb.checked);
      updateMarksBadge();
    });
  });
}

function setDefaultWindow() {
  const now = new Date();
  const start = new Date(now.getTime() + 15 * 60000);
  const end = new Date(start.getTime() + 2 * 3600000);
  form.scheduled_start.value = toDatetimeLocalValue(start.toISOString());
  form.scheduled_end.value = toDatetimeLocalValue(end.toISOString());
}

async function initEditor() {
  try {
    const qRes = await api.get("/api/examiner/questions");
    allQuestions = qRes.data?.questions || [];
    populatePickerSetFilter();

    if (state.mode === "edit" && state.examId) {
      const exRes = await api.get(`/api/examiner/exams/${encodeURIComponent(state.examId)}`);
      const exam = exRes.data.exam;
      form.title.value = exam.title || "";
      form.course_code.value = exam.course_code || "";
      form.status.value = exam.status || "draft";
      form.scheduled_start.value = toDatetimeLocalValue(exam.scheduled_start);
      form.scheduled_end.value = toDatetimeLocalValue(exam.scheduled_end);
      form.duration_minutes.value = exam.duration_minutes || 60;
      form.passing_marks.value = exam.passing_marks ?? 0;
      form.description.value = exam.description || "";
      form.instructions.value = (exam.instructions || []).join("\n");
      form.shuffle_questions.checked = Boolean(exam.shuffle_questions);
      form.allow_review_after_submit.checked = Boolean(exam.allow_review_after_submit);
      form.rubric_audit_enabled.checked = exam.rubric_audit_enabled !== false;
      form.negative_marking_enabled.checked = Boolean(exam.negative_marking_enabled);
      if (negFractionSel) {
        negFractionSel.disabled = !form.negative_marking_enabled.checked;
        if (exam.negative_mark_fraction) {
          negFractionSel.value = String(exam.negative_mark_fraction);
        }
      }
      renderGradeRules(exam.grade_rules?.length ? exam.grade_rules : DEFAULT_GRADE_RULES);
      (exam.question_ids || []).forEach((id) => selectedQuestionIds.add(id));
    } else {
      setDefaultWindow();
      renderGradeRules(DEFAULT_GRADE_RULES);
    }

    renderQuestionPicker();
    updateMarksBadge();
  } catch (err) {
    showToast({ type: "error", title: "Failed to initialize editor", message: err.message });
  }
}

form?.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearFormErrors(form);

  const startVal = form.scheduled_start.value;
  const endVal = form.scheduled_end.value;

  const errs = {};
  if (form.title.value.trim().length < 3) errs.title = "Enter an examination title (min 3 characters).";
  if (form.course_code.value.trim().length < 2) errs.course_code = "Course code is required.";
  if (!startVal) errs.scheduled_start = "Scheduled start date/time is required.";
  if (!endVal) errs.scheduled_end = "Scheduled end date/time is required.";
  if (startVal && endVal && new Date(endVal) <= new Date(startVal)) {
    errs.scheduled_end = "Scheduled end time must be after start time.";
  }

  const orderedSelectedIds = allQuestions
    .filter((q) => selectedQuestionIds.has(q.question_id))
    .map((q) => q.question_id);

  if (["published", "scheduled"].includes(form.status.value) && !orderedSelectedIds.length) {
    errs.question_ids = "Select at least one question before scheduling or publishing.";
  }

  if (Object.keys(errs).length) {
    applyFieldErrors(form, errs);
    return;
  }

  const payload = {
    title: form.title.value.trim(),
    course_code: form.course_code.value.trim().toUpperCase(),
    status: form.status.value,
    scheduled_start: new Date(startVal).toISOString(),
    scheduled_end: new Date(endVal).toISOString(),
    duration_minutes: Number(form.duration_minutes.value),
    passing_marks: Number(form.passing_marks.value || 0),
    description: form.description.value.trim(),
    instructions: form.instructions.value
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean),
    shuffle_questions: form.shuffle_questions.checked,
    allow_review_after_submit: form.allow_review_after_submit.checked,
    rubric_audit_enabled: form.rubric_audit_enabled.checked,
    negative_marking_enabled: form.negative_marking_enabled.checked,
    negative_mark_fraction: form.negative_marking_enabled.checked ? Number(form.negative_mark_fraction.value || 0.25) : 0,
    grade_rules: collectGradeRules(),
    question_ids: orderedSelectedIds,
  };

  const btn = document.getElementById("save-exam-btn");
  setButtonLoading(btn, true, "Saving examination...");
  try {
    if (state.mode === "edit" && state.examId) {
      await api.put(`/api/examiner/exams/${encodeURIComponent(state.examId)}`, payload);
      showToast({ type: "success", title: "Examination updated", message: "Your changes have been saved." });
    } else {
      await api.post("/api/examiner/exams", payload);
      showToast({ type: "success", title: "Examination created", message: "Redirecting to Examiner Studio..." });
    }
    window.setTimeout(() => {
      window.location.href = "/examiner/dashboard";
    }, 650);
  } catch (err) {
    setButtonLoading(btn, false);
    if (err.details?.fields) applyFieldErrors(form, err.details.fields);
    showToast({ type: "error", title: "Could not save examination", message: err.message });
  }
});

searchInput?.addEventListener("input", renderQuestionPicker);
setFilter?.addEventListener("change", renderQuestionPicker);
marksFilter?.addEventListener("change", renderQuestionPicker);
typeFilter?.addEventListener("change", renderQuestionPicker);
selectVisibleBtn?.addEventListener("click", () => {
  const visible = getFilteredPickerQuestions();
  if (!visible.length) return;
  const allSelected = visible.every((q) => selectedQuestionIds.has(q.question_id));
  visible.forEach((q) => {
    if (allSelected) selectedQuestionIds.delete(q.question_id);
    else selectedQuestionIds.add(q.question_id);
  });
  renderQuestionPicker();
  updateMarksBadge();
});

initEditor();

