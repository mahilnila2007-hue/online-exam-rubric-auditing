"""Rubric repository managing Firestore 'rubrics' documents."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class RubricRepository(BaseFirestoreRepository):
    collection_name = "rubrics"
    id_field = "rubric_id"

    def list_rubrics(
        self,
        *,
        created_by: str | None = None,
        subject: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if created_by:
            items = self.find_where("created_by", "==", created_by, limit=limit)
        else:
            items = self.list_all(limit=limit)

        if subject:
            items = [r for r in items if r.get("subject", "").lower() == subject.lower()]

        return sorted(items, key=lambda x: str(x.get("updated_at", "")), reverse=True)

