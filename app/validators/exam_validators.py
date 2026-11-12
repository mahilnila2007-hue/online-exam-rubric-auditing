"""Validators for examination creation, editing, scheduling, marking, and grade rules."""

from __future__ import annotations

from typing import Any

from app.validators.common import FieldValidator

DEFAULT_GRADE_RULES: list[dict[str, Any]] = [
    {"grade": "A+", "min_percentage": 90.0},
    {"grade": "A", "min_percentage": 80.0},
    {"grade": "B", "min_percentage": 70.0},
    {"grade": "C", "min_percentage": 60.0},
    {"grade": "D", "min_percentage": 50.0},
    {"grade": "F", "min_percentage": 0.0},
]


def validate_grade_rules(raw_rules: Any, errors: dict[str, str]) -> list[dict[str, Any]]:
    """Validate and sort descending grade boundary rules."""
    if raw_rules is None:
        return [dict(rule) for rule in DEFAULT_GRADE_RULES]
    if not isinstance(raw_rules, list) or len(raw_rules) == 0:
        errors["grade_rules"] = "Provide at least one grade boundary rule."
        return [dict(rule) for rule in DEFAULT_GRADE_RULES]

    parsed: list[dict[str, Any]] = []
    seen_grades: set[str] = set()
    for idx, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            errors[f"grade_rules.{idx}"] = "Grade rule must be an object."
            continue
        grade = str(item.get("grade") or "").strip().upper()
        if not grade or len(grade) > 10:
            errors[f"grade_rules.{idx}.grade"] = "Grade label must be 1–10 characters."
            continue
        if grade in seen_grades:
            errors[f"grade_rules.{idx}.grade"] = f"Duplicate grade label '{grade}'."
            continue
        try:
            min_pct = float(item.get("min_percentage"))
        except (TypeError, ValueError):
            errors[f"grade_rules.{idx}.min_percentage"] = "Minimum percentage must be a number."
            continue
        if min_pct < 0 or min_pct > 100:
            errors[f"grade_rules.{idx}.min_percentage"] = "Minimum percentage must be between 0 and 100."
            continue
        seen_grades.add(grade)
        parsed.append({"grade": grade, "min_percentage": round(min_pct, 2)})

    if parsed and all(r["min_percentage"] > 0 for r in parsed):
        errors["grade_rules"] = "Include a fallback grade rule with min_percentage of 0 (e.g., F at 0%)."

    return sorted(parsed, key=lambda r: r["min_percentage"], reverse=True)


def validate_exam_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    v = FieldValidator(payload)
    title = v.require_str("title", label="Examination title", min_len=3, max_len=180)
    course_code = v.require_str("course_code", label="Course code", min_len=2, max_len=30).upper()
    description = v.optional_str("description", max_len=2500)
    duration_minutes = v.require_int("duration_minutes", label="Duration (minutes)", min_value=5, max_value=480)
    passing_marks = v.require_number("passing_marks", label="Passing marks", min_value=0.0, max_value=5000.0, allow_zero=True)
    status = v.require_enum("status", {"draft", "scheduled", "published", "archived"}, label="Status")

    scheduled_start = v.require_iso_datetime("scheduled_start", label="Scheduled start time")
    scheduled_end = v.require_iso_datetime("scheduled_end", label="Scheduled end time")

    if scheduled_start and scheduled_end and scheduled_end <= scheduled_start:
        v.errors["scheduled_end"] = "Scheduled end time must be after scheduled start time."

    raw_instructions = v.payload.get("instructions", [])
    instructions: list[str] = []
    if isinstance(raw_instructions, str):
        instructions = [line.strip() for line in raw_instructions.splitlines() if line.strip()]
    elif isinstance(raw_instructions, list):
        instructions = [str(line).strip() for line in raw_instructions if str(line).strip()]
    else:
        v.errors["instructions"] = "Instructions must be a list of rules or multiline text."

    raw_q_ids = v.payload.get("question_ids", [])
    if not isinstance(raw_q_ids, list):
        v.errors["question_ids"] = "Selected question IDs must be an array."
        question_ids: list[str] = []
    else:
        seen: set[str] = set()
        question_ids = []
        for qid in raw_q_ids:
            cleaned = str(qid).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                question_ids.append(cleaned)

    shuffle_questions = v.require_bool("shuffle_questions", default=False)
    allow_review_after_submit = v.require_bool("allow_review_after_submit", default=True)
    rubric_audit_enabled = v.require_bool("rubric_audit_enabled", default=True)

    # Phase 2: Configurable MCQ negative marking & grade rules
    negative_marking_enabled = v.require_bool("negative_marking_enabled", default=False)
    negative_mark_fraction = 0.0
    if negative_marking_enabled:
        negative_mark_fraction = v.require_number(
            "negative_mark_fraction",
            label="Negative marking deduction fraction",
            min_value=0.0,
            max_value=1.0,
            allow_zero=False,
        )
    elif "negative_mark_fraction" in v.payload and v.payload.get("negative_mark_fraction") not in (None, ""):
        negative_mark_fraction = v.require_number(
            "negative_mark_fraction",
            label="Negative marking deduction fraction",
            min_value=0.0,
            max_value=1.0,
            allow_zero=True,
        )

    grade_rules = validate_grade_rules(v.payload.get("grade_rules"), v.errors)

    if status in {"published", "scheduled"} and len(question_ids) == 0:
        v.errors["question_ids"] = "Attach at least one question before scheduling or publishing an examination."

    v.raise_if_invalid()

    return {
        "title": title,
        "course_code": course_code,
        "description": description,
        "instructions": instructions[:30],
        "scheduled_start": scheduled_start.isoformat() if scheduled_start else "",
        "scheduled_end": scheduled_end.isoformat() if scheduled_end else "",
        "duration_minutes": duration_minutes,
        "passing_marks": passing_marks,
        "status": status,
        "question_ids": question_ids,
        "shuffle_questions": shuffle_questions,
        "allow_review_after_submit": allow_review_after_submit,
        "rubric_audit_enabled": rubric_audit_enabled,
        "negative_marking_enabled": negative_marking_enabled,
        "negative_mark_fraction": round(negative_mark_fraction, 4),
        "grade_rules": grade_rules,
    }
