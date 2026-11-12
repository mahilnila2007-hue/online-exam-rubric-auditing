"""Result calculation, grade rules, publication, and student result access service."""

from __future__ import annotations

import re
from typing import Any

from app.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.repositories.exam_repo import ExamRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.rubric_audit_repo import NotificationRepository
from app.repositories.submission_repo import SubmissionRepository
from app.services.audit_service import AuditService
from app.services.csv_utils import rows_to_csv_string
from app.services.time_utils import utc_now
from app.validators.exam_validators import DEFAULT_GRADE_RULES


def compute_grade_and_pass(
    *,
    obtained_marks: float,
    total_marks: float,
    passing_marks: float,
    grade_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute percentage, letter grade, and pass/fail status deterministically."""
    percentage = round((obtained_marks / total_marks) * 100, 2) if total_marks > 0 else 0.0
    rules = sorted(
        grade_rules or DEFAULT_GRADE_RULES,
        key=lambda r: float(r.get("min_percentage", 0)),
        reverse=True,
    )
    grade = "F"
    for rule in rules:
        if percentage >= float(rule.get("min_percentage", 0)):
            grade = str(rule.get("grade", "F"))
            break

    passed = round(obtained_marks, 2) >= round(float(passing_marks or 0), 2)
    return {
        "percentage": percentage,
        "grade": grade,
        "passed": passed,
        "pass_status": "PASS" if passed else "FAIL",
    }


class ResultService:
    def __init__(
        self,
        exam_repo: ExamRepository,
        question_repo: QuestionRepository,
        submission_repo: SubmissionRepository,
        result_repo: ResultRepository,
        audit_service: AuditService,
        notification_repo: NotificationRepository | None = None,
    ) -> None:
        self.exam_repo = exam_repo
        self.question_repo = question_repo
        self.submission_repo = submission_repo
        self.result_repo = result_repo
        self.audit_service = audit_service
        self.notification_repo = notification_repo

    def _assert_examiner_owns(self, exam: dict[str, Any], user: dict[str, Any]) -> None:
        if user.get("role") == "admin":
            return
        if exam.get("created_by") != user.get("uid"):
            raise AuthorizationError("You do not have permission to manage results for this examination.")

    def upsert_result_for_submission(
        self,
        *,
        exam: dict[str, Any],
        submission: dict[str, Any],
        actor: dict[str, Any],
        publish: bool = False,
        ip_address: str = "",
    ) -> dict[str, Any]:
        grading = submission.get("grading", {})
        eval_status = grading.get("evaluation_status")
        if eval_status not in {"evaluated", "completed"}:
            raise ValidationError(
                "All descriptive answers must be reviewed and finalized by an examiner before generating results."
            )

        mcq_score = float(grading.get("mcq_score", 0.0) or 0.0)
        mcq_max = float(grading.get("mcq_max_score", 0.0) or 0.0)
        desc_score = float(grading.get("descriptive_score", 0.0) or 0.0)
        desc_max = float(grading.get("descriptive_max_score", 0.0) or 0.0)
        total_marks = round(float(grading.get("total_max_score", mcq_max + desc_max) or 0.0), 2)
        obtained_marks = round(mcq_score + desc_score, 2)
        passing_marks = float(exam.get("passing_marks", 0.0) or 0.0)

        computed = compute_grade_and_pass(
            obtained_marks=obtained_marks,
            total_marks=total_marks,
            passing_marks=passing_marks,
            grade_rules=exam.get("grade_rules"),
        )

        questions = self.question_repo.get_many_by_ids(submission.get("question_order", []))
        mcq_breakdown = grading.get("mcq_breakdown", {})
        rubric_evals = grading.get("rubric_evaluations", {})
        answers = submission.get("answers", {})

        question_feedback: list[dict[str, Any]] = []
        for idx, q in enumerate(questions, start=1):
            qid = q["question_id"]
            ans = answers.get(qid, {})
            if q.get("type") == "mcq":
                mb = mcq_breakdown.get(qid, {})
                question_feedback.append(
                    {
                        "index": idx,
                        "question_id": qid,
                        "type": "mcq",
                        "prompt": q["prompt"],
                        "max_marks": float(q.get("marks", 0)),
                        "awarded_marks": float(mb.get("awarded_marks", 0.0)),
                        "outcome": mb.get("outcome", "correct" if mb.get("is_correct") else "incorrect"),
                        "selected_option_id": ans.get("selected_option_id"),
                        "correct_option_id": q.get("correct_option_id") if exam.get("allow_review_after_submit", True) else None,
                        "options": q.get("options", []),
                        "explanation": q.get("explanation", "") if exam.get("allow_review_after_submit", True) else "",
                    }
                )
            else:
                reval = rubric_evals.get(qid, {})
                question_feedback.append(
                    {
                        "index": idx,
                        "question_id": qid,
                        "type": "descriptive",
                        "prompt": q["prompt"],
                        "max_marks": float(q.get("marks", 0)),
                        "awarded_marks": float(reval.get("awarded_marks") or 0.0),
                        "feedback": reval.get("feedback", ""),
                        "student_text": ans.get("text_answer", ""),
                        "criteria_scores": [
                            {
                                "criterion_id": cs.get("criterion_id"),
                                "title": cs.get("title"),
                                "max_marks": cs.get("max_marks"),
                                "awarded_marks": cs.get("awarded_marks"),
                                "feedback": cs.get("feedback", ""),
                            }
                            for cs in reval.get("criteria_scores", [])
                        ],
                    }
                )

        result_id = self.result_repo.build_result_id(exam["exam_id"], submission["student_uid"])
        existing = self.result_repo.get_by_id(result_id)
        now = utc_now()

        was_published = existing and existing.get("publication_status") == "published"
        is_published = bool(publish or was_published)
        pub_status = "published" if is_published else "unpublished"

        payload = {
            "result_id": result_id,
            "submission_id": submission["submission_id"],
            "exam_id": exam["exam_id"],
            "exam_title": exam["title"],
            "course_code": exam["course_code"],
            "examiner_uid": exam.get("created_by", ""),
            "student_uid": submission["student_uid"],
            "student_name": submission.get("student_name", ""),
            "student_email": submission.get("student_email", ""),
            "institution_id": submission.get("institution_id", ""),
            "total_marks": total_marks,
            "obtained_marks": obtained_marks,
            "mcq_score": round(mcq_score, 2),
            "mcq_max_score": round(mcq_max, 2),
            "descriptive_score": round(desc_score, 2),
            "descriptive_max_score": round(desc_max, 2),
            "negative_deductions": float(grading.get("negative_deductions", 0.0) or 0.0),
            "passing_marks": passing_marks,
            "percentage": computed["percentage"],
            "grade": computed["grade"],
            "passed": computed["passed"],
            "pass_status": computed["pass_status"],
            "examiner_feedback": grading.get("examiner_feedback", ""),
            "question_feedback": question_feedback,
            "evaluation_status": "evaluated",
            "publication_status": pub_status,
            "published_at": (existing.get("published_at") if was_published else now) if is_published else None,
            "published_by": (existing.get("published_by") if was_published else actor["uid"]) if is_published else None,
            "evaluated_by": grading.get("evaluated_by") or actor["uid"],
            "evaluated_by_name": grading.get("evaluated_by_name") or actor.get("full_name", actor["email"]),
            "evaluated_at": grading.get("evaluated_at") or now,
            "rubric_audit_ready": desc_max > 0,
            "created_at": (existing or {}).get("created_at") or now,
        }

        saved = self.result_repo.set_merge(result_id, payload)
        self.submission_repo.update(
            submission["submission_id"],
            {
                "result_id": result_id,
                "publication_status": pub_status,
            },
        )

        if publish and not was_published:
            self.audit_service.record(
                actor=actor,
                action="RESULT_PUBLISHED",
                target_type="result",
                target_id=result_id,
                metadata={
                    "exam_id": exam["exam_id"],
                    "obtained_marks": obtained_marks,
                    "total_marks": total_marks,
                    "grade": computed["grade"],
                },
                ip_address=ip_address,
            )
        elif was_published:
            self.audit_service.record(
                actor=actor,
                action="RESULT_REVISED",
                target_type="result",
                target_id=result_id,
                metadata={"obtained_marks": obtained_marks, "grade": computed["grade"]},
                ip_address=ip_address,
            )
        return saved

    def publish_submission_result(
        self,
        submission_id: str,
        current_user: dict[str, Any],
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        submission = self.submission_repo.get_by_id(submission_id)
        if not submission:
            raise NotFoundError("Submission record not found.")
        exam = self.exam_repo.get_by_id(submission["exam_id"])
        if not exam:
            raise NotFoundError("Examination not found.")
        self._assert_examiner_owns(exam, current_user)

        return self.upsert_result_for_submission(
            exam=exam,
            submission=submission,
            actor=current_user,
            publish=True,
            ip_address=ip_address,
        )

    def publish_exam_results(
        self,
        exam_id: str,
        current_user: dict[str, Any],
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")
        self._assert_examiner_owns(exam, current_user)

        submissions = self.submission_repo.list_by_exam(exam_id)
        published_count = 0
        skipped_pending = 0
        already_published = 0

        for sub in submissions:
            if sub.get("status") not in {"submitted", "auto_submitted"}:
                continue
            eval_status = sub.get("grading", {}).get("evaluation_status")
            if eval_status not in {"evaluated", "completed"}:
                skipped_pending += 1
                continue
            existing = self.result_repo.get_by_exam_and_student(exam_id, sub["student_uid"])
            if existing and existing.get("publication_status") == "published":
                already_published += 1
                continue
            self.upsert_result_for_submission(
                exam=exam,
                submission=sub,
                actor=current_user,
                publish=True,
                ip_address=ip_address,
            )
            published_count += 1

        return {
            "published_count": published_count,
            "already_published_count": already_published,
            "skipped_pending_count": skipped_pending,
        }

    def list_exam_results_for_examiner(
        self,
        exam_id: str,
        current_user: dict[str, Any],
    ) -> dict[str, Any]:
        exam = self.exam_repo.get_by_id(exam_id)
        if not exam:
            raise NotFoundError("Examination not found.")
        self._assert_examiner_owns(exam, current_user)

        submissions = self.submission_repo.list_by_exam(exam_id)
        results_by_student = {r["student_uid"]: r for r in self.result_repo.list_by_exam(exam_id)}

        rows: list[dict[str, Any]] = []
        evaluated_count = 0
        published_count = 0
        passed_count = 0
        pct_values: list[float] = []
        grade_distribution: dict[str, int] = {}

        for sub in submissions:
            if sub.get("status") not in {"submitted", "auto_submitted"}:
                continue
            grading = sub.get("grading", {})
            res = results_by_student.get(sub["student_uid"])
            eval_status = grading.get("evaluation_status", "pending_descriptive")
            pub_status = res.get("publication_status") if res else sub.get("publication_status", "unpublished")

            if eval_status in {"evaluated", "completed"}:
                evaluated_count += 1
            if pub_status == "published":
                published_count += 1

            total_max = float(grading.get("total_max_score", exam.get("total_marks", 0)) or 0)
            obtained = res.get("obtained_marks") if res else grading.get("total_score")
            pct = res.get("percentage") if res else (round((obtained / total_max) * 100, 2) if (obtained is not None and total_max > 0) else None)
            grade = res.get("grade") if res else None
            passed = res.get("passed") if res else None
            if pct is not None:
                pct_values.append(float(pct))
            if passed:
                passed_count += 1
            if grade:
                grade_distribution[grade] = grade_distribution.get(grade, 0) + 1

            rows.append(
                {
                    "submission_id": sub["submission_id"],
                    "result_id": res["result_id"] if res else None,
                    "student_uid": sub["student_uid"],
                    "student_name": sub.get("student_name", ""),
                    "student_email": sub.get("student_email", ""),
                    "institution_id": sub.get("institution_id", ""),
                    "submission_status": sub.get("status"),
                    "submitted_at": sub.get("submitted_at"),
                    "mcq_score": grading.get("mcq_score", 0),
                    "mcq_max_score": grading.get("mcq_max_score", 0),
                    "descriptive_score": grading.get("descriptive_score"),
                    "descriptive_max_score": grading.get("descriptive_max_score", 0),
                    "obtained_marks": obtained,
                    "total_marks": total_max,
                    "percentage": pct,
                    "grade": grade,
                    "pass_status": res.get("pass_status") if res else None,
                    "evaluation_status": eval_status,
                    "publication_status": pub_status,
                    "audit_status": sub.get("rubric_audit", {}).get("audit_status", "not_applicable"),
                }
            )

        avg_pct = round(sum(pct_values) / len(pct_values), 2) if pct_values else 0.0
        pass_rate = round((passed_count / evaluated_count) * 100, 1) if evaluated_count > 0 else 0.0

        return {
            "exam": {
                "exam_id": exam["exam_id"],
                "title": exam["title"],
                "course_code": exam["course_code"],
                "total_marks": exam.get("total_marks", 0),
                "passing_marks": exam.get("passing_marks", 0),
                "negative_marking_enabled": exam.get("negative_marking_enabled", False),
                "negative_mark_fraction": exam.get("negative_mark_fraction", 0.0),
                "grade_rules": exam.get("grade_rules", DEFAULT_GRADE_RULES),
            },
            "summary": {
                "total_submissions": len(rows),
                "evaluated_count": evaluated_count,
                "pending_count": len(rows) - evaluated_count,
                "published_count": published_count,
                "passed_count": passed_count,
                "average_percentage": avg_pct,
                "pass_rate": pass_rate,
                "grade_distribution": grade_distribution,
            },
            "rows": rows,
        }

    def export_exam_results_csv(
        self,
        exam_id: str,
        current_user: dict[str, Any],
    ) -> tuple[str, str]:
        """Export candidate scores and evaluation statuses for an examination as formula-safe CSV."""
        data = self.list_exam_results_for_examiner(exam_id, current_user)
        exam = data["exam"]
        headers = [
            "Submission ID",
            "Candidate Name",
            "Institution ID",
            "Email",
            "Submission Status",
            "Submitted At (UTC)",
            "MCQ Score",
            "MCQ Max",
            "Descriptive Score",
            "Descriptive Max",
            "Obtained Marks",
            "Total Marks",
            "Percentage",
            "Grade",
            "Outcome",
            "Evaluation Status",
            "Publication Status",
        ]
        csv_rows = [
            [
                r["submission_id"],
                r["student_name"],
                r["institution_id"],
                r["student_email"],
                r["submission_status"],
                r["submitted_at"] or "",
                r["mcq_score"],
                r["mcq_max_score"],
                "" if r["descriptive_score"] is None else r["descriptive_score"],
                r["descriptive_max_score"],
                "" if r["obtained_marks"] is None else r["obtained_marks"],
                r["total_marks"],
                "" if r["percentage"] is None else f"{r['percentage']}%",
                r["grade"] or "",
                r["pass_status"] or "",
                r["evaluation_status"],
                r["publication_status"],
            ]
            for r in data["rows"]
        ]
        safe_code = re.sub(r"[^A-Za-z0-9_-]+", "_", exam.get("course_code") or "exam").strip("_") or "exam"
        filename = f"{safe_code}_results.csv"
        return filename, rows_to_csv_string(headers, csv_rows)

    # ------------------------------------------------------------------
    # Student-facing Published Results
    # ------------------------------------------------------------------
    def list_student_results(self, student_uid: str) -> dict[str, Any]:
        results = self.result_repo.list_by_student(student_uid, published_only=True)
        avg_pct = (
            round(sum(float(r.get("percentage", 0)) for r in results) / len(results), 2)
            if results
            else 0.0
        )
        passed_count = sum(1 for r in results if r.get("passed"))

        compact = [
            {
                "result_id": r["result_id"],
                "submission_id": r["submission_id"],
                "exam_id": r["exam_id"],
                "exam_title": r["exam_title"],
                "course_code": r["course_code"],
                "obtained_marks": r["obtained_marks"],
                "total_marks": r["total_marks"],
                "mcq_score": r["mcq_score"],
                "mcq_max_score": r["mcq_max_score"],
                "descriptive_score": r["descriptive_score"],
                "descriptive_max_score": r["descriptive_max_score"],
                "percentage": r["percentage"],
                "grade": r["grade"],
                "passed": r["passed"],
                "pass_status": r["pass_status"],
                "published_at": r.get("published_at"),
                "examiner_feedback": r.get("examiner_feedback", ""),
            }
            for r in results
        ]

        return {
            "summary": {
                "published_count": len(compact),
                "passed_count": passed_count,
                "average_percentage": avg_pct,
            },
            "results": compact,
        }

    def get_student_result_detail(self, result_id: str, student_user: dict[str, Any]) -> dict[str, Any]:
        result = self.result_repo.get_by_id(result_id)
        if not result:
            raise NotFoundError("Result record not found or not yet published.")
        if result.get("student_uid") != student_user["uid"]:
            raise AuthorizationError("You can only view your own published examination results.")
        if result.get("publication_status") != "published":
            raise NotFoundError("This examination result has not been published yet.")
        return result

    def list_student_notifications(self, student_uid: str) -> list[dict[str, Any]]:
        if not self.notification_repo:
            return []
        return self.notification_repo.list_for_user(student_uid)

    def mark_notification_read(self, notification_id: str, student_user: dict[str, Any]) -> dict[str, Any]:
        if not self.notification_repo:
            raise NotFoundError("Notification not found.")
        notif = self.notification_repo.get_by_id(notification_id)
        if not notif:
            raise NotFoundError("Notification not found.")
        if notif.get("recipient_uid") != student_user["uid"]:
            raise AuthorizationError("You cannot modify another student's notification.")
        return self.notification_repo.update(notification_id, {"is_read": True}) or {**notif, "is_read": True}

