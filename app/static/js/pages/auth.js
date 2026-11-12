/**
 * Login, student registration, and password reset interactions.
 */

import { api } from "../core/apiClient.js";
import {
  firebaseClientSignOut,
  firebasePasswordReset,
  firebaseRegister,
  firebaseSignIn,
} from "../core/firebaseClient.js";
import { openModal, closeModal } from "../core/modal.js";
import { showToast } from "../core/toast.js";
import { escapeHtml, setButtonLoading } from "../core/ui.js";
import { applyFieldErrors, clearFormErrors, isValidEmail } from "../core/validators.js";

const stateEl = document.getElementById("auth-page-state");
const pageState = stateEl ? JSON.parse(stateEl.textContent || "{}") : {};

const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const staffPendingCard = document.getElementById("staff-pending-card");
const staffPendingSummary = document.getElementById("staff-pending-summary");
const authAlert = document.getElementById("auth-alert");
const authAlertText = document.getElementById("auth-alert-text");
const authHeading = document.getElementById("auth-heading");
const authSubheading = document.getElementById("auth-subheading");
const portalHintText = document.getElementById("portal-hint-text");
const loginSubmitBtn = document.getElementById("login-submit-btn");

const regAccountTypeInput = document.getElementById("reg-account-type");
const regInstIdLabel = document.getElementById("reg-inst-id-label");
const regInstIdInput = document.getElementById("reg-inst-id");
const regEmailInput = document.getElementById("reg-email");
const registerHintText = document.getElementById("register-hint-text");
const registerSubmitBtn = document.getElementById("register-submit-btn");

const PORTAL_META = {
  student: {
    hint: "<strong>Student Portal:</strong> Sign in to attend scheduled examinations, review instructions, and view published results.",
    button: "Sign In to Student Portal",
    heading: "Student Portal Sign In",
  },
  staff: {
    hint: "<strong>Staff Portal (Examiner):</strong> Sign in with your Admin-approved Examiner account to access Exam Studio, Question Bank, Grading, and Rubric Auditing.",
    button: "Sign In to Staff Portal",
    heading: "Staff Portal Sign In",
  },
  admin: {
    hint: "<strong>Admin Portal:</strong> Sign in with Administrator credentials to verify and approve staff registrations, manage user roles, and oversee audit activity.",
    button: "Sign In to Admin Portal",
    heading: "Admin Portal Sign In",
  },
};

const ACCOUNT_TYPE_META = {
  student: {
    hint: "Self-registration as a <strong>Student</strong> grants immediate portal access. Switch to <strong>Staff (Examiner)</strong> to apply for faculty access (Admin approval required).",
    idLabel: "Student ID",
    idPlaceholder: "e.g. STU-2026-041",
    emailPlaceholder: "student@university.edu",
    button: "Create Student Account",
    heading: "Student Registration",
    subheading: "Create your verified student examination account.",
  },
  staff: {
    hint: "<strong>Staff Verification Required:</strong> Staff (Examiner) registrations require Administrator verification and approval before login is enabled. Admin accounts cannot be self-registered.",
    idLabel: "Staff / Faculty ID",
    idPlaceholder: "e.g. FAC-2026-014",
    emailPlaceholder: "faculty@university.edu",
    button: "Submit Staff Registration for Approval",
    heading: "Staff (Examiner) Registration",
    subheading: "Apply for an Examiner account. An Administrator must verify and approve it before login.",
  },
};

let currentPortal = PORTAL_META[pageState.initialPortal] ? pageState.initialPortal : "student";
let currentAccountType = pageState.initialAccountType === "staff" ? "staff" : "student";

function setPortalMode(portal) {
  currentPortal = PORTAL_META[portal] ? portal : "student";
  const meta = PORTAL_META[currentPortal];
  document.querySelectorAll("[data-portal-mode]").forEach((b) =>
    b.classList.toggle("active", b.dataset.portalMode === currentPortal)
  );
  if (portalHintText) portalHintText.innerHTML = meta.hint;
  if (loginSubmitBtn && !loginSubmitBtn.disabled) loginSubmitBtn.textContent = meta.button;
  if (authHeading && !loginForm?.classList.contains("hidden")) {
    authHeading.textContent = meta.heading;
  }
}

