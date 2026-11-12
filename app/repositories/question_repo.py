"""Question bank repository managing Firestore 'questions' documents."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class QuestionRepository(BaseFirestoreRepository):
    collection_name = "questions"
    id_field = "question_id"

    def list_questions(
        self,
        *,
        created_by: str | None = None,
        subject: str | None = None,
        q_type: str | None = None,
        difficulty: str | None = None,
        question_set: str | None = None,
        marks: float | None = None,
        include_archived: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if created_by:
            items = self.find_where("created_by", "==", created_by, limit=limit)
        elif q_type:
            items = self.find_where("type", "==", q_type, limit=limit)
        else:
            items = self.list_all(limit=limit)

        filtered: list[dict[str, Any]] = []
        for q in items:
            if not include_archived and q.get("is_archived", False):
                continue
            if subject and q.get("subject", "").lower() != subject.lower():
                continue
            if q_type and q.get("type") != q_type:
                continue
            if difficulty and q.get("difficulty") != difficulty:
                continue
            if question_set and q.get("question_set", "").lower() != question_set.lower():
                continue
            if marks is not None and abs(float(q.get("marks", 0)) - marks) > 0.01:
                continue
            filtered.append(q)

        return sorted(filtered, key=lambda x: str(x.get("updated_at", "")), reverse=True)

