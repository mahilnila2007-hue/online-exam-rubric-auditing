"""Validators for question bank and descriptive evaluation rubrics."""

from __future__ import annotations

import uuid
from typing import Any

from app.validators.common import FieldValidator


def _parse_phrase_list(raw: Any, *, max_items: int = 25) -> list[str]:
    if isinstance(raw, str):
        return [c.strip() for c in raw.split(",") if c.strip()][:max_items]
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if str(c).strip()][:max_items]
    return []


def validate_rubric_payload(
    payload: dict[str, Any] | None,
    *,
    expected_max_marks: float | None = None,
) -> dict[str, Any]:
    v = FieldValidator(payload)
    title = v.require_str("title", label="Rubric title", min_len=3, max_len=160)
    subject = v.require_str("subject", label="Subject", min_len=2, max_len=100)
    model_answer = v.optional_str("model_answer", max_len=8000)

    raw_criteria = v.payload.get("criteria")
    if not isinstance(raw_criteria, list) or len(raw_criteria) == 0:
        v.errors["criteria"] = "At least one evaluation criterion is required."
        v.raise_if_invalid()

    criteria: list[dict[str, Any]] = []
    total_marks = 0.0

    for idx, item in enumerate(raw_criteria):
        if not isinstance(item, dict):
            v.errors[f"criteria.{idx}"] = "Criterion must be an object."
            continue
        cv = FieldValidator(item)
        c_title = cv.require_str("title", label=f"Criterion {idx + 1} title", min_len=2, max_len=120)
        c_desc = cv.optional_str("description", max_len=1000)
        c_marks = cv.require_number(
            "max_marks",
            label=f"Criterion {idx + 1} max marks",
            min_value=0.0,
            max_value=500.0,
            allow_zero=False,
        )

        key_concepts = _parse_phrase_list(item.get("key_concepts", []), max_items=25)
        alternative_phrases = _parse_phrase_list(item.get("alternative_phrases", []), max_items=35)

        raw_levels = item.get("levels", [])
        levels: list[dict[str, Any]] = []
        if isinstance(raw_levels, list):
            for lv in raw_levels:
                if isinstance(lv, dict) and str(lv.get("label", "")).strip():
                    levels.append(
                        {
                            "label": str(lv.get("label", "")).strip()[:40],
                            "min_score": float(lv.get("min_score", 0) or 0),
                            "max_score": float(lv.get("max_score", c_marks) or c_marks),
                            "descriptor": str(lv.get("descriptor", "")).strip()[:400],
                        }
                    )

        if cv.errors:
            for k, msg in cv.errors.items():
                v.errors[f"criteria.{idx}.{k}"] = msg
        else:
            cid = str(item.get("criterion_id") or f"crit_{uuid.uuid4().hex[:8]}").strip()
            total_marks = round(total_marks + c_marks, 2)
            criteria.append(
                {
                    "criterion_id": cid,
                    "title": c_title,
                    "description": c_desc,
                    "max_marks": c_marks,
                    "key_concepts": key_concepts,
                    "alternative_phrases": alternative_phrases,
                    "levels": levels,
                }
            )

    if total_marks <= 0 and "criteria" not in v.errors:
        v.errors["criteria"] = "Total rubric marks must be greater than zero."

    if expected_max_marks is not None and total_marks > 0 and abs(total_marks - expected_max_marks) > 0.01:
        v.errors["criteria"] = (
            f"Sum of rubric criteria marks ({total_marks:g}) must equal question marks ({expected_max_marks:g})."
        )

    v.raise_if_invalid()

    # Compute normalized weights for Phase 2/3 weighted auditing
    for criterion in criteria:
        criterion["weight"] = round(criterion["max_marks"] / total_marks, 4)

    return {
        "title": title,
        "subject": subject,
        "model_answer": model_answer,
        "max_marks": round(total_marks, 2),
        "criteria": criteria,
    }


def validate_question_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    v = FieldValidator(payload)
    subject = v.require_str("subject", label="Subject", min_len=2, max_len=100)
    topic = v.optional_str("topic", max_len=120, default="Core Concepts")
    difficulty = v.require_enum("difficulty", {"easy", "medium", "hard"}, label="Difficulty")
    q_type = v.require_enum("type", {"mcq", "descriptive"}, label="Question type")
    prompt = v.require_str("prompt", label="Question prompt", min_len=5, max_len=5000)
    marks = v.require_number("marks", label="Marks", min_value=0.0, max_value=200.0, allow_zero=False)
    explanation = v.optional_str("explanation", max_len=2000)
    question_set = v.optional_str("question_set", max_len=120, default="")

    raw_tags = v.payload.get("tags", [])
    if isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()][:15]
    elif isinstance(raw_tags, list):
        tags = [str(t).strip() for t in raw_tags if str(t).strip()][:15]
    else:
        tags = []

    options: list[dict[str, str]] = []
    correct_option_id = ""
    rubric_id: str | None = None
    inline_rubric: dict[str, Any] | None = None

    if q_type == "mcq":
        raw_options = v.payload.get("options")
        if not isinstance(raw_options, list) or len(raw_options) < 2 or len(raw_options) > 6:
            v.errors["options"] = "MCQ questions require between 2 and 6 answer options."
        else:
            seen_ids: set[str] = set()
            seen_texts: set[str] = set()
            for idx, opt in enumerate(raw_options):
                if not isinstance(opt, dict):
                    v.errors[f"options.{idx}"] = "Option must be an object."
                    continue
                opt_id = str(opt.get("id") or f"opt_{idx + 1}").strip()
                opt_text = str(opt.get("text") or "").strip()
                if not opt_text:
                    v.errors[f"options.{idx}"] = f"Option {idx + 1} text cannot be empty."
                    continue
                if opt_id in seen_ids:
                    v.errors[f"options.{idx}"] = "Duplicate option identifier."
                    continue
                lowered = opt_text.lower()
                if lowered in seen_texts:
                    v.errors[f"options.{idx}"] = "Answer options must be distinct."
                    continue
                seen_ids.add(opt_id)
                seen_texts.add(lowered)
                options.append({"id": opt_id, "text": opt_text[:500]})

            correct_option_id = v.require_str("correct_option_id", label="Correct answer option", min_len=1, max_len=50)
            if correct_option_id and correct_option_id not in seen_ids:
                v.errors["correct_option_id"] = "Selected correct option must match one of the provided options."

    elif q_type == "descriptive":
        raw_rubric_id = v.optional_str("rubric_id", max_len=120)
        raw_rubric_obj = v.payload.get("rubric")
        if raw_rubric_id:
            rubric_id = raw_rubric_id
        elif isinstance(raw_rubric_obj, dict):
            inline_rubric = validate_rubric_payload(
                {
                    **raw_rubric_obj,
                    "subject": raw_rubric_obj.get("subject") or subject or "General",
                },
                expected_max_marks=marks if marks > 0 else None,
            )
        else:
            v.errors["rubric"] = (
                "Descriptive questions must link an existing rubric or define evaluation rubric criteria."
            )

    v.raise_if_invalid()

    return {
        "subject": subject,
        "topic": topic or "Core Concepts",
        "difficulty": difficulty,
        "type": q_type,
        "prompt": prompt,
        "marks": marks,
        "explanation": explanation,
        "question_set": question_set,
        "tags": tags,
        "options": options if q_type == "mcq" else [],
        "correct_option_id": correct_option_id if q_type == "mcq" else "",
        "rubric_id": rubric_id,
        "inline_rubric": inline_rubric,
    }

