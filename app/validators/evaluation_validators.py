"""Validators for examiner criterion-level rubric evaluation and result publication."""

from __future__ import annotations

from typing import Any

from app.validators.common import FieldValidator


def validate_examiner_evaluation_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    v = FieldValidator(payload)
    examiner_feedback = v.optional_str("examiner_feedback", max_len=4000)
    publish_result = v.require_bool("publish_result", default=False)

    raw_questions = v.payload.get("question_evaluations")
    if not isinstance(raw_questions, dict):
        v.errors["question_evaluations"] = "question_evaluations must be a map keyed by question ID."
        v.raise_if_invalid()

    question_evaluations: dict[str, Any] = {}
    for qid, q_eval in raw_questions.items():
        q_key = str(qid).strip()
        if not q_key:
            continue
        if not isinstance(q_eval, dict):
            v.errors[f"question_evaluations.{q_key}"] = "Evaluation entry must be an object."
            continue

        q_feedback = str(q_eval.get("feedback") or "").strip()[:2000]
        raw_criteria = q_eval.get("criteria_scores")
        if not isinstance(raw_criteria, list) or len(raw_criteria) == 0:
            v.errors[f"question_evaluations.{q_key}.criteria_scores"] = (
                "Criterion-level scores are required for descriptive question evaluation."
            )
            continue

        criteria_scores: list[dict[str, Any]] = []
        for idx, cs in enumerate(raw_criteria):
            if not isinstance(cs, dict):
                v.errors[f"question_evaluations.{q_key}.criteria_scores.{idx}"] = "Criterion score must be an object."
                continue
            cid = str(cs.get("criterion_id") or "").strip()
            if not cid:
                v.errors[f"question_evaluations.{q_key}.criteria_scores.{idx}.criterion_id"] = "criterion_id is required."
                continue
            try:
                awarded = float(cs.get("awarded_marks"))
            except (TypeError, ValueError):
                v.errors[f"question_evaluations.{q_key}.criteria_scores.{idx}.awarded_marks"] = (
                    "Awarded marks must be a valid number."
                )
                continue
            if awarded < 0:
                v.errors[f"question_evaluations.{q_key}.criteria_scores.{idx}.awarded_marks"] = (
                    "Awarded marks cannot be negative."
                )
                continue

            criteria_scores.append(
                {
                    "criterion_id": cid,
                    "awarded_marks": round(awarded, 2),
                    "feedback": str(cs.get("feedback") or "").strip()[:1000],
                }
            )

        question_evaluations[q_key] = {
            "feedback": q_feedback,
            "criteria_scores": criteria_scores,
        }

    v.raise_if_invalid()
    return {
        "examiner_feedback": examiner_feedback,
        "publish_result": publish_result,
        "question_evaluations": question_evaluations,
    }

