"""Student exam attempt, autosave, deterministic MCQ grading, and submission service."""

from __future__ import annotations

from datetime import timedelta
import random
from typing import Any

from flask import current_app

from app.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.repositories.exam_repo import ExamRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.submission_repo import SubmissionRepository
from app.services.audit_service import AuditService
from app.services.exam_service import compute_exam_availability
from app.services.time_utils import parse_utc_iso, utc_now
from app.validators.submission_validators import validate_answers_payload


def sanitize_question_for_exam(question: dict[str, Any]) -> dict[str, Any]:
    """Strip privileged answer keys and model answers from active student questions."""
    sanitized: dict[str, Any] = {
        "question_id": question["question_id"],
        "subject": question.get("subject", ""),
        "topic": question.get("topic", ""),
        "difficulty": question.get("difficulty", "medium"),
        "type": question["type"],
        "prompt": question["prompt"],
        "marks": question["marks"],
    }
    if question["type"] == "mcq":
        sanitized["options"] = question.get("options", [])
    elif question["type"] == "descriptive" and question.get("rubric_snapshot"):
        snap = question["rubric_snapshot"]
        # Expose evaluation rubric criteria titles & weights to students for transparent assessment,
        # never exposing reference model_answer or internal key_concepts.
        sanitized["rubric_overview"] = {
            "title": snap.get("title", "Analytical Rubric"),
            "max_marks": snap.get("max_marks", question["marks"]),
            "criteria": [
                {
                    "title": c.get("title", ""),
                    "description": c.get("description", ""),
                    "max_marks": c.get("max_marks", 0),
                }
                for c in snap.get("criteria", [])
            ],
        }
    return sanitized


