/**
 * Admin Dashboard: user lifecycle provisioning, exam monitoring, reports, and audit logs.
 */

import { api } from "../core/apiClient.js";
import { closeModal, confirmDialog, openModal } from "../core/modal.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, formatDateTime, formatMetadataChips, setButtonLoading, statusBadge } from "../core/ui.js";
import { applyFieldErrors, clearFormErrors, isValidEmail } from "../core/validators.js";

const usersTbody = document.getElementById("admin-users-tbody");
const examsTbody = document.getElementById("admin-exams-tbody");
const auditTbody = document.getElementById("admin-audit-tbody");
const userSearchInput = document.getElementById("admin-user-search");
const roleFilter = document.getElementById("admin-role-filter");
const statusFilter = document.getElementById("admin-status-filter");
const auditRoleFilter = document.getElementById("admin-audit-role-filter");
const auditActionFilter = document.getElementById("admin-audit-action-filter");

let cachedUsers = [];
let cachedAuditLogs = [];

function switchAdminTab(tab) {
  document.querySelectorAll("[data-admin-tab]").forEach((b) =>
    b.classList.toggle("active", b.dataset.adminTab === tab)
  );
  ["users", "approvals", "exams", "audit"].forEach((name) => {
    document.getElementById(`admin-panel-${name}`)?.classList.toggle("hidden", name !== tab);
  });
}

document.querySelectorAll("[data-admin-tab]").forEach((btn) => {
  btn.addEventListener("click", () => switchAdminTab(btn.dataset.adminTab));
});

async function loadOverviewAndUsers() {
  try {
    const userParams = new URLSearchParams();
    if (roleFilter.value) userParams.set("role", roleFilter.value);
    if (statusFilter.value) userParams.set("status", statusFilter.value);

    const [overviewRes, usersRes] = await Promise.all([
      api.get("/api/admin/overview"),
      api.get(`/api/admin/users?${userParams.toString()}`),
    ]);

    const overview = overviewRes.data;
    const m = overview.metrics || {};

    document.getElementById("adm-kpi-users").textContent = m.total_users ?? 0;
    document.getElementById("adm-kpi-roles").textContent =
      `${m.students ?? 0} Students · ${m.examiners ?? 0} Examiners · ${m.admins ?? 0} Admins`;
    document.getElementById("adm-kpi-exams").textContent = m.total_exams ?? 0;
    document.getElementById("adm-kpi-live-exams").textContent =
      `${m.live_exams ?? 0} live · ${m.upcoming_exams ?? 0} upcoming`;
    document.getElementById("adm-kpi-questions").textContent = m.total_questions ?? 0;
    document.getElementById("adm-kpi-rubrics").textContent = `${m.total_rubrics ?? 0} rubrics configured`;
    document.getElementById("adm-kpi-subs").textContent = m.total_submissions ?? 0;
    document.getElementById("adm-kpi-pending").textContent =
      `${m.pending_descriptive_reviews ?? 0} pending rubric review`;

    cachedUsers = usersRes.data?.users || [];
    cachedAuditLogs = overview.recent_activity || [];

    renderFilteredUsers();
    renderPendingApprovals(overview);
    renderExamReports(overview.exam_reports || []);
    if (auditRoleFilter?.value) {
      await loadFilteredAuditLogs();
    } else {
      renderFilteredAuditLogs();
    }
  } catch (err) {
    showToast({ type: "error", title: "Failed to load admin data", message: err.message });
  }
}

function renderFilteredUsers() {
  const query = (userSearchInput?.value || "").trim().toLowerCase();
  const filtered = query
    ? cachedUsers.filter((u) =>
        [u.full_name, u.email, u.institution_id, u.department]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(query))
      )
    : cachedUsers;
  renderUsers(filtered);
}

