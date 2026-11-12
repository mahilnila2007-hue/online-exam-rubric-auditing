/**
 * Phase 3 Intelligent Rubric Auditing Dashboard:
 * - Run NLP rubric gap analysis with configurable confidence thresholds
 * - Filter pending / approved / rejected gaps by examination and criterion
 * - Inspect side-by-side expected vs detected phrasing & student excerpts
 * - Approve (triggers rubric versioning + re-evaluation) or Reject with full audit history
 */

import { api } from "../core/apiClient.js";
import { closeModal, openModal } from "../core/modal.js";
import { openRubricVersionsModal } from "../core/rubricVersions.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, formatDateTime, formatMetadataChips, setButtonLoading, statusBadge } from "../core/ui.js";

const state = JSON.parse(document.getElementById("rubric-audit-state").textContent || "{}");

const runExamSelect = document.getElementById("run-audit-exam-select");
const thresholdInput = document.getElementById("audit-threshold-range");
const thresholdLabel = document.getElementById("audit-threshold-label");
const filterStatus = document.getElementById("filter-audit-status");
const filterExam = document.getElementById("filter-audit-exam");
const filterCriterion = document.getElementById("filter-audit-criterion");
const suggestionsContainer = document.getElementById("audit-panel-suggestions");
const historyTbody = document.getElementById("audit-history-tbody");

let initializedFilters = false;

function switchTab(tab) {
  document.querySelectorAll("[data-audit-tab]").forEach((b) =>
    b.classList.toggle("active", b.dataset.auditTab === tab)
  );
  document.getElementById("audit-panel-suggestions").classList.toggle("hidden", tab !== "suggestions");
  document.getElementById("audit-panel-history").classList.toggle("hidden", tab !== "history");
  document.getElementById("audit-filter-bar").classList.toggle("hidden", tab !== "suggestions");
}

document.querySelectorAll("[data-audit-tab]").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.auditTab));
});

thresholdInput?.addEventListener("input", () => {
  thresholdLabel.textContent = `${Math.round(Number(thresholdInput.value) * 100)}%`;
});

function populateDropdowns(exams = [], criteriaOptions = []) {
  const prevRunVal = runExamSelect.value || state.initialExamId || "";
  const prevExamFilter = filterExam.value || state.initialExamId || "";
  const prevCritFilter = filterCriterion.value || "";

  runExamSelect.innerHTML =
    `<option value="">Select an examination...</option>` +
    exams
      .map(
        (e) =>
          `<option value="${escapeHtml(e.exam_id)}">${escapeHtml(e.course_code)} · ${escapeHtml(e.title)} (${e.descriptive_count} descriptive)</option>`
      )
      .join("");

  filterExam.innerHTML =
    `<option value="">All Examinations</option>` +
    exams
      .map((e) => `<option value="${escapeHtml(e.exam_id)}">${escapeHtml(e.course_code)} · ${escapeHtml(e.title)}</option>`)
      .join("");

  filterCriterion.innerHTML =
    `<option value="">All Criteria</option>` +
    criteriaOptions
      .map((c) => `<option value="${escapeHtml(c.criterion_id)}">${escapeHtml(c.title)}</option>`)
      .join("");

  if (prevRunVal) runExamSelect.value = prevRunVal;
  if (!initializedFilters && state.initialExamId) {
    filterExam.value = state.initialExamId;
    initializedFilters = true;
  } else if (prevExamFilter) {
    filterExam.value = prevExamFilter;
  }
  if (prevCritFilter) filterCriterion.value = prevCritFilter;
}

