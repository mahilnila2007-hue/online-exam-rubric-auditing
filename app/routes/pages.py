"""HTML page routes for all 10 application views."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, url_for

from app.extensions.firebase import get_firebase_manager
from app.middleware.auth import get_dashboard_url_for_role, roles_required

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def index():
    user = getattr(g, "current_user", None)
    if user:
        return redirect(get_dashboard_url_for_role(user["role"]))
    return redirect(url_for("pages.login_page"))


@pages_bp.route("/health")
def health():
    fb_status = get_firebase_manager().status
    return jsonify({"status": "ok", "firebase": fb_status})


@pages_bp.route("/login")
def login_page():
    user = getattr(g, "current_user", None)
    if user:
        return redirect(get_dashboard_url_for_role(user["role"]))
    tab = "register" if request.args.get("tab") == "register" else "login"
    raw_portal = (request.args.get("portal") or "student").strip().lower()
    portal = raw_portal if raw_portal in {"student", "staff", "admin"} else "student"
    reg_type = "staff" if request.args.get("account_type") == "staff" else "student"
    return render_template(
        "auth/login.html",
        initial_tab=tab,
        initial_portal=portal,
        initial_account_type=reg_type,
        next_url=request.args.get("next", ""),
        firebase_status=get_firebase_manager().status,
        firebase_web_config=current_app.config_cls_web_config(),
    )


@pages_bp.route("/staff/login")
def staff_login_page():
    user = getattr(g, "current_user", None)
    if user:
        return redirect(get_dashboard_url_for_role(user["role"]))
    return render_template(
        "auth/login.html",
        initial_tab="login",
        initial_portal="staff",
        initial_account_type="staff",
        next_url=request.args.get("next", ""),
        firebase_status=get_firebase_manager().status,
        firebase_web_config=current_app.config_cls_web_config(),
    )


@pages_bp.route("/admin/login")
def admin_login_page():
    user = getattr(g, "current_user", None)
    if user:
        return redirect(get_dashboard_url_for_role(user["role"]))
    return render_template(
        "auth/login.html",
        initial_tab="login",
        initial_portal="admin",
        initial_account_type="student",
        next_url=request.args.get("next", ""),
        firebase_status=get_firebase_manager().status,
        firebase_web_config=current_app.config_cls_web_config(),
    )


@pages_bp.route("/register")
def register_page():
    user = getattr(g, "current_user", None)
    if user:
        return redirect(get_dashboard_url_for_role(user["role"]))
    reg_type = "staff" if request.args.get("account_type") == "staff" else "student"
    return render_template(
        "auth/login.html",
        initial_tab="register",
        initial_portal=reg_type,
        initial_account_type=reg_type,
        next_url=request.args.get("next", ""),
        firebase_status=get_firebase_manager().status,
        firebase_web_config=current_app.config_cls_web_config(),
    )


# ------------------------------------------------------------------
# Student Pages
# ------------------------------------------------------------------
@pages_bp.route("/student/dashboard")
@roles_required("student")
def student_dashboard():
    return render_template("student/dashboard.html", user=g.current_user, active_nav="dashboard")


@pages_bp.route("/student/exams/<exam_id>/instructions")
@roles_required("student")
def exam_instructions_page(exam_id: str):
    return render_template(
        "student/exam_instructions.html",
        user=g.current_user,
        exam_id=exam_id,
        active_nav="dashboard",
    )


@pages_bp.route("/student/exams/<exam_id>/attempt")
@roles_required("student")
def exam_attempt_page(exam_id: str):
    return render_template(
        "student/exam_attempt.html",
        user=g.current_user,
        exam_id=exam_id,
    )


@pages_bp.route("/student/submissions/<submission_id>/confirmation")
@roles_required("student")
def submission_confirmation_page(submission_id: str):
    return render_template(
        "student/submission_confirmation.html",
        user=g.current_user,
        submission_id=submission_id,
        active_nav="history",
    )


@pages_bp.route("/student/history")
@roles_required("student")
def exam_history_page():
    return render_template("student/history.html", user=g.current_user, active_nav="history")


@pages_bp.route("/student/results")
@roles_required("student")
def student_results_page():
    return render_template("student/results.html", user=g.current_user, active_nav="results")


@pages_bp.route("/student/results/<result_id>")
@roles_required("student")
def student_result_detail_page(result_id: str):
    return render_template(
        "student/result_detail.html",
        user=g.current_user,
        result_id=result_id,
        active_nav="results",
    )


# ------------------------------------------------------------------
# Examiner Pages
# ------------------------------------------------------------------
@pages_bp.route("/examiner/dashboard")
@roles_required("examiner")
def examiner_dashboard():
    return render_template("examiner/dashboard.html", user=g.current_user, active_nav="dashboard")


@pages_bp.route("/examiner/exams/new")
@roles_required("examiner")
def exam_create_page():
    return render_template(
        "examiner/exam_editor.html",
        user=g.current_user,
        mode="create",
        exam_id="",
        active_nav="create_exam",
    )


@pages_bp.route("/examiner/exams/<exam_id>/edit")
@roles_required("examiner")
def exam_edit_page(exam_id: str):
    return render_template(
        "examiner/exam_editor.html",
        user=g.current_user,
        mode="edit",
        exam_id=exam_id,
        active_nav="create_exam",
    )


@pages_bp.route("/examiner/questions")
@roles_required("examiner")
def question_bank_page():
    return render_template("examiner/question_bank.html", user=g.current_user, active_nav="questions")


@pages_bp.route("/examiner/exams/<exam_id>/results")
@roles_required("examiner")
def examiner_exam_results_page(exam_id: str):
    return render_template(
        "examiner/exam_results.html",
        user=g.current_user,
        exam_id=exam_id,
        active_nav="dashboard",
    )


@pages_bp.route("/examiner/evaluations/<submission_id>")
@roles_required("examiner")
def examiner_evaluate_submission_page(submission_id: str):
    return render_template(
        "examiner/evaluate_submission.html",
        user=g.current_user,
        submission_id=submission_id,
        active_nav="dashboard",
    )


@pages_bp.route("/examiner/audit")
@roles_required("examiner", "admin")
def rubric_audit_page():
    return render_template(
        "examiner/rubric_audit.html",
        user=g.current_user,
        initial_exam_id=request.args.get("exam_id", ""),
        active_nav="audit",
    )


# ------------------------------------------------------------------
# Admin Pages
# ------------------------------------------------------------------
@pages_bp.route("/admin/dashboard")
@roles_required("admin")
def admin_dashboard():
    return render_template("admin/dashboard.html", user=g.current_user, active_nav="dashboard")

