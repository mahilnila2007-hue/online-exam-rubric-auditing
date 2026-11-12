"""Examiner API endpoints for examinations, question bank, rubrics, and submissions."""

from __future__ import annotations

from flask import Blueprint, Response, g, request

from app.exceptions import ValidationError
from app.middleware.auth import roles_required
from app.routes.helpers import api_success, client_ip, get_service, parse_json_body

examiner_api_bp = Blueprint("examiner_api", __name__, url_prefix="/api/examiner")


# ------------------------------------------------------------------
# Examinations
# ------------------------------------------------------------------
@examiner_api_bp.route("/exams", methods=["GET"])
@roles_required("examiner", "admin")
def list_exams():
    status = request.args.get("status") or None
    search = request.args.get("search") or None
    exams = get_service("exam").list_examiner_exams(g.current_user, status=status, search=search)
    return api_success({"exams": exams})


@examiner_api_bp.route("/exams", methods=["POST"])
@roles_required("examiner", "admin")
def create_exam():
    payload = parse_json_body()
    exam = get_service("exam").create_exam(g.current_user, payload, ip_address=client_ip())
    return api_success({"exam": exam}, message="Examination created successfully.", status_code=201)


@examiner_api_bp.route("/exams/<exam_id>", methods=["GET"])
@roles_required("examiner", "admin")
def get_exam(exam_id: str):
    exam = get_service("exam").get_exam_for_examiner(g.current_user, exam_id)
    return api_success({"exam": exam})


@examiner_api_bp.route("/exams/<exam_id>", methods=["PUT"])
@roles_required("examiner", "admin")
def update_exam(exam_id: str):
    payload = parse_json_body()
    exam = get_service("exam").update_exam(g.current_user, exam_id, payload, ip_address=client_ip())
    return api_success({"exam": exam}, message="Examination updated successfully.")


@examiner_api_bp.route("/exams/<exam_id>/status", methods=["PATCH"])
@roles_required("examiner", "admin")
def change_exam_status(exam_id: str):
    payload = parse_json_body()
    new_status = str(payload.get("status", "")).strip().lower()
    exam = get_service("exam").change_exam_status(
        g.current_user, exam_id, new_status, ip_address=client_ip()
    )
    return api_success({"exam": exam}, message=f"Examination status updated to {new_status}.")


@examiner_api_bp.route("/exams/<exam_id>/duplicate", methods=["POST"])
@roles_required("examiner", "admin")
def duplicate_exam(exam_id: str):
    exam = get_service("exam").duplicate_exam(g.current_user, exam_id, ip_address=client_ip())
    return api_success({"exam": exam}, message="Examination cloned into a new draft.", status_code=201)


@examiner_api_bp.route("/exams/<exam_id>/submissions", methods=["GET"])
@roles_required("examiner", "admin")
def list_exam_submissions(exam_id: str):
    subs = get_service("submission").list_exam_submissions_for_examiner(exam_id, g.current_user)
    return api_success({"submissions": subs})


@examiner_api_bp.route("/submissions/<submission_id>", methods=["GET"])
@roles_required("examiner", "admin")
def get_submission_detail(submission_id: str):
    sub = get_service("submission").get_submission_detail(submission_id, g.current_user)
    return api_success({"submission": sub})


# ------------------------------------------------------------------
# Phase 2: Rubric Evaluation & Result Management
# ------------------------------------------------------------------
@examiner_api_bp.route("/exams/<exam_id>/results", methods=["GET"])
@roles_required("examiner", "admin")
def list_exam_results(exam_id: str):
    data = get_service("result").list_exam_results_for_examiner(exam_id, g.current_user)
    return api_success(data)


@examiner_api_bp.route("/exams/<exam_id>/results.csv", methods=["GET"])
@roles_required("examiner", "admin")
def export_exam_results_csv(exam_id: str):
    filename, csv_text = get_service("result").export_exam_results_csv(exam_id, g.current_user)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@examiner_api_bp.route("/exams/<exam_id>/process-evaluations", methods=["POST"])
@roles_required("examiner", "admin")
def batch_process_evaluations(exam_id: str):
    data = get_service("evaluation").batch_preliminary_evaluate_exam(
        exam_id, g.current_user, ip_address=client_ip()
    )
    return api_success(data, message="Preliminary rubric evaluation batch completed.")


@examiner_api_bp.route("/exams/<exam_id>/publish-results", methods=["POST"])
@roles_required("examiner", "admin")
def publish_exam_results(exam_id: str):
    data = get_service("result").publish_exam_results(
        exam_id, g.current_user, ip_address=client_ip()
    )
    return api_success(data, message="Evaluated results published.")


