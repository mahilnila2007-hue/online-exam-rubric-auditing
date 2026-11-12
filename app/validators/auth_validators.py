"""Validators for authentication and registration payloads."""

from __future__ import annotations

from typing import Any

from app.validators.common import FieldValidator


def validate_session_login_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    v = FieldValidator(payload)
    id_token = v.require_str("id_token", label="Firebase ID token", min_len=10, max_len=8192)
    portal_raw = v.optional_str("portal", max_len=20, default="")
    portal = portal_raw.lower() if portal_raw.lower() in {"student", "staff", "admin"} else ""
    v.raise_if_invalid()
    return {"id_token": id_token, "portal": portal}


def validate_register_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    v = FieldValidator(payload)
    id_token = v.require_str("id_token", label="Firebase ID token", min_len=10, max_len=8192)
    full_name = v.require_str("full_name", label="Full name", min_len=2, max_len=120)
    institution_id = v.require_str("institution_id", label="Student / Staff ID", min_len=2, max_len=60)
    department = v.optional_str("department", max_len=100, default="General Studies")

    raw_type = v.payload.get("account_type", "student")
    account_type = str(raw_type).strip().lower() if isinstance(raw_type, str) else "student"
    if account_type not in {"student", "staff"}:
        v.errors["account_type"] = "Account type must be 'student' or 'staff'."

    v.raise_if_invalid()
    return {
        "id_token": id_token,
        "full_name": full_name,
        "institution_id": institution_id,
        "department": department or "General Studies",
        "account_type": account_type,
    }
