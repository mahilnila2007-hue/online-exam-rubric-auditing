/**
 * Question Bank & Structured Descriptive Rubric Builder page.
 */

import { api } from "../core/apiClient.js";
import { closeModal, confirmDialog, openModal } from "../core/modal.js";
import { openRubricVersionsModal } from "../core/rubricVersions.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, setButtonLoading, statusBadge } from "../core/ui.js";
import { applyFieldErrors, clearFormErrors } from "../core/validators.js";

let questions = [];
let rubrics = [];
const knownSets = new Set();

const qTbody = document.getElementById("qb-questions-tbody");
const rTbody = document.getElementById("qb-rubrics-tbody");
const searchInput = document.getElementById("qb-search");
const setFilter = document.getElementById("qb-set-filter");
const marksFilter = document.getElementById("qb-marks-filter");
const typeFilter = document.getElementById("qb-type-filter");
const diffFilter = document.getElementById("qb-difficulty-filter");

function syncSetFilterOptions(items) {
  items.forEach((q) => {
    const s = (q.question_set || "").trim();
    if (s) knownSets.add(s);
  });
  if (!setFilter) return;
  const current = setFilter.value;
  const sorted = Array.from(knownSets).sort((a, b) => a.localeCompare(b));
  setFilter.innerHTML = `<option value="">All Sets</option>${sorted
    .map((s) => `<option value="${escapeHtml(s)}" ${s === current ? "selected" : ""}>${escapeHtml(s)}</option>`)
    .join("")}`;
}

function switchQbTab(tab) {
  document.querySelectorAll("[data-qb-tab]").forEach((b) =>
    b.classList.toggle("active", b.dataset.qbTab === tab)
  );
  document.getElementById("qb-panel-questions").classList.toggle("hidden", tab !== "questions");
  document.getElementById("qb-panel-rubrics").classList.toggle("hidden", tab !== "rubrics");
  document.getElementById("qb-filters").classList.toggle("hidden", tab !== "questions");
}

document.querySelectorAll("[data-qb-tab]").forEach((btn) => {
  btn.addEventListener("click", () => switchQbTab(btn.dataset.qbTab));
});

async function loadData() {
  try {
    const params = new URLSearchParams();
    if (searchInput.value.trim()) params.set("search", searchInput.value.trim());
    if (setFilter?.value) params.set("question_set", setFilter.value);
    if (marksFilter?.value) params.set("marks", marksFilter.value);
    if (typeFilter.value) params.set("type", typeFilter.value);
    if (diffFilter.value) params.set("difficulty", diffFilter.value);

    const [qRes, rRes] = await Promise.all([
      api.get(`/api/examiner/questions?${params.toString()}`),
      api.get("/api/examiner/rubrics"),
    ]);
    questions = qRes.data?.questions || [];
    rubrics = rRes.data?.rubrics || [];
    syncSetFilterOptions(questions);
    renderStatsStrip();
    renderQuestions();
    renderRubrics();
  } catch (err) {
    showToast({ type: "error", title: "Failed to load bank", message: err.message });
  }
}

function renderStatsStrip() {
  const strip = document.getElementById("qb-stats-strip");
  if (!strip) return;
  const total = questions.length;
  const count1 = questions.filter((q) => Number(q.marks) === 1 && q.type === "mcq").length;
  const count2 = questions.filter((q) => Number(q.marks) === 2).length;
  const count5 = questions.filter((q) => Number(q.marks) === 5).length;

  const setChips = Array.from(knownSets)
    .sort((a, b) => a.localeCompare(b))
    .slice(0, 8)
    .map(
      (s) =>
        `<button type="button" class="stat-pill-btn ${setFilter?.value === s ? "is-active" : ""}" data-quick-set="${escapeHtml(s)}">${escapeHtml(s)}</button>`
    )
    .join("");

  strip.innerHTML = `
    <span class="meta-kv-chip"><strong>Showing:</strong> ${total}</span>
    <span class="meta-kv-chip"><strong>1M MCQ:</strong> ${count1}</span>
    <span class="meta-kv-chip"><strong>2-Mark:</strong> ${count2}</span>
    <span class="meta-kv-chip"><strong>5-Mark:</strong> ${count5}</span>
    ${setChips ? `<button type="button" class="stat-pill-btn ${!setFilter?.value ? "is-active" : ""}" data-quick-set="">All Sets</button>${setChips}` : ""}
  `;

  strip.querySelectorAll("[data-quick-set]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (setFilter) {
        setFilter.value = btn.dataset.quickSet || "";
        loadData();
      }
    });
  });
}