class SubmissionService:
    def __init__(
        self,
        exam_repo: ExamRepository,
        question_repo: QuestionRepository,
        submission_repo: SubmissionRepository,
        audit_service: AuditService,
    ) -> None:
        self.exam_repo = exam_repo
        self.question_repo = question_repo
        self.submission_repo = submission_repo
        self.audit_service = audit_service

    def _grace_seconds(self) -> int:
        return int(current_app.config.get("EXAM_SUBMIT_GRACE_SECONDS", 30))

    def _evaluate_submission(
        self,
        exam: dict[str, Any],
        submission: dict[str, Any],
        questions_by_id: dict[str, dict[str, Any]],
        *,
        auto_submit: bool,
    ) -> dict[str, Any]:
        now = utc_now()
        started_at = parse_utc_iso(submission.get("started_at")) or now
        expires_at = parse_utc_iso(submission.get("expires_at")) or now
        effective_end = min(now, expires_at) if auto_submit else now
        seconds_used = max(0, int((effective_end - started_at).total_seconds()))

        answers = submission.get("answers", {})
        neg_enabled = bool(exam.get("negative_marking_enabled", False))
        neg_fraction = float(exam.get("negative_mark_fraction", 0.0) or 0.0)
        raw_mcq_score = 0.0
        negative_deductions = 0.0
        mcq_max_score = 0.0
        descriptive_max_score = 0.0
        mcq_breakdown: dict[str, Any] = {}
        rubric_evaluations: dict[str, Any] = {}
        answered_count = 0

        for qid in submission.get("question_order", []):
            question = questions_by_id.get(qid)
            if not question:
                continue
            marks = float(question.get("marks", 0))
            ans = answers.get(qid, {})

            if question.get("type") == "mcq":
                mcq_max_score += marks
                selected = ans.get("selected_option_id")
                if selected:
                    answered_count += 1
                is_correct = bool(selected and selected == question.get("correct_option_id"))
                if not selected:
                    awarded = 0.0
                    outcome = "unanswered"
                elif is_correct:
                    awarded = marks
                    outcome = "correct"
                else:
                    penalty = round(marks * neg_fraction, 2) if neg_enabled else 0.0
                    awarded = -penalty
                    negative_deductions = round(negative_deductions + penalty, 2)
                    outcome = "incorrect"

                raw_mcq_score += awarded
                mcq_breakdown[qid] = {
                    "selected_option_id": selected,
                    "is_correct": is_correct,
                    "outcome": outcome,
                    "awarded_marks": round(awarded, 2),
                    "max_marks": round(marks, 2),
                }
            else:
                descriptive_max_score += marks
                if ans.get("text_answer"):
                    answered_count += 1
                snap = question.get("rubric_snapshot") or {}
                rubric_evaluations[qid] = {
                    "question_id": qid,
                    "rubric_id": question.get("rubric_id"),
                    "rubric_version": snap.get("version", 1),
                    "max_marks": round(marks, 2),
                    "awarded_marks": None,
                    "evaluation_status": "pending_evaluation",
                    "feedback": "",
                    "criteria_scores": [
                        {
                            "criterion_id": c.get("criterion_id"),
                            "title": c.get("title"),
                            "description": c.get("description", ""),
                            "max_marks": c.get("max_marks"),
                            "weight": c.get("weight", 0),
                            "key_concepts": c.get("key_concepts", []),
                            "alternative_phrases": c.get("alternative_phrases", []),
                            "awarded_marks": None,
                            "feedback": "",
                        }
                        for c in snap.get("criteria", [])
                    ],
                }

        mcq_score = round(max(0.0, raw_mcq_score), 2)
        has_descriptive = descriptive_max_score > 0
        total_max_score = round(mcq_max_score + descriptive_max_score, 2)
        evaluation_status = "pending_descriptive" if has_descriptive else "completed"
        total_score = None if has_descriptive else mcq_score

        audit_status = (
            "pending_audit"
            if (has_descriptive and exam.get("rubric_audit_enabled", True))
            else "not_applicable"
        )

        grading = {
            "mcq_score": mcq_score,
            "raw_mcq_score": round(raw_mcq_score, 2),
            "negative_deductions": round(negative_deductions, 2),
            "mcq_max_score": round(mcq_max_score, 2),
            "descriptive_max_score": round(descriptive_max_score, 2),
            "descriptive_score": None if has_descriptive else 0.0,
            "total_score": total_score,
            "total_max_score": total_max_score,
            "evaluation_status": evaluation_status,
            "mcq_breakdown": mcq_breakdown,
            "rubric_evaluations": rubric_evaluations,
            "decision_history": [],
        }

        rubric_audit = {
            "audit_status": audit_status,
            "consistency_score": None,
            "nlp_model_version": None,
            "audit_notes": [],
        }

        status = "auto_submitted" if auto_submit else "submitted"
        updated = self.submission_repo.update(
            submission["submission_id"],
            {
                "status": status,
                "submitted_at": now,
                "duration_seconds_used": seconds_used,
                "answered_count": answered_count,
                "total_questions": len(submission.get("question_order", [])),
                "grading": grading,
                "rubric_audit": rubric_audit,
            },
        )
        return updated or {
            **submission,
            "status": status,
            "submitted_at": now.isoformat(),
            "duration_seconds_used": seconds_used,
            "answered_count": answered_count,
            "total_questions": len(submission.get("question_order", [])),
            "grading": grading,
            "rubric_audit": rubric_audit,
        }

    def start_or_resume_attempt(
        self,
        exam_id: str,
        student_user: dict[str, Any],
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam or exam.get("status") not in {"published", "scheduled"}:
            raise NotFoundError("Examination was not found or is not available.")

        now = utc_now()
        availability = compute_exam_availability(exam, now)
        existing = self.submission_repo.get_by_exam_and_student(exam_id, student_user["uid"])

        if existing:
            if existing.get("status") in {"submitted", "auto_submitted"}:
                raise ConflictError(
                    "You have already submitted this examination.",
                    error_code="EXAM_ALREADY_SUBMITTED",
                    details={"submission_id": existing["submission_id"]},
                )

            expires_at = parse_utc_iso(existing.get("expires_at")) or now
            if now > expires_at + timedelta(seconds=self._grace_seconds()):
                questions = self.question_repo.get_many_by_ids(existing.get("question_order", []))
                q_map = {q["question_id"]: q for q in questions}
                finalized = self._evaluate_submission(exam, existing, q_map, auto_submit=True)
                self.audit_service.record(
                    actor=student_user,
                    action="EXAM_AUTO_SUBMITTED",
                    target_type="submission",
                    target_id=finalized["submission_id"],
                    metadata={"exam_id": exam_id, "reason": "timer_expired"},
                    ip_address=ip_address,
                )
                raise ConflictError(
                    "Your exam timer has expired. Your previously saved answers have been submitted automatically.",
                    error_code="EXAM_TIME_EXPIRED",
                    details={"submission_id": finalized["submission_id"]},
                )

            questions = self.question_repo.get_many_by_ids(existing.get("question_order", []))
            remaining_seconds = max(0, int((expires_at - now).total_seconds()))
            return {
                "submission_id": existing["submission_id"],
                "exam": {
                    "exam_id": exam["exam_id"],
                    "title": exam["title"],
                    "course_code": exam["course_code"],
                    "duration_minutes": exam["duration_minutes"],
                    "total_marks": exam.get("total_marks", 0),
                },
                "started_at": existing["started_at"],
                "expires_at": existing["expires_at"],
                "remaining_seconds": remaining_seconds,
                "questions": [sanitize_question_for_exam(q) for q in questions],
                "answers": existing.get("answers", {}),
            }

        # Creating a brand-new attempt
        if availability == "upcoming":
            raise ValidationError("This examination has not opened yet.")
        if availability == "ended":
            raise ValidationError("The examination window has already closed.")

        question_ids = list(exam.get("question_ids", []))
        if not question_ids:
            raise ValidationError("This examination does not contain any questions.")

        if exam.get("shuffle_questions"):
            random.shuffle(question_ids)

        scheduled_end = parse_utc_iso(exam.get("scheduled_end")) or (now + timedelta(minutes=exam["duration_minutes"]))
        duration_end = now + timedelta(minutes=int(exam["duration_minutes"]))
        expires_at = min(duration_end, scheduled_end)

        submission_id = self.submission_repo.build_attempt_id(exam_id, student_user["uid"])
        submission = self.submission_repo.create(
            {
                "submission_id": submission_id,
                "exam_id": exam_id,
                "exam_title": exam["title"],
                "course_code": exam["course_code"],
                "examiner_uid": exam.get("created_by", ""),
                "student_uid": student_user["uid"],
                "student_name": student_user.get("full_name", student_user["email"]),
                "student_email": student_user["email"],
                "institution_id": student_user.get("institution_id", ""),
                "status": "in_progress",
                "started_at": now,
                "expires_at": expires_at,
                "submitted_at": None,
                "duration_seconds_used": 0,
                "question_order": question_ids,
                "total_questions": len(question_ids),
                "answered_count": 0,
                "answers": {},
                "grading": {
                    "mcq_score": 0.0,
                    "mcq_max_score": exam.get("mcq_marks", 0.0),
                    "descriptive_max_score": exam.get("descriptive_marks", 0.0),
                    "descriptive_score": None,
                    "total_score": None,
                    "total_max_score": exam.get("total_marks", 0.0),
                    "evaluation_status": "in_progress",
                    "mcq_breakdown": {},
                    "rubric_evaluations": {},
                },
                "rubric_audit": {
                    "audit_status": "not_applicable",
                    "consistency_score": None,
                    "nlp_model_version": None,
                    "audit_notes": [],
                },
            },
            doc_id=submission_id,
        )

        self.audit_service.record(
            actor=student_user,
            action="EXAM_STARTED",
            target_type="submission",
            target_id=submission_id,
            metadata={"exam_id": exam_id},
            ip_address=ip_address,
        )

        questions = self.question_repo.get_many_by_ids(question_ids)
        remaining_seconds = max(0, int((expires_at - now).total_seconds()))
        return {
            "submission_id": submission_id,
            "exam": {
                "exam_id": exam["exam_id"],
                "title": exam["title"],
                "course_code": exam["course_code"],
                "duration_minutes": exam["duration_minutes"],
                "total_marks": exam.get("total_marks", 0),
            },
            "started_at": submission["started_at"],
            "expires_at": submission["expires_at"],
            "remaining_seconds": remaining_seconds,
            "questions": [sanitize_question_for_exam(q) for q in questions],
            "answers": {},
        }

    def _merge_validated_answers(
        self,
        submission: dict[str, Any],
        validated_answers: dict[str, dict[str, Any]],
        questions_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        allowed_qids = set(submission.get("question_order", []))
        merged = dict(submission.get("answers", {}))
        now_iso = utc_now().isoformat()

        for qid, ans in validated_answers.items():
            if qid not in allowed_qids:
                raise ValidationError(f"Question '{qid}' is not part of this examination attempt.")
            question = questions_by_id.get(qid)
            if not question:
                continue

            selected_opt = ans.get("selected_option_id")
            if question.get("type") == "mcq" and selected_opt is not None:
                valid_opts = {o["id"] for o in question.get("options", [])}
                if selected_opt not in valid_opts:
                    raise ValidationError(f"Invalid option selected for question '{qid}'.")

            merged[qid] = {
                "question_id": qid,
                "type": question["type"],
                "selected_option_id": selected_opt if question["type"] == "mcq" else None,
                "text_answer": ans.get("text_answer") if question["type"] == "descriptive" else None,
                "flagged_for_review": bool(ans.get("flagged_for_review", False)),
                "saved_at": now_iso,
            }
        return merged

    def save_progress(
        self,
        exam_id: str,
        student_user: dict[str, Any],
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_answers_payload(payload)
        submission = self.submission_repo.get_by_exam_and_student(exam_id, student_user["uid"])
        if not submission:
            raise NotFoundError("No active examination attempt was found.")
        if submission.get("status") != "in_progress":
            raise ConflictError(
                "This examination has already been submitted.",
                error_code="EXAM_ALREADY_SUBMITTED",
                details={"submission_id": submission["submission_id"]},
            )

        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")

        now = utc_now()
        expires_at = parse_utc_iso(submission.get("expires_at")) or now
        questions = self.question_repo.get_many_by_ids(submission.get("question_order", []))
        q_map = {q["question_id"]: q for q in questions}

        if now > expires_at + timedelta(seconds=self._grace_seconds()):
            finalized = self._evaluate_submission(exam, submission, q_map, auto_submit=True)
            self.audit_service.record(
                actor=student_user,
                action="EXAM_AUTO_SUBMITTED",
                target_type="submission",
                target_id=finalized["submission_id"],
                metadata={"exam_id": exam_id, "reason": "save_after_expiry"},
                ip_address=ip_address,
            )
            raise ConflictError(
                "Exam duration has elapsed. Your previously saved responses have been submitted automatically.",
                error_code="EXAM_TIME_EXPIRED",
                details={"submission_id": finalized["submission_id"]},
            )

        merged_answers = self._merge_validated_answers(submission, validated, q_map)
        answered_count = sum(
            1
            for a in merged_answers.values()
            if a.get("selected_option_id") or a.get("text_answer")
        )

        self.submission_repo.update(
            submission["submission_id"],
            {
                "answers": merged_answers,
                "answered_count": answered_count,
            },
        )
        return {
            "submission_id": submission["submission_id"],
            "saved_at": now.isoformat(),
            "answered_count": answered_count,
            "remaining_seconds": max(0, int((expires_at - now).total_seconds())),
        }

    def submit_exam(
        self,
        exam_id: str,
        student_user: dict[str, Any],
        payload: dict[str, Any] | None = None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        submission = self.submission_repo.get_by_exam_and_student(exam_id, student_user["uid"])
        if not submission:
            raise NotFoundError("No active examination attempt was found.")

        if submission.get("status") in {"submitted", "auto_submitted"}:
            return self.get_submission_detail(submission["submission_id"], student_user)

        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")

        now = utc_now()
        expires_at = parse_utc_iso(submission.get("expires_at")) or now
        within_grace = now <= expires_at + timedelta(seconds=self._grace_seconds())
        auto_submit = bool((payload or {}).get("auto_submit", False)) or not within_grace

        questions = self.question_repo.get_many_by_ids(submission.get("question_order", []))
        q_map = {q["question_id"]: q for q in questions}

        if payload and isinstance(payload.get("answers"), dict) and within_grace:
            validated = validate_answers_payload(payload)
            submission["answers"] = self._merge_validated_answers(submission, validated, q_map)
            self.submission_repo.update(submission["submission_id"], {"answers": submission["answers"]})

        finalized = self._evaluate_submission(exam, submission, q_map, auto_submit=auto_submit)

        self.audit_service.record(
            actor=student_user,
            action="EXAM_AUTO_SUBMITTED" if auto_submit else "EXAM_SUBMITTED",
            target_type="submission",
            target_id=finalized["submission_id"],
            metadata={
                "exam_id": exam_id,
                "mcq_score": finalized["grading"]["mcq_score"],
                "evaluation_status": finalized["grading"]["evaluation_status"],
            },
            ip_address=ip_address,
        )
        return self.get_submission_detail(finalized["submission_id"], student_user)

    def list_student_history(self, student_uid: str) -> list[dict[str, Any]]:
        submissions = self.submission_repo.list_by_student(student_uid)
        exams = {
            e["exam_id"]: e
            for e in self.exam_repo.get_many_by_ids(list({s["exam_id"] for s in submissions}))
        }
        history: list[dict[str, Any]] = []
        for sub in submissions:
            exam = exams.get(sub["exam_id"], {})
            grading = sub.get("grading", {})
            audit = sub.get("rubric_audit", {})
            pub_status = sub.get("publication_status", "unpublished")
            is_published = pub_status == "published"
            has_desc = float(grading.get("descriptive_max_score", 0) or 0) > 0
            history.append(
                {
                    "submission_id": sub["submission_id"],
                    "exam_id": sub["exam_id"],
                    "exam_title": sub.get("exam_title") or exam.get("title", "Examination"),
                    "course_code": sub.get("course_code") or exam.get("course_code", ""),
                    "status": sub.get("status"),
                    "started_at": sub.get("started_at"),
                    "submitted_at": sub.get("submitted_at"),
                    "duration_seconds_used": sub.get("duration_seconds_used", 0),
                    "answered_count": sub.get("answered_count", 0),
                    "total_questions": sub.get("total_questions", 0),
                    "mcq_score": grading.get("mcq_score", 0),
                    "mcq_max_score": grading.get("mcq_max_score", 0),
                    "descriptive_max_score": grading.get("descriptive_max_score", 0),
                    "descriptive_score": grading.get("descriptive_score") if (is_published or not has_desc) else None,
                    "total_score": grading.get("total_score") if (is_published or not has_desc) else None,
                    "total_max_score": grading.get("total_max_score", 0),
                    "evaluation_status": grading.get("evaluation_status", "in_progress"),
                    "publication_status": pub_status,
                    "result_id": sub.get("result_id") if is_published else None,
                    "audit_status": audit.get("audit_status", "not_applicable"),
                }
            )
        return history

    def list_exam_submissions_for_examiner(
        self,
        exam_id: str,
        current_user: dict[str, Any],
    ) -> list[dict[str, Any]]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")
        if current_user.get("role") != "admin" and exam.get("created_by") != current_user.get("uid"):
            raise AuthorizationError("You do not have permission to view submissions for this examination.")

        submissions = self.submission_repo.list_by_exam(exam_id)
        return [
            {
                "submission_id": s["submission_id"],
                "exam_id": s["exam_id"],
                "student_uid": s["student_uid"],
                "student_name": s.get("student_name", ""),
                "student_email": s.get("student_email", ""),
                "institution_id": s.get("institution_id", ""),
                "status": s.get("status"),
                "started_at": s.get("started_at"),
                "submitted_at": s.get("submitted_at"),
                "duration_seconds_used": s.get("duration_seconds_used", 0),
                "answered_count": s.get("answered_count", 0),
                "total_questions": s.get("total_questions", 0),
                "grading": {
                    "mcq_score": s.get("grading", {}).get("mcq_score", 0),
                    "mcq_max_score": s.get("grading", {}).get("mcq_max_score", 0),
                    "descriptive_max_score": s.get("grading", {}).get("descriptive_max_score", 0),
                    "total_max_score": s.get("grading", {}).get("total_max_score", 0),
                    "evaluation_status": s.get("grading", {}).get("evaluation_status", ""),
                },
                "rubric_audit": s.get("rubric_audit", {}),
            }
            for s in submissions
        ]

    def get_submission_detail(
        self,
        submission_id: str,
        current_user: dict[str, Any],
    ) -> dict[str, Any]:
        submission = self.submission_repo.get_by_id(submission_id)
        if not submission:
            raise NotFoundError("Submission record not found.")

        exam = self.exam_repo.get_by_id(submission["exam_id"])
        role = current_user.get("role")
        if role == "student" and submission.get("student_uid") != current_user.get("uid"):
            raise AuthorizationError("You can only view your own examination submissions.")
        if role == "examiner" and exam and exam.get("created_by") != current_user.get("uid"):
            raise AuthorizationError("You can only inspect submissions for examinations you created.")

        questions = self.question_repo.get_many_by_ids(submission.get("question_order", []))
        answers = submission.get("answers", {})
        grading = submission.get("grading", {})
        mcq_breakdown = grading.get("mcq_breakdown", {})
        rubric_evals = grading.get("rubric_evaluations", {})

        is_staff = role in {"examiner", "admin"}
        allow_student_review = bool(
            exam
            and exam.get("allow_review_after_submit", True)
            and submission.get("status") in {"submitted", "auto_submitted"}
        )

        question_reviews: list[dict[str, Any]] = []
        for idx, q in enumerate(questions, start=1):
            qid = q["question_id"]
            ans = answers.get(qid, {})
            item: dict[str, Any] = {
                "index": idx,
                "question_id": qid,
                "type": q["type"],
                "prompt": q["prompt"],
                "marks": q["marks"],
                "subject": q.get("subject", ""),
                "student_answer": {
                    "selected_option_id": ans.get("selected_option_id"),
                    "text_answer": ans.get("text_answer"),
                },
            }
            if q["type"] == "mcq":
                item["options"] = q.get("options", [])
                mcqb = mcq_breakdown.get(qid, {})
                item["awarded_marks"] = mcqb.get("awarded_marks")
                item["is_correct"] = mcqb.get("is_correct")
                if is_staff or allow_student_review:
                    item["correct_option_id"] = q.get("correct_option_id")
                    item["explanation"] = q.get("explanation", "")
            else:
                if is_staff or submission.get("publication_status") == "published":
                    item["rubric_snapshot"] = q.get("rubric_snapshot")
                    item["rubric_evaluation"] = rubric_evals.get(qid)
                else:
                    item["rubric_snapshot"] = None
                    item["rubric_evaluation"] = None
                if is_staff:
                    item["rubric_id"] = q.get("rubric_id")

            question_reviews.append(item)

        pub_status = submission.get("publication_status", "unpublished")
        can_see_final_desc = is_staff or pub_status == "published" or float(grading.get("descriptive_max_score", 0) or 0) == 0

        return {
            "submission_id": submission["submission_id"],
            "exam_id": submission["exam_id"],
            "exam_title": submission.get("exam_title") or (exam or {}).get("title", "Examination"),
            "course_code": submission.get("course_code") or (exam or {}).get("course_code", ""),
            "student_name": submission.get("student_name", ""),
            "student_email": submission.get("student_email", ""),
            "institution_id": submission.get("institution_id", ""),
            "status": submission.get("status"),
            "started_at": submission.get("started_at"),
            "submitted_at": submission.get("submitted_at"),
            "duration_seconds_used": submission.get("duration_seconds_used", 0),
            "answered_count": submission.get("answered_count", 0),
            "total_questions": submission.get("total_questions", len(questions)),
            "publication_status": pub_status,
            "result_id": submission.get("result_id") if can_see_final_desc else None,
            "grading": {
                "mcq_score": grading.get("mcq_score", 0),
                "negative_deductions": grading.get("negative_deductions", 0),
                "mcq_max_score": grading.get("mcq_max_score", 0),
                "descriptive_max_score": grading.get("descriptive_max_score", 0),
                "descriptive_score": grading.get("descriptive_score") if can_see_final_desc else None,
                "total_score": grading.get("total_score") if can_see_final_desc else None,
                "total_max_score": grading.get("total_max_score", 0),
                "evaluation_status": grading.get("evaluation_status", "in_progress"),
                "examiner_feedback": grading.get("examiner_feedback", "") if can_see_final_desc else "",
            },
            "rubric_audit": submission.get("rubric_audit", {}),
            "allow_review": is_staff or allow_student_review,
            "questions": question_reviews,
        }

