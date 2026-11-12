"""Audit log repository managing Firestore 'audit_logs' documents."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class AuditRepository(BaseFirestoreRepository):
    collection_name = "audit_logs"
    id_field = "log_id"

    def list_recent(
        self,
        *,
        actor_role: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if actor_role:
            items = self.find_where("actor_role", "==", actor_role, limit=limit)
        elif action:
            items = self.find_where("action", "==", action, limit=limit)
        else:
            items = self.list_all(limit=limit)

        if actor_role and action:
            items = [i for i in items if i.get("action") == action]

        return sorted(items, key=lambda x: str(x.get("created_at", "")), reverse=True)[:limit]

