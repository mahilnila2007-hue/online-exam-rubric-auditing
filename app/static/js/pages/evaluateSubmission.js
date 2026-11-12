/**
 * Examiner Rubric Evaluation Studio: criterion-level scoring, feedback, and result publication.
 */

import { api } from "../core/apiClient.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, formatDateTime, formatDurationSeconds, setButtonLoading, statusBadge } from "../core/ui.js";

const state = JSON.parse(document.getElementById("eval-workspace-state").textContent || "{}");
const root = document.getElementById("eval-workspace-root");

let workspace = null;

function computeLocalGrade(obtained, total, passingMarks, gradeRules) {
  const pct = total > 0 ? Math.round((obtained / total) * 10000) / 100 : 0;
  const rules = [...(gradeRules || [])].sort((a, b) => Number(b.min_percentage) - Number(a.min_percentage));
  let grade = "F";
  for (const r of rules) {
    if (pct >= Number(r.min_percentage)) {
      grade = r.grade;
      break;
    }
  }
  const passed = obtained >= Number(passingMarks || 0);
  return { percentage: pct, grade, pass_status: passed ? "PASS" : "FAIL" };
}

function updateLiveTotals() {
  if (!workspace) return;
  const mcqScore = Number(workspace.grading.mcq_score || 0);
  const totalMax = Number(workspace.grading.total_max_score || 0);
  let descScore = 0;

  document.querySelectorAll("[data-question-card]").forEach((qCard) => {
    let qSum = 0;
    qCard.querySelectorAll("[data-crit-score-input]").forEach((inp) => {
      const val = Math.max(0, Math.min(Number(inp.max), Number(inp.value || 0)));
      qSum += val;
    });
    qSum = Math.round(qSum * 100) / 100;
    descScore += qSum;
    const badge = qCard.querySelector("[data-q-score-display]");
    if (badge) badge.textContent = `${qSum} / ${qCard.dataset.qMax} Marks`;
  });

  descScore = Math.round(descScore * 100) / 100;
  const obtained = Math.round((mcqScore + descScore) * 100) / 100;
  const preview = computeLocalGrade(
    obtained,
    totalMax,
    workspace.exam.passing_marks,
    workspace.exam.grade_rules
  );

  document.getElementById("live-desc-score").textContent = `${descScore} / ${workspace.grading.descriptive_max_score}`;
  document.getElementById("live-total-score").textContent = `${obtained} / ${totalMax}`;
  document.getElementById("live-pct-grade").textContent = `${preview.percentage}% · Grade ${preview.grade} (${preview.pass_status})`;
}