@examiner_api_bp.route("/submissions/<submission_id>/evaluation", methods=["GET"])
@roles_required("examiner", "admin")
def get_evaluation_workspace(submission_id: str):
    data = get_service("evaluation").get_evaluation_workspace(submission_id, g.current_user)
    return api_success(data)


@examiner_api_bp.route("/submissions/<submission_id>/auto-evaluate", methods=["POST"])
@roles_required("examiner", "admin")
def auto_evaluate_submission(submission_id: str):
    sub = get_service("evaluation").run_preliminary_evaluation(
        submission_id, g.current_user, ip_address=client_ip()
    )
    return api_success({"submission": sub}, message="Preliminary rubric evaluation completed.")


@examiner_api_bp.route("/submissions/<submission_id>/evaluate", methods=["PUT"])
@roles_required("examiner", "admin")
def save_examiner_evaluation(submission_id: str):
    payload = parse_json_body()
    data = get_service("evaluation").save_examiner_evaluation(
        submission_id, g.current_user, payload, ip_address=client_ip()
    )
    return api_success(data, message="Evaluation saved and result updated.")


@examiner_api_bp.route("/submissions/<submission_id>/publish-result", methods=["POST"])
@roles_required("examiner", "admin")
def publish_submission_result(submission_id: str):
    result = get_service("result").publish_submission_result(
        submission_id, g.current_user, ip_address=client_ip()
    )
    return api_success({"result": result}, message="Student result published.")


