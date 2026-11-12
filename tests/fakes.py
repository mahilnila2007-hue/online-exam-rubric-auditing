"""Test doubles implementing the repository and Firebase Auth gateway contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
import uuid

from app.exceptions import AuthenticationError
from app.repositories.base import serialize_value
from app.repositories.rubric_audit_repo import (
    AuditHistoryRepository,
    AuditReportRepository,
    AuditSuggestionRepository,
    NotificationRepository,
    RubricVersionRepository,
)


class InMemoryRepository:
    """In-memory collection store matching BaseFirestoreRepository method signatures."""

    id_field: str = "id"

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def new_id(self, prefix: str = "") -> str:
        raw = uuid.uuid4().hex[:12]
        return f"{prefix}_{raw}" if prefix else raw

    def get_by_id(self, doc_id: str) -> dict[str, Any] | None:
        doc = self._docs.get(doc_id)
        return deepcopy(serialize_value(doc)) if doc else None

    def get_many_by_ids(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        return [self.get_by_id(did) for did in doc_ids if did in self._docs]  # type: ignore[misc]

    def create(self, data: dict[str, Any], doc_id: str | None = None) -> dict[str, Any]:
        target_id = doc_id or data.get(self.id_field) or self.new_id()
        now = datetime.now(timezone.utc)
        payload = {
            **deepcopy(data),
            self.id_field: target_id,
            "created_at": data.get("created_at") or now,
            "updated_at": data.get("updated_at") or now,
        }
        self._docs[target_id] = payload
        return deepcopy(serialize_value(payload))

    def update(self, doc_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        if doc_id not in self._docs:
            return None
        self._docs[doc_id] = {
            **self._docs[doc_id],
            **deepcopy(updates),
            "updated_at": datetime.now(timezone.utc),
        }
        return deepcopy(serialize_value(self._docs[doc_id]))

    def set_merge(self, doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
        existing = self._docs.get(doc_id, {})
        self._docs[doc_id] = {
            **existing,
            **deepcopy(data),
            self.id_field: doc_id,
            "updated_at": datetime.now(timezone.utc),
        }
        return deepcopy(serialize_value(self._docs[doc_id]))

    def delete(self, doc_id: str) -> bool:
        return self._docs.pop(doc_id, None) is not None

    def list_all(self, *, limit: int = 500) -> list[dict[str, Any]]:
        return [deepcopy(serialize_value(d)) for d in list(self._docs.values())[:limit]]

    def find_where(self, field: str, op: str, value: Any, *, limit: int = 500) -> list[dict[str, Any]]:
        if op != "==":
            raise NotImplementedError(f"Operator {op} not implemented in test double")
        matches = [d for d in self._docs.values() if d.get(field) == value]
        return [deepcopy(serialize_value(d)) for d in matches[:limit]]


class FakeUserRepository(InMemoryRepository):
    id_field = "uid"

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        matches = self.find_where("email", "==", email.strip().lower(), limit=1)
        return matches[0] if matches else None

    def list_users(self, *, role: str | None = None, status: str | None = None, limit: int = 500):
        users = self.list_all(limit=limit)
        if role:
            users = [u for u in users if u.get("role") == role]
        if status:
            users = [u for u in users if u.get("status") == status]
        return sorted(users, key=lambda u: str(u.get("created_at", "")), reverse=True)


class FakeQuestionRepository(InMemoryRepository):
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
    ):
        items = self.list_all(limit=limit)
        filtered = []
        for q in items:
            if not include_archived and q.get("is_archived", False):
                continue
            if created_by and q.get("created_by") != created_by:
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


class FakeRubricRepository(InMemoryRepository):
    id_field = "rubric_id"

    def list_rubrics(self, *, created_by: str | None = None, subject: str | None = None, limit: int = 500):
        items = self.list_all(limit=limit)
        if created_by:
            items = [r for r in items if r.get("created_by") == created_by]
        if subject:
            items = [r for r in items if r.get("subject", "").lower() == subject.lower()]
        return sorted(items, key=lambda x: str(x.get("updated_at", "")), reverse=True)


class FakeExamRepository(InMemoryRepository):
    id_field = "exam_id"

    def list_exams(self, *, created_by: str | None = None, status: str | None = None, limit: int = 500):
        items = self.list_all(limit=limit)
        if created_by:
            items = [e for e in items if e.get("created_by") == created_by]
        if status:
            items = [e for e in items if e.get("status") == status]
        return sorted(items, key=lambda x: str(x.get("scheduled_start", "")), reverse=True)

    def list_student_visible_exams(self, limit: int = 500):
        items = [e for e in self.list_all(limit=limit) if e.get("status") in {"published", "scheduled"}]
        return sorted(items, key=lambda x: str(x.get("scheduled_start", "")))


class FakeSubmissionRepository(InMemoryRepository):
    id_field = "submission_id"

    @staticmethod
    def build_attempt_id(exam_id: str, student_uid: str) -> str:
        return f"{exam_id}__{student_uid}"

    def get_by_exam_and_student(self, exam_id: str, student_uid: str):
        return self.get_by_id(self.build_attempt_id(exam_id, student_uid))

    def list_by_student(self, student_uid: str, limit: int = 200):
        items = self.find_where("student_uid", "==", student_uid, limit=limit)
        return sorted(items, key=lambda x: str(x.get("started_at", "")), reverse=True)

    def list_by_exam(self, exam_id: str, limit: int = 500):
        items = self.find_where("exam_id", "==", exam_id, limit=limit)
        return sorted(items, key=lambda x: str(x.get("submitted_at") or x.get("started_at") or ""), reverse=True)

    def list_recent(self, limit: int = 200):
        items = self.list_all(limit=limit)
        return sorted(items, key=lambda x: str(x.get("updated_at", "")), reverse=True)


class FakeAuditRepository(InMemoryRepository):
    id_field = "log_id"

    def list_recent(self, *, actor_role: str | None = None, action: str | None = None, limit: int = 100):
        items = self.list_all(limit=limit)
        if actor_role:
            items = [i for i in items if i.get("actor_role") == actor_role]
        if action:
            items = [i for i in items if i.get("action") == action]
        return sorted(items, key=lambda x: str(x.get("created_at", "")), reverse=True)[:limit]


class FakeResultRepository(InMemoryRepository):
    id_field = "result_id"

    @staticmethod
    def build_result_id(exam_id: str, student_uid: str) -> str:
        return f"{exam_id}__{student_uid}"

    def get_by_exam_and_student(self, exam_id: str, student_uid: str):
        return self.get_by_id(self.build_result_id(exam_id, student_uid))

    def list_by_exam(self, exam_id: str, limit: int = 500):
        items = self.find_where("exam_id", "==", exam_id, limit=limit)
        return sorted(items, key=lambda r: float(r.get("obtained_marks", 0)), reverse=True)

    def list_by_student(self, student_uid: str, *, published_only: bool = True, limit: int = 200):
        items = self.find_where("student_uid", "==", student_uid, limit=limit)
        if published_only:
            items = [r for r in items if r.get("publication_status") == "published"]
        return sorted(
            items,
            key=lambda r: str(r.get("published_at") or r.get("evaluated_at") or r.get("updated_at") or ""),
            reverse=True,
        )


class FakeAuditReportRepository(InMemoryRepository, AuditReportRepository):
    id_field = "audit_id"


class FakeAuditSuggestionRepository(InMemoryRepository, AuditSuggestionRepository):
    id_field = "suggestion_id"


class FakeRubricVersionRepository(InMemoryRepository, RubricVersionRepository):
    id_field = "version_id"


class FakeAuditHistoryRepository(InMemoryRepository, AuditHistoryRepository):
    id_field = "history_id"


class FakeNotificationRepository(InMemoryRepository, NotificationRepository):
    id_field = "notification_id"


class FakeAuthGateway:
    """In-memory Firebase Auth gateway for deterministic integration testing."""

    def __init__(self) -> None:
        self.users_by_uid: dict[str, dict[str, Any]] = {}
        self.id_tokens: dict[str, dict[str, Any]] = {}
        self.session_cookies: dict[str, dict[str, Any]] = {}

    def issue_id_token(self, *, uid: str, email: str, role: str = "student") -> str:
        self.users_by_uid.setdefault(uid, {"uid": uid, "email": email, "claims": {"role": role}, "disabled": False})
        token = f"idtok_{uid}_{uuid.uuid4().hex[:8]}"
        self.id_tokens[token] = {"uid": uid, "email": email, "role": role}
        return token

    def verify_id_token(self, id_token: str) -> dict[str, Any]:
        payload = self.id_tokens.get(id_token)
        if not payload:
            raise AuthenticationError("Invalid test ID token.")
        u = self.users_by_uid.get(payload["uid"], {})
        if u.get("disabled"):
            raise AuthenticationError("User disabled.")
        return {**payload, **u.get("claims", {})}

    def create_session_cookie(self, id_token: str, expires_in: timedelta) -> str:
        claims = self.verify_id_token(id_token)
        cookie = f"sess_{claims['uid']}_{uuid.uuid4().hex[:10]}"
        self.session_cookies[cookie] = {
            "uid": claims["uid"],
            "email": claims["email"],
            "exp": datetime.now(timezone.utc) + expires_in,
        }
        return cookie

    def verify_session_cookie(self, session_cookie: str) -> dict[str, Any]:
        data = self.session_cookies.get(session_cookie)
        if not data or datetime.now(timezone.utc) > data["exp"]:
            raise AuthenticationError("Session expired or revoked.")
        u = self.users_by_uid.get(data["uid"], {})
        if u.get("disabled"):
            raise AuthenticationError("Account disabled.")
        return {"uid": data["uid"], "email": data["email"], **u.get("claims", {})}

    def set_custom_claims(self, uid: str, claims: dict[str, Any]) -> None:
        self.users_by_uid.setdefault(uid, {"uid": uid, "claims": {}, "disabled": False})["claims"] = claims

    def create_user(self, *, email: str, password: str, display_name: str) -> Any:
        for u in self.users_by_uid.values():
            if u.get("email") == email:
                raise ValueError("Email already exists in Auth")
        uid = f"uid_{uuid.uuid4().hex[:10]}"
        self.users_by_uid[uid] = {
            "uid": uid,
            "email": email,
            "display_name": display_name,
            "password": password,
            "claims": {},
            "disabled": False,
        }
        return SimpleNamespace(uid=uid, email=email, display_name=display_name)

    def update_user_status(self, uid: str, *, disabled: bool) -> None:
        if uid in self.users_by_uid:
            self.users_by_uid[uid]["disabled"] = disabled

    def revoke_refresh_tokens(self, uid: str) -> None:
        for k in [k for k, v in self.session_cookies.items() if v["uid"] == uid]:
            self.session_cookies.pop(k, None)