function renderWorkspace() {
  const { submission, exam, grading, mcq_questions, descriptive_questions, rubric_audit } = workspace;
  const canAutoRun = grading.evaluation_status === "pending_descriptive";

  const mcqHtml = mcq_questions.length
    ? `
      <div class="card mb-6">
        <div class="card-header">
          <div>
            <h2 class="card-title">Automated MCQ Evaluation Summary</h2>
            <p class="card-subtitle">
              MCQ Score: ${grading.mcq_score} / ${grading.mcq_max_score}
              ${grading.negative_deductions > 0 ? ` · Negative Marking Deductions: -${grading.negative_deductions}` : ""}
            </p>
          </div>
          ${statusBadge("completed", "Auto-Graded")}
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Question</th>
                <th>Selected</th>
                <th>Correct Answer</th>
                <th>Outcome</th>
                <th>Marks</th>
              </tr>
            </thead>
            <tbody>
              ${mcq_questions
                .map((m) => {
                  const selOpt = (m.options || []).find((o) => o.id === m.selected_option_id);
                  const corOpt = (m.options || []).find((o) => o.id === m.correct_option_id);
                  return `
                    <tr>
                      <td class="mono">${m.index}</td>
                      <td class="text-sm">${escapeHtml(m.prompt.slice(0, 95))}${m.prompt.length > 95 ? "..." : ""}</td>
                      <td class="text-sm">${escapeHtml(selOpt ? selOpt.text : "Unanswered")}</td>
                      <td class="text-sm text-secondary">${escapeHtml(corOpt ? corOpt.text : "")}</td>
                      <td>${statusBadge(m.outcome === "correct" ? "pass" : m.outcome === "incorrect" ? "fail" : "neutral", m.outcome)}</td>
                      <td class="fw-semibold tabular-nums">${m.awarded_marks} / ${m.marks}</td>
                    </tr>
                  `;
                })
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `
    : "";

  const descHtml = descriptive_questions
    .map((dq) => {
      const criteriaCards = (dq.criteria || [])
        .map((c) => {
          const matchedSet = new Set(c.matched_concepts || []);
          const altMatchedSet = new Set(c.matched_alternatives || []);
          const conceptChips = (c.key_concepts || [])
            .map((kc) =>
              matchedSet.has(kc)
                ? `<span class="badge badge-success">${escapeHtml(kc)} &check;</span>`
                : `<span class="badge badge-neutral">${escapeHtml(kc)}</span>`
            )
            .join(" ");
          const altChips = (c.alternative_phrases || [])
            .map((ap) =>
              altMatchedSet.has(ap)
                ? `<span class="badge badge-upcoming">${escapeHtml(ap)} &check;</span>`
                : `<span class="badge badge-neutral">${escapeHtml(ap)}</span>`
            )
            .join(" ");

          return `
            <div class="criterion-card" data-crit-row="${escapeHtml(c.criterion_id)}" style="background:var(--bg-surface);">
              <div class="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <div class="fw-semibold">${escapeHtml(c.title)}</div>
                  <div class="text-xs text-muted">${escapeHtml(c.description || "Rubric criterion")}</div>
                </div>
                <span class="badge badge-brand">Max: ${c.max_marks}m · Weight: ${Math.round((c.weight || 0) * 100)}%</span>
              </div>

              ${
                conceptChips || altChips
                  ? `
                  <div class="text-xs">
                    ${conceptChips ? `<div class="mb-1"><strong class="text-secondary">Expected Concepts:</strong> <span class="flex flex-wrap gap-1 mt-1">${conceptChips}</span></div>` : ""}
                    ${altChips ? `<div><strong class="text-secondary">Acceptable Alternatives:</strong> <span class="flex flex-wrap gap-1 mt-1">${altChips}</span></div>` : ""}
                  </div>
                `
                  : `<div class="text-xs text-muted">Manual criterion (no keyword indicators configured).</div>`
              }

              <div class="alert alert-info" style="padding:0.55rem 0.8rem;">
                <div class="text-xs">
                  <strong>Transparent Indicator Summary:</strong> Coverage ${Math.round((c.coverage_ratio || 0) * 100)}% · Preliminary Suggested: <strong>${c.suggested_marks ?? 0} / ${c.max_marks}</strong>
                </div>
              </div>

              <div class="form-grid">
                <div class="form-group">
                  <label class="form-label">Awarded Marks (0 – ${c.max_marks}) <span class="form-required">*</span></label>
                  <input type="number" step="0.25" min="0" max="${c.max_marks}" class="form-input tabular-nums fw-semibold" data-crit-score-input value="${c.awarded_marks ?? 0}">
                </div>
                <div class="form-group">
                  <label class="form-label">Criterion Feedback</label>
                  <input type="text" class="form-input" data-crit-feedback-input value="${escapeHtml(c.feedback || "")}" placeholder="Specific feedback for this criterion...">
                </div>
              </div>
            </div>
          `;
        })
        .join("");

      return `
        <section class="card mb-6" data-question-card data-qid="${escapeHtml(dq.question_id)}" data-q-max="${dq.marks}">
          <div class="card-header">
            <div>
              <div class="flex items-center gap-2 mb-1">
                <span class="badge badge-descriptive">Question ${dq.index} · Descriptive</span>
                <span class="badge badge-neutral">${escapeHtml(dq.rubric.title)} (v${dq.rubric.version})</span>
              </div>
              <h2 class="card-title" style="font-size:1.05rem;">${escapeHtml(dq.prompt)}</h2>
            </div>
            <span class="badge badge-brand" data-q-score-display>0 / ${dq.marks} Marks</span>
          </div>

          <div class="card-body">
            <div class="mb-4">
              <div class="text-xs fw-semibold text-muted mb-1" style="text-transform:uppercase;">Candidate Response</div>
              <div style="background:var(--bg-subtle);border:1px solid var(--border-default);border-radius:var(--radius-md);padding:1rem;white-space:pre-wrap;font-size:0.92rem;">${escapeHtml(dq.student_answer || "Candidate did not submit an answer for this question.")}</div>
            </div>

            ${
              dq.rubric.model_answer
                ? `
                <details class="mb-4" style="background:var(--info-soft);border:1px solid var(--info-border);border-radius:var(--radius-md);padding:0.75rem 1rem;">
                  <summary class="fw-semibold text-sm" style="cursor:pointer;">View Reference Model Answer</summary>
                  <div class="text-sm mt-2" style="white-space:pre-wrap;">${escapeHtml(dq.rubric.model_answer)}</div>
                </details>
              `
                : ""
            }

            <div class="text-xs fw-semibold text-muted mb-2" style="text-transform:uppercase;">Criterion-Level Rubric Scoring</div>
            <div style="display:grid;gap:0.85rem;">${criteriaCards}</div>

            <div class="form-group mt-4">
              <label class="form-label">Question-Level Examiner Notes</label>
              <input type="text" class="form-input" data-q-feedback-input value="${escapeHtml(dq.question_feedback || "")}" placeholder="Optional summary note for this answer...">
            </div>
          </div>
        </section>
      `;
    })
    .join("");

  const historyHtml = (grading.decision_history || []).length
    ? `
      <div class="card mb-6">
        <div class="card-header"><h2 class="card-title">Recorded Examiner Decisions</h2></div>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Timestamp</th><th>Examiner</th><th>Descriptive</th><th>Total</th><th>Feedback Note</th></tr></thead>
            <tbody>
              ${grading.decision_history
                .map(
                  (d) => `
                  <tr>
                    <td class="text-xs">${escapeHtml(formatDateTime(d.evaluated_at))}</td>
                    <td class="text-sm fw-semibold">${escapeHtml(d.evaluated_by_name)}</td>
                    <td class="tabular-nums text-sm">${d.descriptive_score}</td>
                    <td class="tabular-nums fw-semibold text-sm">${d.total_score}</td>
                    <td class="text-xs text-secondary">${escapeHtml(d.examiner_feedback || "—")}</td>
                  </tr>
                `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `
    : "";

  const auditBannerHtml =
    rubric_audit && rubric_audit.audit_status === "flagged"
      ? `
      <div class="alert alert-warning mb-6 justify-between items-center flex-wrap gap-2">
        <div>
          <strong>Rubric Audit Alert (${(rubric_audit.audit_notes || []).length} potential gap(s) flagged)</strong>
          <div class="text-xs mt-1">An answer may express a rubric concept using alternative wording. Review and approve/reject suggestions in the Rubric Audit Dashboard.</div>
        </div>
        <a href="/examiner/audit?exam_id=${encodeURIComponent(exam.exam_id)}" class="btn btn-primary btn-sm">Open Audit Dashboard</a>
      </div>
    `
      : "";

  const evalSnapshotsHtml = (grading.evaluation_history || []).length
    ? `
      <div class="card mb-6">
        <div class="card-header"><h2 class="card-title">Preserved Historical Evaluation Snapshots</h2></div>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Captured At</th><th>Trigger</th><th>Rubric Version</th><th>Prior Descriptive</th><th>Prior Total</th></tr></thead>
            <tbody>
              ${grading.evaluation_history
                .map(
                  (h) => `
                  <tr>
                    <td class="text-xs">${escapeHtml(formatDateTime(h.snapshot_at))}</td>
                    <td class="text-xs mono">${escapeHtml(h.trigger || "snapshot")}</td>
                    <td class="mono text-xs">v${h.rubric_version_before ?? 1}</td>
                    <td class="tabular-nums text-sm">${h.descriptive_score_before ?? "—"}</td>
                    <td class="tabular-nums text-sm">${h.total_score_before ?? "—"}</td>
                  </tr>
                `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `
    : "";

  root.innerHTML = `
    <div class="page-header">
      <div>
        <div class="flex items-center gap-2 mb-1 flex-wrap">
          <span class="badge badge-brand mono">${escapeHtml(exam.course_code)}</span>
          ${statusBadge(grading.evaluation_status)}
          ${statusBadge(submission.publication_status)}
          ${rubric_audit?.audit_status ? statusBadge(rubric_audit.audit_status) : ""}
        </div>
        <h1>Evaluate Submission · ${escapeHtml(submission.student_name)}</h1>
        <p>${escapeHtml(submission.institution_id || submission.student_email)} · Submitted ${escapeHtml(formatDateTime(submission.submitted_at))} · Time used: ${formatDurationSeconds(submission.duration_seconds_used)}</p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <a href="/examiner/exams/${encodeURIComponent(exam.exam_id)}/results" class="btn btn-secondary">Back to Results Console</a>
        <a href="/examiner/audit?exam_id=${encodeURIComponent(exam.exam_id)}" class="btn btn-secondary">Rubric Audit</a>
        ${canAutoRun ? `<button type="button" id="run-precheck-btn" class="btn btn-secondary">Run Preliminary Rubric Check</button>` : ""}
      </div>
    </div>

    ${auditBannerHtml}

    <section class="kpi-grid mb-6">
      <div class="kpi-card"><div><div class="kpi-label">MCQ Marks</div><div class="kpi-value" style="font-size:1.45rem;">${grading.mcq_score} / ${grading.mcq_max_score}</div><div class="kpi-meta">${grading.negative_deductions > 0 ? `-${grading.negative_deductions} penalty` : "Auto-evaluated"}</div></div></div>
      <div class="kpi-card"><div><div class="kpi-label">Descriptive Marks</div><div class="kpi-value" id="live-desc-score" style="font-size:1.45rem;">—</div><div class="kpi-meta">Criterion sum</div></div></div>
      <div class="kpi-card"><div><div class="kpi-label">Live Total</div><div class="kpi-value" id="live-total-score" style="font-size:1.45rem;">—</div><div class="kpi-meta" id="live-pct-grade">Calculating...</div></div></div>
    </section>

    ${mcqHtml}
    ${descHtml}

    <div class="card mb-6">
      <div class="card-header">
        <div>
          <h2 class="card-title">Finalize Examiner Decision &amp; Feedback</h2>
          <p class="card-subtitle">All criterion marks and examiner decisions are saved cleanly for Phase 3 rubric auditing.</p>
        </div>
      </div>
      <div class="card-body">
        <div class="form-group mb-4">
          <label class="form-label" for="overall-examiner-feedback">Overall Examiner Feedback (visible to student upon publication)</label>
          <textarea id="overall-examiner-feedback" class="form-textarea" rows="3" placeholder="Provide constructive summary feedback on strengths, missed concepts, and areas for improvement...">${escapeHtml(grading.examiner_feedback || "")}</textarea>
        </div>

        <div class="flex items-center justify-end gap-3 flex-wrap">
          <button type="button" id="save-eval-btn" class="btn btn-primary btn-lg">Save Evaluation</button>
          <button type="button" id="save-publish-eval-btn" class="btn btn-success btn-lg">Save &amp; Publish Result</button>
        </div>
      </div>
    </div>

    ${historyHtml}
    ${evalSnapshotsHtml}
  `;

  root.querySelectorAll("[data-crit-score-input]").forEach((inp) => {
    inp.addEventListener("input", updateLiveTotals);
  });

  document.getElementById("run-precheck-btn")?.addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    setButtonLoading(btn, true, "Analyzing...");
    try {
      await api.post(`/api/examiner/submissions/${encodeURIComponent(state.submissionId)}/auto-evaluate`, {});
      showToast({ type: "success", title: "Preliminary Check Complete", message: "Suggested criterion marks populated." });
      await loadWorkspace();
    } catch (err) {
      setButtonLoading(btn, false);
      showToast({ type: "error", title: "Pre-check failed", message: err.message });
    }
  });

  document.getElementById("save-eval-btn")?.addEventListener("click", (ev) => submitEvaluation(false, ev.currentTarget));
  document.getElementById("save-publish-eval-btn")?.addEventListener("click", (ev) => submitEvaluation(true, ev.currentTarget));

  updateLiveTotals();
}

