"""Immutable activity audit trail service."""

from __future__ import annotations

import logging
from typing import Any

from app.repositories.audit_repo import AuditRepository

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, audit_repo: AuditRepository) -> None:
        self.audit_repo = audit_repo

    def record(
        self,
        *,
        actor: dict[str, Any] | None,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict[str, Any] | None = None,
        ip_address: str = "",
    ) -> None:
        try:
            self.audit_repo.create(
                {
                    "actor_uid": (actor or {}).get("uid", "system"),
                    "actor_email": (actor or {}).get("email", "system"),
                    "actor_role": (actor or {}).get("role", "system"),
                    "action": action,
                    "target_type": target_type,
                    "target_id": target_id,
                    "metadata": metadata or {},
                    "ip_address": ip_address,
                }
            )
        except Exception as exc:  # pragma: no cover - audit logging must never break primary flows
            logger.warning("Failed to persist audit log (%s): %s", action, exc)

    def list_recent(
        self,
        *,
        actor_role: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.audit_repo.list_recent(actor_role=actor_role, action=action, limit=limit)

