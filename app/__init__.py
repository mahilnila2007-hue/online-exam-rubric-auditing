"""Flask application factory and dependency wiring."""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv
from flask import Flask, request

from app.config import resolve_config
from app.extensions.firebase import firebase_manager
from app.middleware.auth import load_current_user
from app.middleware.csrf import get_csrf_token, validate_csrf_request
from app.middleware.error_handlers import register_error_handlers
from app.repositories.audit_repo import AuditRepository
from app.repositories.exam_repo import ExamRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.rubric_audit_repo import (
    AuditHistoryRepository,
    AuditReportRepository,
    AuditSuggestionRepository,
    NotificationRepository,
    RubricVersionRepository,
)
from app.repositories.rubric_repo import RubricRepository
from app.repositories.submission_repo import SubmissionRepository
from app.repositories.user_repo import UserRepository
from app.routes.admin_api import admin_api_bp
from app.routes.auth_api import auth_api_bp
from app.routes.examiner_api import examiner_api_bp
from app.routes.pages import pages_bp
from app.routes.student_api import student_api_bp
from app.services.admin_service import AdminService
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.evaluation_service import EvaluationService
from app.services.exam_service import ExamService
from app.services.excel_question_service import ExcelQuestionService
from app.services.question_service import QuestionService
from app.services.result_service import ResultService
from app.services.rubric_audit_service import RubricAuditService
from app.services.submission_service import SubmissionService


def _wire_dependencies(app: Flask, custom_repos: dict[str, Any] | None = None) -> None:
    repos = custom_repos or {
        "users": UserRepository(),
        "questions": QuestionRepository(),
        "rubrics": RubricRepository(),
        "exams": ExamRepository(),
        "submissions": SubmissionRepository(),
        "results": ResultRepository(),
        "audit_logs": AuditRepository(),
        "audit_reports": AuditReportRepository(),
        "audit_suggestions": AuditSuggestionRepository(),
        "rubric_versions": RubricVersionRepository(),
        "audit_history": AuditHistoryRepository(),
        "notifications": NotificationRepository(),
    }

    audit_service = AuditService(repos["audit_logs"])
    auth_service = AuthService(repos["users"], audit_service)
    question_service = QuestionService(repos["questions"], repos["rubrics"], audit_service)
    exam_service = ExamService(repos["exams"], repos["questions"], repos["submissions"], audit_service)
    excel_question_service = ExcelQuestionService(question_service, audit_service, exam_service)
    submission_service = SubmissionService(repos["exams"], repos["questions"], repos["submissions"], audit_service)
    result_service = ResultService(
        repos["exams"],
        repos["questions"],
        repos["submissions"],
        repos["results"],
        audit_service,
        notification_repo=repos["notifications"],
    )
    evaluation_service = EvaluationService(
        repos["exams"],
        repos["questions"],
        repos["rubrics"],
        repos["submissions"],
        result_service,
        audit_service,
    )
    rubric_audit_service = RubricAuditService(
        exam_repo=repos["exams"],
        question_repo=repos["questions"],
        rubric_repo=repos["rubrics"],
        submission_repo=repos["submissions"],
        result_repo=repos["results"],
        audit_report_repo=repos["audit_reports"],
        audit_suggestion_repo=repos["audit_suggestions"],
        rubric_version_repo=repos["rubric_versions"],
        audit_history_repo=repos["audit_history"],
        notification_repo=repos["notifications"],
        result_service=result_service,
        audit_service=audit_service,
    )
    admin_service = AdminService(
        repos["users"],
        repos["exams"],
        repos["questions"],
        repos["rubrics"],
        repos["submissions"],
        audit_service,
    )

    app.extensions["repositories"] = repos
    app.extensions["services"] = {
        "audit": audit_service,
        "auth": auth_service,
        "question": question_service,
        "excel_question": excel_question_service,
        "exam": exam_service,
        "submission": submission_service,
        "evaluation": evaluation_service,
        "result": result_service,
        "rubric_audit": rubric_audit_service,
        "admin": admin_service,
    }


def create_app(
    env_name: str | None = None,
    *,
    test_config: dict[str, Any] | None = None,
    repositories: dict[str, Any] | None = None,
    auth_gateway: Any | None = None,
) -> Flask:
    """Create and configure the Flask application instance."""
    load_dotenv()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    config_cls = resolve_config(env_name)
    app.config.from_object(config_cls)
    if test_config:
        app.config.update(test_config)

    app.config_cls_web_config = config_cls.get_firebase_web_config  # type: ignore[attr-defined]

    firebase_manager.init_app(app)
    app.extensions["firebase_manager"] = firebase_manager
    if auth_gateway is not None:
        app.extensions["auth_gateway"] = auth_gateway

    _wire_dependencies(app, repositories)

    # Request lifecycle hooks
    @app.before_request
    def _before_request() -> None:
        if request.endpoint == "static":
            return
        validate_csrf_request()
        load_current_user()

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.context_processor
    def _inject_template_globals() -> dict[str, Any]:
        return {
            "csrf_token": get_csrf_token(),
            "app_name": app.config["APP_NAME"],
            "app_short_name": app.config["APP_SHORT_NAME"],
        }

    # Register blueprints
    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_api_bp)
    app.register_blueprint(student_api_bp)
    app.register_blueprint(examiner_api_bp)
    app.register_blueprint(admin_api_bp)

    register_error_handlers(app)
    return app

