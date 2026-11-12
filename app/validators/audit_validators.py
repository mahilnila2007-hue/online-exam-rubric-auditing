"""Validators for Phase 3 rubric auditing, suggestion approval/rejection, and thresholds."""

from __future__ import annotations

from typing import Any

from app.validators.common import FieldValidator


def validate_run_audit_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload or {}
    v = FieldValidator(raw)
    threshold = 0.56
    if "confidence_threshold" in raw and raw.get("confidence_threshold") not in (None, ""):
        threshold = v.require_number(
            "confidence_threshold",
            label="Confidence threshold",
            min_value=0.40,
            max_value=0.95,
            allow_zero=True,
        )
    v.raise_if_invalid()
    return {"confidence_threshold": round(float(threshold), 4)}


def validate_approve_suggestion_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    raw = payload or {}
    v = FieldValidator(raw)
    phrase_override = v.optional_str("phrase_override", max_len=160)
    approval_note = v.optional_str("approval_note", max_len=1000)
    v.raise_if_invalid()
    return {
        "phrase_override": phrase_override,
        "approval_note": approval_note,
    }


def validate_reject_suggestion_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    raw = payload or {}
    v = FieldValidator(raw)
    reason = v.optional_str("reason", max_len=1000)
    v.raise_if_invalid()
    return {"reason": reason}

