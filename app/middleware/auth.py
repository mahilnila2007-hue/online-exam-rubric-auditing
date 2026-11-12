"""Server-side authentication and role-based access control middleware."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable
from urllib.parse import quote

from flask import current_app, g, redirect, render_template, request, url_for

from app.exceptions import AuthenticationError, AuthorizationError, ServiceUnavailableError
from app.extensions.firebase import get_firebase_manager

logger = logging.getLogger(__name__)

VALID_ROLES = {"student", "examiner", "admin"}

ROLE_HOME_ENDPOINTS = {
    "student": "pages.student_dashboard",
    "examiner": "pages.examiner_dashboard",
    "admin": "pages.admin_dashboard",
}


class FirebaseAuthGateway:
    """Abstraction around Firebase Admin Auth operations for testability and clean separation."""

    def verify_id_token(self, id_token: str) -> dict[str, Any]:
        fb_auth = get_firebase_manager().require_auth()
        try:
            return fb_auth.verify_id_token(id_token, check_revoked=True)
        except Exception as exc:
            raise AuthenticationError(f"Invalid or expired authentication token: {exc}") from exc

    def verify_session_cookie(self, session_cookie: str) -> dict[str, Any]:
        fb_auth = get_firebase_manager().require_auth()
        try:
            return fb_auth.verify_session_cookie(session_cookie, check_revoked=True)
        except Exception as exc:
            raise AuthenticationError(f"Session has expired or been revoked: {exc}") from exc

    def create_session_cookie(self, id_token: str, expires_in: timedelta) -> str:
        fb_auth = get_firebase_manager().require_auth()
        try:
            return fb_auth.create_session_cookie(id_token, expires_in=expires_in)
        except Exception as exc:
            # Firebase Auth Emulator may not support create_session_cookie in some setups
            raise AuthenticationError(f"Could not establish secure session cookie: {exc}") from exc

    def set_custom_claims(self, uid: str, claims: dict[str, Any]) -> None:
        fb_auth = get_firebase_manager().require_auth()
        fb_auth.set_custom_user_claims(uid, claims)

    def create_user(self, *, email: str, password: str, display_name: str) -> Any:
        fb_auth = get_firebase_manager().require_auth()
        return fb_auth.create_user(email=email, password=password, display_name=display_name)

    def update_user_status(self, uid: str, *, disabled: bool) -> None:
        fb_auth = get_firebase_manager().require_auth()
        fb_auth.update_user(uid, disabled=disabled)

    def revoke_refresh_tokens(self, uid: str) -> None:
        fb_auth = get_firebase_manager().require_auth()
        fb_auth.revoke_refresh_tokens(uid)


def get_auth_gateway() -> Any:
    return current_app.extensions.get("auth_gateway") or FirebaseAuthGateway()


def _is_api_request() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def _resolve_bearer_or_cookie_claims() -> dict[str, Any] | None:
    gateway = get_auth_gateway()
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return gateway.verify_id_token(token)

    cookie_name = current_app.config.get("FIREBASE_SESSION_COOKIE_NAME", "rubriassess_fb_session")
    session_cookie = request.cookies.get(cookie_name)
    if session_cookie:
        return gateway.verify_session_cookie(session_cookie)

    return None


def load_current_user() -> None:
    """Populate flask.g.current_user from verified Firebase session cookie or Bearer token."""
    g.current_user = None
    g.auth_error = None

    # Skip verification for static assets
    if request.endpoint == "static":
        return

    try:
        claims = _resolve_bearer_or_cookie_claims()
    except ServiceUnavailableError as exc:
        g.auth_error = exc.message
        return
    except AuthenticationError as exc:
        g.auth_error = exc.message
        return

    if not claims:
        return

    uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    if not uid:
        return

    repos = current_app.extensions.get("repositories", {})
    user_repo = repos.get("users")
    if user_repo is None:
        return

    try:
        user_doc = user_repo.get_by_id(uid)
    except ServiceUnavailableError as exc:
        g.auth_error = exc.message
        return

    if not user_doc:
        g.auth_error = "User profile record does not exist."
        return

    status = user_doc.get("status")
    if status == "pending_approval":
        g.auth_error = "Your staff registration is pending Administrator verification and approval."
        return
    if status == "rejected":
        g.auth_error = "Your staff registration request was declined by an Administrator."
        return
    if status != "active":
        g.auth_error = "Account is suspended. Contact an administrator."
        return

    if user_doc.get("role") not in VALID_ROLES:
        g.auth_error = "User role is invalid."
        return

    g.current_user = user_doc


def get_dashboard_url_for_role(role: str) -> str:
    endpoint = ROLE_HOME_ENDPOINTS.get(role, "pages.login_page")
    return url_for(endpoint)


def _login_endpoint_for_path(path: str) -> str:
    if path.startswith("/examiner"):
        return "pages.staff_login_page"
    if path.startswith("/admin"):
        return "pages.admin_login_page"
    return "pages.login_page"


def login_required(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Require an authenticated active user."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if getattr(g, "current_user", None) is None:
            message = getattr(g, "auth_error", None) or "Authentication is required to access this resource."
            if _is_api_request():
                raise AuthenticationError(message)
            next_url = quote(request.full_path.rstrip("?"))
            login_endpoint = _login_endpoint_for_path(request.path)
            return redirect(f"{url_for(login_endpoint)}?next={next_url}")
        return fn(*args, **kwargs)

    return wrapper


def roles_required(*allowed_roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Require an authenticated user whose role matches one of allowed_roles."""

    allowed = set(allowed_roles)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        @login_required
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = g.current_user
            if user.get("role") not in allowed:
                if _is_api_request():
                    raise AuthorizationError(
                        f"Access denied. Required role: {', '.join(sorted(allowed))}."
                    )
                return (
                    render_template(
                        "errors/403.html",
                        user=user,
                        required_roles=sorted(allowed),
                        home_url=get_dashboard_url_for_role(user.get("role", "")),
                    ),
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
