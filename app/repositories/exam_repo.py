"""Examination repository managing Firestore 'exams' documents."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class ExamRepository(BaseFirestoreRepository):
    collection_name = "exams"
    id_field = "exam_id"

    def list_exams(
        self,
        *,
        created_by: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if created_by:
            items = self.find_where("created_by", "==", created_by, limit=limit)
        elif status:
            items = self.find_where("status", "==", status, limit=limit)
        else:
            items = self.list_all(limit=limit)

        if created_by and status:
            items = [e for e in items if e.get("status") == status]

        return sorted(items, key=lambda x: str(x.get("scheduled_start", "")), reverse=True)

    def list_student_visible_exams(self, limit: int = 500) -> list[dict[str, Any]]:
        """Return published and scheduled exams eligible for student visibility."""
        all_exams = self.list_all(limit=limit)
        visible = [e for e in all_exams if e.get("status") in {"published", "scheduled"}]
        return sorted(visible, key=lambda x: str(x.get("scheduled_start", "")))

