"""Shared route helpers for accessing services and parsing JSON safely."""

from __future__ import annotations

from typing import Any

from flask import Response, current_app, jsonify, request

from app.exceptions import ValidationError


def get_service(name: str) -> Any:
    return current_app.extensions["services"][name]


def parse_json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        raise ValidationError("Request body must contain valid JSON.")
    if not isinstance(data, dict):
        raise ValidationError("JSON request body must be an object.")
    return data


def api_success(data: Any = None, *, message: str | None = None, status_code: int = 200) -> tuple[Response, int]:
    payload: dict[str, Any] = {"success": True}
    if message:
        payload["message"] = message
    if data is not None:
        payload["data"] = data
    return jsonify(payload), status_code


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "")

