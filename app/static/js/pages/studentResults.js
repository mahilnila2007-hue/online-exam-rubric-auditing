/**
 * Student Published Results Portal.
 */

import { api } from "../core/apiClient.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, renderStudentNotifications, statusBadge } from "../core/ui.js";

const tbody = document.getElementById("student-results-tbody");

async function loadResults() {
  try {
    renderStudentNotifications("student-notifications-banner");
    const res = await api.get("/api/student/results");
    const { summary, results } = res.data;

    document.getElementById("res-kpi-total").textContent = summary.published_count ?? 0;
    document.getElementById("res-kpi-passed").textContent = summary.passed_count ?? 0;
    document.getElementById("res-kpi-avg").textContent = `${summary.average_percentage ?? 0}%`;

    if (!results || !results.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8">
            <div class="empty-state">
              <h3>No Published Results Yet</h3>
              <p class="text-sm">Once your examiner finalizes rubric evaluations and publishes results, your official scorecards will appear here.</p>
            </div>
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = results
      .map(
        (r) => `
        <tr>
          <td>
            <div class="fw-semibold">${escapeHtml(r.exam_title)}</div>
            <div class="text-xs text-muted mono">${escapeHtml(r.course_code)}</div>
          </td>
          <td class="tabular-nums text-sm">${r.mcq_score} / ${r.mcq_max_score}</td>
          <td class="tabular-nums text-sm">${r.descriptive_max_score > 0 ? `${r.descriptive_score} / ${r.descriptive_max_score}` : "N/A"}</td>
          <td class="fw-semibold tabular-nums">${r.obtained_marks} / ${r.total_marks}</td>
          <td class="fw-semibold tabular-nums">${r.percentage}%</td>
          <td><span class="badge badge-brand mono">${escapeHtml(r.grade)}</span></td>
          <td>${statusBadge(r.pass_status)}</td>
          <td style="text-align:right;">
            <a href="/student/results/${encodeURIComponent(r.result_id)}" class="btn btn-primary btn-sm">View Report</a>
          </td>
        </tr>
      `
      )
      .join("");
  } catch (err) {
    showToast({ type: "error", title: "Could not load results", message: err.message });
  }
}

document.getElementById("res-refresh-btn")?.addEventListener("click", loadResults);
loadResults();