function renderQuestions() {
  if (!questions.length) {
    qTbody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="empty-state">
            <h3>Your Question Bank Is Empty</h3>
            <p class="text-sm">Add MCQ or rubric-backed descriptive questions individually, or upload a multi-tier Excel Set.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  qTbody.innerHTML = questions
    .map((q) => {
      let keySummary = "";
      if (q.type === "mcq") {
        const correct = (q.options || []).find((o) => o.id === q.correct_option_id);
        keySummary = `<span class="text-xs"><strong>Key:</strong> ${escapeHtml(correct ? correct.text.slice(0, 48) : q.correct_option_id)}</span>`;
      } else {
        const snap = q.rubric_snapshot;
        keySummary = snap
          ? `<span class="text-xs"><strong>${escapeHtml(snap.title)}</strong> (${(snap.criteria || []).length} criteria)</span>`
          : `<span class="text-xs text-muted">No rubric</span>`;
      }

      const setChip = q.question_set
        ? `<span class="badge badge-brand" style="margin-top:2px;">${escapeHtml(q.question_set)}</span>`
        : "";

      return `
        <tr>
          <td style="max-width:340px;">
            <div class="fw-semibold text-sm">${escapeHtml(q.prompt.slice(0, 115))}${q.prompt.length > 115 ? "..." : ""}</div>
            ${setChip}
          </td>
          <td class="text-sm">
            <div>${escapeHtml(q.subject)}</div>
            <div class="text-xs text-muted">${escapeHtml(q.topic)}</div>
          </td>
          <td>${statusBadge(q.type)}</td>
          <td><span class="badge badge-neutral" style="text-transform:capitalize;">${escapeHtml(q.difficulty)}</span></td>
          <td class="fw-semibold tabular-nums">${q.marks}</td>
          <td>${keySummary}</td>
          <td style="text-align:right;">
            <div class="flex items-center justify-end gap-2">
              <button type="button" class="btn btn-secondary btn-sm" data-preview-q="${escapeHtml(q.question_id)}">Preview</button>
              <button type="button" class="btn btn-secondary btn-sm" data-edit-q="${escapeHtml(q.question_id)}">Edit</button>
              <button type="button" class="btn btn-danger-outline btn-sm" data-del-q="${escapeHtml(q.question_id)}">Archive</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  qTbody.querySelectorAll("[data-preview-q]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = questions.find((item) => item.question_id === btn.dataset.previewQ);
      if (q) openQuestionPreviewModal(q);
    });
  });

  qTbody.querySelectorAll("[data-edit-q]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = questions.find((item) => item.question_id === btn.dataset.editQ);
      if (q) openQuestionModal(q);
    });
  });

  qTbody.querySelectorAll("[data-del-q]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ok = await confirmDialog({
        title: "Archive Question?",
        message: "Archived questions are hidden from new examinations while preserving historical exam records.",
        confirmLabel: "Archive",
        confirmVariant: "danger",
      });
      if (!ok) return;
      try {
        await api.delete(`/api/examiner/questions/${encodeURIComponent(btn.dataset.delQ)}`);
        showToast({ type: "success", title: "Question archived", message: "Removed from active bank." });
        loadData();
      } catch (err) {
        showToast({ type: "error", title: "Archive failed", message: err.message });
      }
    });
  });
}

function renderRubrics() {
  if (!rubrics.length) {
    rTbody.innerHTML = `
      <tr>
        <td colspan="7">
          <div class="empty-state">
            <h3>No Evaluation Rubrics Yet</h3>
            <p class="text-sm">Create reusable analytical rubrics with criteria weights, key concepts, and model answers.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  rTbody.innerHTML = rubrics
    .map(
      (r) => `
      <tr>
        <td class="fw-semibold">${escapeHtml(r.title)}</td>
        <td class="text-sm">${escapeHtml(r.subject)}</td>
        <td class="text-sm">${(r.criteria || []).length} criteria</td>
        <td class="fw-semibold tabular-nums">${r.max_marks}</td>
        <td>${r.model_answer ? '<span class="badge badge-success">Provided</span>' : '<span class="badge badge-neutral">Optional</span>'}</td>
        <td class="mono text-xs">v${r.version || 1}</td>
        <td style="text-align:right;">
          <div class="flex items-center justify-end gap-2">
            <button type="button" class="btn btn-secondary btn-sm" data-ver-r="${escapeHtml(r.rubric_id)}" data-ver-title="${escapeHtml(r.title)}">History</button>
            <button type="button" class="btn btn-secondary btn-sm" data-edit-r="${escapeHtml(r.rubric_id)}">Edit</button>
            <button type="button" class="btn btn-danger-outline btn-sm" data-del-r="${escapeHtml(r.rubric_id)}">Delete</button>
          </div>
        </td>
      </tr>
    `
    )
    .join("");

  rTbody.querySelectorAll("[data-ver-r]").forEach((btn) => {
    btn.addEventListener("click", () => openRubricVersionsModal(btn.dataset.verR, btn.dataset.verTitle));
  });

  rTbody.querySelectorAll("[data-edit-r]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const r = rubrics.find((item) => item.rubric_id === btn.dataset.editR);
      if (r) openRubricModal(r);
    });
  });

  rTbody.querySelectorAll("[data-del-r]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ok = await confirmDialog({
        title: "Delete Rubric?",
        message: "Only rubrics not attached to active descriptive questions can be deleted.",
        confirmLabel: "Delete",
        confirmVariant: "danger",
      });
      if (!ok) return;
      try {
        await api.delete(`/api/examiner/rubrics/${encodeURIComponent(btn.dataset.delR)}`);
        showToast({ type: "success", title: "Rubric deleted", message: "Template removed." });
        loadData();
      } catch (err) {
        showToast({ type: "error", title: "Cannot delete rubric", message: err.message });
      }
    });
  });
}

