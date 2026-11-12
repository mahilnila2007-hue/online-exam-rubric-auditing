"""Examination creation, scheduling, publishing, and availability service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.exceptions import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.repositories.exam_repo import ExamRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.submission_repo import SubmissionRepository
from app.services.audit_service import AuditService
from app.services.time_utils import parse_utc_iso, utc_now
from app.validators.exam_validators import validate_exam_payload


def compute_exam_availability(exam: dict[str, Any], now: datetime | None = None) -> str:
    """Compute real-time student availability state for an examination."""
    now = now or utc_now()
    status = exam.get("status", "draft")
    if status == "draft":
        return "draft"
    if status == "archived":
        return "archived"

    start = parse_utc_iso(exam.get("scheduled_start"))
    end = parse_utc_iso(exam.get("scheduled_end"))
    if not start or not end:
        return "upcoming"
    if now < start:
        return "upcoming"
    if start <= now <= end:
        return "live"
    return "ended"


class ExamService:
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

    def _assert_can_manage(self, exam: dict[str, Any], user: dict[str, Any]) -> None:
        if user.get("role") == "admin":
            return
        if exam.get("created_by") != user.get("uid"):
            raise AuthorizationError("You do not have permission to manage this examination.")

    def _compute_question_metrics(self, user: dict[str, Any], question_ids: list[str]) -> dict[str, Any]:
        if not question_ids:
            return {
                "question_count": 0,
                "total_marks": 0.0,
                "mcq_count": 0,
                "descriptive_count": 0,
                "mcq_marks": 0.0,
                "descriptive_marks": 0.0,
            }

        questions = self.question_repo.get_many_by_ids(question_ids)
        by_id = {q["question_id"]: q for q in questions if not q.get("is_archived", False)}

        missing = [qid for qid in question_ids if qid not in by_id]
        if missing:
            raise ValidationError(
                f"One or more selected questions do not exist or were archived: {', '.join(missing)}.",
                details={"fields": {"question_ids": "Selected question list contains invalid or archived items."}},
            )

        if user.get("role") != "admin":
            unauthorized = [q["question_id"] for q in by_id.values() if q.get("created_by") != user.get("uid")]
            if unauthorized:
                raise AuthorizationError("You can only attach questions from your own question bank.")

        mcq_count = 0
        descriptive_count = 0
        mcq_marks = 0.0
        descriptive_marks = 0.0

        for qid in question_ids:
            q = by_id[qid]
            marks = float(q.get("marks", 0))
            if q.get("type") == "mcq":
                mcq_count += 1
                mcq_marks += marks
            else:
                descriptive_count += 1
                descriptive_marks += marks

        total_marks = round(mcq_marks + descriptive_marks, 2)
        return {
            "question_count": len(question_ids),
            "total_marks": total_marks,
            "mcq_count": mcq_count,
            "descriptive_count": descriptive_count,
            "mcq_marks": round(mcq_marks, 2),
            "descriptive_marks": round(descriptive_marks, 2),
        }

    def list_examiner_exams(
        self,
        user: dict[str, Any],
        *,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        created_by = None if user.get("role") == "admin" else user.get("uid")
        exams = self.exam_repo.list_exams(created_by=created_by, status=status)
        if search:
            term = search.strip().lower()
            exams = [
                e
                for e in exams
                if term in (e.get("title") or "").lower() or term in (e.get("course_code") or "").lower()
            ]
        now = utc_now()
        enriched: list[dict[str, Any]] = []
        for exam in exams:
            submissions = self.submission_repo.list_by_exam(exam["exam_id"])
            submitted_count = sum(1 for s in submissions if s.get("status") in {"submitted", "auto_submitted"})
            in_progress_count = sum(1 for s in submissions if s.get("status") == "in_progress")
            enriched.append(
                {
                    **exam,
                    "availability": compute_exam_availability(exam, now),
                    "submission_count": submitted_count,
                    "active_attempt_count": in_progress_count,
                }
            )
        return enriched

    def get_exam_for_examiner(self, user: dict[str, Any], exam_id: str) -> dict[str, Any]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")
        self._assert_can_manage(exam, user)
        questions = self.question_repo.get_many_by_ids(exam.get("question_ids", []))
        return {
            **exam,
            "availability": compute_exam_availability(exam),
            "questions": questions,
        }

    def create_exam(
        self,
        user: dict[str, Any],
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_exam_payload(payload)
        metrics = self._compute_question_metrics(user, validated["question_ids"])

        if validated["question_ids"] and validated["passing_marks"] > metrics["total_marks"]:
            raise ValidationError(
                f"Passing marks ({validated['passing_marks']:g}) cannot exceed total exam marks ({metrics['total_marks']:g}).",
                details={"fields": {"passing_marks": "Passing marks cannot exceed total exam marks."}},
            )

        exam = self.exam_repo.create(
            {
                **validated,
                **metrics,
                "created_by": user["uid"],
                "created_by_name": user.get("full_name", user["email"]),
            },
            doc_id=self.exam_repo.new_id("exam"),
        )
        self.audit_service.record(
            actor=user,
            action="EXAM_CREATED",
            target_type="exam",
            target_id=exam["exam_id"],
            metadata={
                "title": exam["title"],
                "status": exam["status"],
                "question_count": exam["question_count"],
                "total_marks": exam["total_marks"],
            },
            ip_address=ip_address,
        )
        return exam

    def update_exam(
        self,
        user: dict[str, Any],
        exam_id: str,
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        existing = self.exam_repo.get_by_id(exam_id)
        if not existing:
            raise NotFoundError("Examination not found.")
        self._assert_can_manage(existing, user)

        validated = validate_exam_payload(payload)
        existing_submissions = self.submission_repo.list_by_exam(exam_id)
        if existing_submissions and validated["question_ids"] != existing.get("question_ids", []):
            raise ConflictError(
                "Questions cannot be reordered or modified after students have started attempting this examination."
            )

        metrics = self._compute_question_metrics(user, validated["question_ids"])
        if validated["question_ids"] and validated["passing_marks"] > metrics["total_marks"]:
            raise ValidationError(
                f"Passing marks ({validated['passing_marks']:g}) cannot exceed total exam marks ({metrics['total_marks']:g}).",
                details={"fields": {"passing_marks": "Passing marks cannot exceed total exam marks."}},
            )

        updated = self.exam_repo.update(exam_id, {**validated, **metrics})
        if not updated:
            raise NotFoundError("Examination not found.")

        self.audit_service.record(
            actor=user,
            action="EXAM_UPDATED",
            target_type="exam",
            target_id=exam_id,
            metadata={"status": updated["status"], "total_marks": updated["total_marks"]},
            ip_address=ip_address,
        )
        return updated

    def change_exam_status(
        self,
        user: dict[str, Any],
        exam_id: str,
        new_status: str,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        if new_status not in {"draft", "scheduled", "published", "archived"}:
            raise ValidationError("Invalid examination status.")

        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")
        self._assert_can_manage(exam, user)

        if new_status in {"published", "scheduled"} and exam.get("question_count", 0) <= 0:
            raise ValidationError(
                "Add at least one question before publishing or scheduling an examination."
            )

        updated = self.exam_repo.update(exam_id, {"status": new_status})
        if not updated:
            raise NotFoundError("Examination not found.")

        self.audit_service.record(
            actor=user,
            action=f"EXAM_{new_status.upper()}",
            target_type="exam",
            target_id=exam_id,
            metadata={"title": exam["title"]},
            ip_address=ip_address,
        )
        return updated

    def duplicate_exam(
        self,
        user: dict[str, Any],
        exam_id: str,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        """Clone an existing examination structure into a fresh draft examination."""
        source = self.exam_repo.get_by_id(exam_id)
        if not source:
            raise NotFoundError("Examination not found.")
        self._assert_can_manage(source, user)

        qids = list(source.get("question_ids", []))
        active_questions = {
            q["question_id"]: q
            for q in self.question_repo.get_many_by_ids(qids)
            if not q.get("is_archived", False)
        }
        kept_qids = [qid for qid in qids if qid in active_questions]
        metrics = self._compute_question_metrics(user, kept_qids)
        passing = min(float(source.get("passing_marks", 0) or 0), float(metrics["total_marks"]))

        cloned = self.exam_repo.create(
            {
                "title": f"Copy of {source['title']}"[:160],
                "course_code": source.get("course_code", "GEN"),
                "description": source.get("description", ""),
                "instructions": list(source.get("instructions", [])),
                "status": "draft",
                "scheduled_start": source.get("scheduled_start"),
                "scheduled_end": source.get("scheduled_end"),
                "duration_minutes": source.get("duration_minutes", 60),
                "passing_marks": passing,
                "shuffle_questions": bool(source.get("shuffle_questions", False)),
                "allow_review_after_submit": bool(source.get("allow_review_after_submit", True)),
                "rubric_audit_enabled": bool(source.get("rubric_audit_enabled", True)),
                "negative_marking_enabled": bool(source.get("negative_marking_enabled", False)),
                "negative_mark_fraction": float(source.get("negative_mark_fraction", 0.0) or 0.0),
                "grade_rules": list(source.get("grade_rules", [])),
                "question_ids": kept_qids,
                **metrics,
                "created_by": user["uid"],
                "created_by_name": user.get("full_name", user["email"]),
                "cloned_from_exam_id": exam_id,
            },
            doc_id=self.exam_repo.new_id("exam"),
        )
        self.audit_service.record(
            actor=user,
            action="EXAM_DUPLICATED",
            target_type="exam",
            target_id=cloned["exam_id"],
            metadata={"source_exam_id": exam_id, "question_count": cloned["question_count"]},
            ip_address=ip_address,
        )
        return cloned

    # ------------------------------------------------------------------
    # Student-facing Views (Strictly sanitized)
    # ------------------------------------------------------------------
    def list_student_exams(self, student_uid: str) -> dict[str, Any]:
        exams = self.exam_repo.list_student_visible_exams()
        submissions = self.submission_repo.list_by_student(student_uid)
        sub_by_exam = {s["exam_id"]: s for s in submissions}
        now = utc_now()

        cards: list[dict[str, Any]] = []
        for exam in exams:
            availability = compute_exam_availability(exam, now)
            sub = sub_by_exam.get(exam["exam_id"])
            attempt_status = sub.get("status") if sub else "not_started"

            can_start = availability == "live" and attempt_status == "not_started"
            can_resume = availability == "live" and attempt_status == "in_progress"

            cards.append(
                {
                    "exam_id": exam["exam_id"],
                    "title": exam["title"],
                    "course_code": exam["course_code"],
                    "description": exam.get("description", ""),
                    "created_by_name": exam.get("created_by_name", "Examiner"),
                    "scheduled_start": exam["scheduled_start"],
                    "scheduled_end": exam["scheduled_end"],
                    "duration_minutes": exam["duration_minutes"],
                    "total_marks": exam.get("total_marks", 0),
                    "passing_marks": exam.get("passing_marks", 0),
                    "question_count": exam.get("question_count", 0),
                    "mcq_count": exam.get("mcq_count", 0),
                    "descriptive_count": exam.get("descriptive_count", 0),
                    "rubric_audit_enabled": exam.get("rubric_audit_enabled", True),
                    "availability": availability,
                    "attempt_status": attempt_status,
                    "submission_id": sub["submission_id"] if sub else None,
                    "can_start": can_start,
                    "can_resume": can_resume,
                }
            )

        completed_count = sum(
            1 for s in submissions if s.get("status") in {"submitted", "auto_submitted"}
        )
        live_count = sum(
            1 for c in cards if c["availability"] == "live" and c["attempt_status"] in {"not_started", "in_progress"}
        )
        upcoming_count = sum(1 for c in cards if c["availability"] == "upcoming")

        return {
            "summary": {
                "live_count": live_count,
                "upcoming_count": upcoming_count,
                "completed_count": completed_count,
                "total_visible": len(cards),
            },
            "exams": cards,
        }

    def get_student_exam_instructions(self, exam_id: str, student_uid: str) -> dict[str, Any]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam or exam.get("status") not in {"published", "scheduled"}:
            raise NotFoundError("Examination is unavailable or not published.")

        now = utc_now()
        availability = compute_exam_availability(exam, now)
        sub = self.submission_repo.get_by_exam_and_student(exam_id, student_uid)
        attempt_status = sub.get("status") if sub else "not_started"

        default_rules = [
            "Ensure a stable internet connection before launching the examination.",
            "Your countdown timer starts immediately upon clicking Start Examination and cannot be paused.",
            "Answers are automatically synchronized at regular intervals and upon question navigation.",
            "Do not open unauthorized reference tabs or attempt to submit after the timer expires.",
            "Descriptive responses will be evaluated using predefined analytical rubrics.",
        ]

        return {
            "exam_id": exam["exam_id"],
            "title": exam["title"],
            "course_code": exam["course_code"],
            "description": exam.get("description", ""),
            "created_by_name": exam.get("created_by_name", "Examiner"),
            "scheduled_start": exam["scheduled_start"],
            "scheduled_end": exam["scheduled_end"],
            "duration_minutes": exam["duration_minutes"],
            "total_marks": exam.get("total_marks", 0),
            "passing_marks": exam.get("passing_marks", 0),
            "question_count": exam.get("question_count", 0),
            "mcq_count": exam.get("mcq_count", 0),
            "descriptive_count": exam.get("descriptive_count", 0),
            "mcq_marks": exam.get("mcq_marks", 0),
            "descriptive_marks": exam.get("descriptive_marks", 0),
            "shuffle_questions": exam.get("shuffle_questions", False),
            "rubric_audit_enabled": exam.get("rubric_audit_enabled", True),
            "negative_marking_enabled": exam.get("negative_marking_enabled", False),
            "negative_mark_fraction": exam.get("negative_mark_fraction", 0.0),
            "instructions": exam.get("instructions") or default_rules,
            "availability": availability,
            "attempt_status": attempt_status,
            "submission_id": sub["submission_id"] if sub else None,
            "can_start": availability == "live" and attempt_status == "not_started",
            "can_resume": availability == "live" and attempt_status == "in_progress",
            "server_time": now.isoformat(),
        }

