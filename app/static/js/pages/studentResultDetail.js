/**
 * Student Detailed Result Report: grade card, examiner feedback, and rubric criterion marks.
 */

import { api } from "../core/apiClient.js";
import { escapeHtml, formatDateTime, statusBadge } from "../core/ui.js";

const state = JSON.parse(document.getElementById("result-detail-state").textContent || "{}");
const root = document.getElementById("result-detail-root");

async function loadDetail() {
  try {
    const res = await api.get(`/api/student/results/${encodeURIComponent(state.resultId)}`);
    const r = res.data.result;

    const breakdownHtml = (r.question_feedback || [])
      .map((q) => {
        if (q.type === "mcq") {
          const sel = (q.options || []).find((o) => o.id === q.selected_option_id);
          const cor = (q.options || []).find((o) => o.id === q.correct_option_id);
          return `
            <div class="card card-body mb-3" style="padding:1rem;">
              <div class="flex items-center justify-between gap-2 mb-2">
                <span class="badge badge-mcq">Q${q.index} · MCQ</span>
                <span class="fw-semibold text-sm tabular-nums">${q.awarded_marks} / ${q.max_marks} Marks</span>
              </div>
              <div class="fw-semibold mb-2">${escapeHtml(q.prompt)}</div>
              <div class="text-sm"><strong>Your Choice:</strong> ${escapeHtml(sel ? sel.text : "Unanswered")}</div>
              ${cor ? `<div class="text-sm text-secondary mt-1"><strong>Correct Answer:</strong> ${escapeHtml(cor.text)}</div>` : ""}
              ${q.explanation ? `<div class="text-xs text-muted mt-1"><strong>Explanation:</strong> ${escapeHtml(q.explanation)}</div>` : ""}
            </div>
          `;
        }

        const criteriaRows = (q.criteria_scores || [])
          .map(
            (cs) => `
            <tr>
              <td class="fw-semibold text-sm">${escapeHtml(cs.title)}</td>
              <td class="tabular-nums fw-semibold">${cs.awarded_marks ?? 0} / ${cs.max_marks}</td>
              <td class="text-sm text-secondary">${escapeHtml(cs.feedback || "—")}</td>
            </tr>
          `
          )
          .join("");

        return `
          <div class="card card-body mb-4" style="padding:1.1rem;">
            <div class="flex items-center justify-between gap-2 mb-2">
              <span class="badge badge-descriptive">Q${q.index} · Descriptive</span>
              <span class="badge badge-brand tabular-nums">${q.awarded_marks} / ${q.max_marks} Marks</span>
            </div>
            <div class="fw-semibold mb-2">${escapeHtml(q.prompt)}</div>
            <div class="text-sm mb-3" style="background:var(--bg-subtle);padding:0.85rem;border-radius:var(--radius-sm);white-space:pre-wrap;">${escapeHtml(q.student_text || "No response provided.")}</div>
            ${
              criteriaRows
                ? `
                <div class="table-wrap mb-2">
                  <table class="data-table">
                    <thead><tr><th>Rubric Criterion</th><th>Score</th><th>Examiner Feedback</th></tr></thead>
                    <tbody>${criteriaRows}</tbody>
                  </table>
                </div>
              `
                : ""
            }
            ${q.feedback ? `<div class="text-xs text-secondary mt-2"><strong>Question Note:</strong> ${escapeHtml(q.feedback)}</div>` : ""}
          </div>
        `;
      })
      .join("");

    root.innerHTML = `
      <div class="page-header">
        <div>
          <div class="flex items-center gap-2 mb-1">
            <span class="badge badge-brand mono">${escapeHtml(r.course_code)}</span>
            ${statusBadge(r.pass_status)}
            <span class="badge badge-brand mono">Grade ${escapeHtml(r.grade)}</span>
          </div>
          <h1>${escapeHtml(r.exam_title)}</h1>
          <p>Published ${escapeHtml(formatDateTime(r.published_at))} · Evaluated by ${escapeHtml(r.evaluated_by_name || "Examiner")}</p>
        </div>
        <div class="flex items-center gap-2 no-print">
          <button type="button" id="print-result-btn" class="btn btn-secondary">Print Report</button>
          <a href="/student/results" class="btn btn-primary">Back to Results</a>
        </div>
      </div>

      <section class="kpi-grid mb-6">
        <div class="kpi-card"><div><div class="kpi-label">Total Score</div><div class="kpi-value" style="font-size:1.5rem;">${r.obtained_marks} / ${r.total_marks}</div><div class="kpi-meta">Passing: ${r.passing_marks}</div></div></div>
        <div class="kpi-card"><div><div class="kpi-label">Percentage</div><div class="kpi-value" style="font-size:1.5rem;">${r.percentage}%</div><div class="kpi-meta">Grade: ${escapeHtml(r.grade)}</div></div></div>
        <div class="kpi-card"><div><div class="kpi-label">MCQ Score</div><div class="kpi-value" style="font-size:1.5rem;">${r.mcq_score} / ${r.mcq_max_score}</div><div class="kpi-meta">${r.negative_deductions > 0 ? `-${r.negative_deductions} negative penalty` : "Auto-graded"}</div></div></div>
        <div class="kpi-card"><div><div class="kpi-label">Descriptive</div><div class="kpi-value" style="font-size:1.5rem;">${r.descriptive_max_score > 0 ? `${r.descriptive_score} / ${r.descriptive_max_score}` : "N/A"}</div><div class="kpi-meta">Rubric-evaluated</div></div></div>
      </section>

      ${
        r.examiner_feedback
          ? `
          <div class="alert alert-info mb-6">
            <div>
              <div class="fw-semibold mb-1">Examiner Feedback</div>
              <div class="text-sm">${escapeHtml(r.examiner_feedback)}</div>
            </div>
          </div>
        `
          : ""
      }

      ${
        (r.revision_history || []).length
          ? `
          <div class="alert alert-success mb-6" style="display:block;">
            <div class="fw-semibold mb-1">Rubric Audit Re-evaluation Notice</div>
            <ul style="margin:0;padding-left:1.2rem;" class="text-xs">
              ${r.revision_history
                .map(
                  (rev) =>
                    `<li>Updated on ${escapeHtml(formatDateTime(rev.revised_at))}: prior score <strong>${rev.previous_obtained_marks}</strong> (${rev.previous_percentage}% · Grade ${escapeHtml(rev.previous_grade || "—")})</li>`
                )
                .join("")}
            </ul>
          </div>
        `
          : ""
      }

      <h2 class="mb-3" style="font-size:1.15rem;">Detailed Answer &amp; Rubric Breakdown</h2>
      ${breakdownHtml}
    `;
    document.getElementById("print-result-btn")?.addEventListener("click", () => window.print());
  } catch (err) {
    root.innerHTML = `
      <div class="card card-body">
        <div class="alert alert-danger mb-4">${escapeHtml(err.message)}</div>
        <div class="flex items-center gap-2 no-print">
          <button type="button" id="print-result-btn" class="btn btn-secondary">Print Report</button>
          <a href="/student/results" class="btn btn-primary">Back to Results</a>
        </div>
      </div>
    `;
  }
}

loadDetail();