function renderUsers(users) {
  if (!users.length) {
    usersTbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><h3>No Matching Users</h3></div></td></tr>`;
    return;
  }

  usersTbody.innerHTML = users
    .map((u) => {
      const nextStatus = u.status === "active" ? "suspended" : "active";
      const statusBtnLabel = u.status === "active" ? "Suspend" : "Activate";
      const statusBtnClass = u.status === "active" ? "btn-danger-outline" : "btn-success";
      const isPending = u.status === "pending_approval";
      const isRejected = u.status === "rejected";

      let manageHtml = `<button type="button" class="btn ${statusBtnClass} btn-sm" data-toggle-user="${escapeHtml(u.uid)}" data-next-status="${nextStatus}">${statusBtnLabel}</button>`;
      if (isPending) {
        manageHtml = `
          <div class="flex items-center justify-end gap-2">
            <button type="button" class="btn btn-success btn-sm" data-approve-staff="${escapeHtml(u.uid)}" data-staff-name="${escapeHtml(u.full_name)}">Approve</button>
            <button type="button" class="btn btn-danger-outline btn-sm" data-reject-staff="${escapeHtml(u.uid)}" data-staff-name="${escapeHtml(u.full_name)}">Decline</button>
          </div>
        `;
      } else if (isRejected) {
        manageHtml = `<button type="button" class="btn btn-success btn-sm" data-approve-staff="${escapeHtml(u.uid)}" data-staff-name="${escapeHtml(u.full_name)}">Approve</button>`;
      }

      return `
        <tr>
          <td>
            <div class="fw-semibold">${escapeHtml(u.full_name)}</div>
            <div class="text-xs text-muted">${escapeHtml(u.email)}</div>
          </td>
          <td class="mono text-xs">${escapeHtml(u.institution_id || "—")}</td>
          <td class="text-sm">${escapeHtml(u.department || "—")}</td>
          <td>
            <select class="form-select" data-user-role="${escapeHtml(u.uid)}" ${isPending ? 'disabled title="Approve or decline pending staff request first"' : ""} style="padding:0.35rem 0.55rem;font-size:0.8rem;width:auto;">
              <option value="student" ${u.role === "student" ? "selected" : ""}>Student</option>
              <option value="examiner" ${u.role === "examiner" ? "selected" : ""}>Examiner</option>
              <option value="admin" ${u.role === "admin" ? "selected" : ""}>Admin</option>
            </select>
          </td>
          <td>${statusBadge(u.status)}</td>
          <td style="text-align:right;">
            ${manageHtml}
          </td>
        </tr>
      `;
    })
    .join("");

  wireStaffDecisionButtons(usersTbody);

  usersTbody.querySelectorAll("[data-user-role]").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const uid = sel.dataset.userRole;
      const newRole = sel.value;
      try {
        await api.patch(`/api/admin/users/${encodeURIComponent(uid)}`, { role: newRole });
        showToast({ type: "success", title: "Role updated", message: `Assigned role: ${newRole}.` });
        loadOverviewAndUsers();
      } catch (err) {
        showToast({ type: "error", title: "Role update failed", message: err.message });
        loadOverviewAndUsers();
      }
    });
  });

  usersTbody.querySelectorAll("[data-toggle-user]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const uid = btn.dataset.toggleUser;
      const nextStatus = btn.dataset.nextStatus;
      const ok = await confirmDialog({
        title: nextStatus === "suspended" ? "Suspend User Account?" : "Activate User Account?",
        message:
          nextStatus === "suspended"
            ? "The user will be immediately blocked from signing in or submitting examinations."
            : "The user will regain platform access.",
        confirmLabel: nextStatus === "suspended" ? "Suspend" : "Activate",
        confirmVariant: nextStatus === "suspended" ? "danger" : "success",
      });
      if (!ok) return;
      try {
        await api.patch(`/api/admin/users/${encodeURIComponent(uid)}`, { status: nextStatus });
        showToast({ type: "success", title: "Account updated", message: `Account is now ${nextStatus}.` });
        loadOverviewAndUsers();
      } catch (err) {
        showToast({ type: "error", title: "Status update failed", message: err.message });
      }
    });
  });
}

function renderExamReports(reports) {
  if (!reports.length) {
    examsTbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><h3>No Examinations Recorded</h3></div></td></tr>`;
    return;
  }

  examsTbody.innerHTML = reports
    .map(
      (r) => `
      <tr>
        <td>
          <a href="/examiner/audit?exam_id=${encodeURIComponent(r.exam_id)}" class="fw-semibold" style="color:var(--brand-primary);text-decoration:none;">
            ${escapeHtml(r.title)}
          </a>
          <div class="text-xs text-muted mono">${escapeHtml(r.course_code)} · ${r.question_count} Qs (${r.total_marks}m) · <a href="/examiner/audit?exam_id=${encodeURIComponent(r.exam_id)}">Inspect Rubric Audit</a></div>
        </td>
        <td class="text-sm">${escapeHtml(r.created_by_name)}</td>
        <td class="text-xs">${escapeHtml(formatDateTime(r.scheduled_start))}</td>
        <td>${statusBadge(r.status)} ${r.status === "published" ? statusBadge(r.availability) : ""}</td>
        <td class="text-sm">${r.total_attempts} / ${r.completed_submissions}</td>
        <td class="fw-semibold tabular-nums">${r.avg_mcq_score}</td>
        <td class="text-sm">${r.pending_descriptive}</td>
      </tr>
    `
    )
    .join("");
}

