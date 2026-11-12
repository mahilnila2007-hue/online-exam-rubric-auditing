"""User repository managing Firestore 'users' documents."""

from __future__ import annotations

from typing import Any

from app.repositories.base import BaseFirestoreRepository


class UserRepository(BaseFirestoreRepository):
    collection_name = "users"
    id_field = "uid"

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        normalized = email.strip().lower()
        matches = self.find_where("email", "==", normalized, limit=1)
        return matches[0] if matches else None

    def list_users(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if role:
            users = self.find_where("role", "==", role, limit=limit)
        elif status:
            users = self.find_where("status", "==", status, limit=limit)
        else:
            users = self.list_all(limit=limit)

        if role and status:
            users = [u for u in users if u.get("status") == status]

        return sorted(users, key=lambda u: str(u.get("created_at", "")), reverse=True)