function openQuestionPreviewModal(q) {
  let detailHtml = "";
  if (q.type === "mcq") {
    detailHtml = `
      <div style="display:grid;gap:0.5rem;">
        ${(q.options || [])
          .map((opt, idx) => {
            const isCorrect = opt.id === q.correct_option_id;
            const letter = String.fromCharCode(65 + idx);
            return `
              <div style="padding:0.65rem 0.85rem;border-radius:var(--radius-sm);border:1px solid ${isCorrect ? "var(--success-border)" : "var(--border-default)"};background:${isCorrect ? "var(--success-soft)" : "var(--bg-surface)"};">
                <span class="mono fw-semibold">${letter}.</span> ${escapeHtml(opt.text)}
                ${isCorrect ? `<span class="badge badge-success" style="margin-left:8px;">Correct Answer</span>` : ""}
              </div>
            `;
          })
          .join("")}
      </div>
      ${q.explanation ? `<div class="alert alert-info mt-3"><div class="text-xs"><strong>Rationale:</strong> ${escapeHtml(q.explanation)}</div></div>` : ""}
    `;
  } else {
    const snap = q.rubric_snapshot;
    const linked = rubrics.find((r) => r.rubric_id === q.rubric_id);
    const modelAnswer = snap?.model_answer || linked?.model_answer || "";
    detailHtml = `
      ${modelAnswer ? `<div class="alert alert-info mb-3"><div class="text-xs"><strong>Reference Model Answer:</strong> ${escapeHtml(modelAnswer)}</div></div>` : ""}
      ${
        snap
          ? `<div style="display:grid;gap:0.55rem;">
              ${(snap.criteria || [])
                .map(
                  (c) => `
                  <div class="criterion-card" style="background:var(--bg-subtle);">
                    <div class="flex items-center justify-between gap-2">
                      <strong>${escapeHtml(c.title)}</strong>
                      <span class="badge badge-brand">${c.max_marks} Marks</span>
                    </div>
                    ${c.description ? `<div class="text-xs text-secondary">${escapeHtml(c.description)}</div>` : ""}
                    <div class="text-xs"><strong>Keywords:</strong> ${escapeHtml((c.key_concepts || []).join(", ") || "—")}</div>
                    ${(c.alternative_phrases || []).length ? `<div class="text-xs text-muted"><strong>Approved Alternatives:</strong> ${escapeHtml(c.alternative_phrases.join(", "))}</div>` : ""}
                  </div>
                `
                )
                .join("")}
            </div>`
          : `<div class="text-sm text-muted">No rubric attached.</div>`
      }
    `;
  }

  openModal({
    title: `Question Preview · ${q.marks} Marks (${q.type.toUpperCase()})`,
    size: "lg",
    bodyHtml: `
      <div class="flex items-center gap-2 flex-wrap mb-3">
        ${statusBadge(q.type)}
        <span class="badge badge-neutral" style="text-transform:capitalize;">${escapeHtml(q.difficulty)}</span>
        <span class="badge badge-neutral">${escapeHtml(q.subject)} / ${escapeHtml(q.topic || "General")}</span>
        ${q.question_set ? `<span class="badge badge-brand">Set: ${escapeHtml(q.question_set)}</span>` : ""}
      </div>
      <div class="card card-body mb-4" style="background:var(--bg-subtle);padding:1rem;white-space:pre-wrap;font-weight:600;">${escapeHtml(q.prompt)}</div>
      ${detailHtml}
    `,
    footerHtml: `<button type="button" class="btn btn-primary" data-modal-close>Close</button>`,
  });
}

function buildCriteriaRowHtml(c = {}, idx = 0) {
  return `
    <div class="criterion-card" data-criterion-row>
      <div class="flex items-center justify-between gap-2">
        <span class="text-xs fw-semibold text-muted">Criterion #${idx + 1}</span>
        <button type="button" class="btn btn-ghost btn-sm" data-remove-crit style="color:var(--danger);padding:2px 6px;">Remove</button>
      </div>
      <div class="form-grid">
        <div class="form-group">
          <label class="form-label">Criterion Title <span class="form-required">*</span></label>
          <input type="text" class="form-input" data-crit-title value="${escapeHtml(c.title || "")}" placeholder="e.g., Algorithmic Complexity Analysis" required>
        </div>
        <div class="form-group">
          <label class="form-label">Max Marks <span class="form-required">*</span></label>
          <input type="number" step="0.5" min="0.5" class="form-input" data-crit-marks value="${c.max_marks ?? 5}" required>
        </div>
        <div class="form-group span-2">
          <label class="form-label">Evaluation Descriptor</label>
          <input type="text" class="form-input" data-crit-desc value="${escapeHtml(c.description || "")}" placeholder="What qualifies for full credit on this criterion...">
        </div>
        <div class="form-group span-2">
          <label class="form-label">Expected Concepts / Keywords (comma-separated)</label>
          <input type="text" class="form-input" data-crit-concepts value="${escapeHtml((c.key_concepts || []).join(", "))}" placeholder="e.g., consensus, quorum, fault tolerance, Raft">
        </div>
        <div class="form-group span-2">
          <label class="form-label">Alternative Acceptable Phrases (comma-separated)</label>
          <input type="text" class="form-input" data-crit-alternatives value="${escapeHtml((c.alternative_phrases || []).join(", "))}" placeholder="e.g., majority agreement, randomized backoff, split vote resolution">
        </div>
      </div>
    </div>
  `;
}

function collectCriteria(container) {
  return Array.from(container.querySelectorAll("[data-criterion-row]")).map((row) => ({
    title: row.querySelector("[data-crit-title]").value.trim(),
    max_marks: Number(row.querySelector("[data-crit-marks]").value || 0),
    description: row.querySelector("[data-crit-desc]").value.trim(),
    key_concepts: row
      .querySelector("[data-crit-concepts]")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean),
    alternative_phrases: row
      .querySelector("[data-crit-alternatives]")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  }));
}