function renderSuggestionCards(suggestions = []) {
  if (!suggestions.length) {
    suggestionsContainer.innerHTML = `
      <div class="card card-body">
        <div class="empty-state">
          <h3>No Rubric Gap Suggestions Found</h3>
          <p class="text-sm">Select an examination above and click <strong>Run Intelligent Rubric Audit</strong>, or adjust your active filters.</p>
        </div>
      </div>
    `;
    return;
  }

  suggestionsContainer.innerHTML = suggestions
    .map((s) => {
      const confPct = Math.round(Number(s.confidence_score || 0) * 100);
      const excerptsHtml = (s.sample_excerpts || [])
        .map(
          (ex) => `
          <div style="border:1px solid var(--border-default);border-radius:var(--radius-sm);padding:0.75rem;background:var(--bg-surface);">
            <div class="flex items-center justify-between gap-2 mb-1 flex-wrap">
              <span class="fw-semibold text-xs">${escapeHtml(ex.student_name)} ${ex.institution_id ? `(${escapeHtml(ex.institution_id)})` : ""}</span>
              <span class="text-xs text-muted tabular-nums">
                Similarity: ${Math.round(Number(ex.similarity_score || 0) * 100)}%
                · Criterion Score: ${ex.awarded_marks ?? "—"} / ${ex.criterion_max_marks}
              </span>
            </div>
            <div class="text-sm" style="color:var(--text-primary);">&ldquo;${escapeHtml(ex.excerpt)}&rdquo;</div>
          </div>
        `
        )
        .join("");

      let footerSection = "";
      if (s.status === "pending") {
        footerSection = `
          <div class="flex items-center justify-between gap-3 flex-wrap mt-4" style="border-top:1px solid var(--border-default);padding-top:1rem;">
            <span class="text-xs text-muted">No marks or rubrics change until you explicitly approve this suggestion.</span>
            <div class="flex items-center gap-2">
              <button type="button" class="btn btn-danger-outline btn-sm" data-reject-sug="${escapeHtml(s.suggestion_id)}">Reject Suggestion</button>
              <button type="button" class="btn btn-success btn-sm" data-approve-sug="${escapeHtml(s.suggestion_id)}">Approve &amp; Re-evaluate</button>
            </div>
          </div>
        `;
      } else if (s.status === "approved") {
        const reeval = s.reevaluation_summary || {};
        const changes = (reeval.score_changes || [])
          .map(
            (c) =>
              `<li class="text-xs">${escapeHtml(c.student_name)}: criterion ${c.previous_criterion_marks} &rarr; <strong>${c.updated_criterion_marks}</strong> (Total: ${c.previous_total_score ?? "—"} &rarr; <strong>${c.updated_total_score}</strong>)</li>`
          )
          .join("");
        footerSection = `
          <div class="alert alert-success mt-4" style="display:block;">
            <div class="text-sm fw-semibold">
              Approved by ${escapeHtml(s.decision?.decided_by_name || "Examiner")} (${escapeHtml(formatDateTime(s.decision?.decided_at))})
              · Rubric v${s.decision?.previous_rubric_version ?? s.rubric_version} &rarr; v${s.decision?.new_rubric_version ?? (s.rubric_version + 1)}
            </div>
            <div class="text-xs mt-1">
              Added phrase: <strong>&ldquo;${escapeHtml(s.decision?.approved_phrase || s.suggested_phrase)}&rdquo;</strong>
              · Re-evaluated ${reeval.affected_count ?? 0} submission(s), updated marks on ${reeval.updated_count ?? 0}.
            </div>
            ${changes ? `<ul style="margin:0.45rem 0 0 1.2rem;padding:0;">${changes}</ul>` : ""}
          </div>
        `;
      } else {
        footerSection = `
          <div class="alert alert-neutral mt-4" style="background:var(--bg-subtle);border-color:var(--border-default);display:block;">
            <div class="text-sm fw-semibold">Rejected by ${escapeHtml(s.decision?.decided_by_name || "Examiner")} (${escapeHtml(formatDateTime(s.decision?.decided_at))})</div>
            <div class="text-xs text-secondary mt-1">Reason: ${escapeHtml(s.decision?.reason || "No reason provided.")} · Original rubric unchanged.</div>
          </div>
        `;
      }

      return `
        <article class="card">
          <div class="card-header">
            <div style="min-width:0;">
              <div class="flex items-center gap-2 flex-wrap mb-1">
                <span class="badge badge-brand mono">${escapeHtml(s.course_code)}</span>
                ${statusBadge(s.status)}
                <span class="badge badge-neutral">${s.affected_count} Affected Submission(s)</span>
                <span class="badge badge-violet">Criterion: ${escapeHtml(s.criterion_title)} (${s.criterion_max_marks}m)</span>
              </div>
              <div class="text-sm fw-semibold">${escapeHtml(s.question_prompt)}</div>
            </div>

            <div style="min-width:140px;text-align:right;">
              <div class="text-xs text-muted">Confidence Score</div>
              <div class="fw-semibold mono" style="font-size:1.15rem;color:var(--brand-primary);">${confPct}%</div>
              <div style="height:6px;background:var(--bg-subtle);border-radius:999px;overflow:hidden;margin-top:4px;">
                <div style="height:100%;width:${confPct}%;background:linear-gradient(90deg,#2563eb,#059669);"></div>
              </div>
            </div>
          </div>

          <div class="card-body">
            <div class="form-grid mb-3">
              <div class="criterion-card" style="background:var(--bg-subtle);">
                <div class="text-xs fw-semibold text-muted" style="text-transform:uppercase;">Expected Rubric Phrase</div>
                <div class="fw-semibold" style="font-size:1rem;">${escapeHtml(s.expected_phrase)}</div>
                <div class="flex items-center justify-between gap-2 flex-wrap">
                  <span class="text-xs text-secondary">Rubric: ${escapeHtml(s.rubric_title)} (v${s.rubric_version})</span>
                  ${s.rubric_id ? `<button type="button" class="btn btn-secondary btn-sm" data-ver-rubric="${escapeHtml(s.rubric_id)}" data-rubric-title="${escapeHtml(s.rubric_title)}">Version History</button>` : ""}
                </div>
              </div>
              <div class="criterion-card" style="background:var(--brand-soft);border-color:var(--brand-border);">
                <div class="text-xs fw-semibold" style="color:var(--brand-primary);text-transform:uppercase;">Detected Alternative Phrase</div>
                <div class="fw-semibold" style="font-size:1rem;color:var(--brand-primary);">&ldquo;${escapeHtml(s.suggested_phrase)}&rdquo;</div>
                <div class="text-xs text-secondary">Not present in rubric keywords or existing alternatives</div>
              </div>
            </div>

            <div class="alert alert-info mb-3">
              <div class="text-xs"><strong>Audit Rationale:</strong> ${escapeHtml(s.explanation)}</div>
            </div>

            <details>
              <summary class="text-sm fw-semibold" style="cursor:pointer;">Inspect Affected Student Answer Excerpts (${(s.sample_excerpts || []).length})</summary>
              <div style="display:grid;gap:0.55rem;margin-top:0.75rem;">${excerptsHtml}</div>
            </details>

            ${footerSection}
          </div>
        </article>
      `;
    })
    .join("");

  suggestionsContainer.querySelectorAll("[data-approve-sug]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sug = suggestions.find((x) => x.suggestion_id === btn.dataset.approveSug);
      if (sug) openApproveModal(sug);
    });
  });

  suggestionsContainer.querySelectorAll("[data-reject-sug]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sug = suggestions.find((x) => x.suggestion_id === btn.dataset.rejectSug);
      if (sug) openRejectModal(sug);
    });
  });

  suggestionsContainer.querySelectorAll("[data-ver-rubric]").forEach((btn) => {
    btn.addEventListener("click", () => openRubricVersionsModal(btn.dataset.verRubric, btn.dataset.rubricTitle));
  });
}

