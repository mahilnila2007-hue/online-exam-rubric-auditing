"""Validators for administrative user lifecycle actions."""

from __future__ import annotations

from typing import Any

from app.validators.common import FieldValidator


def validate_admin_create_user_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    v = FieldValidator(payload)
    email = v.require_email("email")
    password = v.require_str("password", label="Temporary password", min_len=8, max_len=128)
    full_name = v.require_str("full_name", label="Full name", min_len=2, max_len=120)
    role = v.require_enum("role", {"student", "examiner", "admin"}, label="Role")
    institution_id = v.require_str("institution_id", label="Institution ID", min_len=2, max_len=60)
    department = v.optional_str("department", max_len=100, default="Academic Affairs")
    v.raise_if_invalid()
    return {
        "email": email,
        "password": password,
        "full_name": full_name,
        "role": role,
        "institution_id": institution_id,
        "department": department or "Academic Affairs",
    }


def validate_admin_update_user_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    v = FieldValidator(payload)
    updates: dict[str, Any] = {}

    if "role" in v.payload:
        updates["role"] = v.require_enum("role", {"student", "examiner", "admin"}, label="Role")
    if "status" in v.payload:
        updates["status"] = v.require_enum("status", {"active", "suspended"}, label="Account status")
    if "full_name" in v.payload:
        updates["full_name"] = v.require_str("full_name", label="Full name", min_len=2, max_len=120)
    if "institution_id" in v.payload:
        updates["institution_id"] = v.require_str("institution_id", label="Institution ID", min_len=2, max_len=60)
    if "department" in v.payload:
        updates["department"] = v.optional_str("department", max_len=100, default="General Studies")

    if not updates and not v.errors:
        v.errors["payload"] = "Provide at least one updatable field."

    v.raise_if_invalid()
    return updates


def validate_reject_staff_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    v = FieldValidator(payload or {})
    reason = v.optional_str("reason", max_len=500, default="")
    v.raise_if_invalid()
    return {"reason": reason}