# ------------------------------------------------------------------
# Question Bank
# ------------------------------------------------------------------
def _is_truthy_form_flag(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


@examiner_api_bp.route("/questions", methods=["GET"])
@roles_required("examiner", "admin")
def list_questions():
    raw_marks = request.args.get("marks")
    marks_filter: float | None = None
    if raw_marks:
        try:
            marks_filter = float(raw_marks)
        except ValueError as exc:
            raise ValidationError("Invalid marks filter.") from exc

    items = get_service("question").list_questions(
        g.current_user,
        subject=request.args.get("subject") or None,
        q_type=request.args.get("type") or None,
        difficulty=request.args.get("difficulty") or None,
        question_set=request.args.get("question_set") or None,
        marks=marks_filter,
        search=request.args.get("search") or None,
    )
    return api_success({"questions": items})


@examiner_api_bp.route("/questions/excel-template", methods=["GET"])
@roles_required("examiner", "admin")
def download_question_excel_template():
    workbook_bytes = get_service("excel_question").build_excel_template()
    return Response(
        workbook_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="RubriAssess_Question_Set_Template.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@examiner_api_bp.route("/questions/import-excel", methods=["POST"])
@roles_required("examiner", "admin")
def import_questions_from_excel():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        raise ValidationError("Please select an Excel (.xlsx) or CSV (.csv) file to upload.")

    file_bytes = uploaded.read()
    mode = str(request.form.get("mode", "commit")).strip().lower()
    common_kwargs = {
        "file_bytes": file_bytes,
        "filename": uploaded.filename,
        "default_set_name": request.form.get("default_set_name", ""),
        "override_set_name": _is_truthy_form_flag(request.form.get("override_set_name")),
        "default_subject": request.form.get("default_subject", ""),
        "default_topic": request.form.get("default_topic", "Core Concepts"),
        "default_difficulty": request.form.get("default_difficulty", "medium"),
    }

    service = get_service("excel_question")
    if mode == "preview":
        preview = service.preview_upload(**common_kwargs)
        return api_success(preview, message="Workbook validated for preview.")

    result = service.commit_upload(
        g.current_user,
        **common_kwargs,
        skip_invalid=_is_truthy_form_flag(request.form.get("skip_invalid")),
        create_exam=_is_truthy_form_flag(request.form.get("create_exam")),
        exam_title=request.form.get("exam_title", ""),
        course_code=request.form.get("course_code", ""),
        ip_address=client_ip(),
    )
    return api_success(
        result,
        message=f"Imported {result['imported_count']} question(s) from Excel set.",
        status_code=201,
    )


@examiner_api_bp.route("/questions", methods=["POST"])
@roles_required("examiner", "admin")
def create_question():
    payload = parse_json_body()
    question = get_service("question").create_question(g.current_user, payload, ip_address=client_ip())
    return api_success({"question": question}, message="Question added to bank.", status_code=201)


@examiner_api_bp.route("/questions/<question_id>", methods=["GET"])
@roles_required("examiner", "admin")
def get_question(question_id: str):
    question = get_service("question").get_question(g.current_user, question_id)
    return api_success({"question": question})


@examiner_api_bp.route("/questions/<question_id>", methods=["PUT"])
@roles_required("examiner", "admin")
def update_question(question_id: str):
    payload = parse_json_body()
    question = get_service("question").update_question(
        g.current_user, question_id, payload, ip_address=client_ip()
    )
    return api_success({"question": question}, message="Question updated.")


@examiner_api_bp.route("/questions/<question_id>", methods=["DELETE"])
@roles_required("examiner", "admin")
def archive_question(question_id: str):
    get_service("question").archive_question(g.current_user, question_id, ip_address=client_ip())
    return api_success(message="Question archived.")


# ------------------------------------------------------------------
# Descriptive Rubrics
# ------------------------------------------------------------------
@examiner_api_bp.route("/rubrics", methods=["GET"])
@roles_required("examiner", "admin")
def list_rubrics():
    rubrics = get_service("question").list_rubrics(
        g.current_user, subject=request.args.get("subject") or None
    )
    return api_success({"rubrics": rubrics})


@examiner_api_bp.route("/rubrics", methods=["POST"])
@roles_required("examiner", "admin")
def create_rubric():
    payload = parse_json_body()
    rubric = get_service("question").create_rubric(g.current_user, payload, ip_address=client_ip())
    return api_success({"rubric": rubric}, message="Evaluation rubric created.", status_code=201)


@examiner_api_bp.route("/rubrics/<rubric_id>", methods=["GET"])
@roles_required("examiner", "admin")
def get_rubric(rubric_id: str):
    rubric = get_service("question").get_rubric(g.current_user, rubric_id)
    return api_success({"rubric": rubric})


@examiner_api_bp.route("/rubrics/<rubric_id>", methods=["PUT"])
@roles_required("examiner", "admin")
def update_rubric(rubric_id: str):
    payload = parse_json_body()
    rubric = get_service("question").update_rubric(
        g.current_user, rubric_id, payload, ip_address=client_ip()
    )
    return api_success({"rubric": rubric}, message="Evaluation rubric updated.")


@examiner_api_bp.route("/rubrics/<rubric_id>", methods=["DELETE"])
@roles_required("examiner", "admin")
def delete_rubric(rubric_id: str):
    get_service("question").delete_rubric(g.current_user, rubric_id, ip_address=client_ip())
    return api_success(message="Evaluation rubric deleted.")


# ------------------------------------------------------------------
# Phase 3: Intelligent Rubric Auditing & Approval System
# ------------------------------------------------------------------
@examiner_api_bp.route("/audit", methods=["GET"])
@roles_required("examiner", "admin")
def get_audit_dashboard():
    data = get_service("rubric_audit").get_audit_dashboard(
        g.current_user,
        exam_id=request.args.get("exam_id") or None,
        status=request.args.get("status") or None,
        criterion_id=request.args.get("criterion_id") or None,
    )
    return api_success(data)


@examiner_api_bp.route("/exams/<exam_id>/audit", methods=["POST"])
@roles_required("examiner", "admin")
def run_exam_rubric_audit(exam_id: str):
    payload = request.get_json(silent=True) or {}
    data = get_service("rubric_audit").run_exam_audit(
        exam_id, g.current_user, payload, ip_address=client_ip()
    )
    return api_success(data, message="Intelligent rubric audit completed.", status_code=201)


@examiner_api_bp.route("/audit/suggestions/<suggestion_id>/approve", methods=["POST"])
@roles_required("examiner", "admin")
def approve_audit_suggestion(suggestion_id: str):
    payload = request.get_json(silent=True) or {}
    data = get_service("rubric_audit").approve_suggestion(
        suggestion_id, g.current_user, payload, ip_address=client_ip()
    )
    return api_success(data, message="Suggestion approved, rubric updated, and affected answers re-evaluated.")


@examiner_api_bp.route("/audit/suggestions/<suggestion_id>/reject", methods=["POST"])
@roles_required("examiner", "admin")
def reject_audit_suggestion(suggestion_id: str):
    payload = request.get_json(silent=True) or {}
    data = get_service("rubric_audit").reject_suggestion(
        suggestion_id, g.current_user, payload, ip_address=client_ip()
    )
    return api_success(data, message="Suggestion rejected. Original rubric remains unchanged.")


@examiner_api_bp.route("/rubrics/<rubric_id>/versions", methods=["GET"])
@roles_required("examiner", "admin")
def get_rubric_versions(rubric_id: str):
    versions = get_service("rubric_audit").get_rubric_versions(rubric_id, g.current_user)
    current_rubric = get_service("question").get_rubric(g.current_user, rubric_id)
    return api_success({"versions": versions, "current_rubric": current_rubric})

