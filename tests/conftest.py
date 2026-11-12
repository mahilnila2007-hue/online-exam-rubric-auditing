"""Shared pytest fixtures for full-stack Flask integration testing."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app import create_app
from tests.fakes import (
    FakeAuditHistoryRepository,
    FakeAuditReportRepository,
    FakeAuditRepository,
    FakeAuditSuggestionRepository,
    FakeAuthGateway,
    FakeExamRepository,
    FakeNotificationRepository,
    FakeQuestionRepository,
    FakeResultRepository,
    FakeRubricRepository,
    FakeRubricVersionRepository,
    FakeSubmissionRepository,
    FakeUserRepository,
)


@pytest.fixture()
def repos():
    return {
        "users": FakeUserRepository(),
        "questions": FakeQuestionRepository(),
        "rubrics": FakeRubricRepository(),
        "exams": FakeExamRepository(),
        "submissions": FakeSubmissionRepository(),
        "results": FakeResultRepository(),
        "audit_logs": FakeAuditRepository(),
        "audit_reports": FakeAuditReportRepository(),
        "audit_suggestions": FakeAuditSuggestionRepository(),
        "rubric_versions": FakeRubricVersionRepository(),
        "audit_history": FakeAuditHistoryRepository(),
        "notifications": FakeNotificationRepository(),
    }


@pytest.fixture()
def auth_gateway():
    return FakeAuthGateway()


@pytest.fixture()
def app(repos, auth_gateway):
    flask_app = create_app(
        "testing",
        repositories=repos,
        auth_gateway=auth_gateway,
    )
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def get_csrf_headers(client) -> dict[str, str]:
    res = client.get("/api/auth/csrf")
    token = res.get_json()["data"]["csrf_token"]
    return {"X-CSRF-Token": token}


def seed_user(repos, auth_gateway, *, uid: str, email: str, role: str, full_name: str, inst_id: str = "ID-1"):
    auth_gateway.users_by_uid[uid] = {
        "uid": uid,
        "email": email,
        "claims": {"role": role},
        "disabled": False,
    }
    return repos["users"].create(
        {
            "uid": uid,
            "email": email,
            "full_name": full_name,
            "role": role,
            "institution_id": inst_id,
            "department": "Computer Science",
            "status": "active",
            "last_login_at": datetime.now(timezone.utc),
        },
        doc_id=uid,
    )


def login_as(client, auth_gateway, *, uid: str, email: str, role: str) -> dict[str, str]:
    headers = get_csrf_headers(client)
    token = auth_gateway.issue_id_token(uid=uid, email=email, role=role)
    res = client.post("/api/auth/session-login", json={"id_token": token}, headers=headers)
    assert res.status_code == 200, res.get_json()
    return headers