function wireCriteriaBuilder(container, addBtn, initialCriteria = []) {
  const list = initialCriteria.length
    ? initialCriteria
    : [{ title: "Conceptual Accuracy", max_marks: 5, description: "Core principles explained accurately", key_concepts: [] }];

  const renderRows = (rows) => {
    container.innerHTML = rows.map((c, i) => buildCriteriaRowHtml(c, i)).join("");
    container.querySelectorAll("[data-remove-crit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (container.querySelectorAll("[data-criterion-row]").length <= 1) {
          showToast({ type: "warning", message: "At least one criterion is required." });
          return;
        }
        btn.closest("[data-criterion-row]").remove();
      });
    });
  };

  renderRows(list);
  addBtn.addEventListener("click", () => {
    const current = collectCriteria(container);
    current.push({ title: "", max_marks: 2, description: "", key_concepts: [] });
    renderRows(current);
  });
}

function openRubricModal(existing = null) {
  const linkedRubric = existing?.rubric_id ? rubrics.find((r) => r.rubric_id === existing.rubric_id) : null;
  const initialModelAnswer = existing?.rubric_snapshot?.model_answer || linkedRubric?.model_answer || "";

  const modal = openModal({
    title: existing ? "Edit Evaluation Rubric" : "New Evaluation Rubric Template",
    size: "lg",
    bodyHtml: `
      <form id="rubric-modal-form" novalidate>
        <div class="form-grid mb-3">
          <div class="form-group">
            <label class="form-label">Rubric Title <span class="form-required">*</span></label>
            <input name="title" type="text" class="form-input" value="${escapeHtml(existing?.title || "")}" placeholder="e.g., Distributed Consensus Essay Rubric" required>
            <div class="form-error" data-error-for="title"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Subject <span class="form-required">*</span></label>
            <input name="subject" type="text" class="form-input" value="${escapeHtml(existing?.subject || "")}" placeholder="e.g., Distributed Systems" required>
            <div class="form-error" data-error-for="subject"></div>
          </div>
          <div class="form-group span-2">
            <label class="form-label">Reference Model Answer (for Phase 2/3 Auditing)</label>
            <textarea name="model_answer" class="form-textarea" rows="3" placeholder="Ideal reference response used to benchmark consistency...">${escapeHtml(existing?.model_answer || "")}</textarea>
          </div>
        </div>

        <div class="flex items-center justify-between mb-2">
          <span class="fw-semibold text-sm">Rubric Criteria</span>
          <button type="button" id="modal-add-crit-btn" class="btn btn-secondary btn-sm">+ Add Criterion</button>
        </div>
        <div class="form-error mb-2" data-error-for="criteria"></div>
        <div id="modal-criteria-container" style="display:grid;gap:0.75rem;"></div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" id="save-rubric-modal-btn" class="btn btn-primary">${existing ? "Update Rubric" : "Create Rubric"}</button>
    `,
  });

  const form = modal.querySelector("#rubric-modal-form");
  wireCriteriaBuilder(
    modal.querySelector("#modal-criteria-container"),
    modal.querySelector("#modal-add-crit-btn"),
    existing?.criteria || []
  );

  modal.querySelector("#save-rubric-modal-btn").addEventListener("click", async (ev) => {
    clearFormErrors(form);
    const payload = {
      title: form.title.value.trim(),
      subject: form.subject.value.trim(),
      model_answer: form.model_answer.value.trim(),
      criteria: collectCriteria(modal.querySelector("#modal-criteria-container")),
    };
    const btn = ev.currentTarget;
    setButtonLoading(btn, true, "Saving...");
    try {
      if (existing) {
        await api.put(`/api/examiner/rubrics/${encodeURIComponent(existing.rubric_id)}`, payload);
        showToast({ type: "success", title: "Rubric updated", message: "Changes saved." });
      } else {
        await api.post("/api/examiner/rubrics", payload);
        showToast({ type: "success", title: "Rubric created", message: "Available in rubric bank." });
      }
      closeModal();
      loadData();
    } catch (err) {
      setButtonLoading(btn, false);
      if (err.details?.fields) applyFieldErrors(form, err.details.fields);
      showToast({ type: "error", title: "Validation error", message: err.message });
    }
  });
}

