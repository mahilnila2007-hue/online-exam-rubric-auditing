"""Validators for student exam answer saving and submission."""

from __future__ import annotations

from typing import Any

from app.validators.common import FieldValidator


def validate_answers_payload(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    v = FieldValidator(payload)
    raw_answers = v.payload.get("answers")
    if not isinstance(raw_answers, dict):
        v.errors["answers"] = "Answers payload must be a map keyed by question ID."
        v.raise_if_invalid()

    normalized: dict[str, dict[str, Any]] = {}
    for qid, ans in raw_answers.items():
        q_key = str(qid).strip()
        if not q_key:
            continue
        if not isinstance(ans, dict):
            v.errors[f"answers.{q_key}"] = "Answer entry must be an object."
            continue

        selected_opt = ans.get("selected_option_id")
        if selected_opt is not None and not isinstance(selected_opt, str):
            v.errors[f"answers.{q_key}.selected_option_id"] = "Selected option must be a string."
            continue

        text_answer = ans.get("text_answer")
        if text_answer is not None and not isinstance(text_answer, str):
            v.errors[f"answers.{q_key}.text_answer"] = "Descriptive answer must be text."
            continue

        if isinstance(text_answer, str) and len(text_answer) > 25000:
            v.errors[f"answers.{q_key}.text_answer"] = "Descriptive answer exceeds 25,000 character limit."
            continue

        flagged = bool(ans.get("flagged_for_review", False))
        normalized[q_key] = {
            "selected_option_id": selected_opt.strip() if isinstance(selected_opt, str) and selected_opt.strip() else None,
            "text_answer": text_answer.strip() if isinstance(text_answer, str) and text_answer.strip() else None,
            "flagged_for_review": flagged,
        }

    v.raise_if_invalid()
    return normalized

