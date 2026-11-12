"""Authentication and session API endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from flask import Blueprint, current_app, g, make_response

from app.extensions.firebase import get_firebase_manager
from app.middleware.auth import get_dashboard_url_for_role, login_required
from app.middleware.csrf import get_csrf_token
from app.routes.helpers import api_success, client_ip, get_service, parse_json_body

auth_api_bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")


def _set_session_cookie(response, session_cookie: str) -> None:
    cookie_name = current_app.config.get("FIREBASE_SESSION_COOKIE_NAME", "rubriassess_fb_session")
    hours = int(current_app.config.get("SESSION_DURATION_HOURS", 12))
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    response.set_cookie(
        cookie_name,
        session_cookie,
        expires=expires,
        httponly=True,
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
        samesite=current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
        path="/",
    )


@auth_api_bp.route("/csrf", methods=["GET"])
def fetch_csrf_token():
    return api_success({"csrf_token": get_csrf_token()})


@auth_api_bp.route("/client-config", methods=["GET"])
def firebase_client_config():
    return api_success(
        {
            "firebase": current_app.config_cls_web_config(),
            "status": get_firebase_manager().status,
        }
    )


@auth_api_bp.route("/register", methods=["POST"])
def register():
    payload = parse_json_body()
    result = get_service("auth").register_student(payload, ip_address=client_ip())
    user = result["user"]
    if result.get("requires_approval"):
        return api_success(
            {
                "user": user,
                "requires_approval": True,
                "redirect_url": "/staff/login",
            },
            message="Staff registration submitted. Your account is pending Administrator verification and approval.",
            status_code=202,
        )

    resp, code = api_success(
        {
            "user": user,
            "requires_approval": False,
            "redirect_url": get_dashboard_url_for_role(user["role"]),
        },
        message="Account registered successfully.",
        status_code=201,
    )
    response = make_response(resp, code)
    _set_session_cookie(response, result["session_cookie"])
    return response


@auth_api_bp.route("/session-login", methods=["POST"])
def session_login():
    payload = parse_json_body()
    result = get_service("auth").session_login(payload, ip_address=client_ip())
    user = result["user"]
    resp, code = api_success(
        {
            "user": user,
            "redirect_url": get_dashboard_url_for_role(user["role"]),
        },
        message="Signed in successfully.",
    )
    response = make_response(resp, code)
    _set_session_cookie(response, result["session_cookie"])
    return response


@auth_api_bp.route("/logout", methods=["POST"])
def logout():
    user = getattr(g, "current_user", None)
    role = (user or {}).get("role", "")
    redirect_url = "/staff/login" if role == "examiner" else ("/admin/login" if role == "admin" else "/login")
    get_service("auth").logout(user, ip_address=client_ip())
    resp, code = api_success({"redirect_url": redirect_url}, message="Signed out successfully.")
    response = make_response(resp, code)
    cookie_name = current_app.config.get("FIREBASE_SESSION_COOKIE_NAME", "rubriassess_fb_session")
    response.delete_cookie(cookie_name, path="/")
    return response


@auth_api_bp.route("/me", methods=["GET"])
@login_required
def current_profile():
    return api_success({"user": g.current_user})