function openQuestionModal(existing = null) {
  const initialType = existing?.type || "mcq";
  const initialOptions = existing?.options?.length
    ? existing.options
    : [
        { id: "opt_1", text: "" },
        { id: "opt_2", text: "" },
        { id: "opt_3", text: "" },
        { id: "opt_4", text: "" },
      ];

  const linkedRubric = existing?.rubric_id ? rubrics.find((r) => r.rubric_id === existing.rubric_id) : null;
  const initialModelAnswer = existing?.rubric_snapshot?.model_answer || linkedRubric?.model_answer || "";

  const modal = openModal({
    title: existing ? "Edit Question" : "Add Question to Bank",
    size: "lg",
    bodyHtml: `
      <form id="question-modal-form" novalidate>
        <div class="form-grid mb-3">
          <div class="form-group">
            <label class="form-label">Question Type</label>
            <select name="type" id="q-type-select" class="form-select">
              <option value="mcq" ${initialType === "mcq" ? "selected" : ""}>Multiple Choice (MCQ)</option>
              <option value="descriptive" ${initialType === "descriptive" ? "selected" : ""}>Descriptive (Rubric-Backed)</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Difficulty</label>
            <select name="difficulty" class="form-select">
              <option value="easy" ${existing?.difficulty === "easy" ? "selected" : ""}>Easy</option>
              <option value="medium" ${!existing || existing?.difficulty === "medium" ? "selected" : ""}>Medium</option>
              <option value="hard" ${existing?.difficulty === "hard" ? "selected" : ""}>Hard</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Subject <span class="form-required">*</span></label>
            <input name="subject" type="text" class="form-input" value="${escapeHtml(existing?.subject || "")}" placeholder="e.g., Operating Systems" required>
            <div class="form-error" data-error-for="subject"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Topic</label>
            <input name="topic" type="text" class="form-input" value="${escapeHtml(existing?.topic || "")}" placeholder="e.g., Deadlock Avoidance">
          </div>
          <div class="form-group">
            <label class="form-label">Marks <span class="form-required">*</span></label>
            <input name="marks" id="q-marks-input" type="number" min="0.5" step="0.5" class="form-input" value="${existing?.marks ?? (initialType === "mcq" ? 2 : 10)}" required>
            <div class="form-error" data-error-for="marks"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Question Set / Group</label>
            <input name="question_set" type="text" class="form-input" value="${escapeHtml(existing?.question_set || "")}" placeholder="e.g., Midterm Set A">
            <div class="form-error" data-error-for="question_set"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Tags (comma-separated)</label>
            <input name="tags" type="text" class="form-input" value="${escapeHtml((existing?.tags || []).join(", "))}" placeholder="e.g., midterm, theory">
          </div>
          <div class="form-group span-2">
            <label class="form-label">Question Prompt <span class="form-required">*</span></label>
            <textarea name="prompt" class="form-textarea" rows="3" placeholder="Enter the complete, unambiguous question statement..." required>${escapeHtml(existing?.prompt || "")}</textarea>
            <div class="form-error" data-error-for="prompt"></div>
          </div>
        </div>

        <!-- MCQ Section -->
        <div id="q-mcq-section" class="${initialType === "mcq" ? "" : "hidden"}">
          <div class="flex items-center justify-between mb-2">
            <span class="fw-semibold text-sm">Answer Options (Select the correct answer radio)</span>
            <button type="button" id="q-add-opt-btn" class="btn btn-secondary btn-sm">+ Add Option</button>
          </div>
          <div class="form-error mb-2" data-error-for="options"></div>
          <div class="form-error mb-2" data-error-for="correct_option_id"></div>
          <div id="mcq-options-container" style="display:grid;gap:0.6rem;margin-bottom:1rem;"></div>
          <div class="form-group">
            <label class="form-label">Post-Submit Rationale / Explanation (Optional)</label>
            <input name="explanation" type="text" class="form-input" value="${escapeHtml(existing?.explanation || "")}" placeholder="Shown during post-submission review if enabled.">
          </div>
        </div>

        <!-- Descriptive Rubric Section -->
        <div id="q-desc-section" class="${initialType === "descriptive" ? "" : "hidden"}">
          <div class="form-group mb-3">
            <label class="form-label">Rubric Assignment Mode</label>
            <select id="q-rubric-mode" class="form-select">
              <option value="inline" ${!existing?.rubric_id ? "selected" : ""}>Define / Customize Rubric Inline</option>
              ${rubrics.length ? `<option value="existing" ${existing?.rubric_id ? "selected" : ""}>Link Existing Rubric Template</option>` : ""}
            </select>
          </div>

          <div id="q-existing-rubric-box" class="hidden form-group mb-3">
            <label class="form-label">Select Rubric Template (total marks must match question marks)</label>
            <select name="rubric_id" id="q-rubric-select" class="form-select">
              <option value="">Choose rubric...</option>
              ${rubrics
                .map(
                  (r) =>
                    `<option value="${escapeHtml(r.rubric_id)}" ${existing?.rubric_id === r.rubric_id ? "selected" : ""}>${escapeHtml(r.title)} (${r.max_marks} marks · ${(r.criteria || []).length} criteria)</option>`
                )
                .join("")}
            </select>
            <div class="form-error" data-error-for="rubric_id"></div>
          </div>

          <div id="q-inline-rubric-box">
            <div class="form-grid mb-3">
              <div class="form-group">
                <label class="form-label">Rubric Title</label>
                <input id="inline-rubric-title" type="text" class="form-input" value="${escapeHtml(existing?.rubric_snapshot?.title || "Analytical Evaluation Rubric")}">
              </div>
              <div class="form-group">
                <label class="form-label">Reference Model Answer</label>
                <input id="inline-rubric-model" type="text" class="form-input" value="${escapeHtml(initialModelAnswer)}" placeholder="Key points expected in ideal answer...">
              </div>
            </div>
            <div class="flex items-center justify-between mb-2">
              <span class="fw-semibold text-sm">Evaluation Criteria (must sum to Question Marks)</span>
              <button type="button" id="q-add-crit-btn" class="btn btn-secondary btn-sm">+ Add Criterion</button>
            </div>
            <div class="form-error mb-2" data-error-for="criteria"></div>
            <div class="form-error mb-2" data-error-for="rubric"></div>
            <div id="q-inline-criteria" style="display:grid;gap:0.7rem;"></div>
          </div>
        </div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" id="save-question-modal-btn" class="btn btn-primary">${existing ? "Save Question" : "Create Question"}</button>
    `,
  });

  const form = modal.querySelector("#question-modal-form");
  const typeSelect = modal.querySelector("#q-type-select");
  const rubricMode = modal.querySelector("#q-rubric-mode");
  const existingBox = modal.querySelector("#q-existing-rubric-box");
  const inlineBox = modal.querySelector("#q-inline-rubric-box");
  const optionsContainer = modal.querySelector("#mcq-options-container");
  const addOptBtn = modal.querySelector("#q-add-opt-btn");

  let optionItems = initialOptions.map((o) => ({ id: o.id, text: o.text || "" }));
  let selectedCorrectId = existing?.correct_option_id || optionItems[0]?.id || "opt_1";

  const captureOptionEdits = () => {
    const rows = Array.from(optionsContainer.querySelectorAll("[data-opt-id]"));
    if (rows.length) {
      optionItems = rows.map((inp) => ({ id: inp.dataset.optId, text: inp.value }));
      const checked = optionsContainer.querySelector('input[name="correct_option_id"]:checked');
      if (checked) selectedCorrectId = checked.value;
    }
  };

  const renderMcqOptions = () => {
    optionsContainer.innerHTML = optionItems
      .map(
        (opt, i) => `
        <div class="flex items-center gap-2" data-opt-row>
          <input type="radio" name="correct_option_id" value="${escapeHtml(opt.id)}" ${selectedCorrectId === opt.id ? "checked" : ""} style="accent-color:var(--success);width:18px;height:18px;">
          <input type="text" class="form-input" data-opt-id="${escapeHtml(opt.id)}" value="${escapeHtml(opt.text)}" placeholder="Option ${String.fromCharCode(65 + i)}">
          ${optionItems.length > 2 ? `<button type="button" class="btn btn-ghost btn-sm" data-remove-opt="${escapeHtml(opt.id)}" style="color:var(--danger);padding:4px 8px;">&times;</button>` : ""}
        </div>
      `
      )
      .join("");

    optionsContainer.querySelectorAll("[data-remove-opt]").forEach((btn) => {
      btn.addEventListener("click", () => {
        captureOptionEdits();
        if (optionItems.length <= 2) return;
        const rmId = btn.dataset.removeOpt;
        optionItems = optionItems.filter((o) => o.id !== rmId);
        if (selectedCorrectId === rmId) selectedCorrectId = optionItems[0]?.id || "";
        renderMcqOptions();
      });
    });
  };

  renderMcqOptions();
  addOptBtn?.addEventListener("click", () => {
    captureOptionEdits();
    if (optionItems.length >= 6) {
      showToast({ type: "warning", message: "Maximum 6 options allowed per MCQ question." });
      return;
    }
    const nextIdx = optionItems.length + 1;
    let candidateId = `opt_${nextIdx}`;
    const existingIds = new Set(optionItems.map((o) => o.id));
    let n = nextIdx;
    while (existingIds.has(candidateId)) {
      n += 1;
      candidateId = `opt_${n}`;
    }
    optionItems.push({ id: candidateId, text: "" });
    renderMcqOptions();
  });

  const syncVisibility = () => {
    const isMcq = typeSelect.value === "mcq";
    modal.querySelector("#q-mcq-section").classList.toggle("hidden", !isMcq);
    modal.querySelector("#q-desc-section").classList.toggle("hidden", isMcq);
    if (!isMcq) {
      const useExisting = rubricMode.value === "existing";
      existingBox.classList.toggle("hidden", !useExisting);
      inlineBox.classList.toggle("hidden", useExisting);
    }
  };

  typeSelect.addEventListener("change", syncVisibility);
  rubricMode.addEventListener("change", syncVisibility);
  syncVisibility();

  const initialCrit = existing?.rubric_snapshot?.criteria?.length
    ? existing.rubric_snapshot.criteria
    : [
        { title: "Conceptual Accuracy", max_marks: 6, description: "Correct explanation of core mechanism", key_concepts: [] },
        { title: "Examples & Justification", max_marks: 4, description: "Concrete examples or trade-off analysis", key_concepts: [] },
      ];
  wireCriteriaBuilder(
    modal.querySelector("#q-inline-criteria"),
    modal.querySelector("#q-add-crit-btn"),
    initialCrit
  );

  modal.querySelector("#save-question-modal-btn").addEventListener("click", async (ev) => {
    clearFormErrors(form);
    const qType = typeSelect.value;
    const payload = {
      type: qType,
      difficulty: form.difficulty.value,
      subject: form.subject.value.trim(),
      topic: form.topic.value.trim(),
      marks: Number(form.marks.value || 0),
      question_set: form.question_set?.value?.trim() || "",
      tags: form.tags.value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      prompt: form.prompt.value.trim(),
      explanation: form.explanation?.value?.trim() || "",
    };

    if (qType === "mcq") {
      const options = Array.from(modal.querySelectorAll("[data-opt-id]"))
        .map((inp) => ({ id: inp.dataset.optId, text: inp.value.trim() }))
        .filter((o) => o.text.length > 0);
      const checkedRadio = modal.querySelector('input[name="correct_option_id"]:checked');
      payload.options = options;
      payload.correct_option_id = checkedRadio ? checkedRadio.value : "";
    } else if (rubricMode.value === "existing") {
      payload.rubric_id = form.rubric_id.value;
    } else {
      payload.rubric = {
        title: modal.querySelector("#inline-rubric-title").value.trim() || "Analytical Rubric",
        subject: payload.subject || "General",
        model_answer: modal.querySelector("#inline-rubric-model").value.trim(),
        criteria: collectCriteria(modal.querySelector("#q-inline-criteria")),
      };
    }

    const btn = ev.currentTarget;
    setButtonLoading(btn, true, "Saving...");
    try {
      if (existing) {
        await api.put(`/api/examiner/questions/${encodeURIComponent(existing.question_id)}`, payload);
        showToast({ type: "success", title: "Question updated", message: "Changes saved to bank." });
      } else {
        await api.post("/api/examiner/questions", payload);
        showToast({ type: "success", title: "Question created", message: "Added to question bank." });
      }
      closeModal();
      loadData();
    } catch (err) {
      setButtonLoading(btn, false);
      if (err.details?.fields) applyFieldErrors(form, err.details.fields);
      showToast({ type: "error", title: "Could not save question", message: err.message });
    }
  });
}