async function submitEvaluation(publishResult, btn) {
  const questionEvaluations = {};
  let validationError = null;

  document.querySelectorAll("[data-question-card]").forEach((qCard) => {
    const qid = qCard.dataset.qid;
    const qFeedback = qCard.querySelector("[data-q-feedback-input]")?.value.trim() || "";
    const criteriaScores = [];

    qCard.querySelectorAll("[data-crit-row]").forEach((row) => {
      const cid = row.dataset.critRow;
      const inp = row.querySelector("[data-crit-score-input]");
      const maxVal = Number(inp.max);
      const val = Number(inp.value);
      if (Number.isNaN(val) || val < 0 || val > maxVal) {
        validationError = `Marks must be between 0 and ${maxVal} for every rubric criterion.`;
        inp.classList.add("is-invalid");
      } else {
        inp.classList.remove("is-invalid");
      }
      criteriaScores.push({
        criterion_id: cid,
        awarded_marks: val,
        feedback: row.querySelector("[data-crit-feedback-input]")?.value.trim() || "",
      });
    });

    questionEvaluations[qid] = {
      feedback: qFeedback,
      criteria_scores: criteriaScores,
    };
  });

  if (validationError) {
    showToast({ type: "error", title: "Invalid marks", message: validationError });
    return;
  }

  const payload = {
    examiner_feedback: document.getElementById("overall-examiner-feedback")?.value.trim() || "",
    publish_result: publishResult,
    question_evaluations: questionEvaluations,
  };

  setButtonLoading(btn, true, publishResult ? "Publishing..." : "Saving...");
  try {
    await api.put(`/api/examiner/submissions/${encodeURIComponent(state.submissionId)}/evaluate`, payload);
    showToast({
      type: "success",
      title: publishResult ? "Evaluation Saved & Published" : "Evaluation Saved",
      message: publishResult ? "Student result is now published." : "Scores and examiner decision recorded.",
    });
    await loadWorkspace();
  } catch (err) {
    setButtonLoading(btn, false);
    showToast({ type: "error", title: "Failed to save evaluation", message: err.message });
  }
}

async function loadWorkspace() {
  try {
    const res = await api.get(`/api/examiner/submissions/${encodeURIComponent(state.submissionId)}/evaluation`);
    workspace = res.data;
    renderWorkspace();
  } catch (err) {
    root.innerHTML = `<div class="card card-body"><div class="alert alert-danger">${escapeHtml(err.message)}</div></div>`;
  }
}

loadWorkspace();

