"""Firestore repositories for Phase 3 rubric auditing, versioning, history, and notifications."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class AuditReportRepository(BaseFirestoreRepository):
    collection_name = "audit_reports"
    id_field = "audit_id"

    def list_by_exam(self, exam_id: str, limit: int = 100) -> list[dict[str, Any]]:
        items = self.find_where("exam_id", "==", exam_id, limit=limit)
        return sorted(items, key=lambda x: str(x.get("created_at", "")), reverse=True)

    def list_by_examiner(self, examiner_uid: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        items = (
            self.find_where("examiner_uid", "==", examiner_uid, limit=limit)
            if examiner_uid
            else self.list_all(limit=limit)
        )
        return sorted(items, key=lambda x: str(x.get("created_at", "")), reverse=True)


class AuditSuggestionRepository(BaseFirestoreRepository):
    collection_name = "audit_suggestions"
    id_field = "suggestion_id"

    def list_suggestions(
        self,
        *,
        examiner_uid: str | None = None,
        exam_id: str | None = None,
        status: str | None = None,
        criterion_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if exam_id:
            items = self.find_where("exam_id", "==", exam_id, limit=limit)
        elif examiner_uid:
            items = self.find_where("examiner_uid", "==", examiner_uid, limit=limit)
        elif status:
            items = self.find_where("status", "==", status, limit=limit)
        else:
            items = self.list_all(limit=limit)

        filtered: list[dict[str, Any]] = []
        for s in items:
            if examiner_uid and s.get("examiner_uid") != examiner_uid:
                continue
            if exam_id and s.get("exam_id") != exam_id:
                continue
            if status and s.get("status") != status:
                continue
            if criterion_id and s.get("criterion_id") != criterion_id:
                continue
            filtered.append(s)

        return sorted(
            filtered,
            key=lambda x: (
                0 if x.get("status") == "pending" else 1,
                -float(x.get("confidence_score", 0)),
                str(x.get("created_at", "")),
            ),
        )


class RubricVersionRepository(BaseFirestoreRepository):
    collection_name = "rubric_versions"
    id_field = "version_id"

    def list_by_rubric(self, rubric_id: str, limit: int = 100) -> list[dict[str, Any]]:
        items = self.find_where("rubric_id", "==", rubric_id, limit=limit)
        return sorted(items, key=lambda x: int(x.get("version_number", 0)), reverse=True)


class AuditHistoryRepository(BaseFirestoreRepository):
    collection_name = "audit_history"
    id_field = "history_id"

    def list_history(
        self,
        *,
        exam_id: str | None = None,
        examiner_uid: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if exam_id:
            items = self.find_where("exam_id", "==", exam_id, limit=limit)
        elif examiner_uid:
            items = self.find_where("examiner_uid", "==", examiner_uid, limit=limit)
        else:
            items = self.list_all(limit=limit)
        return sorted(items, key=lambda x: str(x.get("created_at", "")), reverse=True)[:limit]


class NotificationRepository(BaseFirestoreRepository):
    collection_name = "notifications"
    id_field = "notification_id"

    def list_for_user(self, uid: str, *, unread_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        items = self.find_where("recipient_uid", "==", uid, limit=limit)
        if unread_only:
            items = [n for n in items if not n.get("is_read", False)]
        return sorted(items, key=lambda x: str(x.get("created_at", "")), reverse=True)

