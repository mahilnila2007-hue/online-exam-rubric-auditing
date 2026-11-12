"""Transparent rubric-based descriptive evaluation & examiner review service."""

from __future__ import annotations

import re
from typing import Any

from app.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.repositories.exam_repo import ExamRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.rubric_repo import RubricRepository
from app.repositories.submission_repo import SubmissionRepository
from app.services.audit_service import AuditService
from app.services.result_service import ResultService, compute_grade_and_pass
from app.services.time_utils import utc_now
from app.validators.evaluation_validators import validate_examiner_evaluation_payload


def _phrase_present(text_lower: str, phrase: str) -> bool:
    """Check whether a phrase appears cleanly in normalized student response text."""
    needle = phrase.strip().lower()
    if not needle:
        return False
    # Use word boundaries when alphanumeric; fall back to substring for math/symbolic terms
    if re.match(r"^[a-z0-9][a-z0-9\s\-_]*[a-z0-9]$", needle) or re.match(r"^[a-z0-9]+$", needle):
        pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
        return bool(re.search(pattern, text_lower))
    return needle in text_lower


def evaluate_criterion_transparently(text_answer: str, criterion: dict[str, Any]) -> dict[str, Any]:
    """
    Transparent, deterministic preliminary rubric check against expected concepts and
    alternative acceptable phrases. Does not claim semantic comprehension; intended as
    an auditable aid for examiner review.
    """
    max_marks = float(criterion.get("max_marks", 0.0) or 0.0)
    key_concepts = [str(c).strip() for c in criterion.get("key_concepts", []) if str(c).strip()]
    alt_phrases = [str(p).strip() for p in criterion.get("alternative_phrases", []) if str(p).strip()]
    text_lower = " ".join((text_answer or "").lower().split())

    matched_concepts = [c for c in key_concepts if _phrase_present(text_lower, c)]
    missing_concepts = [c for c in key_concepts if c not in matched_concepts]
    matched_alternatives = [p for p in alt_phrases if _phrase_present(text_lower, p)]

    if not text_lower:
        coverage_ratio = 0.0
        suggested_marks = 0.0
        feedback = "No response provided for this criterion."
    elif key_concepts:
        covered_units = min(len(key_concepts), len(matched_concepts) + len(matched_alternatives))
        coverage_ratio = round(covered_units / len(key_concepts), 4)
        suggested_marks = round(min(max_marks, max_marks * coverage_ratio), 2)
        feedback = (
            f"Transparent rubric check matched {covered_units}/{len(key_concepts)} configured concept "
            f"slot(s) ({round(coverage_ratio * 100)}% indicator coverage). Requires examiner verification."
        )
    elif alt_phrases:
        covered_units = len(matched_alternatives)
        coverage_ratio = round(covered_units / len(alt_phrases), 4)
        suggested_marks = round(min(max_marks, max_marks * coverage_ratio), 2)
        feedback = (
            f"Transparent rubric check matched {covered_units}/{len(alt_phrases)} acceptable phrase(s). "
            f"Requires examiner verification."
        )
    else:
        coverage_ratio = 0.0
        suggested_marks = 0.0
        feedback = "No concept keywords configured on this rubric criterion; manual examiner scoring required."

    return {
        "criterion_id": criterion.get("criterion_id"),
        "title": criterion.get("title", ""),
        "description": criterion.get("description", ""),
        "max_marks": round(max_marks, 2),
        "weight": criterion.get("weight", 0),
        "key_concepts": key_concepts,
        "alternative_phrases": alt_phrases,
        "matched_concepts": matched_concepts,
        "missing_concepts": missing_concepts,
        "matched_alternatives": matched_alternatives,
        "coverage_ratio": coverage_ratio,
        "suggested_marks": suggested_marks,
        "awarded_marks": suggested_marks,
        "examiner_override": False,
        "evaluation_method": "transparent_phrase_rubric_match",
        "feedback": feedback,
    }


