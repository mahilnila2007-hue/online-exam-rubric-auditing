"""Shared Firestore base repository with clean serialization and zero duplication."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from app.extensions.firebase import get_firebase_manager


def serialize_value(value: Any) -> Any:
    """Recursively convert Firestore/datetime objects into JSON-safe primitives."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value


class BaseFirestoreRepository:
    """Generic CRUD repository backed by a Cloud Firestore collection."""

    collection_name: str = ""
    id_field: str = "id"

    def _collection(self) -> Any:
        db = get_firebase_manager().require_db()
        return db.collection(self.collection_name)

    def _serialize_doc(self, doc: Any) -> dict[str, Any] | None:
        if not doc or not doc.exists:
            return None
        data = serialize_value(doc.to_dict() or {})
        data.setdefault(self.id_field, doc.id)
        return data

    def new_id(self, prefix: str = "") -> str:
        raw = uuid.uuid4().hex[:16]
        return f"{prefix}_{raw}" if prefix else raw

    def get_by_id(self, doc_id: str) -> dict[str, Any] | None:
        if not doc_id:
            return None
        snap = self._collection().document(doc_id).get()
        return self._serialize_doc(snap)

    def get_many_by_ids(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not doc_ids:
            return results
        col = self._collection()
        # Preserve caller ordering while batch-reading cleanly
        by_id: dict[str, dict[str, Any]] = {}
        for chunk_start in range(0, len(doc_ids), 25):
            chunk = doc_ids[chunk_start : chunk_start + 25]
            refs = [col.document(item_id) for item_id in chunk]
            db = get_firebase_manager().require_db()
            for snap in db.get_all(refs):
                serialized = self._serialize_doc(snap)
                if serialized:
                    by_id[snap.id] = serialized
        for item_id in doc_ids:
            if item_id in by_id:
                results.append(by_id[item_id])
        return results

    def create(self, data: dict[str, Any], doc_id: str | None = None) -> dict[str, Any]:
        target_id = doc_id or data.get(self.id_field) or self.new_id()
        now = datetime.now(timezone.utc)
        payload = {
            **data,
            self.id_field: target_id,
            "created_at": data.get("created_at") or now,
            "updated_at": data.get("updated_at") or now,
        }
        self._collection().document(target_id).set(payload)
        return serialize_value(payload)

    def update(self, doc_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        ref = self._collection().document(doc_id)
        snap = ref.get()
        if not snap.exists:
            return None
        merged = {
            **updates,
            "updated_at": datetime.now(timezone.utc),
        }
        ref.update(merged)
        updated_snap = ref.get()
        return self._serialize_doc(updated_snap)

    def set_merge(self, doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
        ref = self._collection().document(doc_id)
        payload = {
            **data,
            self.id_field: doc_id,
            "updated_at": datetime.now(timezone.utc),
        }
        ref.set(payload, merge=True)
        return self._serialize_doc(ref.get()) or serialize_value(payload)

    def delete(self, doc_id: str) -> bool:
        ref = self._collection().document(doc_id)
        snap = ref.get()
        if not snap.exists:
            return False
        ref.delete()
        return True

    def list_all(self, *, limit: int = 500) -> list[dict[str, Any]]:
        snaps = self._collection().limit(limit).stream()
        items: list[dict[str, Any]] = []
        for snap in snaps:
            serialized = self._serialize_doc(snap)
            if serialized:
                items.append(serialized)
        return items

    def find_where(
        self,
        field: str,
        op: str,
        value: Any,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            query = self._collection().where(filter=FieldFilter(field, op, value)).limit(limit)
        except ImportError:  # pragma: no cover
            query = self._collection().where(field, op, value).limit(limit)

        items: list[dict[str, Any]] = []
        for snap in query.stream():
            serialized = self._serialize_doc(snap)
            if serialized:
                items.append(serialized)
        return items

