"""Result repository managing Firestore 'results' documents."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class ResultRepository(BaseFirestoreRepository):
    collection_name = "results"
    id_field = "result_id"

    @staticmethod
    def build_result_id(exam_id: str, student_uid: str) -> str:
        return f"{exam_id}__{student_uid}"

    def get_by_exam_and_student(self, exam_id: str, student_uid: str) -> dict[str, Any] | None:
        return self.get_by_id(self.build_result_id(exam_id, student_uid))

    def list_by_exam(self, exam_id: str, limit: int = 500) -> list[dict[str, Any]]:
        items = self.find_where("exam_id", "==", exam_id, limit=limit)
        return sorted(items, key=lambda r: float(r.get("obtained_marks", 0)), reverse=True)

    def list_by_student(self, student_uid: str, *, published_only: bool = True, limit: int = 200) -> list[dict[str, Any]]:
        items = self.find_where("student_uid", "==", student_uid, limit=limit)
        if published_only:
            items = [r for r in items if r.get("publication_status") == "published"]
        return sorted(
            items,
            key=lambda r: str(r.get("published_at") or r.get("evaluated_at") or r.get("updated_at") or ""),
            reverse=True,
        )