function setAccountType(accountType) {
  currentAccountType = accountType === "staff" ? "staff" : "student";
  const meta = ACCOUNT_TYPE_META[currentAccountType];
  if (regAccountTypeInput) regAccountTypeInput.value = currentAccountType;
  document.querySelectorAll("[data-account-type]").forEach((b) =>
    b.classList.toggle("active", b.dataset.accountType === currentAccountType)
  );
  if (registerHintText) registerHintText.innerHTML = meta.hint;
  if (regInstIdLabel) regInstIdLabel.textContent = meta.idLabel;
  if (regInstIdInput) regInstIdInput.placeholder = meta.idPlaceholder;
  if (regEmailInput) regEmailInput.placeholder = meta.emailPlaceholder;
  if (registerSubmitBtn && !registerSubmitBtn.disabled) registerSubmitBtn.textContent = meta.button;
  if (authHeading && !registerForm?.classList.contains("hidden")) {
    authHeading.textContent = meta.heading;
    if (authSubheading) authSubheading.textContent = meta.subheading;
  }
}

document.querySelectorAll("[data-portal-mode]").forEach((btn) => {
  btn.addEventListener("click", () => setPortalMode(btn.dataset.portalMode));
});

document.querySelectorAll("[data-account-type]").forEach((btn) => {
  btn.addEventListener("click", () => setAccountType(btn.dataset.accountType));
});

function showAlert(message) {
  if (!authAlert || !authAlertText) return;
  authAlertText.textContent = message;
  authAlert.classList.remove("hidden");
}

function hideAlert() {
  authAlert?.classList.add("hidden");
}

function friendlyFirebaseError(err) {
  const code = err?.code || "";
  const map = {
    "auth/invalid-credential": "Invalid email address or password.",
    "auth/wrong-password": "Incorrect password. Please try again.",
    "auth/user-not-found": "No Firebase account was found for that email address.",
    "auth/user-disabled": "This account has been disabled or declined by an administrator.",
    "auth/email-already-in-use": "An account with this email already exists. Try signing in instead.",
    "auth/weak-password": "Password must be at least 6 characters (8+ recommended).",
    "auth/too-many-requests": "Too many failed attempts. Please wait a moment and try again.",
    "auth/network-request-failed": "Network error connecting to Firebase Authentication.",
  };
  return map[code] || err?.message || "Authentication failed.";
}

function safeRedirectUrl(fallbackUrl) {
  const next = pageState.nextUrl || "";
  if (next.startsWith("/") && !next.startsWith("//") && next !== "/login") {
    return next;
  }
  return fallbackUrl;
}

function switchTab(tab) {
  hideAlert();
  staffPendingCard?.classList.add("hidden");
  document.querySelectorAll("[data-auth-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.authTab === tab);
  });
  if (tab === "register") {
    loginForm?.classList.add("hidden");
    registerForm?.classList.remove("hidden");
    setAccountType(currentAccountType);
  } else {
    registerForm?.classList.add("hidden");
    loginForm?.classList.remove("hidden");
    if (authSubheading) authSubheading.textContent = "Sign in with your institutional credentials.";
    setPortalMode(currentPortal);
  }
}

document.querySelectorAll("[data-auth-tab]").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.authTab));
});

document.getElementById("go-staff-register-btn")?.addEventListener("click", () => {
  setAccountType("staff");
  switchTab("register");
});

document.getElementById("pending-to-staff-login-btn")?.addEventListener("click", () => {
  staffPendingCard?.classList.add("hidden");
  setPortalMode("staff");
  switchTab("login");
});

document.getElementById("pending-register-another-btn")?.addEventListener("click", () => {
  staffPendingCard?.classList.add("hidden");
  registerForm?.reset();
  setAccountType("staff");
  switchTab("register");
});

loginForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAlert();
  clearFormErrors(loginForm);

  const email = loginForm.email.value.trim();
  const password = loginForm.password.value;

  const errs = {};
  if (!isValidEmail(email)) errs.email = "Enter a valid email address.";
  if (!password) errs.password = "Password is required.";
  if (Object.keys(errs).length) {
    applyFieldErrors(loginForm, errs);
    return;
  }

  const submitBtn = document.getElementById("login-submit-btn");
  setButtonLoading(submitBtn, true, "Signing in...");
  try {
    const { idToken } = await firebaseSignIn(email, password);
    const res = await api.post("/api/auth/session-login", {
      id_token: idToken,
      portal: currentPortal,
    });
    const target = safeRedirectUrl(res.data?.redirect_url || "/");
    window.location.href = target;
  } catch (err) {
    await firebaseClientSignOut();
    setButtonLoading(submitBtn, false);
    if (err.details?.fields) applyFieldErrors(loginForm, err.details.fields);
    showAlert(friendlyFirebaseError(err));
  }
});

registerForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAlert();
  clearFormErrors(registerForm);

  const accountType = currentAccountType === "staff" ? "staff" : "student";
  const fullName = registerForm.full_name.value.trim();
  const institutionId = registerForm.institution_id.value.trim();
  const department = registerForm.department.value.trim();
  const email = registerForm.email.value.trim();
  const password = registerForm.password.value;
  const confirmPassword = registerForm.confirm_password.value;

  const errs = {};
  if (fullName.length < 2) errs.full_name = "Enter your full name (at least 2 characters).";
  if (institutionId.length < 2) {
    errs.institution_id =
      accountType === "staff" ? "Staff / Faculty ID is required." : "Student ID is required.";
  }
  if (!isValidEmail(email)) errs.email = "Enter a valid institutional email address.";
  if (password.length < 8) errs.password = "Password must be at least 8 characters.";
  if (password !== confirmPassword) errs.confirm_password = "Passwords do not match.";

  if (Object.keys(errs).length) {
    applyFieldErrors(registerForm, errs);
    return;
  }

  const submitBtn = document.getElementById("register-submit-btn");
  setButtonLoading(
    submitBtn,
    true,
    accountType === "staff" ? "Submitting request..." : "Creating account..."
  );
  try {
    const { idToken } = await firebaseRegister(email, password, fullName);
    const res = await api.post("/api/auth/register", {
      id_token: idToken,
      full_name: fullName,
      institution_id: institutionId,
      department,
      account_type: accountType,
    });

    if (res.data?.requires_approval) {
      await firebaseClientSignOut();
      setButtonLoading(submitBtn, false);
      const user = res.data.user || {};
      registerForm.reset();
      registerForm.classList.add("hidden");
      if (staffPendingSummary) {
        staffPendingSummary.textContent = `${user.full_name || fullName} (${user.email || email}) • ID: ${user.institution_id || institutionId}`;
      }
      if (authHeading) authHeading.textContent = "Awaiting Admin Approval";
      if (authSubheading) {
        authSubheading.textContent = "Your staff account registration has been sent for verification.";
      }
      staffPendingCard?.classList.remove("hidden");
      showToast({
        type: "success",
        title: "Staff registration submitted",
        message: "An Administrator must verify and approve your account before login.",
      });
      return;
    }

    window.location.href = res.data?.redirect_url || "/student/dashboard";
  } catch (err) {
    await firebaseClientSignOut();
    setButtonLoading(submitBtn, false);
    if (err.details?.fields) applyFieldErrors(registerForm, err.details.fields);
    showAlert(friendlyFirebaseError(err));
  }
});

document.getElementById("forgot-password-btn")?.addEventListener("click", () => {
  const prefill = loginForm?.email?.value?.trim() || "";
  const modal = openModal({
    title: "Reset Account Password",
    bodyHtml: `
      <p class="text-sm text-secondary mb-3">Enter your registered email address and Firebase Authentication will send a password reset link.</p>
      <div class="form-group">
        <label class="form-label" for="reset-email-input">Email Address</label>
        <input id="reset-email-input" type="email" class="form-input" value="${escapeHtml(prefill)}" placeholder="you@university.edu">
        <div id="reset-email-error" class="form-error"></div>
      </div>
    `,
    footerHtml: `
      <button type="button" class="btn btn-secondary" data-modal-close>Cancel</button>
      <button type="button" class="btn btn-primary" id="send-reset-btn">Send Reset Link</button>
    `,
  });

  modal.querySelector("#send-reset-btn").addEventListener("click", async (ev) => {
    const emailInput = modal.querySelector("#reset-email-input");
    const errEl = modal.querySelector("#reset-email-error");
    const email = emailInput.value.trim();
    errEl.textContent = "";
    if (!isValidEmail(email)) {
      errEl.textContent = "Please enter a valid email address.";
      return;
    }
    const btn = ev.currentTarget;
    setButtonLoading(btn, true, "Sending...");
    try {
      await firebasePasswordReset(email);
      closeModal();
      showToast({ type: "success", title: "Reset email dispatched", message: `Check ${email} for instructions.` });
    } catch (err) {
      setButtonLoading(btn, false);
      errEl.textContent = friendlyFirebaseError(err);
    }
  });
});

document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.togglePassword);
    if (!input) return;
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    btn.textContent = reveal ? "Hide" : "Show";
    btn.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
  });
});

setAccountType(currentAccountType);
if (pageState.initialTab === "register") {
  switchTab("register");
} else {
  setPortalMode(currentPortal);
}