async function loadFilteredAuditLogs() {
  try {
    const params = new URLSearchParams({ limit: "150" });
    if (auditRoleFilter?.value) params.set("actor_role", auditRoleFilter.value);
    const res = await api.get(`/api/admin/audit-logs?${params.toString()}`);
    cachedAuditLogs = res.data?.logs || [];
    renderFilteredAuditLogs();
  } catch (err) {
    showToast({ type: "error", title: "Failed to filter audit logs", message: err.message });
  }
}

function renderFilteredAuditLogs() {
  const query = (auditActionFilter?.value || "").trim().toLowerCase();
  const filtered = query
    ? cachedAuditLogs.filter((l) =>
        [l.action, l.actor_email, l.target_type, l.target_id]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(query))
      )
    : cachedAuditLogs;
  renderAuditLogs(filtered);
}

function renderAuditLogs(logs) {
  if (!logs.length) {
    auditTbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><h3>No Activity Logs Match Filter</h3></div></td></tr>`;
    return;
  }

  auditTbody.innerHTML = logs
    .map(
      (l) => `
      <tr>
        <td class="text-xs">${escapeHtml(formatDateTime(l.created_at))}</td>
        <td>
          <div class="text-sm fw-semibold">${escapeHtml(l.actor_email)}</div>
          <div class="text-xs text-muted" style="text-transform:capitalize;">${escapeHtml(l.actor_role)}</div>
        </td>
        <td><span class="badge badge-neutral mono">${escapeHtml(l.action)}</span></td>
        <td class="text-xs mono">${escapeHtml(l.target_type)}:${escapeHtml(l.target_id)}</td>
        <td>${formatMetadataChips(l.metadata || {})}</td>
      </tr>
    `
    )
    .join("");
}

document.getElementById("admin-create-user-btn")?.addEventListener("click", () => {
  const modal = openModal({
    title: "Provision Platform Account",
    bodyHtml: `
      <form id="admin-user-form" novalidate>
        <div class="form-grid">
          <div class="form-group span-2">
            <label class="form-label">Full Name <span class="form-required">*</span></label>
            <input name="full_name" type="text" class="form-input" placeholder="Dr. Elena Vance" required>
            <div class="form-error" data-error-for="full_name"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Email Address <span class="form-required">*</span></label>
            <input name="email" type="email" class="form-input" placeholder="elena.vance@university.edu" required>
            <div class="form-error" data-error-for="email"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Role <span class="form-required">*</span></label>
            <select name="role" class="form-select">
              <option value="examiner">Examiner</option>
              <option value="student">Student</option>
              <option value="admin">Administrator</option>
            </select>
            <div class="form-error" data-error-for="role"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Institution ID <span class="form-required">*</span></label>
            <input name="institution_id" type="text" class="form-input" placeholder="FAC-204" required>
            <div class="form-error" data-error-for="institution_id"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Department</label>
            <input name="department" type="text" class="form-input" placeholder="Computer Science">
          </div>
          <div class="form-group span-2">
            <label class="form-label">Temporary Password (min 8 chars) <span class="form-required">*</span></label>
            <input name="password" type="password" class="form-input" placeholder="Minimum 8 characters" required>
            <div class="form-error" data-error-for="password"></div>
          </div>
        </div>
      </form>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" id="admin-submit-user-btn" class="btn btn-primary">Create Account</button>
    `,
  });

  const form = modal.querySelector("#admin-user-form");
  modal.querySelector("#admin-submit-user-btn").addEventListener("click", async (ev) => {
    clearFormErrors(form);
    const errs = {};
    if (form.full_name.value.trim().length < 2) errs.full_name = "Full name is required.";
    if (!isValidEmail(form.email.value.trim())) errs.email = "Enter a valid email address.";
    if (form.institution_id.value.trim().length < 2) errs.institution_id = "Institution ID is required.";
    if (form.password.value.length < 8) errs.password = "Password must be at least 8 characters.";
    if (Object.keys(errs).length) {
      applyFieldErrors(form, errs);
      return;
    }

    const btn = ev.currentTarget;
    setButtonLoading(btn, true, "Creating...");
    try {
      await api.post("/api/admin/users", {
        full_name: form.full_name.value.trim(),
        email: form.email.value.trim(),
        role: form.role.value,
        institution_id: form.institution_id.value.trim(),
        department: form.department.value.trim(),
        password: form.password.value,
      });
      closeModal();
      showToast({ type: "success", title: "Account provisioned", message: "User created in Firebase Auth and Firestore." });
      loadOverviewAndUsers();
    } catch (err) {
      setButtonLoading(btn, false);
      if (err.details?.fields) applyFieldErrors(form, err.details.fields);
      showToast({ type: "error", title: "Creation failed", message: err.message });
    }
  });
});

async function approveStaffAccount(uid, fullName) {
  const ok = await confirmDialog({
    title: "Verify & Approve Staff Registration?",
    message: `Grant active Examiner portal access to ${fullName || "this applicant"}? They will be able to create exams, manage rubrics, and evaluate submissions.`,
    confirmLabel: "Verify & Approve",
    confirmVariant: "success",
  });
  if (!ok) return;
  try {
    await api.post(`/api/admin/users/${encodeURIComponent(uid)}/approve`, {});
    showToast({
      type: "success",
      title: "Staff account approved",
      message: `${fullName || "Staff user"} can now sign in to the Staff Portal.`,
    });
    loadOverviewAndUsers();
  } catch (err) {
    showToast({ type: "error", title: "Approval failed", message: err.message });
  }
}

function openRejectStaffModal(uid, fullName) {
  const modal = openModal({
    title: `Decline Staff Registration — ${fullName || "Applicant"}`,
    bodyHtml: `
      <p class="text-sm text-secondary mb-3">
        Declining this request blocks login access for this account. Provide a verification note if needed.
      </p>
      <div class="form-group">
        <label class="form-label" for="reject-staff-reason">Verification / Rejection Reason (optional)</label>
        <textarea id="reject-staff-reason" class="form-textarea" rows="3" placeholder="e.g. Faculty ID could not be verified against department directory."></textarea>
      </div>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" id="confirm-reject-staff-btn" class="btn btn-danger">Decline Registration</button>
    `,
  });

  modal.querySelector("#confirm-reject-staff-btn").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    const reason = modal.querySelector("#reject-staff-reason").value.trim();
    setButtonLoading(btn, true, "Declining...");
    try {
      await api.post(`/api/admin/users/${encodeURIComponent(uid)}/reject`, { reason });
      closeModal();
      showToast({
        type: "info",
        title: "Staff registration declined",
        message: "The account remains blocked and audit-logged.",
      });
      loadOverviewAndUsers();
    } catch (err) {
      setButtonLoading(btn, false);
      showToast({ type: "error", title: "Action failed", message: err.message });
    }
  });
}

function wireStaffDecisionButtons(container) {
  if (!container) return;
  container.querySelectorAll("[data-approve-staff]").forEach((btn) => {
    btn.addEventListener("click", () =>
      approveStaffAccount(btn.dataset.approveStaff, btn.dataset.staffName)
    );
  });
  container.querySelectorAll("[data-reject-staff]").forEach((btn) => {
    btn.addEventListener("click", () =>
      openRejectStaffModal(btn.dataset.rejectStaff, btn.dataset.staffName)
    );
  });
}

function renderPendingApprovals(overview) {
  const pending = overview.pending_staff_approvals || [];
  const count = overview.metrics?.pending_staff_count ?? pending.length;

  const tabBtn = document.getElementById("admin-approvals-tab-btn");
  if (tabBtn) {
    tabBtn.textContent = count > 0 ? `Pending Staff Approvals (${count})` : "Pending Staff Approvals";
  }

  const bannerEl = document.getElementById("admin-pending-banner");
  if (bannerEl) {
    if (count > 0) {
      bannerEl.classList.remove("hidden");
      bannerEl.innerHTML = `
        <div class="alert alert-warning flex items-center justify-between gap-3 flex-wrap">
          <div class="text-sm">
            <strong>${count} Pending Staff Verification${count === 1 ? "" : "s"}:</strong>
            Self-registered Staff (Examiner) ${count === 1 ? "account awaits" : "accounts await"} Administrator verification and approval before sign-in.
          </div>
          <button type="button" id="jump-to-approvals-btn" class="btn btn-primary btn-sm">Review Approval Queue &rarr;</button>
        </div>
      `;
      bannerEl.querySelector("#jump-to-approvals-btn")?.addEventListener("click", () => {
        switchAdminTab("approvals");
      });
    } else {
      bannerEl.classList.add("hidden");
      bannerEl.innerHTML = "";
    }
  }

  const approvalsTbody = document.getElementById("admin-approvals-tbody");
  if (!approvalsTbody) return;

  if (!pending.length) {
    approvalsTbody.innerHTML = `
      <tr>
        <td colspan="6">
          <div class="empty-state">
            <h3>No Pending Staff Registrations</h3>
            <p class="text-sm text-secondary">All self-registered Examiner applications have been reviewed.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  approvalsTbody.innerHTML = pending
    .map(
      (u) => `
      <tr>
        <td>
          <div class="fw-semibold">${escapeHtml(u.full_name)}</div>
          <div class="text-xs text-muted">${escapeHtml(u.email)}</div>
        </td>
        <td class="mono text-xs">${escapeHtml(u.institution_id || "—")}</td>
        <td class="text-sm">${escapeHtml(u.department || "—")}</td>
        <td class="text-xs">${escapeHtml(formatDateTime(u.created_at))}</td>
        <td>${statusBadge(u.status)}</td>
        <td style="text-align:right;">
          <div class="flex items-center justify-end gap-2">
            <button type="button" class="btn btn-success btn-sm" data-approve-staff="${escapeHtml(u.uid)}" data-staff-name="${escapeHtml(u.full_name)}">Verify &amp; Approve</button>
            <button type="button" class="btn btn-danger-outline btn-sm" data-reject-staff="${escapeHtml(u.uid)}" data-staff-name="${escapeHtml(u.full_name)}">Decline</button>
          </div>
        </td>
      </tr>
    `
    )
    .join("");

  wireStaffDecisionButtons(approvalsTbody);
}

userSearchInput?.addEventListener("input", renderFilteredUsers);
roleFilter?.addEventListener("change", loadOverviewAndUsers);
statusFilter?.addEventListener("change", loadOverviewAndUsers);
auditRoleFilter?.addEventListener("change", loadFilteredAuditLogs);
auditActionFilter?.addEventListener("input", renderFilteredAuditLogs);
document.getElementById("admin-refresh-btn")?.addEventListener("click", loadOverviewAndUsers);

loadOverviewAndUsers();

