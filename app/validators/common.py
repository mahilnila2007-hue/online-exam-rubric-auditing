"""Reusable request validation primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from email_validator import EmailNotValidError, validate_email

from app.exceptions import ValidationError


class FieldValidator:
    """Accumulates field-level validation errors and raises a unified ValidationError."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            raise ValidationError("Request payload must be a JSON object.")
        self.payload = payload
        self.errors: dict[str, str] = {}

    def require_str(
        self,
        field: str,
        *,
        label: str | None = None,
        min_len: int = 1,
        max_len: int = 2000,
    ) -> str:
        name = label or field.replace("_", " ").capitalize()
        raw = self.payload.get(field)
        if not isinstance(raw, str):
            self.errors[field] = f"{name} is required."
            return ""
        cleaned = raw.strip()
        if len(cleaned) < min_len:
            self.errors[field] = (
                f"{name} is required." if min_len <= 1 else f"{name} must be at least {min_len} characters."
            )
            return cleaned
        if len(cleaned) > max_len:
            self.errors[field] = f"{name} must not exceed {max_len} characters."
        return cleaned

    def optional_str(self, field: str, *, max_len: int = 5000, default: str = "") -> str:
        raw = self.payload.get(field)
        if raw is None:
            return default
        if not isinstance(raw, str):
            self.errors[field] = f"{field.replace('_', ' ').capitalize()} must be text."
            return default
        cleaned = raw.strip()
        if len(cleaned) > max_len:
            self.errors[field] = f"{field.replace('_', ' ').capitalize()} must not exceed {max_len} characters."
        return cleaned

    def require_email(self, field: str = "email") -> str:
        raw = self.require_str(field, label="Email address", min_len=3, max_len=254)
        if field in self.errors:
            return ""
        try:
            info = validate_email(raw, check_deliverability=False)
            return info.normalized.lower()
        except EmailNotValidError as exc:
            self.errors[field] = f"Invalid email address: {exc}"
            return ""

    def require_enum(self, field: str, allowed: Iterable[str], *, label: str | None = None) -> str:
        allowed_set = set(allowed)
        name = label or field.replace("_", " ").capitalize()
        raw = self.payload.get(field)
        if not isinstance(raw, str) or raw.strip().lower() not in allowed_set:
            self.errors[field] = f"{name} must be one of: {', '.join(sorted(allowed_set))}."
            return ""
        return raw.strip().lower()

    def require_number(
        self,
        field: str,
        *,
        label: str | None = None,
        min_value: float = 0.0,
        max_value: float = 10000.0,
        allow_zero: bool = False,
    ) -> float:
        name = label or field.replace("_", " ").capitalize()
        raw = self.payload.get(field)
        try:
            num = float(raw)
        except (TypeError, ValueError):
            self.errors[field] = f"{name} must be a valid number."
            return 0.0
        if (not allow_zero and num <= min_value) or (allow_zero and num < min_value):
            comparator = "greater than" if not allow_zero else "at least"
            self.errors[field] = f"{name} must be {comparator} {min_value:g}."
        elif num > max_value:
            self.errors[field] = f"{name} must not exceed {max_value:g}."
        return round(num, 2)

    def require_int(
        self,
        field: str,
        *,
        label: str | None = None,
        min_value: int = 1,
        max_value: int = 10000,
    ) -> int:
        name = label or field.replace("_", " ").capitalize()
        raw = self.payload.get(field)
        if isinstance(raw, bool):
            self.errors[field] = f"{name} must be a whole number."
            return min_value
        try:
            val = int(raw)
            if isinstance(raw, float) and not raw.is_integer():
                raise ValueError("not integer")
        except (TypeError, ValueError):
            self.errors[field] = f"{name} must be a whole number."
            return min_value
        if val < min_value or val > max_value:
            self.errors[field] = f"{name} must be between {min_value} and {max_value}."
        return val

    def require_bool(self, field: str, *, default: bool = False) -> bool:
        raw = self.payload.get(field, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        self.errors[field] = f"{field.replace('_', ' ').capitalize()} must be true or false."
        return default

    def require_iso_datetime(self, field: str, *, label: str | None = None) -> datetime | None:
        name = label or field.replace("_", " ").capitalize()
        raw = self.payload.get(field)
        if not isinstance(raw, str) or not raw.strip():
            self.errors[field] = f"{name} is required."
            return None
        cleaned = raw.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            self.errors[field] = f"{name} must be a valid ISO-8601 date/time."
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def raise_if_invalid(self, message: str = "Please correct the highlighted validation errors.") -> None:
        if self.errors:
            raise ValidationError(message, details={"fields": self.errors})