function buildExcelFormData(modal, mode) {
  const fileInput = modal.querySelector("#excel-file-input");
  const file = fileInput?.files?.[0];
  if (!file) {
    throw new Error("Please choose an Excel (.xlsx) or CSV (.csv) file first.");
  }

  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", mode);
  fd.append("default_set_name", modal.querySelector("#excel-set-name").value.trim());
  fd.append("override_set_name", modal.querySelector("#excel-override-set").checked ? "true" : "false");
  fd.append("default_subject", modal.querySelector("#excel-subject").value.trim());
  fd.append("default_topic", modal.querySelector("#excel-topic").value.trim());
  fd.append("default_difficulty", modal.querySelector("#excel-difficulty").value);
  fd.append("skip_invalid", modal.querySelector("#excel-skip-invalid").checked ? "true" : "false");
  fd.append("create_exam", modal.querySelector("#excel-create-exam").checked ? "true" : "false");
  fd.append("exam_title", modal.querySelector("#excel-exam-title").value.trim());
  fd.append("course_code", modal.querySelector("#excel-course-code").value.trim());
  return fd;
}

function renderExcelPreview(panel, data) {
  const tiers = data.tier_summary || {};
  const sets = (data.sets || []).length ? data.sets.join(", ") : "General";
  const rowsHtml = (data.preview_rows || [])
    .slice(0, 60)
    .map((r) => {
      const statusHtml = r.valid
        ? `<span class="badge badge-success">${r.type === "mcq" ? `${r.options_count} options` : `${r.criteria_count} criteria`}</span>`
        : `<span class="badge badge-danger">${escapeHtml(r.error || "Invalid")}</span>`;
      return `
        <tr>
          <td class="mono text-xs">${escapeHtml(r.sheet)} #${r.row}</td>
          <td class="text-xs">${escapeHtml(r.question_set || "—")}</td>
          <td class="text-xs">${r.type ? statusBadge(r.type) : "—"}</td>
          <td class="fw-semibold tabular-nums text-xs">${r.marks ?? "—"}</td>
          <td class="text-xs" style="max-width:240px;">${escapeHtml(r.prompt || "—")}</td>
          <td>${statusHtml}</td>
        </tr>
      `;
    })
    .join("");

  const extraNote =
    (data.preview_rows || []).length > 60
      ? `<div class="text-xs text-muted mt-2">Showing first 60 rows of ${data.preview_rows.length} total.</div>`
      : "";

  panel.classList.remove("hidden");
  panel.innerHTML = `
    <div class="alert ${data.error_count ? "alert-warning" : "alert-success"} mb-3">
      <div>
        <strong>Preview Result:</strong> ${data.valid_count} valid question(s), ${data.error_count} error(s) ·
        <strong>1-Mark MCQ:</strong> ${tiers["1_mark"] || 0} ·
        <strong>2-Mark:</strong> ${tiers["2_mark"] || 0} ·
        <strong>5-Mark:</strong> ${tiers["5_mark"] || 0} ·
        <strong>Sets:</strong> ${escapeHtml(sets)}
      </div>
    </div>
    <div class="table-wrap" style="max-height:260px;overflow-y:auto;border:1px solid var(--border-default);border-radius:var(--radius-sm);">
      <table class="data-table">
        <thead>
          <tr>
            <th>Sheet / Row</th>
            <th>Set</th>
            <th>Type</th>
            <th>Marks</th>
            <th>Question Prompt</th>
            <th>Validation / Rubric</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
    ${extraNote}
  `;
}

