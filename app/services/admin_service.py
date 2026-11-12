"""Administrative user management, platform monitoring, and reporting service."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.middleware.auth import get_auth_gateway
from app.repositories.exam_repo import ExamRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.rubric_repo import RubricRepository
from app.repositories.submission_repo import SubmissionRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_service import AuditService
from app.services.csv_utils import rows_to_csv_string
from app.services.exam_service import compute_exam_availability
from app.services.time_utils import utc_now
from app.validators.admin_validators import (
    validate_admin_create_user_payload,
    validate_admin_update_user_payload,
    validate_reject_staff_payload,
)


class AdminService:
    def __init__(
        self,
        user_repo: UserRepository,
        exam_repo: ExamRepository,
        question_repo: QuestionRepository,
        rubric_repo: RubricRepository,
        submission_repo: SubmissionRepository,
        audit_service: AuditService,
    ) -> None:
        self.user_repo = user_repo
        self.exam_repo = exam_repo
        self.question_repo = question_repo
        self.rubric_repo = rubric_repo
        self.submission_repo = submission_repo
        self.audit_service = audit_service

    def list_users(self, *, role: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return self.user_repo.list_users(role=role, status=status)

    def create_user_account(
        self,
        admin_user: dict[str, Any],
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        data = validate_admin_create_user_payload(payload)
        existing = self.user_repo.get_by_email(data["email"])
        if existing:
            raise ConflictError("An account with this email address already exists.")

        gateway = get_auth_gateway()
        try:
            fb_user = gateway.create_user(
                email=data["email"],
                password=data["password"],
                display_name=data["full_name"],
            )
        except Exception as exc:
            raise ValidationError(f"Unable to provision Firebase Auth account: {exc}") from exc

        uid = fb_user.uid
        gateway.set_custom_claims(uid, {"role": data["role"]})

        created = self.user_repo.create(
            {
                "uid": uid,
                "email": data["email"],
                "full_name": data["full_name"],
                "role": data["role"],
                "institution_id": data["institution_id"],
                "department": data["department"],
                "status": "active",
                "last_login_at": None,
            },
            doc_id=uid,
        )

        self.audit_service.record(
            actor=admin_user,
            action="ADMIN_USER_CREATED",
            target_type="user",
            target_id=uid,
            metadata={"email": data["email"], "role": data["role"]},
            ip_address=ip_address,
        )
        return created

    def update_user_account(
        self,
        admin_user: dict[str, Any],
        target_uid: str,
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        updates = validate_admin_update_user_payload(payload)
        target = self.user_repo.get_by_id(target_uid)
        if not target:
            raise NotFoundError("Target user account was not found.")

        if target_uid == admin_user["uid"]:
            if updates.get("status") == "suspended":
                raise ValidationError("You cannot suspend your own active administrator account.")
            if updates.get("role") and updates["role"] != "admin":
                raise ValidationError("You cannot demote your own administrator role.")

        gateway = get_auth_gateway()
        if "role" in updates and updates["role"] != target.get("role"):
            gateway.set_custom_claims(target_uid, {"role": updates["role"]})

        if "status" in updates and updates["status"] != target.get("status"):
            disabled = updates["status"] == "suspended"
            gateway.update_user_status(target_uid, disabled=disabled)
            if disabled:
                try:
                    gateway.revoke_refresh_tokens(target_uid)
                except Exception:
                    pass

        updated = self.user_repo.update(target_uid, updates)
        if not updated:
            raise NotFoundError("Target user account was not found.")

        self.audit_service.record(
            actor=admin_user,
            action="ADMIN_USER_UPDATED",
            target_type="user",
            target_id=target_uid,
            metadata={"updated_fields": sorted(updates.keys()), "status": updated.get("status"), "role": updated.get("role")},
            ip_address=ip_address,
        )
        return updated

    def approve_staff_user(
        self,
        admin_user: dict[str, Any],
        target_uid: str,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        target = self.user_repo.get_by_id(target_uid)
        if not target:
            raise NotFoundError("Target user account was not found.")
        if target.get("status") not in {"pending_approval", "rejected"}:
            raise ConflictError("This account is not awaiting administrator approval.")

        gateway = get_auth_gateway()
        role = target.get("role", "examiner")
        gateway.update_user_status(target_uid, disabled=False)
        gateway.set_custom_claims(target_uid, {"role": role, "approved": True})

        now = utc_now()
        updated = self.user_repo.update(
            target_uid,
            {
                "status": "active",
                "approval_status": "approved",
                "approved_by": admin_user["uid"],
                "approved_by_name": admin_user.get("full_name", admin_user["email"]),
                "approved_at": now,
            },
        )
        if not updated:
            raise NotFoundError("Target user account was not found.")

        self.audit_service.record(
            actor=admin_user,
            action="ADMIN_STAFF_APPROVED",
            target_type="user",
            target_id=target_uid,
            metadata={"email": updated.get("email"), "role": role},
            ip_address=ip_address,
        )
        return updated

    def reject_staff_user(
        self,
        admin_user: dict[str, Any],
        target_uid: str,
        payload: dict[str, Any] | None = None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        data = validate_reject_staff_payload(payload)
        target = self.user_repo.get_by_id(target_uid)
        if not target:
            raise NotFoundError("Target user account was not found.")
        if target.get("status") != "pending_approval":
            raise ConflictError("This account is not awaiting administrator approval.")

        gateway = get_auth_gateway()
        gateway.update_user_status(target_uid, disabled=True)
        try:
            gateway.revoke_refresh_tokens(target_uid)
        except Exception:
            pass

        now = utc_now()
        updated = self.user_repo.update(
            target_uid,
            {
                "status": "rejected",
                "approval_status": "rejected",
                "rejected_by": admin_user["uid"],
                "rejected_by_name": admin_user.get("full_name", admin_user["email"]),
                "rejected_at": now,
                "rejection_reason": data["reason"],
            },
        )
        if not updated:
            raise NotFoundError("Target user account was not found.")

        self.audit_service.record(
            actor=admin_user,
            action="ADMIN_STAFF_REJECTED",
            target_type="user",
            target_id=target_uid,
            metadata={"email": updated.get("email"), "reason": data["reason"]},
            ip_address=ip_address,
        )
        return updated

    def get_dashboard_overview(self) -> dict[str, Any]:
        users = self.user_repo.list_users()
        exams = self.exam_repo.list_exams()
        questions = self.question_repo.list_questions()
        rubrics = self.rubric_repo.list_rubrics()
        submissions = self.submission_repo.list_recent(limit=500)
        logs = self.audit_service.list_recent(limit=50)

        role_counts = Counter(u.get("role", "student") for u in users)
        status_counts = Counter(u.get("status", "active") for u in users)
        exam_avail_counts = Counter(compute_exam_availability(e) for e in exams)
        eval_counts = Counter(s.get("grading", {}).get("evaluation_status", "in_progress") for s in submissions)

        exam_reports: list[dict[str, Any]] = []
        subs_by_exam: dict[str, list[dict[str, Any]]] = {}
        for sub in submissions:
            subs_by_exam.setdefault(sub["exam_id"], []).append(sub)

        for exam in exams:
            ex_subs = subs_by_exam.get(exam["exam_id"], [])
            completed = [s for s in ex_subs if s.get("status") in {"submitted", "auto_submitted"}]
            avg_mcq = (
                round(
                    sum(float(s.get("grading", {}).get("mcq_score", 0)) for s in completed) / len(completed),
                    2,
                )
                if completed
                else 0.0
            )
            pending_desc = sum(
                1 for s in completed if s.get("grading", {}).get("evaluation_status") == "pending_descriptive"
            )
            exam_reports.append(
                {
                    "exam_id": exam["exam_id"],
                    "title": exam["title"],
                    "course_code": exam["course_code"],
                    "created_by_name": exam.get("created_by_name", "Examiner"),
                    "status": exam["status"],
                    "availability": compute_exam_availability(exam),
                    "scheduled_start": exam.get("scheduled_start"),
                    "scheduled_end": exam.get("scheduled_end"),
                    "total_marks": exam.get("total_marks", 0),
                    "question_count": exam.get("question_count", 0),
                    "total_attempts": len(ex_subs),
                    "completed_submissions": len(completed),
                    "pending_descriptive": pending_desc,
                    "avg_mcq_score": avg_mcq,
                }
            )

        pending_staff = [u for u in users if u.get("status") == "pending_approval"]

        return {
            "metrics": {
                "total_users": len(users),
                "students": role_counts.get("student", 0),
                "examiners": role_counts.get("examiner", 0),
                "admins": role_counts.get("admin", 0),
                "active_users": status_counts.get("active", 0),
                "suspended_users": status_counts.get("suspended", 0),
                "pending_staff_count": len(pending_staff),
                "total_exams": len(exams),
                "live_exams": exam_avail_counts.get("live", 0),
                "upcoming_exams": exam_avail_counts.get("upcoming", 0),
                "total_questions": len(questions),
                "total_rubrics": len(rubrics),
                "total_submissions": len(submissions),
                "pending_descriptive_reviews": eval_counts.get("pending_descriptive", 0),
            },
            "pending_staff_approvals": pending_staff,
            "exam_reports": exam_reports,
            "recent_activity": logs,
        }

    def export_exam_report_csv(self) -> str:
        overview = self.get_dashboard_overview()
        headers = [
            "Exam ID",
            "Course Code",
            "Title",
            "Examiner",
            "Status",
            "Availability",
            "Questions",
            "Total Marks",
            "Total Attempts",
            "Completed Submissions",
            "Pending Descriptive Reviews",
            "Average MCQ Score",
        ]
        rows = [
            [
                row["exam_id"],
                row["course_code"],
                row["title"],
                row["created_by_name"],
                row["status"],
                row["availability"],
                row["question_count"],
                row["total_marks"],
                row["total_attempts"],
                row["completed_submissions"],
                row["pending_descriptive"],
                row["avg_mcq_score"],
            ]
            for row in overview["exam_reports"]
        ]
        return rows_to_csv_string(headers, rows)

