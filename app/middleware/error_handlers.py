"""Centralized Flask error handling for JSON APIs and HTML pages."""

from __future__ import annotations

import logging

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from app.exceptions import AppError
from app.middleware.auth import get_dashboard_url_for_role

logger = logging.getLogger(__name__)


def _wants_json() -> bool:
    return (
        request.path.startswith("/api/")
        or request.accept_mimetypes.best == "application/json"
    )


def register_error_handlers(app: Flask) -> None:
    """Attach global error handlers to the Flask application."""

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):
        if _wants_json():
            return jsonify(exc.to_dict()), exc.status_code

        user = getattr(g, "current_user", None)
        home_url = get_dashboard_url_for_role(user["role"]) if user else "/login"
        if exc.status_code == 403:
            return render_template("errors/403.html", user=user, home_url=home_url, message=exc.message), 403
        if exc.status_code == 404:
            return render_template("errors/404.html", user=user, home_url=home_url, message=exc.message), 404
        return render_template("errors/500.html", user=user, home_url=home_url, message=exc.message), exc.status_code

    @app.errorhandler(404)
    def handle_not_found(exc: HTTPException):
        if _wants_json():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": {"code": "NOT_FOUND", "message": "Requested resource was not found."},
                    }
                ),
                404,
            )
        user = getattr(g, "current_user", None)
        home_url = get_dashboard_url_for_role(user["role"]) if user else "/login"
        return render_template("errors/404.html", user=user, home_url=home_url), 404

    @app.errorhandler(403)
    def handle_forbidden(exc: HTTPException):
        if _wants_json():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": {"code": "FORBIDDEN", "message": "You do not have permission for this action."},
                    }
                ),
                403,
            )
        user = getattr(g, "current_user", None)
        home_url = get_dashboard_url_for_role(user["role"]) if user else "/login"
        return render_template("errors/403.html", user=user, home_url=home_url), 403

    @app.errorhandler(413)
    def handle_payload_too_large(exc: HTTPException):
        message = "Uploaded file or request body exceeds the maximum allowed size limit (10 MB)."
        if _wants_json():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": {"code": "PAYLOAD_TOO_LARGE", "message": message},
                    }
                ),
                413,
            )
        user = getattr(g, "current_user", None)
        home_url = get_dashboard_url_for_role(user["role"]) if user else "/login"
        return render_template("errors/500.html", user=user, home_url=home_url, message=message), 413

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        if isinstance(exc, HTTPException):
            if _wants_json():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": {"code": "HTTP_ERROR", "message": exc.description},
                        }
                    ),
                    exc.code or 500,
                )
            return exc

        logger.exception("Unhandled exception on %s %s", request.method, request.path)
        if _wants_json():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "An unexpected server error occurred.",
                        },
                    }
                ),
                500,
            )
        user = getattr(g, "current_user", None)
        home_url = get_dashboard_url_for_role(user["role"]) if user else "/login"
        return render_template("errors/500.html", user=user, home_url=home_url), 500

