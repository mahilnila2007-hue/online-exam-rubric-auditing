"""Submission repository managing Firestore 'submissions' documents."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class SubmissionRepository(BaseFirestoreRepository):
    collection_name = "submissions"
    id_field = "submission_id"

    @staticmethod
    def build_attempt_id(exam_id: str, student_uid: str) -> str:
        return f"{exam_id}__{student_uid}"

    def get_by_exam_and_student(self, exam_id: str, student_uid: str) -> dict[str, Any] | None:
        return self.get_by_id(self.build_attempt_id(exam_id, student_uid))

    def list_by_student(self, student_uid: str, limit: int = 200) -> list[dict[str, Any]]:
        items = self.find_where("student_uid", "==", student_uid, limit=limit)
        return sorted(items, key=lambda x: str(x.get("started_at", "")), reverse=True)

    def list_by_exam(self, exam_id: str, limit: int = 500) -> list[dict[str, Any]]:
        items = self.find_where("exam_id", "==", exam_id, limit=limit)
        return sorted(items, key=lambda x: str(x.get("submitted_at") or x.get("started_at") or ""), reverse=True)

    def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        items = self.list_all(limit=limit)
        return sorted(items, key=lambda x: str(x.get("updated_at", "")), reverse=True)