function openExcelImportModal() {
  const linkedRubric = existing?.rubric_id ? rubrics.find((r) => r.rubric_id === existing.rubric_id) : null;
  const initialModelAnswer = existing?.rubric_snapshot?.model_answer || linkedRubric?.model_answer || "";

  const modal = openModal({
    title: "Upload Multi-Tier Question Set from Excel",
    size: "lg",
    bodyHtml: `
      <form id="excel-import-form" novalidate>
        <div class="alert alert-info mb-3 flex items-center justify-between gap-3 flex-wrap">
          <div class="text-xs">
            <strong>Supported Workbook Layout:</strong> Use <code>All_In_One_Set</code> (separate 1M MCQ cell + side-by-side Option A–D, spaced 2-Mark, and 5-Mark blocks in one sheet) <strong>or</strong> individual sheets
            <code>1_Mark_MCQ</code>, <code>2_Mark_Questions</code>, and <code>5_Mark_Questions</code> sharing the same <strong>Set Name</strong>.
          </div>
          <a href="/api/examiner/questions/excel-template" class="btn btn-secondary btn-sm" download>Download Sample .xlsx</a>
        </div>

        <div class="form-grid mb-3">
          <div class="form-group span-2">
            <label class="form-label" for="excel-file-input">Excel / CSV File <span class="form-required">*</span></label>
            <input id="excel-file-input" type="file" accept=".xlsx,.xlsm,.csv" class="form-input" required>
            <div class="text-xs text-muted mt-1">Accepts <code>.xlsx</code>, <code>.xlsm</code>, or <code>.csv</code> up to 5 MB (max 500 questions per upload).</div>
          </div>
          <div class="form-group">
            <label class="form-label" for="excel-set-name">Question Set Name</label>
            <input id="excel-set-name" type="text" class="form-input" placeholder="e.g., Midterm Set A">
          </div>
          <div class="form-group">
            <label class="form-label" for="excel-subject">Default Subject (if blank in sheet)</label>
            <input id="excel-subject" type="text" class="form-input" placeholder="e.g., Operating Systems">
          </div>
          <div class="form-group">
            <label class="form-label" for="excel-topic">Default Topic</label>
            <input id="excel-topic" type="text" class="form-input" value="Core Concepts">
          </div>
          <div class="form-group">
            <label class="form-label" for="excel-difficulty">Default Difficulty</label>
            <select id="excel-difficulty" class="form-select">
              <option value="easy">Easy</option>
              <option value="medium" selected>Medium</option>
              <option value="hard">Hard</option>
            </select>
          </div>
        </div>

        <div class="flex flex-wrap gap-3 mb-3">
          <label class="checkbox-row" style="flex:1;min-width:210px;">
            <input type="checkbox" id="excel-override-set">
            <span class="text-xs">Apply Question Set Name above to all sheets/rows</span>
          </label>
          <label class="checkbox-row" style="flex:1;min-width:210px;">
            <input type="checkbox" id="excel-skip-invalid">
            <span class="text-xs">Import valid rows even if some rows fail validation</span>
          </label>
          <label class="checkbox-row" style="flex:1;min-width:210px;">
            <input type="checkbox" id="excel-create-exam">
            <span class="text-xs">Also create a Draft Examination from this Set</span>
          </label>
        </div>

        <div id="excel-exam-options" class="form-grid mb-3 hidden" style="padding:0.85rem;background:var(--bg-subtle);border-radius:var(--radius-sm);">
          <div class="form-group">
            <label class="form-label" for="excel-exam-title">Draft Exam Title</label>
            <input id="excel-exam-title" type="text" class="form-input" placeholder="e.g., OS Midterm Set A Exam">
          </div>
          <div class="form-group">
            <label class="form-label" for="excel-course-code">Course Code</label>
            <input id="excel-course-code" type="text" class="form-input mono" placeholder="e.g., CS401">
          </div>
        </div>

        <div id="excel-preview-panel" class="hidden"></div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" id="excel-preview-btn" class="btn btn-secondary">Validate &amp; Preview</button>
      <button type="button" id="excel-commit-btn" class="btn btn-primary">Import Question Set</button>
    `,
  });

  const createExamCb = modal.querySelector("#excel-create-exam");
  const examOptionsBox = modal.querySelector("#excel-exam-options");
  const previewPanel = modal.querySelector("#excel-preview-panel");
  const previewBtn = modal.querySelector("#excel-preview-btn");
  const commitBtn = modal.querySelector("#excel-commit-btn");

  createExamCb.addEventListener("change", () => {
    examOptionsBox.classList.toggle("hidden", !createExamCb.checked);
  });

  previewBtn.addEventListener("click", async () => {
    try {
      const fd = buildExcelFormData(modal, "preview");
      setButtonLoading(previewBtn, true, "Validating...");
      const res = await api.post("/api/examiner/questions/import-excel", fd);
      setButtonLoading(previewBtn, false);
      renderExcelPreview(previewPanel, res.data);
    } catch (err) {
      setButtonLoading(previewBtn, false);
      showToast({ type: "error", title: "Preview failed", message: err.message });
    }
  });

  commitBtn.addEventListener("click", async () => {
    try {
      const fd = buildExcelFormData(modal, "commit");
      setButtonLoading(commitBtn, true, "Importing...");
      const res = await api.post("/api/examiner/questions/import-excel", fd);
      const data = res.data || {};
      closeModal();
      loadData();

      if (data.created_exam?.exam_id) {
        const exam = data.created_exam;
        showToast({
          type: "success",
          title: `Imported ${data.imported_count} questions & created draft exam`,
          message: `${exam.title} (${exam.total_marks} marks) created.`,
        });
        openModal({
          title: "Question Set Imported & Draft Exam Ready",
          bodyHtml: `
            <p class="text-sm mb-3">
              Imported <strong>${data.imported_count}</strong> question(s) (1M MCQ: ${data.tier_summary?.["1_mark"] || 0},
              2M: ${data.tier_summary?.["2_mark"] || 0}, 5M: ${data.tier_summary?.["5_mark"] || 0}) and created
              draft examination <strong>${escapeHtml(exam.title)}</strong> (${exam.total_marks} total marks).
            </p>
          `,
          footerHtml: `
            <button type="button" class="btn btn-secondary" data-modal-close>Stay in Question Bank</button>
            <a href="/examiner/exams/${encodeURIComponent(exam.exam_id)}/edit" class="btn btn-primary">Open Draft Examination &rarr;</a>
          `,
        });
      } else {
        showToast({
          type: "success",
          title: `Imported ${data.imported_count} question(s)`,
          message: `1M MCQ: ${data.tier_summary?.["1_mark"] || 0} · 2M: ${data.tier_summary?.["2_mark"] || 0} · 5M: ${data.tier_summary?.["5_mark"] || 0}`,
        });
      }
    } catch (err) {
      setButtonLoading(commitBtn, false);
      if (err.details?.preview) {
        renderExcelPreview(previewPanel, err.details.preview);
      }
      showToast({ type: "error", title: "Import failed", message: err.message });
    }
  });
}

document.getElementById("import-excel-btn")?.addEventListener("click", openExcelImportModal);
document.getElementById("new-question-btn")?.addEventListener("click", () => openQuestionModal(null));
document.getElementById("new-rubric-btn")?.addEventListener("click", () => openRubricModal(null));

searchInput?.addEventListener("input", loadData);
setFilter?.addEventListener("change", loadData);
marksFilter?.addEventListener("change", loadData);
typeFilter?.addEventListener("change", loadData);
diffFilter?.addEventListener("change", loadData);

loadData();

