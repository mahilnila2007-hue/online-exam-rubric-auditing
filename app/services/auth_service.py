"""Authentication, registration, staff verification gating, and session lifecycle service."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import current_app

from app.exceptions import AuthenticationError, AuthorizationError, ConflictError
from app.middleware.auth import get_auth_gateway
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditService
from app.services.time_utils import utc_now
from app.validators.auth_validators import (
    validate_register_payload,
    validate_session_login_payload,
)


class AuthService:
    def __init__(self, user_repo: UserRepository, audit_service: AuditService) -> None:
        self.user_repo = user_repo
        self.audit_service = audit_service

    def _session_duration(self) -> timedelta:
        hours = int(current_app.config.get("SESSION_DURATION_HOURS", 12))
        return timedelta(hours=hours)

    def register_student(self, payload: dict[str, Any] | None, *, ip_address: str = "") -> dict[str, Any]:
        """Register either an immediately active Student or a pending-approval Staff (Examiner) account."""
        data = validate_register_payload(payload)
        gateway = get_auth_gateway()
        claims = gateway.verify_id_token(data["id_token"])

        uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
        email = (claims.get("email") or "").strip().lower()
        if not uid or not email:
            raise AuthenticationError("Firebase account token must contain a valid UID and email.")

        existing = self.user_repo.get_by_id(uid)
        if existing:
            raise ConflictError("An account profile already exists for this user. Please sign in instead.")

        now = utc_now()
        is_staff_request = data["account_type"] == "staff"

        # Public registration can ONLY yield 'student' (active) or 'examiner' (pending admin approval).
        # Admin accounts can never be self-registered.
        assigned_role = "examiner" if is_staff_request else "student"
        assigned_status = "pending_approval" if is_staff_request else "active"

        user_doc = self.user_repo.create(
            {
                "uid": uid,
                "email": email,
                "full_name": data["full_name"],
                "role": assigned_role,
                "institution_id": data["institution_id"],
                "department": data["department"],
                "status": assigned_status,
                "approval_status": "pending" if is_staff_request else "approved",
                "last_login_at": None if is_staff_request else now,
            },
            doc_id=uid,
        )

        gateway.set_custom_claims(
            uid,
            {"role": assigned_role, "approved": not is_staff_request},
        )

        if is_staff_request:
            self.audit_service.record(
                actor=user_doc,
                action="STAFF_REGISTRATION_PENDING",
                target_type="user",
                target_id=uid,
                metadata={"role": "examiner", "institution_id": data["institution_id"]},
                ip_address=ip_address,
            )
            return {
                "user": user_doc,
                "session_cookie": None,
                "requires_approval": True,
            }

        session_cookie = gateway.create_session_cookie(data["id_token"], expires_in=self._session_duration())
        self.audit_service.record(
            actor=user_doc,
            action="USER_REGISTERED",
            target_type="user",
            target_id=uid,
            metadata={"role": "student", "institution_id": data["institution_id"]},
            ip_address=ip_address,
        )

        return {
            "user": user_doc,
            "session_cookie": session_cookie,
            "requires_approval": False,
        }

    def session_login(self, payload: dict[str, Any] | None, *, ip_address: str = "") -> dict[str, Any]:
        data = validate_session_login_payload(payload)
        gateway = get_auth_gateway()
        claims = gateway.verify_id_token(data["id_token"])

        uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
        if not uid:
            raise AuthenticationError("Invalid Firebase authentication token.")

        user_doc = self.user_repo.get_by_id(uid)
        if not user_doc:
            raise AuthenticationError(
                "No platform profile was found for this account. Please register first or contact an administrator."
            )

        status = user_doc.get("status")
        if status == "pending_approval":
            raise AuthorizationError(
                "Your staff registration is pending Administrator verification and approval.",
                error_code="ACCOUNT_PENDING_APPROVAL",
            )
        if status == "rejected":
            raise AuthorizationError(
                "Your staff registration request was declined by an Administrator.",
                error_code="ACCOUNT_REJECTED",
            )
        if status != "active":
            raise AuthorizationError("Your account has been suspended. Please contact an administrator.")

        role = user_doc.get("role", "student")
        portal = data.get("portal", "")
        if portal == "admin" and role != "admin":
            raise AuthorizationError(
                "This account does not have Administrator privileges. Please use the Student or Staff Login.",
                error_code="PORTAL_ROLE_MISMATCH",
            )
        if portal == "staff" and role not in {"examiner", "admin"}:
            raise AuthorizationError(
                "This account is a Student account. Please use the Student Login portal.",
                error_code="PORTAL_ROLE_MISMATCH",
            )
        if portal == "student" and role != "student":
            raise AuthorizationError(
                "Staff/Admin accounts must sign in through Staff Login or Admin Login.",
                error_code="PORTAL_ROLE_MISMATCH",
            )

        if claims.get("role") != role:
            gateway.set_custom_claims(uid, {"role": role, "approved": True})

        updated_user = self.user_repo.update(uid, {"last_login_at": utc_now()}) or user_doc
        session_cookie = gateway.create_session_cookie(data["id_token"], expires_in=self._session_duration())

        self.audit_service.record(
            actor=updated_user,
            action="USER_LOGIN",
            target_type="user",
            target_id=uid,
            metadata={"role": role},
            ip_address=ip_address,
        )

        return {"user": updated_user, "session_cookie": session_cookie}

    def logout(self, user: dict[str, Any] | None, *, ip_address: str = "") -> None:
        if not user:
            return
        uid = user.get("uid")
        if uid:
            try:
                get_auth_gateway().revoke_refresh_tokens(uid)
            except Exception:
                # Cookie clearance still terminates browser session even if remote revocation errors
                pass
            self.audit_service.record(
                actor=user,
                action="USER_LOGOUT",
                target_type="user",
                target_id=uid,
                ip_address=ip_address,
            )