function renderAuditHistory(history = []) {
  if (!history.length) {
    historyTbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><h3>No Audit History Yet</h3></div></td></tr>`;
    return;
  }
  historyTbody.innerHTML = history
    .map(
      (h) => `
      <tr>
        <td class="text-xs">${escapeHtml(formatDateTime(h.created_at))}</td>
        <td><span class="badge badge-neutral mono">${escapeHtml(h.event_type)}</span></td>
        <td class="text-sm fw-semibold">${escapeHtml(h.actor_name)}</td>
        <td>${formatMetadataChips(h.details || {}, { maxItems: 6 })}</td>
      </tr>
    `
    )
    .join("");
}

function openApproveModal(sug) {
  const modal = openModal({
    title: "Approve Rubric Alternative Phrase",
    bodyHtml: `
      <p class="text-sm text-secondary mb-3">
        Approving this suggestion archives <strong>v${sug.rubric_version}</strong> of <em>${escapeHtml(sug.rubric_title)}</em>, adds the phrase to criterion <strong>${escapeHtml(sug.criterion_title)}</strong>, and re-evaluates affected student responses.
      </p>
      <div class="form-group mb-3">
        <label class="form-label" for="approve-phrase-input">Alternative Phrase to Add</label>
        <input id="approve-phrase-input" type="text" class="form-input" value="${escapeHtml(sug.suggested_phrase)}">
      </div>
      <div class="form-group">
        <label class="form-label" for="approve-note-input">Examiner Approval Note (Optional)</label>
        <textarea id="approve-note-input" class="form-textarea" rows="2" placeholder="Record rationale for accepting this phrasing..."></textarea>
      </div>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" id="confirm-approve-btn" class="btn btn-success">Approve, Version &amp; Re-evaluate</button>
    `,
  });

  modal.querySelector("#confirm-approve-btn").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    const phrase = modal.querySelector("#approve-phrase-input").value.trim();
    const note = modal.querySelector("#approve-note-input").value.trim();
    if (!phrase) {
      showToast({ type: "error", message: "Phrase cannot be empty." });
      return;
    }
    setButtonLoading(btn, true, "Updating rubric...");
    try {
      const res = await api.post(`/api/examiner/audit/suggestions/${encodeURIComponent(sug.suggestion_id)}/approve`, {
        phrase_override: phrase,
        approval_note: note,
      });
      const re = res.data?.reevaluation_summary || {};
      closeModal();
      showToast({
        type: "success",
        title: "Rubric Updated & Re-evaluated",
        message: `Added '${phrase}'. Re-evaluated ${re.affected_count ?? 0} submission(s); ${re.updated_count ?? 0} score(s) updated.`,
      });
      loadDashboard();
    } catch (err) {
      setButtonLoading(btn, false);
      showToast({ type: "error", title: "Approval failed", message: err.message });
    }
  });
}

function openRejectModal(sug) {
  const modal = openModal({
    title: "Reject Suggested Phrase",
    bodyHtml: `
      <p class="text-sm text-secondary mb-3">
        Rejecting <strong>&ldquo;${escapeHtml(sug.suggested_phrase)}&rdquo;</strong> keeps the original rubric unchanged and does not alter any student marks.
      </p>
      <div class="form-group">
        <label class="form-label" for="reject-reason-input">Rejection Reason (Optional)</label>
        <textarea id="reject-reason-input" class="form-textarea" rows="3" placeholder="e.g., Concept lacks required technical precision for full rubric credit..."></textarea>
      </div>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" id="confirm-reject-btn" class="btn btn-danger">Confirm Rejection</button>
    `,
  });

  modal.querySelector("#confirm-reject-btn").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    const reason = modal.querySelector("#reject-reason-input").value.trim();
    setButtonLoading(btn, true, "Rejecting...");
    try {
      await api.post(`/api/examiner/audit/suggestions/${encodeURIComponent(sug.suggestion_id)}/reject`, {
        reason,
      });
      closeModal();
      showToast({ type: "info", title: "Suggestion Rejected", message: "Original rubric remains unchanged." });
      loadDashboard();
    } catch (err) {
      setButtonLoading(btn, false);
      showToast({ type: "error", title: "Rejection failed", message: err.message });
    }
  });
}

async function loadDashboard() {
  try {
    const params = new URLSearchParams();
    if (filterStatus.value) params.set("status", filterStatus.value);
    const exVal = initializedFilters ? filterExam.value : (state.initialExamId || filterExam.value);
    if (exVal) params.set("exam_id", exVal);
    if (filterCriterion.value) params.set("criterion_id", filterCriterion.value);

    const res = await api.get(`/api/examiner/audit?${params.toString()}`);
    const data = res.data;
    const s = data.summary || {};

    document.getElementById("aud-kpi-pending").textContent = s.pending_count ?? 0;
    document.getElementById("aud-kpi-approved").textContent = s.approved_count ?? 0;
    document.getElementById("aud-kpi-rejected").textContent = s.rejected_count ?? 0;
    document.getElementById("aud-kpi-affected").textContent = s.affected_submissions ?? 0;

    populateDropdowns(data.exams || [], data.criteria_options || []);
    renderSuggestionCards(data.suggestions || []);
    renderAuditHistory(data.history || []);
  } catch (err) {
    showToast({ type: "error", title: "Could not load audit dashboard", message: err.message });
  }
}

document.getElementById("run-audit-btn")?.addEventListener("click", async (ev) => {
  const examId = runExamSelect.value;
  if (!examId) {
    showToast({ type: "warning", message: "Please select an examination with descriptive questions first." });
    return;
  }
  const btn = ev.currentTarget;
  setButtonLoading(btn, true, "Auditing responses...");
  try {
    const res = await api.post(`/api/examiner/exams/${encodeURIComponent(examId)}/audit`, {
      confidence_threshold: Number(thresholdInput.value || 0.56),
    });
    const report = res.data?.report || {};
    showToast({
      type: "success",
      title: "Rubric Audit Complete",
      message: `Analyzed ${report.total_submissions_analyzed ?? 0} submission(s); detected ${report.new_suggestions_created ?? 0} new gap suggestion(s).`,
    });
    filterExam.value = examId;
    loadDashboard();
  } catch (err) {
    showToast({ type: "error", title: "Audit could not run", message: err.message });
  } finally {
    setButtonLoading(btn, false);
  }
});

filterStatus?.addEventListener("change", loadDashboard);
filterExam?.addEventListener("change", loadDashboard);
filterCriterion?.addEventListener("change", loadDashboard);
document.getElementById("audit-refresh-btn")?.addEventListener("click", loadDashboard);

loadDashboard();