class EvaluationService:
    def __init__(
        self,
        exam_repo: ExamRepository,
        question_repo: QuestionRepository,
        rubric_repo: RubricRepository,
        submission_repo: SubmissionRepository,
        result_service: ResultService,
        audit_service: AuditService,
    ) -> None:
        self.exam_repo = exam_repo
        self.question_repo = question_repo
        self.rubric_repo = rubric_repo
        self.submission_repo = submission_repo
        self.result_service = result_service
        self.audit_service = audit_service

    def _load_authorized_submission_and_exam(
        self,
        submission_id: str,
        user: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        submission = self.submission_repo.get_by_id(submission_id)
        if not submission:
            raise NotFoundError("Submission record not found.")
        exam = self.exam_repo.get_by_id(submission["exam_id"])
        if not exam:
            raise NotFoundError("Examination record not found.")
        if user.get("role") != "admin" and exam.get("created_by") != user.get("uid"):
            raise AuthorizationError("Only the owning examiner or an administrator can evaluate this submission.")
        if submission.get("status") not in {"submitted", "auto_submitted"}:
            raise ValidationError("Cannot evaluate a submission while the examination attempt is still in progress.")
        return submission, exam

    def _resolve_question_rubric(self, question: dict[str, Any]) -> dict[str, Any]:
        rubric_id = question.get("rubric_id")
        if rubric_id:
            rubric = self.rubric_repo.get_by_id(rubric_id)
            if rubric:
                return rubric
        return question.get("rubric_snapshot") or {
            "rubric_id": None,
            "title": "Analytical Rubric",
            "version": 1,
            "model_answer": "",
            "criteria": [],
        }

    def run_preliminary_evaluation(
        self,
        submission_id: str,
        current_user: dict[str, Any],
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        """Run transparent criterion-level preliminary evaluation across descriptive answers."""
        submission, exam = self._load_authorized_submission_and_exam(submission_id, current_user)
        grading = dict(submission.get("grading", {}))
        current_status = grading.get("evaluation_status")

        if current_status in {"evaluated", "completed"}:
            raise ConflictError(
                "This submission has already completed evaluation. Use Examiner Review to adjust marks.",
                error_code="DUPLICATE_EVALUATION_PREVENTED",
            )
        if current_status == "preliminary_evaluated":
            raise ConflictError(
                "Preliminary rubric evaluation has already been executed for this submission.",
                error_code="DUPLICATE_EVALUATION_PREVENTED",
            )

        questions = self.question_repo.get_many_by_ids(submission.get("question_order", []))
        answers = submission.get("answers", {})
        rubric_evals = dict(grading.get("rubric_evaluations", {}))
        descriptive_score = 0.0

        for q in questions:
            if q.get("type") != "descriptive":
                continue
            qid = q["question_id"]
            text_ans = (answers.get(qid, {}) or {}).get("text_answer") or ""
            rubric = self._resolve_question_rubric(q)
            criteria_results = [
                evaluate_criterion_transparently(text_ans, crit)
                for crit in rubric.get("criteria", [])
            ]
            q_score = round(sum(c["suggested_marks"] for c in criteria_results), 2)
            descriptive_score = round(descriptive_score + q_score, 2)

            rubric_evals[qid] = {
                "question_id": qid,
                "rubric_id": q.get("rubric_id"),
                "rubric_version": rubric.get("version", 1),
                "max_marks": round(float(q.get("marks", 0)), 2),
                "awarded_marks": q_score,
                "suggested_marks": q_score,
                "evaluation_status": "preliminary_evaluated",
                "feedback": "Preliminary rubric criterion matching complete; awaiting examiner review.",
                "criteria_scores": criteria_results,
            }

        mcq_score = float(grading.get("mcq_score", 0.0) or 0.0)
        grading["descriptive_score"] = descriptive_score
        grading["total_score"] = round(mcq_score + descriptive_score, 2)
        grading["evaluation_status"] = "preliminary_evaluated"
        grading["rubric_evaluations"] = rubric_evals
        grading["preliminary_evaluated_at"] = utc_now().isoformat()

        updated = self.submission_repo.update(submission_id, {"grading": grading}) or {
            **submission,
            "grading": grading,
        }
        self.audit_service.record(
            actor=current_user,
            action="RUBRIC_PRELIMINARY_EVALUATED",
            target_type="submission",
            target_id=submission_id,
            metadata={"exam_id": exam["exam_id"], "preliminary_descriptive_score": descriptive_score},
            ip_address=ip_address,
        )
        return updated

    def batch_preliminary_evaluate_exam(
        self,
        exam_id: str,
        current_user: dict[str, Any],
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")
        if current_user.get("role") != "admin" and exam.get("created_by") != current_user.get("uid"):
            raise AuthorizationError("You do not have permission to evaluate this examination.")

        submissions = self.submission_repo.list_by_exam(exam_id)
        processed = 0
        skipped = 0

        for sub in submissions:
            if sub.get("status") not in {"submitted", "auto_submitted"}:
                continue
            eval_status = sub.get("grading", {}).get("evaluation_status")
            if eval_status == "pending_descriptive":
                self.run_preliminary_evaluation(sub["submission_id"], current_user, ip_address=ip_address)
                processed += 1
            else:
                skipped += 1

        return {"processed_count": processed, "skipped_count": skipped}

    def get_evaluation_workspace(
        self,
        submission_id: str,
        current_user: dict[str, Any],
    ) -> dict[str, Any]:
        submission, exam = self._load_authorized_submission_and_exam(submission_id, current_user)
        questions = self.question_repo.get_many_by_ids(submission.get("question_order", []))
        answers = submission.get("answers", {})
        grading = submission.get("grading", {})
        mcq_breakdown = grading.get("mcq_breakdown", {})
        rubric_evals = grading.get("rubric_evaluations", {})

        mcq_items: list[dict[str, Any]] = []
        descriptive_items: list[dict[str, Any]] = []

        for idx, q in enumerate(questions, start=1):
            qid = q["question_id"]
            ans = answers.get(qid, {})
            if q.get("type") == "mcq":
                mb = mcq_breakdown.get(qid, {})
                mcq_items.append(
                    {
                        "index": idx,
                        "question_id": qid,
                        "prompt": q["prompt"],
                        "marks": float(q["marks"]),
                        "options": q.get("options", []),
                        "selected_option_id": ans.get("selected_option_id"),
                        "correct_option_id": q.get("correct_option_id"),
                        "is_correct": mb.get("is_correct", False),
                        "outcome": mb.get("outcome", "correct" if mb.get("is_correct") else "incorrect"),
                        "awarded_marks": float(mb.get("awarded_marks", 0.0)),
                    }
                )
            else:
                rubric = self._resolve_question_rubric(q)
                text_ans = ans.get("text_answer") or ""
                existing_eval = rubric_evals.get(qid, {})
                existing_crit_map = {
                    c.get("criterion_id"): c for c in existing_eval.get("criteria_scores", [])
                }

                criteria_workspace: list[dict[str, Any]] = []
                for crit in rubric.get("criteria", []):
                    cid = crit.get("criterion_id")
                    prev = existing_crit_map.get(cid, {})
                    preview = evaluate_criterion_transparently(text_ans, crit)
                    criteria_workspace.append(
                        {
                            **preview,
                            "suggested_marks": prev.get("suggested_marks", preview["suggested_marks"]),
                            "awarded_marks": (
                                prev.get("awarded_marks")
                                if prev.get("awarded_marks") is not None
                                else preview["suggested_marks"]
                            ),
                            "examiner_override": bool(prev.get("examiner_override", False)),
                            "feedback": prev.get("feedback") or preview["feedback"],
                        }
                    )

                descriptive_items.append(
                    {
                        "index": idx,
                        "question_id": qid,
                        "prompt": q["prompt"],
                        "marks": float(q["marks"]),
                        "subject": q.get("subject", ""),
                        "student_answer": text_ans,
                        "rubric": {
                            "rubric_id": rubric.get("rubric_id"),
                            "title": rubric.get("title", "Analytical Rubric"),
                            "version": rubric.get("version", 1),
                            "model_answer": rubric.get("model_answer", ""),
                        },
                        "question_feedback": existing_eval.get("feedback", ""),
                        "evaluation_status": existing_eval.get("evaluation_status", "pending_evaluation"),
                        "criteria": criteria_workspace,
                    }
                )

        existing_result = self.result_service.result_repo.get_by_exam_and_student(
            exam["exam_id"], submission["student_uid"]
        )
        total_max = float(grading.get("total_max_score", exam.get("total_marks", 0)) or 0)
        mcq_score = float(grading.get("mcq_score", 0.0) or 0.0)
        desc_score = float(grading.get("descriptive_score") or 0.0)
        preview_grade = compute_grade_and_pass(
            obtained_marks=round(mcq_score + desc_score, 2),
            total_marks=total_max,
            passing_marks=float(exam.get("passing_marks", 0.0) or 0.0),
            grade_rules=exam.get("grade_rules"),
        )

        return {
            "submission": {
                "submission_id": submission["submission_id"],
                "exam_id": exam["exam_id"],
                "student_name": submission.get("student_name", ""),
                "student_email": submission.get("student_email", ""),
                "institution_id": submission.get("institution_id", ""),
                "status": submission.get("status"),
                "submitted_at": submission.get("submitted_at"),
                "duration_seconds_used": submission.get("duration_seconds_used", 0),
                "publication_status": (existing_result or {}).get("publication_status", "unpublished"),
                "result_id": (existing_result or {}).get("result_id"),
            },
            "exam": {
                "exam_id": exam["exam_id"],
                "title": exam["title"],
                "course_code": exam["course_code"],
                "total_marks": exam.get("total_marks", total_max),
                "passing_marks": exam.get("passing_marks", 0),
                "negative_marking_enabled": exam.get("negative_marking_enabled", False),
                "negative_mark_fraction": exam.get("negative_mark_fraction", 0.0),
                "grade_rules": exam.get("grade_rules"),
            },
            "grading": {
                "mcq_score": mcq_score,
                "mcq_max_score": float(grading.get("mcq_max_score", 0.0) or 0.0),
                "negative_deductions": float(grading.get("negative_deductions", 0.0) or 0.0),
                "descriptive_score": grading.get("descriptive_score"),
                "descriptive_max_score": float(grading.get("descriptive_max_score", 0.0) or 0.0),
                "total_score": grading.get("total_score"),
                "total_max_score": total_max,
                "evaluation_status": grading.get("evaluation_status"),
                "examiner_feedback": grading.get("examiner_feedback", ""),
                "decision_history": grading.get("decision_history", []),
                "evaluation_history": grading.get("evaluation_history", []),
                "preview_grade": preview_grade,
            },
            "rubric_audit": submission.get("rubric_audit", {}),
            "mcq_questions": mcq_items,
            "descriptive_questions": descriptive_items,
        }

    def save_examiner_evaluation(
        self,
        submission_id: str,
        current_user: dict[str, Any],
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_examiner_evaluation_payload(payload)
        submission, exam = self._load_authorized_submission_and_exam(submission_id, current_user)
        questions = self.question_repo.get_many_by_ids(submission.get("question_order", []))
        answers = submission.get("answers", {})
        grading = dict(submission.get("grading", {}))
        existing_rubric_evals = dict(grading.get("rubric_evaluations", {}))

        desc_questions = [q for q in questions if q.get("type") == "descriptive"]
        submitted_map = validated["question_evaluations"]
        missing_q = [q["question_id"] for q in desc_questions if q["question_id"] not in submitted_map]
        if missing_q:
            raise ValidationError(
                f"Evaluation scores are required for all descriptive questions: {', '.join(missing_q)}."
            )

        updated_rubric_evals: dict[str, Any] = {}
        descriptive_score = 0.0
        now = utc_now()
        now_iso = now.isoformat()

        for q in desc_questions:
            qid = q["question_id"]
            rubric = self._resolve_question_rubric(q)
            text_ans = (answers.get(qid, {}) or {}).get("text_answer") or ""
            rubric_criteria = {c["criterion_id"]: c for c in rubric.get("criteria", [])}
            q_input = submitted_map[qid]

            provided_crit_map = {cs["criterion_id"]: cs for cs in q_input["criteria_scores"]}
            if set(rubric_criteria.keys()) != set(provided_crit_map.keys()):
                raise ValidationError(
                    f"Question '{qid}' evaluation must score every criterion defined in its rubric."
                )

            prev_q_eval = existing_rubric_evals.get(qid, {})
            prev_crit_map = {c.get("criterion_id"): c for c in prev_q_eval.get("criteria_scores", [])}

            final_criteria_scores: list[dict[str, Any]] = []
            q_total = 0.0
            for cid, crit in rubric_criteria.items():
                crit_max = float(crit.get("max_marks", 0.0))
                entry = provided_crit_map[cid]
                awarded = float(entry["awarded_marks"])
                if awarded > crit_max + 0.001:
                    raise ValidationError(
                        f"Awarded marks ({awarded:g}) for '{crit['title']}' cannot exceed criterion max ({crit_max:g})."
                    )

                baseline = prev_crit_map.get(cid) or evaluate_criterion_transparently(text_ans, crit)
                suggested = baseline.get("suggested_marks")
                is_override = suggested is not None and abs(awarded - float(suggested)) > 0.001

                final_criteria_scores.append(
                    {
                        "criterion_id": cid,
                        "title": crit.get("title", ""),
                        "description": crit.get("description", ""),
                        "max_marks": round(crit_max, 2),
                        "weight": crit.get("weight", 0),
                        "key_concepts": crit.get("key_concepts", []),
                        "alternative_phrases": crit.get("alternative_phrases", []),
                        "matched_concepts": baseline.get("matched_concepts", []),
                        "missing_concepts": baseline.get("missing_concepts", []),
                        "matched_alternatives": baseline.get("matched_alternatives", []),
                        "coverage_ratio": baseline.get("coverage_ratio"),
                        "suggested_marks": suggested,
                        "awarded_marks": round(awarded, 2),
                        "examiner_override": is_override,
                        "evaluation_method": "examiner_reviewed",
                        "feedback": entry["feedback"],
                    }
                )
                q_total = round(q_total + awarded, 2)

            descriptive_score = round(descriptive_score + q_total, 2)
            updated_rubric_evals[qid] = {
                "question_id": qid,
                "rubric_id": q.get("rubric_id"),
                "rubric_version": rubric.get("version", 1),
                "max_marks": round(float(q.get("marks", 0)), 2),
                "awarded_marks": q_total,
                "suggested_marks": prev_q_eval.get("suggested_marks"),
                "evaluation_status": "evaluated",
                "feedback": q_input["feedback"],
                "evaluated_by": current_user["uid"],
                "evaluated_at": now_iso,
                "criteria_scores": final_criteria_scores,
            }

        mcq_score = float(grading.get("mcq_score", 0.0) or 0.0)
        total_score = round(mcq_score + descriptive_score, 2)
        history = list(grading.get("decision_history", []))
        history.append(
            {
                "evaluated_by": current_user["uid"],
                "evaluated_by_name": current_user.get("full_name", current_user["email"]),
                "evaluated_at": now_iso,
                "mcq_score": mcq_score,
                "descriptive_score": descriptive_score,
                "total_score": total_score,
                "publish_requested": validated["publish_result"],
                "examiner_feedback": validated["examiner_feedback"],
            }
        )

        grading.update(
            {
                "descriptive_score": descriptive_score,
                "total_score": total_score,
                "evaluation_status": "evaluated",
                "examiner_feedback": validated["examiner_feedback"],
                "evaluated_by": current_user["uid"],
                "evaluated_by_name": current_user.get("full_name", current_user["email"]),
                "evaluated_at": now_iso,
                "rubric_evaluations": updated_rubric_evals,
                "decision_history": history,
            }
        )

        updated_sub = self.submission_repo.update(submission_id, {"grading": grading}) or {
            **submission,
            "grading": grading,
        }

        result_doc = self.result_service.upsert_result_for_submission(
            exam=exam,
            submission=updated_sub,
            actor=current_user,
            publish=validated["publish_result"],
            ip_address=ip_address,
        )

        self.audit_service.record(
            actor=current_user,
            action="SUBMISSION_EVALUATED",
            target_type="submission",
            target_id=submission_id,
            metadata={
                "exam_id": exam["exam_id"],
                "descriptive_score": descriptive_score,
                "total_score": total_score,
                "published": validated["publish_result"],
            },
            ip_address=ip_address,
        )

        return {
            "submission": updated_sub,
            "result": result_doc,
        }

