"""CSRF protection utilities for API and form requests."""

from __future__ import annotations

import secrets
from flask import current_app, request, session

from app.exceptions import AuthorizationError

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def get_csrf_token() -> str:
    """Return the session-bound CSRF token, generating one if missing."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf_request() -> None:
    """Validate CSRF token for state-changing requests."""
    if request.method in SAFE_METHODS:
        return

    if current_app.config.get("WTF_CSRF_DISABLED"):
        return

    # Requests authenticating purely via Bearer Authorization header (non-cookie API clients)
    auth_header = request.headers.get("Authorization", "")
    session_cookie_name = current_app.config.get("FIREBASE_SESSION_COOKIE_NAME", "rubriassess_fb_session")
    if auth_header.startswith("Bearer ") and session_cookie_name not in request.cookies:
        return

    expected = session.get("csrf_token")
    provided = request.headers.get(CSRF_HEADER) or request.form.get("csrf_token")

    if not expected or not provided or not secrets.compare_digest(str(expected), str(provided)):
        raise AuthorizationError(
            "Invalid or missing security (CSRF) token. Please refresh the page and try again.",
            error_code="CSRF_VALIDATION_FAILED",
        )
