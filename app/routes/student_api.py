"""Student-facing API endpoints for examinations, attempts, and history."""

from __future__ import annotations

from flask import Blueprint, g, request

from app.middleware.auth import roles_required
from app.routes.helpers import api_success, client_ip, get_service, parse_json_body

student_api_bp = Blueprint("student_api", __name__, url_prefix="/api/student")


@student_api_bp.route("/exams", methods=["GET"])
@roles_required("student")
def list_exams():
    data = get_service("exam").list_student_exams(g.current_user["uid"])
    return api_success(data)


@student_api_bp.route("/exams/<exam_id>/instructions", methods=["GET"])
@roles_required("student")
def exam_instructions(exam_id: str):
    data = get_service("exam").get_student_exam_instructions(exam_id, g.current_user["uid"])
    return api_success({"exam": data})


@student_api_bp.route("/exams/<exam_id>/start", methods=["POST"])
@roles_required("student")
def start_or_resume_exam(exam_id: str):
    data = get_service("submission").start_or_resume_attempt(
        exam_id, g.current_user, ip_address=client_ip()
    )
    return api_success(data)


@student_api_bp.route("/exams/<exam_id>/answers", methods=["PUT"])
@roles_required("student")
def save_answers(exam_id: str):
    payload = parse_json_body()
    data = get_service("submission").save_progress(
        exam_id, g.current_user, payload, ip_address=client_ip()
    )
    return api_success(data, message="Progress saved.")


@student_api_bp.route("/exams/<exam_id>/submit", methods=["POST"])
@roles_required("student")
def submit_exam(exam_id: str):
    payload = request.get_json(silent=True) or {}
    data = get_service("submission").submit_exam(
        exam_id, g.current_user, payload, ip_address=client_ip()
    )
    return api_success({"submission": data}, message="Examination submitted successfully.")


@student_api_bp.route("/history", methods=["GET"])
@roles_required("student")
def exam_history():
    items = get_service("submission").list_student_history(g.current_user["uid"])
    return api_success({"submissions": items})


@student_api_bp.route("/submissions/<submission_id>", methods=["GET"])
@roles_required("student")
def submission_detail(submission_id: str):
    data = get_service("submission").get_submission_detail(submission_id, g.current_user)
    return api_success({"submission": data})


@student_api_bp.route("/results", methods=["GET"])
@roles_required("student")
def list_results():
    data = get_service("result").list_student_results(g.current_user["uid"])
    return api_success(data)


@student_api_bp.route("/results/<result_id>", methods=["GET"])
@roles_required("student")
def result_detail(result_id: str):
    data = get_service("result").get_student_result_detail(result_id, g.current_user)
    return api_success({"result": data})


@student_api_bp.route("/notifications", methods=["GET"])
@roles_required("student")
def list_notifications():
    items = get_service("result").list_student_notifications(g.current_user["uid"])
    return api_success({"notifications": items})


@student_api_bp.route("/notifications/<notification_id>/read", methods=["POST"])
@roles_required("student")
def mark_notification_read(notification_id: str):
    item = get_service("result").mark_notification_read(notification_id, g.current_user)
    return api_success({"notification": item})

