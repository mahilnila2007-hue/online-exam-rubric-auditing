"""Question bank and descriptive evaluation rubric management service."""

from __future__ import annotations

from typing import Any

from app.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.repositories.question_repo import QuestionRepository
from app.repositories.rubric_repo import RubricRepository
from app.services.audit_service import AuditService
from app.validators.question_validators import (
    validate_question_payload,
    validate_rubric_payload,
)


def _build_rubric_snapshot(rubric: dict[str, Any]) -> dict[str, Any]:
    """Build a compact rubric snapshot stored alongside descriptive questions."""
    return {
        "rubric_id": rubric["rubric_id"],
        "title": rubric["title"],
        "max_marks": rubric["max_marks"],
        "version": rubric.get("version", 1),
        "has_model_answer": bool(rubric.get("model_answer")),
        "criteria": [
            {
                "criterion_id": c["criterion_id"],
                "title": c["title"],
                "description": c.get("description", ""),
                "max_marks": c["max_marks"],
                "weight": c.get("weight", 0),
                "key_concepts": c.get("key_concepts", []),
                "alternative_phrases": c.get("alternative_phrases", []),
            }
            for c in rubric.get("criteria", [])
        ],
    }


class QuestionService:
    def __init__(
        self,
        question_repo: QuestionRepository,
        rubric_repo: RubricRepository,
        audit_service: AuditService,
    ) -> None:
        self.question_repo = question_repo
        self.rubric_repo = rubric_repo
        self.audit_service = audit_service

    def _assert_can_manage(self, resource: dict[str, Any], user: dict[str, Any], label: str) -> None:
        if user.get("role") == "admin":
            return
        if resource.get("created_by") != user.get("uid"):
            raise AuthorizationError(f"You do not have permission to modify this {label}.")

    # ------------------------------------------------------------------
    # Rubrics
    # ------------------------------------------------------------------
    def list_rubrics(self, user: dict[str, Any], *, subject: str | None = None) -> list[dict[str, Any]]:
        created_by = None if user.get("role") == "admin" else user.get("uid")
        return self.rubric_repo.list_rubrics(created_by=created_by, subject=subject)

    def get_rubric(self, user: dict[str, Any], rubric_id: str) -> dict[str, Any]:
        rubric = self.rubric_repo.get_by_id(rubric_id)
        if not rubric:
            raise NotFoundError("Evaluation rubric not found.")
        self._assert_can_manage(rubric, user, "rubric")
        return rubric

    def create_rubric(
        self,
        user: dict[str, Any],
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_rubric_payload(payload)
        rubric = self.rubric_repo.create(
            {
                **validated,
                "created_by": user["uid"],
                "created_by_name": user.get("full_name", user["email"]),
                "version": 1,
            },
            doc_id=self.rubric_repo.new_id("rub"),
        )
        self.audit_service.record(
            actor=user,
            action="RUBRIC_CREATED",
            target_type="rubric",
            target_id=rubric["rubric_id"],
            metadata={"title": rubric["title"], "max_marks": rubric["max_marks"]},
            ip_address=ip_address,
        )
        return rubric

    def update_rubric(
        self,
        user: dict[str, Any],
        rubric_id: str,
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        existing = self.get_rubric(user, rubric_id)
        validated = validate_rubric_payload(payload)
        next_version = int(existing.get("version", 1)) + 1
        updated = self.rubric_repo.update(
            rubric_id,
            {
                **validated,
                "version": next_version,
            },
        )
        if not updated:
            raise NotFoundError("Evaluation rubric not found.")

        # Propagate snapshot updates to questions referencing this rubric
        snapshot = _build_rubric_snapshot(updated)
        linked_questions = self.question_repo.find_where("rubric_id", "==", rubric_id)
        for question in linked_questions:
            if abs(float(question.get("marks", 0)) - float(updated["max_marks"])) <= 0.01:
                self.question_repo.update(question["question_id"], {"rubric_snapshot": snapshot})

        self.audit_service.record(
            actor=user,
            action="RUBRIC_UPDATED",
            target_type="rubric",
            target_id=rubric_id,
            metadata={"version": next_version},
            ip_address=ip_address,
        )
        return updated

    def delete_rubric(self, user: dict[str, Any], rubric_id: str, *, ip_address: str = "") -> None:
        self.get_rubric(user, rubric_id)
        linked = [
            q for q in self.question_repo.find_where("rubric_id", "==", rubric_id)
            if not q.get("is_archived", False)
        ]
        if linked:
            raise ValidationError(
                "This rubric is linked to active descriptive questions and cannot be deleted."
            )
        self.rubric_repo.delete(rubric_id)
        self.audit_service.record(
            actor=user,
            action="RUBRIC_DELETED",
            target_type="rubric",
            target_id=rubric_id,
            ip_address=ip_address,
        )

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------
    def _resolve_descriptive_rubric(
        self,
        user: dict[str, Any],
        validated: dict[str, Any],
        *,
        ip_address: str = "",
    ) -> tuple[str, dict[str, Any]]:
        if validated.get("rubric_id"):
            rubric = self.get_rubric(user, validated["rubric_id"])
            if abs(float(rubric["max_marks"]) - float(validated["marks"])) > 0.01:
                raise ValidationError(
                    f"Selected rubric total marks ({rubric['max_marks']:g}) must match "
                    f"question marks ({validated['marks']:g}).",
                    details={"fields": {"rubric_id": "Rubric max marks do not match question marks."}},
                )
            return rubric["rubric_id"], _build_rubric_snapshot(rubric)

        inline = validated.get("inline_rubric")
        if not inline:
            raise ValidationError("Descriptive questions require an evaluation rubric.")
        rubric = self.rubric_repo.create(
            {
                **inline,
                "created_by": user["uid"],
                "created_by_name": user.get("full_name", user["email"]),
                "version": 1,
            },
            doc_id=self.rubric_repo.new_id("rub"),
        )
        self.audit_service.record(
            actor=user,
            action="RUBRIC_CREATED",
            target_type="rubric",
            target_id=rubric["rubric_id"],
            metadata={"title": rubric["title"], "inline": True},
            ip_address=ip_address,
        )
        return rubric["rubric_id"], _build_rubric_snapshot(rubric)

    def list_questions(
        self,
        user: dict[str, Any],
        *,
        subject: str | None = None,
        q_type: str | None = None,
        difficulty: str | None = None,
        question_set: str | None = None,
        marks: float | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        created_by = None if user.get("role") == "admin" else user.get("uid")
        items = self.question_repo.list_questions(
            created_by=created_by,
            subject=subject,
            q_type=q_type,
            difficulty=difficulty,
            question_set=question_set,
            marks=marks,
        )
        if search:
            needle = search.strip().lower()
            items = [
                q
                for q in items
                if needle in q.get("prompt", "").lower()
                or needle in q.get("subject", "").lower()
                or needle in q.get("topic", "").lower()
                or needle in q.get("question_set", "").lower()
                or any(needle in t.lower() for t in q.get("tags", []))
            ]
        return items

    def get_question(self, user: dict[str, Any], question_id: str) -> dict[str, Any]:
        question = self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError("Question not found.")
        self._assert_can_manage(question, user, "question")
        return question

    def create_question(
        self,
        user: dict[str, Any],
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        validated = validate_question_payload(payload)
        rubric_id: str | None = None
        rubric_snapshot: dict[str, Any] | None = None

        if validated["type"] == "descriptive":
            rubric_id, rubric_snapshot = self._resolve_descriptive_rubric(
                user, validated, ip_address=ip_address
            )

        doc = self.question_repo.create(
            {
                "created_by": user["uid"],
                "created_by_name": user.get("full_name", user["email"]),
                "subject": validated["subject"],
                "topic": validated["topic"],
                "difficulty": validated["difficulty"],
                "type": validated["type"],
                "prompt": validated["prompt"],
                "marks": validated["marks"],
                "options": validated["options"],
                "correct_option_id": validated["correct_option_id"],
                "explanation": validated["explanation"],
                "question_set": validated["question_set"],
                "rubric_id": rubric_id,
                "rubric_snapshot": rubric_snapshot,
                "tags": validated["tags"],
                "is_archived": False,
            },
            doc_id=self.question_repo.new_id("q"),
        )

        self.audit_service.record(
            actor=user,
            action="QUESTION_CREATED",
            target_type="question",
            target_id=doc["question_id"],
            metadata={"type": doc["type"], "subject": doc["subject"], "marks": doc["marks"]},
            ip_address=ip_address,
        )
        return doc

    def update_question(
        self,
        user: dict[str, Any],
        question_id: str,
        payload: dict[str, Any] | None,
        *,
        ip_address: str = "",
    ) -> dict[str, Any]:
        self.get_question(user, question_id)
        validated = validate_question_payload(payload)

        rubric_id: str | None = None
        rubric_snapshot: dict[str, Any] | None = None
        if validated["type"] == "descriptive":
            rubric_id, rubric_snapshot = self._resolve_descriptive_rubric(
                user, validated, ip_address=ip_address
            )

        updated = self.question_repo.update(
            question_id,
            {
                "subject": validated["subject"],
                "topic": validated["topic"],
                "difficulty": validated["difficulty"],
                "type": validated["type"],
                "prompt": validated["prompt"],
                "marks": validated["marks"],
                "options": validated["options"],
                "correct_option_id": validated["correct_option_id"],
                "explanation": validated["explanation"],
                "question_set": validated["question_set"],
                "rubric_id": rubric_id,
                "rubric_snapshot": rubric_snapshot,
                "tags": validated["tags"],
            },
        )
        if not updated:
            raise NotFoundError("Question not found.")

        self.audit_service.record(
            actor=user,
            action="QUESTION_UPDATED",
            target_type="question",
            target_id=question_id,
            metadata={"type": updated["type"], "marks": updated["marks"]},
            ip_address=ip_address,
        )
        return updated

    def archive_question(self, user: dict[str, Any], question_id: str, *, ip_address: str = "") -> None:
        self.get_question(user, question_id)
        self.question_repo.update(question_id, {"is_archived": True})
        self.audit_service.record(
            actor=user,
            action="QUESTION_ARCHIVED",
            target_type="question",
            target_id=question_id,
            ip_address=ip_address,
        )

