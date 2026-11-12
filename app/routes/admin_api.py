"""Administrative API endpoints for user management, monitoring, and reports."""

from __future__ import annotations

from flask import Blueprint, Response, g, request

from app.middleware.auth import roles_required
from app.routes.helpers import api_success, client_ip, get_service, parse_json_body

admin_api_bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")


@admin_api_bp.route("/overview", methods=["GET"])
@roles_required("admin")
def overview():
    data = get_service("admin").get_dashboard_overview()
    return api_success(data)


@admin_api_bp.route("/users", methods=["GET"])
@roles_required("admin")
def list_users():
    users = get_service("admin").list_users(
        role=request.args.get("role") or None,
        status=request.args.get("status") or None,
    )
    return api_success({"users": users})


@admin_api_bp.route("/users", methods=["POST"])
@roles_required("admin")
def create_user():
    payload = parse_json_body()
    user = get_service("admin").create_user_account(g.current_user, payload, ip_address=client_ip())
    return api_success({"user": user}, message="User account created successfully.", status_code=201)


@admin_api_bp.route("/users/<uid>", methods=["PATCH"])
@roles_required("admin")
def update_user(uid: str):
    payload = parse_json_body()
    user = get_service("admin").update_user_account(g.current_user, uid, payload, ip_address=client_ip())
    return api_success({"user": user}, message="User account updated.")


@admin_api_bp.route("/users/<uid>/approve", methods=["POST"])
@roles_required("admin")
def approve_staff_user(uid: str):
    user = get_service("admin").approve_staff_user(g.current_user, uid, ip_address=client_ip())
    return api_success({"user": user}, message="Staff account verified and approved.")


@admin_api_bp.route("/users/<uid>/reject", methods=["POST"])
@roles_required("admin")
def reject_staff_user(uid: str):
    payload = request.get_json(silent=True) or {}
    user = get_service("admin").reject_staff_user(g.current_user, uid, payload, ip_address=client_ip())
    return api_success({"user": user}, message="Staff registration declined.")


@admin_api_bp.route("/audit-logs", methods=["GET"])
@roles_required("admin")
def audit_logs():
    logs = get_service("audit").list_recent(
        actor_role=request.args.get("actor_role") or None,
        action=request.args.get("action") or None,
        limit=min(int(request.args.get("limit", 100)), 250),
    )
    return api_success({"logs": logs})


@admin_api_bp.route("/reports/exams.csv", methods=["GET"])
@roles_required("admin")
def export_exam_report():
    csv_text = get_service("admin").export_exam_report_csv()
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=examination_report.csv"},
    )


@admin_api_bp.route("/rubric-audits", methods=["GET"])
@roles_required("admin")
def rubric_audit_oversight():
    data = get_service("rubric_audit").get_audit_dashboard(
        g.current_user,
        exam_id=request.args.get("exam_id") or None,
        status=request.args.get("status") or None,
    )
    return api_success(data)

